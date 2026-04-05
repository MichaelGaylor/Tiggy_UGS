"""
TiggyUGS Motion Planner

Converts G-code lines into motion segments for the WiFi CNC packet protocol.
Each segment contains step counts, timing, and velocity information that the
CNC controller firmware can execute directly.
"""

import math
import logging
from typing import Optional

from core.gcode_parser import GCodeLine

logger = logging.getLogger(__name__)

# Segment flag bits
FLAG_RAPID = 0x01
FLAG_LAST = 0x02
FLAG_PROBE = 0x04
FLAG_EXACT_STOP = 0x08

# Maximum segment duration - no splitting, ESP32 handles timing internally.
# Each G-code line becomes ONE segment to avoid flooding the buffer.
MAX_SEGMENT_DURATION_US = 600_000_000  # 10 minutes (effectively no limit)
# Minimum segment duration
MIN_SEGMENT_DURATION_US = 500
# Arc linearization tolerance in mm
ARC_TOLERANCE_MM = 0.01
# Minimum arc segment length in mm
ARC_MIN_SEGMENT_MM = 0.05
# Maximum number of arc segments (safety limit)
ARC_MAX_SEGMENTS = 10_000
# Inches to mm conversion factor
INCH_TO_MM = 25.4


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


class MotionPlanner:
    """Converts G-code moves into motion segments for the WiFi CNC packet protocol.

    The planner maintains machine state (position, modes) and produces
    motion segment dicts that can be serialized into binary packets.
    """

    def __init__(self):
        # Current machine position in mm (X, Y, Z, A, B, C)
        self.position = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        # Machine configuration (per axis, indexed 0=X, 1=Y, 2=Z, 3=A, 4=B, 5=C)
        self.steps_per_mm = [800.0, 800.0, 800.0, 800.0, 800.0, 800.0]
        self.max_rate = [20000, 20000, 20000, 20000, 20000, 20000]   # steps/sec
        self.acceleration = [5000, 5000, 5000, 5000, 5000, 5000]     # steps/sec^2

        # Modal state
        self.absolute_mode = True   # G90 vs G91
        self.feed_rate = 1000.0     # mm/min (F word)
        self.rapid_rate = 5000.0    # mm/min for G0 moves
        self.feed_override_pct = 100  # Feed override percentage (1-200)
        self.metric = True          # G21 (mm) vs G20 (inch)
        self.spindle_speed = 0.0    # S word
        self.spindle_on = False
        self.spindle_dir = 0       # 0=off, 1=CW, 2=CCW
        self.coolant_state = 0     # 0=off, 1=flood, 2=mist
        self._io_changed = False   # flag for IO update needed
        self.motion_mode = 'G0'     # active modal motion: G0, G1, G2, G3

        # Work coordinate offsets (G54-G59) - simplified: just one active set
        self.work_offset = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        # Segment counter
        self.segment_id = 0

    def reset(self):
        """Reset planner to initial state."""
        self.position = [0.0] * 6
        self.absolute_mode = True
        self.feed_rate = 1000.0
        self.rapid_rate = 5000.0
        self.metric = True
        self.spindle_speed = 0.0
        self.spindle_on = False
        self.spindle_dir = 0
        self.coolant_state = 0
        self._io_changed = False
        self.motion_mode = 'G0'
        self.work_offset = [0.0] * 6
        self.segment_id = 0

    def configure(self, steps_per_mm=None, max_rate=None, acceleration=None,
                  rapid_rate=None):
        """Update machine configuration parameters."""
        if steps_per_mm is not None:
            for i, v in enumerate(steps_per_mm[:6]):
                self.steps_per_mm[i] = float(v)
        if max_rate is not None:
            for i, v in enumerate(max_rate[:6]):
                self.max_rate[i] = int(v)
        if acceleration is not None:
            for i, v in enumerate(acceleration[:6]):
                self.acceleration[i] = int(v)
        if rapid_rate is not None:
            self.rapid_rate = float(rapid_rate)

    def process_line(self, gcode_line: GCodeLine) -> list[dict]:
        """Process a G-code line and return motion segments.

        Returns an empty list for non-motion commands (modal changes,
        M-codes, comments, etc.).
        """
        if gcode_line.is_empty or gcode_line.is_comment:
            return []

        # Handle modal commands first (they may change state even on motion lines)
        self.handle_modal_commands(gcode_line)

        cmd = gcode_line.command.upper() if gcode_line.command else ''
        params = gcode_line.params

        # Normalize command
        cmd_norm = cmd.replace('G00', 'G0').replace('G01', 'G1')
        cmd_norm = cmd_norm.replace('G02', 'G2').replace('G03', 'G3')

        # Determine effective motion command
        effective = cmd_norm
        if not effective and gcode_line.is_motion:
            effective = self.motion_mode

        # Update modal motion mode
        if effective in ('G0', 'G1', 'G2', 'G3'):
            self.motion_mode = effective

        # Dispatch to the appropriate move planner
        if effective == 'G0':
            target = self._compute_target(params)
            if target is None:
                return []
            return self.plan_linear_move(target, self.rapid_rate, is_rapid=True)

        elif effective == 'G1':
            target = self._compute_target(params)
            if target is None:
                return []
            feed = params.get('F', self.feed_rate)
            if feed <= 0:
                feed = self.feed_rate
            return self.plan_linear_move(target, feed, is_rapid=False)

        elif effective in ('G2', 'G3'):
            clockwise = (effective == 'G2')
            target = self._compute_target(params)
            if target is None:
                return []
            feed = params.get('F', self.feed_rate)
            if feed <= 0:
                feed = self.feed_rate

            # Determine arc center: I/J/K offsets or R radius
            if 'R' in params:
                center_offset = self._compute_arc_center_from_radius(
                    target, params['R'], clockwise)
            else:
                center_offset = [
                    params.get('I', 0.0),
                    params.get('J', 0.0),
                    params.get('K', 0.0),
                ]
            return self.plan_arc_move(target, center_offset, clockwise, feed)

        elif effective == 'G28':
            # Home move: rapid to zero (through optional intermediate)
            if any(a in params for a in 'XYZABC'):
                intermediate = self._compute_target(params)
                segments = self.plan_linear_move(intermediate, self.rapid_rate, is_rapid=True)
            else:
                segments = []
            home = [0.0] * 6
            segments.extend(self.plan_linear_move(home, self.rapid_rate, is_rapid=True))
            return segments

        elif effective == 'G92':
            # Set position: update current position to given values
            axis_map = {'X': 0, 'Y': 1, 'Z': 2, 'A': 3, 'B': 4, 'C': 5}
            for letter, idx in axis_map.items():
                if letter in params:
                    val = params[letter]
                    if not self.metric:
                        val *= INCH_TO_MM
                    self.position[idx] = val
            return []

        return []

    def plan_linear_move(self, target: list[float], feed_rate: float,
                         is_rapid: bool) -> list[dict]:
        """Plan a G0/G1 linear move from current position to target.

        For long moves, splits into sub-segments of max ~50ms each
        for smooth motion. Returns list of segment dicts.
        """
        # Calculate deltas in mm
        delta_mm = [target[i] - self.position[i] for i in range(6)]
        total_dist = math.sqrt(sum(d * d for d in delta_mm[:3]))  # XYZ distance

        if total_dist < 1e-6:
            # Check rotary axes
            rotary_dist = math.sqrt(sum(d * d for d in delta_mm[3:6]))
            if rotary_dist < 1e-6:
                # No actual motion
                return []
            total_dist = rotary_dist

        # Convert feed rate from mm/min to mm/sec
        feed_mmps = feed_rate / 60.0
        if feed_mmps <= 0:
            feed_mmps = self.rapid_rate / 60.0

        # Determine number of sub-segments based on duration
        move_time_sec = total_dist / feed_mmps
        max_segment_sec = MAX_SEGMENT_DURATION_US / 1_000_000.0
        num_segments = max(1, math.ceil(move_time_sec / max_segment_sec))

        segments = []
        for seg_idx in range(num_segments):
            # Fractional deltas for this sub-segment
            frac = 1.0 / num_segments
            sub_delta = [d * frac for d in delta_mm]

            is_last = (seg_idx == num_segments - 1)
            segment = self._compute_segment(
                sub_delta, feed_rate, is_rapid, is_last)
            if segment is not None:
                segments.append(segment)

        # Update position
        self.position = list(target)

        return segments

    def plan_arc_move(self, target: list[float], center_offset: list[float],
                      clockwise: bool, feed_rate: float) -> list[dict]:
        """Plan a G2/G3 arc move by linearizing into small line segments.

        The arc is in the XY plane. Z moves linearly from start to end
        (helical interpolation).
        """
        cx = self.position[0] + center_offset[0]
        cy = self.position[1] + center_offset[1]

        # Start and end vectors relative to center
        sx = self.position[0] - cx
        sy = self.position[1] - cy
        ex = target[0] - cx
        ey = target[1] - cy

        radius = math.sqrt(sx * sx + sy * sy)
        if radius < 1e-6:
            # Degenerate arc, treat as linear
            return self.plan_linear_move(target, feed_rate, is_rapid=False)

        # Start and end angles
        start_angle = math.atan2(sy, sx)
        end_angle = math.atan2(ey, ex)

        # Calculate angular sweep
        if clockwise:
            # CW: angle decreases
            sweep = start_angle - end_angle
            if sweep <= 0:
                sweep += 2.0 * math.pi
            sweep = -sweep  # negative for CW
        else:
            # CCW: angle increases
            sweep = end_angle - start_angle
            if sweep <= 0:
                sweep += 2.0 * math.pi

        # Full circle detection: if target is same as start and I/J are given
        if (abs(target[0] - self.position[0]) < 1e-4 and
                abs(target[1] - self.position[1]) < 1e-4):
            if clockwise:
                sweep = -2.0 * math.pi
            else:
                sweep = 2.0 * math.pi

        arc_length = abs(sweep) * radius

        # Determine number of linear segments from arc tolerance
        if radius > ARC_TOLERANCE_MM:
            # Segments needed for the given tolerance
            theta_per_seg = 2.0 * math.acos(
                _clamp(1.0 - ARC_TOLERANCE_MM / radius, -1.0, 1.0))
            if theta_per_seg < 1e-6:
                theta_per_seg = 0.01
            num_segs = max(1, int(math.ceil(abs(sweep) / theta_per_seg)))
        else:
            num_segs = max(1, int(math.ceil(arc_length / ARC_MIN_SEGMENT_MM)))

        num_segs = min(num_segs, ARC_MAX_SEGMENTS)

        # Z interpolation (helical)
        z_start = self.position[2]
        z_end = target[2]
        z_delta = z_end - z_start

        # A/B/C interpolation
        abc_start = self.position[3:6]
        abc_end = target[3:6]
        abc_delta = [abc_end[i] - abc_start[i] for i in range(3)]

        # Generate linear segments along the arc
        all_segments = []
        prev = list(self.position)

        for i in range(1, num_segs + 1):
            frac = i / num_segs
            angle = start_angle + sweep * frac
            seg_target = [0.0] * 6
            seg_target[0] = cx + radius * math.cos(angle)
            seg_target[1] = cy + radius * math.sin(angle)
            seg_target[2] = z_start + z_delta * frac
            for j in range(3):
                seg_target[3 + j] = abc_start[j] + abc_delta[j] * frac

            # Compute delta from prev to this point
            sub_delta = [seg_target[k] - prev[k] for k in range(6)]
            is_last = (i == num_segs)
            segment = self._compute_segment(sub_delta, feed_rate,
                                            is_rapid=False, is_last=is_last)
            if segment is not None:
                all_segments.append(segment)

            prev = list(seg_target)

        # Snap final position to the commanded target
        self.position = list(target)

        return all_segments

    def _compute_segment(self, delta_mm: list[float], feed_rate_mmpm: float,
                         is_rapid: bool, is_last: bool) -> Optional[dict]:
        """Compute a single motion segment from mm deltas and feed rate.

        Returns a dict matching the WiFi CNC segment protocol, or None
        if the segment has zero motion.
        """
        # Convert mm to steps
        steps = [0] * 6
        for i in range(6):
            steps[i] = round(delta_mm[i] * self.steps_per_mm[i])

        # Check for zero-length segment
        if all(s == 0 for s in steps):
            return None

        # Total distance in mm (XYZ only for speed calculation)
        dist_mm = math.sqrt(sum(d * d for d in delta_mm[:3]))
        if dist_mm < 1e-9:
            dist_mm = math.sqrt(sum(d * d for d in delta_mm))
            if dist_mm < 1e-9:
                return None

        # Feed rate in mm/sec (with override applied for non-rapid moves)
        if is_rapid:
            feed_mmps = self._compute_rapid_speed(steps)
        else:
            effective_rate = feed_rate_mmpm * self.feed_override_pct / 100.0
            feed_mmps = effective_rate / 60.0
            if feed_mmps <= 0:
                feed_mmps = self.rapid_rate / 60.0

        # Clamp to max rate of dominant axis
        feed_mmps = self._clamp_to_max_rate(feed_mmps, delta_mm, dist_mm)

        # Duration in microseconds
        if feed_mmps > 0:
            duration_sec = dist_mm / feed_mmps
        else:
            duration_sec = 0.001

        duration_us = max(MIN_SEGMENT_DURATION_US,
                          round(duration_sec * 1_000_000))

        # Speed in steps/sec for the dominant axis
        max_steps = max(abs(s) for s in steps)
        if duration_us > 0:
            speed_stps = max_steps / (duration_us / 1_000_000.0)
        else:
            speed_stps = 0

        # Simplified velocity profile: entry and exit speeds
        # For a standalone segment planner (no look-ahead), we use 0 for
        # start/end and the dominant axis acceleration.
        dominant_axis = 0
        for i in range(6):
            if abs(steps[i]) > abs(steps[dominant_axis]):
                dominant_axis = i

        accel = self.acceleration[dominant_axis]

        # entry_speed_sqr and exit_speed_sqr (speed^2 * 1000, uint32)
        # For simplicity: entry=0, exit=0 (trapezoid from zero to zero)
        # A proper look-ahead planner would fill these in.
        # Clamp to uint32 max (4294967295) to prevent struct.pack overflow.
        UINT32_MAX = 0xFFFFFFFF
        entry_speed_sqr = 0
        raw_exit = int(speed_stps * speed_stps * 1000 * 0.5) if not is_last else 0
        exit_speed_sqr = max(0, min(raw_exit, UINT32_MAX))

        # Flags
        flags = 0
        if is_rapid:
            flags |= FLAG_RAPID
        if is_last:
            flags |= FLAG_LAST

        self.segment_id = (self.segment_id + 1) & 0xFFFF

        return {
            'steps': list(steps),
            'duration_us': max(0, min(int(duration_us), UINT32_MAX)),
            'entry_speed_sqr': max(0, min(int(entry_speed_sqr), UINT32_MAX)),
            'exit_speed_sqr': max(0, min(int(exit_speed_sqr), UINT32_MAX)),
            'acceleration': max(0, min(int(accel * 100), UINT32_MAX)),
            'segment_id': self.segment_id,
            'flags': flags,
        }

    def _compute_rapid_speed(self, steps: list[int]) -> float:
        """Compute rapid traverse speed in mm/sec based on axis max rates."""
        # Find the axis that will take the longest
        max_time = 0.0
        for i in range(6):
            if steps[i] != 0 and self.steps_per_mm[i] > 0:
                dist_mm = abs(steps[i]) / self.steps_per_mm[i]
                rate_mmps = self.max_rate[i] / self.steps_per_mm[i]
                if rate_mmps > 0:
                    axis_time = dist_mm / rate_mmps
                    max_time = max(max_time, axis_time)

        if max_time <= 0:
            return self.rapid_rate / 60.0

        # Total XYZ distance
        total_dist = 0.0
        for i in range(3):
            if self.steps_per_mm[i] > 0:
                d = abs(steps[i]) / self.steps_per_mm[i]
                total_dist += d * d
        total_dist = math.sqrt(total_dist)
        if total_dist < 1e-9:
            for i in range(6):
                if self.steps_per_mm[i] > 0:
                    d = abs(steps[i]) / self.steps_per_mm[i]
                    total_dist += d * d
            total_dist = math.sqrt(total_dist)

        if total_dist < 1e-9:
            return self.rapid_rate / 60.0

        return total_dist / max_time

    def _clamp_to_max_rate(self, feed_mmps: float, delta_mm: list[float],
                           total_dist: float) -> float:
        """Ensure the feed rate doesn't exceed any axis's max rate."""
        if total_dist < 1e-9:
            return feed_mmps

        for i in range(6):
            if abs(delta_mm[i]) < 1e-9:
                continue
            if self.steps_per_mm[i] <= 0:
                continue

            # Axis speed at given feed rate
            axis_frac = abs(delta_mm[i]) / total_dist
            axis_speed_mmps = feed_mmps * axis_frac
            axis_speed_stps = axis_speed_mmps * self.steps_per_mm[i]

            if axis_speed_stps > self.max_rate[i]:
                # Scale down feed rate
                scale = self.max_rate[i] / axis_speed_stps
                feed_mmps *= scale

        return feed_mmps

    def _compute_target(self, params: dict) -> Optional[list[float]]:
        """Compute target position from G-code parameters.

        Handles absolute (G90) and incremental (G91) modes, and
        inch-to-mm conversion if in G20 mode.
        """
        axis_map = {'X': 0, 'Y': 1, 'Z': 2, 'A': 3, 'B': 4, 'C': 5}
        has_motion = False

        target = list(self.position)
        for letter, idx in axis_map.items():
            if letter in params:
                val = params[letter]
                if not self.metric:
                    val *= INCH_TO_MM
                if self.absolute_mode:
                    target[idx] = val
                else:
                    target[idx] = self.position[idx] + val
                has_motion = True

        if not has_motion:
            return None

        return target

    def _compute_arc_center_from_radius(self, target: list[float],
                                        radius: float,
                                        clockwise: bool) -> list[float]:
        """Compute I/J center offsets from an R-format arc specification.

        Given start position, target, and radius R, calculate the center
        point offsets. A negative R selects the large arc.
        """
        dx = target[0] - self.position[0]
        dy = target[1] - self.position[1]
        d_sq = dx * dx + dy * dy
        d = math.sqrt(d_sq)

        if d < 1e-9:
            return [0.0, 0.0, 0.0]

        r = abs(radius)
        if r < d / 2.0:
            # Radius too small, clamp to minimum
            r = d / 2.0

        # Height of the triangle from chord midpoint to center
        h_sq = r * r - d_sq / 4.0
        if h_sq < 0:
            h_sq = 0.0
        h = math.sqrt(h_sq)

        # Midpoint of chord
        mx = dx / 2.0
        my = dy / 2.0

        # Perpendicular direction (normalized)
        px = -dy / d
        py = dx / d

        # Choose center side based on CW/CCW and sign of R
        # CW with positive R -> center on right side of chord direction
        # Negative R -> large arc (center on opposite side)
        if (clockwise and radius > 0) or (not clockwise and radius < 0):
            h = -h

        i_offset = mx + h * px
        j_offset = my + h * py

        return [i_offset, j_offset, 0.0]

    def handle_modal_commands(self, gcode_line: GCodeLine):
        """Handle state-changing G/M codes: G90/G91, G20/G21, F, S, etc."""
        cmd = gcode_line.command.upper() if gcode_line.command else ''
        params = gcode_line.params

        # Feed rate update (can appear on any line)
        if 'F' in params:
            val = params['F']
            if not self.metric:
                val *= INCH_TO_MM
            if val > 0:
                self.feed_rate = val

        # Spindle speed (can appear on any line)
        if 'S' in params and params['S'] >= 0:
            self.spindle_speed = params['S']

        # G-code modal state changes
        if cmd == 'G90':
            self.absolute_mode = True
        elif cmd == 'G91' and cmd != 'G91.1':
            # G91 = incremental positioning, G91.1 = incremental arc mode (different!)
            self.absolute_mode = False
        elif cmd == 'G20':
            self.metric = False
        elif cmd == 'G21':
            self.metric = True
        elif cmd in ('G54', 'G55', 'G56', 'G57', 'G58', 'G59'):
            # Work coordinate system selection - just acknowledge
            logger.debug("Work coordinate system: %s", cmd)
        elif cmd == 'G92':
            # Handled in process_line
            pass

        # M-code handling - track state AND flag for IO update
        self._io_changed = False
        if cmd in ('M3', 'M03'):
            self.spindle_on = True
            self.spindle_dir = 1  # CW
            self._io_changed = True
        elif cmd in ('M4', 'M04'):
            self.spindle_on = True
            self.spindle_dir = 2  # CCW
            self._io_changed = True
        elif cmd in ('M5', 'M05'):
            self.spindle_on = False
            self.spindle_dir = 0
            self._io_changed = True
        elif cmd in ('M7', 'M07'):
            self.coolant_state = 1  # flood
            self._io_changed = True
        elif cmd in ('M8', 'M08'):
            self.coolant_state = 2  # mist
            self._io_changed = True
        elif cmd in ('M9', 'M09'):
            self.coolant_state = 0  # off
            self._io_changed = True

        # Also handle multiple G-codes on the same line by checking cleaned text.
        # Use negative lookahead to avoid G91.1 (arc incremental) matching G91.
        import re
        cleaned = gcode_line.cleaned.upper() if gcode_line.cleaned else ''
        if re.search(r'G90(?![.\d])', cleaned) and cmd != 'G90':
            self.absolute_mode = True
        if re.search(r'G91(?![.\d])', cleaned) and cmd != 'G91':
            self.absolute_mode = False
        if re.search(r'G20(?![.\d])', cleaned) and cmd != 'G20':
            self.metric = False
        if 'G21' in cleaned and cmd != 'G21':
            self.metric = True

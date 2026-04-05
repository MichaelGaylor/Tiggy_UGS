"""
TiggyUGS 3D G-Code Toolpath Visualizer

OpenGL-based 3D viewer for G-code toolpaths with rotation, zoom, pan,
and real-time tool position tracking. Uses fixed-function pipeline for
maximum compatibility.
"""

import math
import numpy as np

from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QWheelEvent, QAction
from PyQt6.QtWidgets import QMenu

from OpenGL.GL import (
    glClearColor, glEnable, glDisable, glBlendFunc, glLineWidth,
    glClear, glViewport, glMatrixMode, glLoadIdentity, glTranslatef,
    glRotatef, glBegin, glEnd, glVertex3f, glColor4f, glColor3f,
    glPointSize, glEnableClientState, glDisableClientState,
    glVertexPointer, glColorPointer, glDrawArrays,
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
    GL_LINE_SMOOTH, GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
    GL_LINES, GL_POINTS, GL_MODELVIEW, GL_PROJECTION,
    GL_VERTEX_ARRAY, GL_COLOR_ARRAY, GL_FLOAT,
)
from OpenGL.GLU import gluPerspective

# Import from our project
from core.gcode_parser import GCodeFile, GCodeLine


# Motion code sets (mirroring parser)
_RAPID_CODES = {'G0', 'G00'}
_ARC_CODES = {'G2', 'G02', 'G3', 'G03'}
_MOTION_CODES = {'G0', 'G00', 'G1', 'G01', 'G2', 'G02', 'G3', 'G03'}

# Threshold for switching to VBO-style rendering
_VBO_THRESHOLD = 10000


class VisualizerWidget(QOpenGLWidget):
    """3D G-code toolpath visualizer with rotation, zoom, and pan."""

    # Emitted when the user clicks a point and we can map it to a line
    line_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # ---- View state ----
        self.rotation_x = 30.0
        self.rotation_z = -45.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.zoom = 1.0
        self.last_mouse_pos = QPoint()

        # ---- Toolpath data ----
        # Each segment: (x1, y1, z1, x2, y2, z2, source_line_number)
        self.rapid_segments = []
        self.feed_segments = []

        # ---- Display state ----
        self.current_line = 0
        self.tool_position = [0.0, 0.0, 0.0]
        self.show_rapids = True
        self.show_grid = True
        self.show_axes = True
        self.show_bounds = True
        self.grid_size = 10.0
        self.bounds = None
        self._center_offset = (0.0, 0.0, 0.0)

        # ---- Colors (dark theme) ----
        self.bg_color = (0.05, 0.05, 0.1, 1.0)
        self.rapid_color = (0.3, 0.3, 0.8, 0.5)
        self.feed_color = (0.0, 1.0, 0.25, 1.0)
        self.completed_color = (0.5, 0.5, 0.5, 0.7)
        self.current_color = (1.0, 1.0, 0.0, 1.0)
        self.tool_color = (1.0, 0.0, 0.0, 1.0)
        self.grid_color = (0.15, 0.15, 0.25, 0.5)
        self.axis_colors = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
        self.bounds_color = (0.3, 0.3, 0.0, 0.3)

        # ---- Cached numpy arrays for fast rendering ----
        self._rapid_verts = None  # np.float32 array (N, 3)
        self._rapid_colors_arr = None
        self._feed_verts = None
        self._feed_colors_arr = None
        self._use_arrays = False
        self._needs_rebuild = True

        # Context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_gcode(self, gcode_file: GCodeFile):
        """Parse a GCodeFile and generate 3D path segment data."""
        self.rapid_segments.clear()
        self.feed_segments.clear()
        self.current_line = 0
        self.tool_position = [0.0, 0.0, 0.0]

        if gcode_file is None or not gcode_file.lines:
            self.bounds = None
            self._needs_rebuild = True
            self.update()
            return

        pos = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
        absolute_mode = True
        modal_motion = 'G0'
        unit_factor = 1.0  # 1.0 for metric, 25.4 for imperial->mm

        for line in gcode_file.lines:
            if line.is_empty or line.is_comment:
                continue

            cmd = line.command.upper() if line.command else ''
            norm = self._normalize_cmd(cmd)

            # Modal state changes
            if norm == 'G90':
                absolute_mode = True
                continue
            elif norm == 'G91':
                absolute_mode = False
                continue
            elif norm == 'G20':
                unit_factor = 25.4
                continue
            elif norm == 'G21':
                unit_factor = 1.0
                continue
            elif norm == 'G92':
                for axis in ('X', 'Y', 'Z'):
                    if axis in line.params:
                        pos[axis] = line.params[axis] * unit_factor
                continue
            elif norm == 'G28':
                pos = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
                continue

            # Determine effective motion command
            effective = norm
            if not effective and line.is_motion:
                effective = modal_motion

            if effective in _MOTION_CODES:
                modal_motion = effective

            if not line.is_motion and effective not in _MOTION_CODES:
                continue

            # Compute target
            prev = dict(pos)
            for axis in ('X', 'Y', 'Z'):
                if axis in line.params:
                    val = line.params[axis] * unit_factor
                    if absolute_mode:
                        pos[axis] = val
                    else:
                        pos[axis] += val

            ln = line.line_number

            if effective in _ARC_CODES:
                # Linearize arc
                arc_segs = self._linearize_arc(
                    prev['X'], prev['Y'], prev['Z'],
                    pos['X'], pos['Y'], pos['Z'],
                    line.params, effective, absolute_mode, unit_factor
                )
                for seg in arc_segs:
                    self.feed_segments.append((*seg, ln))
            elif effective in _RAPID_CODES:
                self.rapid_segments.append((
                    prev['X'], prev['Y'], prev['Z'],
                    pos['X'], pos['Y'], pos['Z'], ln
                ))
            else:
                # G1 feed move
                self.feed_segments.append((
                    prev['X'], prev['Y'], prev['Z'],
                    pos['X'], pos['Y'], pos['Z'], ln
                ))

        self.bounds = dict(gcode_file.bounds)
        # Apply unit factor to bounds if imperial
        if unit_factor != 1.0:
            for k in self.bounds:
                self.bounds[k] *= unit_factor

        self._needs_rebuild = True
        self._build_arrays()
        self.fit_view()
        self.update()

    def set_current_line(self, line_number: int):
        """Update which line is 'current' -- everything before is completed."""
        self.current_line = line_number
        if self._use_arrays:
            self._rebuild_feed_colors()
        self.update()

    def set_tool_position(self, x: float, y: float, z: float):
        """Update the real-time tool position marker."""
        self.tool_position = [x, y, z]
        self.update()

    def fit_view(self):
        """Auto-fit the camera to show the entire toolpath."""
        if not self.bounds:
            self.pan_x = 0.0
            self.pan_y = 0.0
            self.zoom = 1.0
            self.update()
            return

        b = self.bounds
        cx = (b['x_min'] + b['x_max']) / 2.0
        cy = (b['y_min'] + b['y_max']) / 2.0
        cz = (b['z_min'] + b['z_max']) / 2.0

        dx = b['x_max'] - b['x_min']
        dy = b['y_max'] - b['y_min']
        dz = b['z_max'] - b['z_min']
        extent = max(dx, dy, dz, 1.0)

        # Zoom so that the object extent maps to roughly the viewport size.
        # The camera distance is zoom * 500, and FOV is 45 degrees.
        # visible_height ~= 2 * distance * tan(22.5) ~= distance * 0.828
        # We want extent to fill ~70% of visible_height.
        self.zoom = extent / (500.0 * 0.828 * 0.7)
        self.zoom = max(0.01, min(100.0, self.zoom))

        # Pan is applied *before* rotation in the modelview stack, so we need
        # to pan in screen-space.  For the default isometric view we zero pan
        # and let the rotation center on the model center.  To truly center we
        # translate the model so its center sits at the origin, which we do by
        # adjusting the view setup.
        self._center_offset = (cx, cy, cz)
        self.pan_x = 0.0
        self.pan_y = 0.0

        # Reset to isometric
        self.rotation_x = 30.0
        self.rotation_z = -45.0
        self.update()

    # ------------------------------------------------------------------
    # View presets
    # ------------------------------------------------------------------

    def set_view_top(self):
        """Look down the Z axis (XY plane from above)."""
        self.rotation_x = 0.0
        self.rotation_z = 0.0
        self.update()

    def set_view_front(self):
        """Look along Y axis (XZ plane)."""
        self.rotation_x = 90.0
        self.rotation_z = 0.0
        self.update()

    def set_view_right(self):
        """Look along X axis (YZ plane)."""
        self.rotation_x = 90.0
        self.rotation_z = 90.0
        self.update()

    def set_view_iso(self):
        """Isometric view (default)."""
        self.rotation_x = 30.0
        self.rotation_z = -45.0
        self.update()

    # ------------------------------------------------------------------
    # OpenGL overrides
    # ------------------------------------------------------------------

    def initializeGL(self):
        glClearColor(*self.bg_color)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_LINE_SMOOTH)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glLineWidth(1.5)

    def resizeGL(self, w: int, h: int):
        glViewport(0, 0, w, h)
        self._update_projection()

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self._setup_view()

        if self.show_grid:
            self._draw_grid()
        if self.show_axes:
            self._draw_axes()
        if self.show_bounds and self.bounds:
            self._draw_bounds()

        self._draw_toolpath()
        self._draw_tool_marker()

    # ------------------------------------------------------------------
    # Internal: view setup
    # ------------------------------------------------------------------

    def _setup_view(self):
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        # Pull back camera
        glTranslatef(self.pan_x, self.pan_y, -self.zoom * 500.0)
        # Apply viewing rotations
        glRotatef(self.rotation_x, 1.0, 0.0, 0.0)
        glRotatef(self.rotation_z, 0.0, 0.0, 1.0)
        # Translate so the model center is at the origin
        cx, cy, cz = getattr(self, '_center_offset', (0.0, 0.0, 0.0))
        glTranslatef(-cx, -cy, -cz)

    def _update_projection(self):
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        w = self.width()
        h = max(self.height(), 1)
        aspect = w / h
        gluPerspective(45.0, aspect, 0.1, 50000.0)
        glMatrixMode(GL_MODELVIEW)

    # ------------------------------------------------------------------
    # Internal: drawing helpers
    # ------------------------------------------------------------------

    def _draw_grid(self):
        """Draw an XY grid plane at Z=0."""
        extent = 200.0
        if self.bounds:
            b = self.bounds
            extent = max(
                abs(b['x_min']), abs(b['x_max']),
                abs(b['y_min']), abs(b['y_max']),
                extent
            )
        # Round up to next grid_size multiple and add margin
        extent = (math.ceil(extent / self.grid_size) + 2) * self.grid_size

        r, g, b_c, a = self.grid_color
        glColor4f(r, g, b_c, a)
        glLineWidth(1.0)
        glBegin(GL_LINES)

        step = self.grid_size
        val = -extent
        while val <= extent:
            # Line parallel to Y
            glVertex3f(val, -extent, 0.0)
            glVertex3f(val, extent, 0.0)
            # Line parallel to X
            glVertex3f(-extent, val, 0.0)
            glVertex3f(extent, val, 0.0)
            val += step

        glEnd()
        glLineWidth(1.5)

    def _draw_axes(self):
        """Draw XYZ axis lines at the origin with small arrowheads."""
        length = 50.0
        if self.bounds:
            b = self.bounds
            max_dim = max(
                b['x_max'] - b['x_min'],
                b['y_max'] - b['y_min'],
                b['z_max'] - b['z_min'],
                1.0
            )
            length = max(50.0, max_dim * 0.15)

        arrow = length * 0.1
        glLineWidth(2.5)

        # X axis (red)
        glColor3f(1.0, 0.0, 0.0)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(length, 0.0, 0.0)
        # Arrowhead
        glVertex3f(length, 0.0, 0.0)
        glVertex3f(length - arrow, arrow * 0.4, 0.0)
        glVertex3f(length, 0.0, 0.0)
        glVertex3f(length - arrow, -arrow * 0.4, 0.0)
        glEnd()

        # Y axis (green)
        glColor3f(0.0, 1.0, 0.0)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, length, 0.0)
        glVertex3f(0.0, length, 0.0)
        glVertex3f(arrow * 0.4, length - arrow, 0.0)
        glVertex3f(0.0, length, 0.0)
        glVertex3f(-arrow * 0.4, length - arrow, 0.0)
        glEnd()

        # Z axis (blue)
        glColor3f(0.0, 0.0, 1.0)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, 0.0, length)
        glVertex3f(0.0, 0.0, length)
        glVertex3f(0.0, arrow * 0.4, length - arrow)
        glVertex3f(0.0, 0.0, length)
        glVertex3f(0.0, -arrow * 0.4, length - arrow)
        glEnd()

        glLineWidth(1.5)

    def _draw_bounds(self):
        """Draw a wireframe bounding box around the toolpath."""
        if not self.bounds:
            return

        b = self.bounds
        x0, x1 = b['x_min'], b['x_max']
        y0, y1 = b['y_min'], b['y_max']
        z0, z1 = b['z_min'], b['z_max']

        glColor4f(*self.bounds_color)
        glLineWidth(1.0)
        glBegin(GL_LINES)

        # Bottom face (z0)
        glVertex3f(x0, y0, z0); glVertex3f(x1, y0, z0)
        glVertex3f(x1, y0, z0); glVertex3f(x1, y1, z0)
        glVertex3f(x1, y1, z0); glVertex3f(x0, y1, z0)
        glVertex3f(x0, y1, z0); glVertex3f(x0, y0, z0)

        # Top face (z1)
        glVertex3f(x0, y0, z1); glVertex3f(x1, y0, z1)
        glVertex3f(x1, y0, z1); glVertex3f(x1, y1, z1)
        glVertex3f(x1, y1, z1); glVertex3f(x0, y1, z1)
        glVertex3f(x0, y1, z1); glVertex3f(x0, y0, z1)

        # Vertical edges
        glVertex3f(x0, y0, z0); glVertex3f(x0, y0, z1)
        glVertex3f(x1, y0, z0); glVertex3f(x1, y0, z1)
        glVertex3f(x1, y1, z0); glVertex3f(x1, y1, z1)
        glVertex3f(x0, y1, z0); glVertex3f(x0, y1, z1)

        glEnd()
        glLineWidth(1.5)

    def _draw_toolpath(self):
        """Draw all toolpath segments, coloring by state."""
        if self._use_arrays:
            self._draw_toolpath_arrays()
        else:
            self._draw_toolpath_immediate()

    def _draw_toolpath_immediate(self):
        """Immediate-mode rendering for smaller files."""
        # Draw rapids
        if self.show_rapids and self.rapid_segments:
            glColor4f(*self.rapid_color)
            glLineWidth(1.0)
            glBegin(GL_LINES)
            for seg in self.rapid_segments:
                glVertex3f(seg[0], seg[1], seg[2])
                glVertex3f(seg[3], seg[4], seg[5])
            glEnd()

        # Draw feed moves
        if self.feed_segments:
            cur = self.current_line
            glLineWidth(1.5)

            # If no progress tracking, draw all in feed color
            if cur <= 0:
                glColor4f(*self.feed_color)
                glBegin(GL_LINES)
                for seg in self.feed_segments:
                    glVertex3f(seg[0], seg[1], seg[2])
                    glVertex3f(seg[3], seg[4], seg[5])
                glEnd()
            else:
                # Completed segments
                glColor4f(*self.completed_color)
                glBegin(GL_LINES)
                for seg in self.feed_segments:
                    if seg[6] < cur:
                        glVertex3f(seg[0], seg[1], seg[2])
                        glVertex3f(seg[3], seg[4], seg[5])
                glEnd()

                # Current segment (highlight)
                glColor4f(*self.current_color)
                glLineWidth(3.0)
                glBegin(GL_LINES)
                for seg in self.feed_segments:
                    if seg[6] == cur:
                        glVertex3f(seg[0], seg[1], seg[2])
                        glVertex3f(seg[3], seg[4], seg[5])
                glEnd()

                # Upcoming segments
                glColor4f(*self.feed_color)
                glLineWidth(1.5)
                glBegin(GL_LINES)
                for seg in self.feed_segments:
                    if seg[6] > cur:
                        glVertex3f(seg[0], seg[1], seg[2])
                        glVertex3f(seg[3], seg[4], seg[5])
                glEnd()

        glLineWidth(1.5)

    def _draw_toolpath_arrays(self):
        """Array-based rendering for large files (>10k segments)."""
        # Draw rapids
        if self.show_rapids and self._rapid_verts is not None and len(self._rapid_verts) > 0:
            glLineWidth(1.0)
            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_COLOR_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, self._rapid_verts)
            glColorPointer(4, GL_FLOAT, 0, self._rapid_colors_arr)
            glDrawArrays(GL_LINES, 0, len(self._rapid_verts))
            glDisableClientState(GL_COLOR_ARRAY)
            glDisableClientState(GL_VERTEX_ARRAY)

        # Draw feed
        if self._feed_verts is not None and len(self._feed_verts) > 0:
            glLineWidth(1.5)
            glEnableClientState(GL_VERTEX_ARRAY)
            glEnableClientState(GL_COLOR_ARRAY)
            glVertexPointer(3, GL_FLOAT, 0, self._feed_verts)
            glColorPointer(4, GL_FLOAT, 0, self._feed_colors_arr)
            glDrawArrays(GL_LINES, 0, len(self._feed_verts))
            glDisableClientState(GL_COLOR_ARRAY)
            glDisableClientState(GL_VERTEX_ARRAY)

        glLineWidth(1.5)

    def _draw_tool_marker(self):
        """Draw a large bright crosshair at the current tool position."""
        tx, ty, tz = self.tool_position
        size = 10.0
        if self.bounds:
            b = self.bounds
            max_dim = max(
                b['x_max'] - b['x_min'],
                b['y_max'] - b['y_min'],
                b['z_max'] - b['z_min'],
                1.0
            )
            size = max(8.0, max_dim * 0.05)

        # Bright yellow crosshair - highly visible
        glColor4f(1.0, 1.0, 0.0, 1.0)
        glLineWidth(3.0)
        glBegin(GL_LINES)
        # X crosshair
        glVertex3f(tx - size, ty, tz)
        glVertex3f(tx + size, ty, tz)
        # Y crosshair
        glVertex3f(tx, ty - size, tz)
        glVertex3f(tx, ty + size, tz)
        # Z crosshair (vertical line going up)
        glVertex3f(tx, ty, tz)
        glVertex3f(tx, ty, tz + size * 2)
        glEnd()

        # Large bright point at center
        glPointSize(10.0)
        glBegin(GL_POINTS)
        glVertex3f(tx, ty, tz)
        glEnd()
        glPointSize(1.0)
        glLineWidth(1.5)

    # ------------------------------------------------------------------
    # Internal: data building
    # ------------------------------------------------------------------

    def _build_arrays(self):
        """Build numpy arrays from segment lists for fast rendering."""
        total = len(self.rapid_segments) + len(self.feed_segments)
        self._use_arrays = total >= _VBO_THRESHOLD

        if not self._use_arrays:
            self._rapid_verts = None
            self._rapid_colors_arr = None
            self._feed_verts = None
            self._feed_colors_arr = None
            self._needs_rebuild = False
            return

        # Build rapid arrays
        if self.rapid_segments:
            n = len(self.rapid_segments)
            verts = np.empty((n * 2, 3), dtype=np.float32)
            colors = np.empty((n * 2, 4), dtype=np.float32)
            rc = self.rapid_color
            for i, seg in enumerate(self.rapid_segments):
                idx = i * 2
                verts[idx] = (seg[0], seg[1], seg[2])
                verts[idx + 1] = (seg[3], seg[4], seg[5])
                colors[idx] = rc
                colors[idx + 1] = rc
            self._rapid_verts = verts
            self._rapid_colors_arr = colors
        else:
            self._rapid_verts = None
            self._rapid_colors_arr = None

        # Build feed arrays
        self._build_feed_arrays()
        self._needs_rebuild = False

    def _build_feed_arrays(self):
        """Build the feed vertex and color arrays."""
        if not self.feed_segments:
            self._feed_verts = None
            self._feed_colors_arr = None
            return

        n = len(self.feed_segments)
        verts = np.empty((n * 2, 3), dtype=np.float32)
        colors = np.empty((n * 2, 4), dtype=np.float32)

        cur = self.current_line
        fc = self.feed_color
        cc = self.completed_color
        hc = self.current_color

        for i, seg in enumerate(self.feed_segments):
            idx = i * 2
            verts[idx] = (seg[0], seg[1], seg[2])
            verts[idx + 1] = (seg[3], seg[4], seg[5])
            ln = seg[6]
            if cur <= 0:
                c = fc
            elif ln < cur:
                c = cc
            elif ln == cur:
                c = hc
            else:
                c = fc
            colors[idx] = c
            colors[idx + 1] = c

        self._feed_verts = verts
        self._feed_colors_arr = colors

    def _rebuild_feed_colors(self):
        """Update only the color array when current_line changes.
        Uses numpy vectorized ops for speed on large files."""
        if self._feed_colors_arr is None or not self.feed_segments:
            return

        cur = self.current_line
        colors = self._feed_colors_arr
        n = len(self.feed_segments)

        if cur <= 0:
            # All upcoming
            colors[:] = self.feed_color
            return

        # Build line number array once and cache it
        if not hasattr(self, '_feed_line_nums') or len(self._feed_line_nums) != n:
            self._feed_line_nums = np.array(
                [seg[6] for seg in self.feed_segments], dtype=np.int32)

        lns = self._feed_line_nums
        fc = np.array(self.feed_color, dtype=np.float32)
        cc = np.array(self.completed_color, dtype=np.float32)
        hc = np.array(self.current_color, dtype=np.float32)

        # Vectorized: assign colors based on line number vs current
        completed = lns < cur
        current = lns == cur

        # Default: upcoming (feed color)
        colors[0::2] = fc
        colors[1::2] = fc
        # Completed segments
        colors[0::2][completed] = cc
        colors[1::2][completed] = cc
        # Current segment
        colors[0::2][current] = hc
        colors[1::2][current] = hc

    # ------------------------------------------------------------------
    # Internal: arc linearization
    # ------------------------------------------------------------------

    @staticmethod
    def _linearize_arc(x0, y0, z0, x1, y1, z1, params, cmd,
                       absolute_mode, unit_factor):
        """Linearize a G2/G3 arc into small line segments.

        Supports I/J center offset format and R radius format.
        Returns a list of (x_start, y_start, z_start, x_end, y_end, z_end) tuples.
        """
        segments = []

        # Determine arc direction: G2 = CW, G3 = CCW
        norm = cmd.replace('G02', 'G2').replace('G03', 'G3')
        clockwise = (norm == 'G2')

        # Get center offsets (I, J relative to start point)
        has_ij = 'I' in params or 'J' in params
        has_r = 'R' in params

        if has_ij:
            ci = params.get('I', 0.0) * unit_factor
            cj = params.get('J', 0.0) * unit_factor
            cx = x0 + ci
            cy = y0 + cj
        elif has_r:
            r = abs(params['R'] * unit_factor)
            # Find center from radius
            dx = x1 - x0
            dy = y1 - y0
            d = math.sqrt(dx * dx + dy * dy)
            if d < 1e-9 or d > 2.0 * r:
                # Degenerate: just draw a straight line
                segments.append((x0, y0, z0, x1, y1, z1))
                return segments
            h = math.sqrt(max(r * r - (d / 2.0) ** 2, 0.0))
            mx = (x0 + x1) / 2.0
            my = (y0 + y1) / 2.0
            # Perpendicular direction
            px = -dy / d
            py = dx / d
            # For G2 (CW) with positive R, center is to the right of travel
            # For G3 (CCW) with positive R, center is to the left
            if clockwise:
                cx = mx + h * px
                cy = my + h * py
            else:
                cx = mx - h * px
                cy = my - h * py
            # If R is negative in original params, flip
            if params.get('R', 0.0) < 0:
                cx = 2.0 * mx - cx
                cy = 2.0 * my - cy
        else:
            # No arc parameters: treat as straight line
            segments.append((x0, y0, z0, x1, y1, z1))
            return segments

        # Calculate start and end angles
        start_angle = math.atan2(y0 - cy, x0 - cx)
        end_angle = math.atan2(y1 - cy, x1 - cx)
        radius = math.sqrt((x0 - cx) ** 2 + (y0 - cy) ** 2)

        if radius < 1e-9:
            segments.append((x0, y0, z0, x1, y1, z1))
            return segments

        # Calculate sweep angle
        if clockwise:
            sweep = start_angle - end_angle
            if sweep <= 0:
                sweep += 2.0 * math.pi
        else:
            sweep = end_angle - start_angle
            if sweep <= 0:
                sweep += 2.0 * math.pi

        # Number of segments: roughly 1 degree per segment, minimum 4
        num_segs = max(4, int(math.degrees(sweep)))
        # Cap at a reasonable maximum
        num_segs = min(num_segs, 360)

        # Z interpolation (helical arcs)
        z_step = (z1 - z0) / num_segs

        px_prev, py_prev, pz_prev = x0, y0, z0
        for i in range(1, num_segs + 1):
            frac = i / num_segs
            if clockwise:
                angle = start_angle - sweep * frac
            else:
                angle = start_angle + sweep * frac

            if i < num_segs:
                px_cur = cx + radius * math.cos(angle)
                py_cur = cy + radius * math.sin(angle)
                pz_cur = z0 + z_step * i
            else:
                # Ensure we end exactly at the target
                px_cur, py_cur, pz_cur = x1, y1, z1

            segments.append((px_prev, py_prev, pz_prev, px_cur, py_cur, pz_cur))
            px_prev, py_prev, pz_prev = px_cur, py_cur, pz_cur

        return segments

    # ------------------------------------------------------------------
    # Internal: command normalization
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_cmd(cmd: str) -> str:
        """Normalize G-code command to short form (G00->G0, etc.)."""
        if not cmd:
            return ''
        c = cmd.upper()
        c = c.replace('G00', 'G0').replace('G01', 'G1')
        c = c.replace('G02', 'G2').replace('G03', 'G3')
        return c

    # ------------------------------------------------------------------
    # Mouse interaction
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent):
        self.last_mouse_pos = event.position().toPoint()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.position().toPoint()
        dx = pos.x() - self.last_mouse_pos.x()
        dy = pos.y() - self.last_mouse_pos.y()

        buttons = event.buttons()
        mods = event.modifiers()
        left = bool(buttons & Qt.MouseButton.LeftButton)
        mid = bool(buttons & Qt.MouseButton.MiddleButton)
        right = bool(buttons & Qt.MouseButton.RightButton)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if right or mid or (left and shift):
            # Pan: right-drag, middle-drag, or shift+left-drag
            scale = self.zoom * 0.5
            self.pan_x += dx * scale
            self.pan_y -= dy * scale
        elif left:
            # Rotate: left-drag
            self.rotation_z += dx * 0.5
            self.rotation_x += dy * 0.5
            self.rotation_x = max(-90.0, min(90.0, self.rotation_x))

        self.last_mouse_pos = pos
        self.update()
        event.accept()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 0.999 ** delta
        self.zoom *= factor
        self.zoom = max(0.01, min(100.0, self.zoom))
        self.update()
        event.accept()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e1e2e;
                color: #cdd6f4;
                border: 1px solid #45475a;
            }
            QMenu::item:selected {
                background-color: #313244;
            }
        """)

        act_fit = QAction("Fit View", self)
        act_fit.triggered.connect(self.fit_view)
        menu.addAction(act_fit)

        menu.addSeparator()

        act_top = QAction("Top (XY)", self)
        act_top.triggered.connect(self.set_view_top)
        menu.addAction(act_top)

        act_front = QAction("Front (XZ)", self)
        act_front.triggered.connect(self.set_view_front)
        menu.addAction(act_front)

        act_right = QAction("Right (YZ)", self)
        act_right.triggered.connect(self.set_view_right)
        menu.addAction(act_right)

        act_iso = QAction("Isometric", self)
        act_iso.triggered.connect(self.set_view_iso)
        menu.addAction(act_iso)

        menu.addSeparator()

        act_rapids = QAction("Show Rapids", self)
        act_rapids.setCheckable(True)
        act_rapids.setChecked(self.show_rapids)
        act_rapids.triggered.connect(self._toggle_rapids)
        menu.addAction(act_rapids)

        act_grid = QAction("Show Grid", self)
        act_grid.setCheckable(True)
        act_grid.setChecked(self.show_grid)
        act_grid.triggered.connect(self._toggle_grid)
        menu.addAction(act_grid)

        act_axes = QAction("Show Axes", self)
        act_axes.setCheckable(True)
        act_axes.setChecked(self.show_axes)
        act_axes.triggered.connect(self._toggle_axes)
        menu.addAction(act_axes)

        act_bounds = QAction("Show Bounds", self)
        act_bounds.setCheckable(True)
        act_bounds.setChecked(self.show_bounds)
        act_bounds.triggered.connect(self._toggle_bounds)
        menu.addAction(act_bounds)

        menu.exec(self.mapToGlobal(pos))

    def _toggle_rapids(self, checked: bool):
        self.show_rapids = checked
        self.update()

    def _toggle_grid(self, checked: bool):
        self.show_grid = checked
        self.update()

    def _toggle_axes(self, checked: bool):
        self.show_axes = checked
        self.update()

    def _toggle_bounds(self, checked: bool):
        self.show_bounds = checked
        self.update()

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_F:
            self.fit_view()
        elif key == Qt.Key.Key_T:
            self.set_view_top()
        elif key == Qt.Key.Key_R:
            self.set_view_right()
        elif key == Qt.Key.Key_I:
            self.set_view_iso()
        elif key == Qt.Key.Key_G:
            self.show_grid = not self.show_grid
            self.update()
        else:
            super().keyPressEvent(event)

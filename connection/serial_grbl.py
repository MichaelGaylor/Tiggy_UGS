"""
Serial GRBL connection backend for TiggyUGS.

Connects to a GRBL controller over a serial (COM) port using pyserial.
Implements the standard GRBL 1.1 protocol with real-time commands.
"""

import re
import threading
import time
import logging

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    serial = None

from .base import ConnectionBase, ConnectionState

log = logging.getLogger(__name__)

# Axis names for up to 6 axes (standard GRBL is 3, some forks support more)
AXIS_NAMES = ['X', 'Y', 'Z', 'A', 'B', 'C']

# GRBL status regex: <State|MPos:x,y,z|...>
_STATUS_RE = re.compile(r'<([^|>]+)\|(.+)>')
# MPos or WPos field
_POS_RE = re.compile(r'([MW]Pos):([\-\d.,]+)')
# Buffer field: Bf:avail,total
_BUF_RE = re.compile(r'Bf:(\d+),(\d+)')
# Feed/speed: FS:feed,spindle_rpm
_FS_RE = re.compile(r'FS:(\d+),(\d+)')
# Feed only: F:feed
_F_RE = re.compile(r'F:(\d+)')
# Limit pins: Pn:letters
_PN_RE = re.compile(r'Pn:([A-Za-z]+)')
# Override: Ov:feed,rapid,spindle
_OV_RE = re.compile(r'Ov:(\d+),(\d+),(\d+)')
# Work Coordinate Offset: WCO:x,y,z (sent periodically with MPos)
_WCO_RE = re.compile(r'WCO:([\-\d.,]+)')
# Accessory state: A:SFM (S=spindle CW, C=spindle CCW, F=flood, M=mist)
_A_RE = re.compile(r'A:([A-Za-z]+)')

# GRBL real-time override commands (single bytes)
_FEED_OVR_RESET     = 0x90
_FEED_OVR_PLUS_10   = 0x91
_FEED_OVR_MINUS_10  = 0x92
_FEED_OVR_PLUS_1    = 0x93
_FEED_OVR_MINUS_1   = 0x94
_RAPID_OVR_100      = 0x95
_RAPID_OVR_50       = 0x96
_RAPID_OVR_25       = 0x97
_SPINDLE_OVR_RESET  = 0x99
_SPINDLE_OVR_PLUS_10 = 0x9A
_SPINDLE_OVR_MINUS_10 = 0x9B
_SPINDLE_OVR_PLUS_1 = 0x9C
_SPINDLE_OVR_MINUS_1 = 0x9D


class SerialGrblConnection(ConnectionBase):
    """Connection to a GRBL controller over serial port."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._serial: 'serial.Serial | None' = None
        self._reader_thread: threading.Thread | None = None
        self._status_thread: threading.Thread | None = None
        self._running = False
        self._line_number = 0
        self._address = ""

        # GRBL state tracking
        self._grbl_ok_event = threading.Event()
        self._grbl_response = ""
        self._send_lock = threading.Lock()
        self._response_queue: 'queue.Queue' = __import__('queue').Queue()
        self._wco = [0.0] * 6  # Work Coordinate Offset from GRBL
        self._status_interval = 0.25  # seconds between '?' queries

    @property
    def connection_type(self) -> str:
        return "Serial GRBL"

    # ----- Port listing -----

    @staticmethod
    def list_ports() -> list:
        """Return list of (port_name, description) for available serial ports."""
        if serial is None:
            return []
        ports = serial.tools.list_ports.comports()
        return [(p.device, p.description) for p in sorted(ports)]

    # ----- Connection lifecycle -----

    def connect_to(self, address: str, **kwargs):
        """Connect to a GRBL device on the given COM port.
        kwargs: baud (int, default 115200)."""
        if serial is None:
            self.error_occurred.emit("pyserial not installed. pip install pyserial")
            return

        if self.state != ConnectionState.DISCONNECTED:
            self.disconnect_from()

        baud = kwargs.get('baud', 115200)
        self.state = ConnectionState.CONNECTING
        self._address = address

        try:
            self._serial = serial.Serial(
                port=address,
                baudrate=baud,
                timeout=0.1,
                write_timeout=2.0,
            )
            self._running = True

            # Wait for GRBL welcome message
            time.sleep(2.0)
            # Flush any startup text
            if self._serial.in_waiting:
                startup = self._serial.read(self._serial.in_waiting)
                startup_text = startup.decode('ascii', errors='replace').strip()
                if startup_text:
                    self.response_received.emit(startup_text)

            # Start reader thread
            self._reader_thread = threading.Thread(
                target=self._reader_loop, daemon=True, name="grbl-reader")
            self._reader_thread.start()

            # Start status polling thread
            self._status_thread = threading.Thread(
                target=self._status_poll_loop, daemon=True, name="grbl-status")
            self._status_thread.start()

            self.state = ConnectionState.CONNECTED
            device_info = {
                'device_name': f"GRBL ({address})",
                'port': address,
                'baud': baud,
                'connection_type': 'serial_grbl',
            }
            self.connected.emit(device_info)
            self.response_received.emit(f"Connected to {address} at {baud} baud")

        except Exception as exc:
            log.exception("Serial connect failed")
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
            self._running = False
            self.state = ConnectionState.DISCONNECTED
            self.error_occurred.emit(f"Serial connect failed: {exc}")

    def disconnect_from(self):
        self._running = False
        for t in (self._reader_thread, self._status_thread):
            if t is not None and t.is_alive():
                t.join(timeout=3.0)
        self._reader_thread = None
        self._status_thread = None
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self.state = ConnectionState.DISCONNECTED
        self.disconnected.emit()

    # ----- Serial I/O -----

    def _write_bytes(self, data: bytes):
        """Write raw bytes to serial port."""
        if self._serial is not None and self._serial.is_open:
            try:
                self._serial.write(data)
            except Exception as exc:
                log.warning("Serial write error: %s", exc)
                self.error_occurred.emit(f"Serial write error: {exc}")

    def _send_line(self, line: str, wait_ok: bool = True) -> str:
        """Send a line to GRBL. If wait_ok is True, block until 'ok' or 'error'."""
        with self._send_lock:
            stripped = line.strip()
            if not stripped:
                return "ok"
            self._grbl_ok_event.clear()
            self._grbl_response = ""
            data = (stripped + '\n').encode('ascii')
            self._write_bytes(data)
            if wait_ok:
                if self._grbl_ok_event.wait(timeout=10.0):
                    return self._grbl_response
                return "timeout"
            return "sent"

    def _send_realtime(self, byte_val: int):
        """Send a single-byte GRBL real-time command (no newline)."""
        self._write_bytes(bytes([byte_val]))

    # ----- Reader thread -----

    def _reader_loop(self):
        """Background thread: read lines from serial port."""
        line_buf = b''
        while self._running:
            if self._serial is None or not self._serial.is_open:
                break
            try:
                chunk = self._serial.read(256)
            except Exception:
                if self._running:
                    self.error_occurred.emit("Serial read error")
                break

            if not chunk:
                continue
            line_buf += chunk
            while b'\n' in line_buf:
                line_bytes, line_buf = line_buf.split(b'\n', 1)
                line_str = line_bytes.decode('ascii', errors='replace').strip()
                if not line_str:
                    continue
                self._handle_grbl_line(line_str)

    def _handle_grbl_line(self, line: str):
        """Process one line of GRBL output."""
        if line.startswith('<') and line.endswith('>'):
            self._parse_grbl_status(line)
        elif line == 'ok':
            self._grbl_response = 'ok'
            self._grbl_ok_event.set()
            self._response_queue.put('ok')
            self.response_received.emit(line)
        elif line.startswith('error:'):
            self._grbl_response = line
            self._grbl_ok_event.set()
            self._response_queue.put(line)
            self.error_occurred.emit(line)
            self.response_received.emit(line)
        elif line.startswith('ALARM:'):
            self._response_queue.put(line)
            self.error_occurred.emit(line)
            self.response_received.emit(line)
        elif line.startswith('Grbl') or line.startswith('['):
            self.response_received.emit(line)
        else:
            self.response_received.emit(line)

    # ----- Status parsing -----

    def _parse_grbl_status(self, raw: str):
        """Parse a GRBL status string like <Idle|MPos:0.000,0.000,0.000|...>."""
        m = _STATUS_RE.match(raw)
        if not m:
            return

        state_str = m.group(1)
        fields_str = m.group(2)

        # Map GRBL state names to our standard names
        grbl_state_map = {
            'Idle': (0, 'Idle'), 'Run': (1, 'Run'), 'Hold': (2, 'Hold'),
            'Hold:0': (2, 'Hold'), 'Hold:1': (2, 'Hold'),
            'Jog': (3, 'Jog'), 'Home': (4, 'Homing'),
            'Alarm': (6, 'Alarm'), 'Check': (1, 'Check'),
            'Door': (2, 'Door'), 'Door:0': (2, 'Door'),
            'Door:1': (2, 'Door'), 'Door:2': (2, 'Door'),
            'Door:3': (2, 'Door'), 'Sleep': (0, 'Sleep'),
        }
        state_id, state_name = grbl_state_map.get(state_str, (0, state_str))

        status = {
            'positions': [0.0] * 6,
            'state': state_name,
            'state_id': state_id,
            'alarm_code': 0,
            'buffer_available': 0,
            'buffer_total': 0,
            'limits': 0,
            'home_switches': 0,
            'estop': False,
            'probe': False,
            'feed_rate': 0.0,
            'spindle_state': 0,
            'spindle_rpm': 0,
            'coolant_state': 0,
            'misc_outputs': 0,
            'misc_inputs': 0,
        }

        # Parse position (MPos = machine, WPos = work coordinates)
        pm = _POS_RE.search(fields_str)
        if pm:
            pos_type = pm.group(1)  # 'MPos' or 'WPos'
            coords = pm.group(2).split(',')
            for i, c in enumerate(coords):
                if i < 6:
                    try:
                        status['positions'][i] = float(c)
                    except ValueError:
                        pass
            # Parse WCO if present (GRBL sends this periodically with MPos)
            wco_m = _WCO_RE.search(fields_str)
            if wco_m:
                wco_coords = wco_m.group(1).split(',')
                for wi, wc in enumerate(wco_coords):
                    if wi < 6:
                        try:
                            self._wco[wi] = float(wc)
                        except ValueError:
                            pass

            # If MPos, convert to WPos using stored WCO so the UI
            # always gets work coordinates that match the G-code
            if pos_type == 'MPos':
                for i in range(min(len(status['positions']), len(self._wco))):
                    status['positions'][i] -= self._wco[i]
                status['position_type'] = 'WPos'  # now it's work coords
            else:
                status['position_type'] = pos_type

        # Parse buffer
        bm = _BUF_RE.search(fields_str)
        if bm:
            status['buffer_available'] = int(bm.group(1))
            status['buffer_total'] = int(bm.group(2))

        # Parse feed/speed
        fsm = _FS_RE.search(fields_str)
        if fsm:
            status['feed_rate'] = float(fsm.group(1))
            status['spindle_rpm'] = int(fsm.group(2))
        else:
            fm = _F_RE.search(fields_str)
            if fm:
                status['feed_rate'] = float(fm.group(1))

        # Parse pin states
        pnm = _PN_RE.search(fields_str)
        if pnm:
            pins = pnm.group(1)
            limit_mask = 0
            if 'X' in pins: limit_mask |= 0x01
            if 'Y' in pins: limit_mask |= 0x02
            if 'Z' in pins: limit_mask |= 0x04
            if 'A' in pins: limit_mask |= 0x08
            if 'B' in pins: limit_mask |= 0x10
            if 'C' in pins: limit_mask |= 0x20
            status['limits'] = limit_mask
            status['probe'] = 'P' in pins
            # 'H' means hold pin, 'D' means door, 'R' means reset
            # GRBL uses lowercase for home switches in some builds

        # Parse accessories
        am = _A_RE.search(fields_str)
        if am:
            acc = am.group(1)
            if 'S' in acc:
                status['spindle_state'] = 1  # CW
            elif 'C' in acc:
                status['spindle_state'] = 2  # CCW
            coolant = 0
            if 'F' in acc:
                coolant |= 0x01  # flood
            if 'M' in acc:
                coolant |= 0x02  # mist
            status['coolant_state'] = coolant

        self.status_updated.emit(status)

    # ----- Status polling -----

    def _status_poll_loop(self):
        """Background thread: periodically send '?' to get status."""
        while self._running:
            if self._serial is not None and self._serial.is_open:
                self._send_realtime(ord('?'))
            time.sleep(self._status_interval)

    # ----- Public control methods -----

    def send_gcode_line(self, line: str):
        """Send a G-code line to GRBL and wait for response."""
        stripped = line.strip()
        if not stripped or stripped.startswith(';') or stripped.startswith('('):
            return
        self._line_number += 1
        self.line_sent.emit(self._line_number, stripped)
        resp = self._send_line(stripped, wait_ok=True)
        if resp.startswith('error'):
            self.error_occurred.emit(f"Line {self._line_number}: {resp}")

    def send_line(self, text: str):
        """Send a raw line (used by GCodeSender character-counting protocol)."""
        stripped = text.strip()
        if not stripped:
            return
        data = (stripped + '\n').encode('ascii')
        self._write_bytes(data)

    def read_line(self, timeout: float = 1.0) -> str | None:
        """Read a response line from the queue (thread-safe).
        Used by GCodeSender to drain 'ok' responses."""
        import queue
        try:
            return self._response_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def jog(self, axis: int, direction: int, speed: float):
        """Jog using GRBL 1.1 $J command. speed in mm/min."""
        if axis < 0 or axis >= len(AXIS_NAMES):
            return
        ax_name = AXIS_NAMES[axis]
        # Use a large distance for continuous jog (will be cancelled by jog_stop)
        dist = 10000.0 * direction
        cmd = f"$J=G91 G21 {ax_name}{dist:.3f} F{speed:.0f}"
        self._send_line(cmd, wait_ok=False)

    def jog_stop(self, axis: int = -1):
        """Cancel jog by sending 0x85 (GRBL jog cancel)."""
        self._send_realtime(0x85)

    def home(self, axis_mask: int = 0x3F):
        """Send $H homing command."""
        self._send_line('$H', wait_ok=False)
        self.response_received.emit("Homing started ($H)")

    def estop(self):
        """Send Ctrl-X (0x18) soft reset as emergency stop."""
        self._send_realtime(0x18)
        self.response_received.emit("E-STOP (soft reset) sent")

    def feed_hold(self):
        """Send '!' feed hold real-time command."""
        self._send_realtime(ord('!'))

    def feed_resume(self):
        """Send '~' cycle resume real-time command."""
        self._send_realtime(ord('~'))

    def reset(self):
        """Send Ctrl-X (0x18) soft reset."""
        self._send_realtime(0x18)
        self.response_received.emit("Soft reset (Ctrl-X) sent")

    def set_io(self, spindle_state: int = 0, spindle_rpm: int = 0,
               coolant_state: int = 0, misc_outputs: int = 0):
        """Set spindle and coolant via G-code commands."""
        # Spindle
        if spindle_state == 0:
            self._send_line('M5', wait_ok=False)
        elif spindle_state == 1:
            self._send_line(f'M3 S{spindle_rpm}', wait_ok=False)
        elif spindle_state == 2:
            self._send_line(f'M4 S{spindle_rpm}', wait_ok=False)

        # Coolant
        if coolant_state == 0:
            self._send_line('M9', wait_ok=False)
        else:
            if coolant_state & 0x01:
                self._send_line('M8', wait_ok=False)  # flood
            if coolant_state & 0x02:
                self._send_line('M7', wait_ok=False)  # mist

    # ----- Feed override -----

    def set_feed_override(self, percent: int):
        """Adjust feed override using GRBL real-time commands.
        First reset to 100%, then adjust up/down."""
        self._send_realtime(_FEED_OVR_RESET)
        diff = percent - 100
        while diff >= 10:
            self._send_realtime(_FEED_OVR_PLUS_10)
            diff -= 10
        while diff <= -10:
            self._send_realtime(_FEED_OVR_MINUS_10)
            diff += 10
        while diff >= 1:
            self._send_realtime(_FEED_OVR_PLUS_1)
            diff -= 1
        while diff <= -1:
            self._send_realtime(_FEED_OVR_MINUS_1)
            diff += 1

    def set_rapid_override(self, percent: int):
        """Set rapid override (GRBL only supports 100%, 50%, 25%)."""
        if percent >= 100:
            self._send_realtime(_RAPID_OVR_100)
        elif percent >= 50:
            self._send_realtime(_RAPID_OVR_50)
        else:
            self._send_realtime(_RAPID_OVR_25)

    def set_spindle_override(self, percent: int):
        """Adjust spindle override using GRBL real-time commands."""
        self._send_realtime(_SPINDLE_OVR_RESET)
        diff = percent - 100
        while diff >= 10:
            self._send_realtime(_SPINDLE_OVR_PLUS_10)
            diff -= 10
        while diff <= -10:
            self._send_realtime(_SPINDLE_OVR_MINUS_10)
            diff += 10
        while diff >= 1:
            self._send_realtime(_SPINDLE_OVR_PLUS_1)
            diff -= 1
        while diff <= -1:
            self._send_realtime(_SPINDLE_OVR_MINUS_1)
            diff += 1

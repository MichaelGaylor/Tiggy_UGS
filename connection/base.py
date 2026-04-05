"""
Connection base class for TiggyUGS.

Defines the abstract interface that all connection backends must implement,
along with PyQt6 signals for UI integration.
"""

from PyQt6.QtCore import QObject, pyqtSignal
from enum import Enum


class ConnectionState(Enum):
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2


class ConnectionBase(QObject):
    """Abstract base class for all CNC connection backends.

    Subclasses must implement all methods that raise NotImplementedError.
    Signals are emitted to communicate state changes to the UI layer.

    Standard status dict keys:
        positions     : list of 6 floats (mm)
        state         : str (human-readable state name)
        state_id      : int (MachineState enum value)
        alarm_code    : int
        buffer_available : int (free slots in motion buffer)
        buffer_total  : int (total motion buffer capacity)
        limits        : int (bitmask, bit0=X .. bit5=C)
        home_switches : int (bitmask, bit0=X .. bit5=C)
        estop         : bool
        probe         : bool
        feed_rate     : float (current feed rate)
        spindle_state : int (0=off, 1=CW, 2=CCW)
        spindle_rpm   : int
        coolant_state : int (bit0=flood, bit1=mist)
        misc_outputs  : int (bitmask)
        misc_inputs   : int (bitmask)
    """

    # Signals
    connected = pyqtSignal(dict)            # device_info dict
    disconnected = pyqtSignal()
    status_updated = pyqtSignal(dict)       # status dict
    error_occurred = pyqtSignal(str)        # error message
    line_sent = pyqtSignal(int, str)        # line_number, line_text
    response_received = pyqtSignal(str)     # response text for console

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = ConnectionState.DISCONNECTED
        self.steps_per_mm = [800.0] * 6     # default, updated from device config

    # ----- Connection lifecycle -----

    def connect_to(self, address: str, **kwargs):
        """Connect to a device at the given address.
        address: IP string for WiFi, COM port for serial."""
        raise NotImplementedError

    def disconnect_from(self):
        """Disconnect from the current device and clean up resources."""
        raise NotImplementedError

    # ----- G-code streaming -----

    def send_gcode_line(self, line: str):
        """Send a single line of G-code to the controller."""
        raise NotImplementedError

    # ----- Manual control -----

    def jog(self, axis: int, direction: int, speed: float):
        """Start jogging an axis. axis: 0-5, direction: -1 or +1, speed: mm/min."""
        raise NotImplementedError

    def jog_stop(self, axis: int = -1):
        """Stop jogging. axis=-1 stops all axes."""
        raise NotImplementedError

    def home(self, axis_mask: int = 0x3F):
        """Home axes specified by bitmask (bit0=X .. bit5=C). 0x3F = all."""
        raise NotImplementedError

    def estop(self):
        """Emergency stop -- halt all motion immediately."""
        raise NotImplementedError

    def feed_hold(self):
        """Pause motion (feed hold)."""
        raise NotImplementedError

    def feed_resume(self):
        """Resume motion after feed hold."""
        raise NotImplementedError

    def reset(self):
        """Soft reset the controller."""
        raise NotImplementedError

    # ----- I/O control -----

    def set_io(self, spindle_state: int = 0, spindle_rpm: int = 0,
               coolant_state: int = 0, misc_outputs: int = 0):
        """Set spindle, coolant, and misc output states."""
        raise NotImplementedError

    # ----- Override controls (optional) -----

    def set_feed_override(self, percent: int):
        """Set feed rate override percentage. Default: no-op."""
        pass

    def set_spindle_override(self, percent: int):
        """Set spindle speed override percentage. Default: no-op."""
        pass

    def set_rapid_override(self, percent: int):
        """Set rapid override percentage. Default: no-op."""
        pass

    # ----- Properties -----

    @property
    def is_connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    @property
    def connection_type(self) -> str:
        """Return a human-readable name for this connection type."""
        raise NotImplementedError

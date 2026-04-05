"""Status Bar Widget - connection info, machine state, LED indicators."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QFrame, QSizePolicy,
)

# Theme
BG = "#1a1a2e"
PANEL = "#16213e"
ACCENT = "#0f3460"
HIGHLIGHT = "#e94560"
TEXT = "#e0e0e0"
GREEN = "#00ff41"
BLUE = "#4a9eff"
YELLOW = "#ffd700"
ORANGE = "#ff8c00"

LED_ON_GREEN = GREEN
LED_ON_RED = HIGHLIGHT
LED_ON_YELLOW = YELLOW
LED_OFF = "#333333"
LED_SIZE = 12

AXIS_NAMES = ["X", "Y", "Z", "A", "B", "C"]

STATE_COLORS = {
    "Idle": GREEN,
    "Run": BLUE,
    "Hold": YELLOW,
    "Jog": BLUE,
    "Home": YELLOW,
    "Alarm": HIGHLIGHT,
    "Check": ORANGE,
    "Door": ORANGE,
    "Sleep": TEXT,
}


def _make_led(color: str = LED_OFF) -> QLabel:
    led = QLabel()
    led.setFixedSize(LED_SIZE, LED_SIZE)
    led.setStyleSheet(
        f"background: {color}; border: 1px solid #555; "
        f"border-radius: {LED_SIZE // 2}px;"
    )
    return led


def _set_led(led: QLabel, active: bool, color: str = LED_ON_GREEN):
    c = color if active else LED_OFF
    led.setStyleSheet(
        f"background: {c}; border: 1px solid #555; "
        f"border-radius: {LED_SIZE // 2}px;"
    )


class StatusBarWidget(QWidget):
    """Status bar - connection info, machine state, limit/home/probe indicators."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setStyleSheet(
            f"StatusBarWidget {{ background: {PANEL}; "
            f"border-top: 1px solid {ACCENT}; }}"
        )

        font = QFont("Consolas", 9)
        lbl_style = f"color: {TEXT}; background: transparent; font-size: 10px;"

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(6)

        def sep():
            s = QFrame()
            s.setFrameShape(QFrame.Shape.VLine)
            s.setStyleSheet(f"color: {ACCENT};")
            return s

        # Connection
        self._conn_led = _make_led()
        lay.addWidget(self._conn_led)
        self._conn_label = QLabel("Disconnected")
        self._conn_label.setFont(font)
        self._conn_label.setStyleSheet(lbl_style)
        lay.addWidget(self._conn_label)
        lay.addWidget(sep())

        # State
        self._state_label = QLabel("Idle")
        self._state_label.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self._state_label.setStyleSheet(f"color: {GREEN}; background: transparent;")
        self._state_label.setMinimumWidth(60)
        lay.addWidget(self._state_label)
        lay.addWidget(sep())

        # Buffer
        self._buffer_label = QLabel("Buf: --/--")
        self._buffer_label.setFont(font)
        self._buffer_label.setStyleSheet(lbl_style)
        lay.addWidget(self._buffer_label)
        lay.addWidget(sep())

        # Limit LEDs
        lim_lbl = QLabel("Lim:")
        lim_lbl.setFont(font)
        lim_lbl.setStyleSheet(lbl_style)
        lay.addWidget(lim_lbl)
        self._limit_leds: list[QLabel] = []
        for name in AXIS_NAMES:
            led = _make_led()
            led.setToolTip(f"Limit {name}")
            self._limit_leds.append(led)
            lay.addWidget(led)
        lay.addWidget(sep())

        # Home LEDs
        home_lbl = QLabel("Home:")
        home_lbl.setFont(font)
        home_lbl.setStyleSheet(lbl_style)
        lay.addWidget(home_lbl)
        self._home_leds: list[QLabel] = []
        for name in AXIS_NAMES:
            led = _make_led()
            led.setToolTip(f"Home {name}")
            self._home_leds.append(led)
            lay.addWidget(led)
        lay.addWidget(sep())

        # Probe LED
        probe_lbl = QLabel("Prb:")
        probe_lbl.setFont(font)
        probe_lbl.setStyleSheet(lbl_style)
        lay.addWidget(probe_lbl)
        self._probe_led = _make_led()
        lay.addWidget(self._probe_led)
        lay.addWidget(sep())

        # E-Stop LED
        estop_lbl = QLabel("ES:")
        estop_lbl.setFont(font)
        estop_lbl.setStyleSheet(lbl_style)
        lay.addWidget(estop_lbl)
        self._estop_led = _make_led()
        lay.addWidget(self._estop_led)
        lay.addWidget(sep())

        # Feed rate
        self._feed_label = QLabel("F: -- mm/min")
        self._feed_label.setFont(font)
        self._feed_label.setStyleSheet(lbl_style)
        lay.addWidget(self._feed_label)
        lay.addWidget(sep())

        # Spindle
        self._spindle_label = QLabel("S: -- RPM")
        self._spindle_label.setFont(font)
        self._spindle_label.setStyleSheet(lbl_style)
        lay.addWidget(self._spindle_label)

        lay.addStretch()

    # ------------------------------------------------------------------ public API
    def update_connection(self, connected: bool, conn_type: str = "", address: str = ""):
        _set_led(self._conn_led, connected, GREEN)
        if connected:
            self._conn_label.setText(f"{conn_type} : {address}")
        else:
            self._conn_label.setText("Disconnected")

    def update_status(self, status: dict):
        """Update from a status dict (see connection status_updated signal)."""
        # State
        state = status.get("state", "Unknown")
        color = STATE_COLORS.get(state, TEXT)
        self._state_label.setText(state)
        self._state_label.setStyleSheet(
            f"color: {color}; background: transparent; font-weight: bold;"
        )

        # Buffer
        avail = status.get("buffer_available", 0)
        total = status.get("buffer_total", 0)
        self._buffer_label.setText(f"Buf: {avail}/{total}")

        # Limits bitmask
        limits = status.get("limits", 0)
        for i, led in enumerate(self._limit_leds):
            _set_led(led, bool(limits & (1 << i)), LED_ON_RED)

        # Home switches bitmask
        homes = status.get("home_switches", 0)
        for i, led in enumerate(self._home_leds):
            _set_led(led, bool(homes & (1 << i)), LED_ON_GREEN)

        # Probe
        _set_led(self._probe_led, status.get("probe", False), LED_ON_YELLOW)

        # E-Stop
        _set_led(self._estop_led, status.get("estop", False), LED_ON_RED)

        # Feed rate
        feed = status.get("feed_rate", 0.0)
        self._feed_label.setText(f"F: {feed:.0f} mm/min")

        # Spindle
        rpm = status.get("spindle_rpm", 0)
        self._spindle_label.setText(f"S: {rpm} RPM")

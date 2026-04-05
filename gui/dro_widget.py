"""Digital Readout Widget - large position display for 6 axes."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy,
)

# Theme colors
BG = "#1a1a2e"
PANEL = "#16213e"
ACCENT = "#0f3460"
HIGHLIGHT = "#e94560"
TEXT = "#e0e0e0"
GREEN = "#00ff41"
BLUE = "#4a9eff"
YELLOW = "#ffd700"
ORANGE = "#ff8c00"

AXIS_COLORS = {
    0: "#e94560",   # X - red
    1: "#00ff41",   # Y - green
    2: "#4a9eff",   # Z - blue
    3: "#ffd700",   # A - yellow
    4: "#00e5ff",   # B - cyan
    5: "#ff40ff",   # C - magenta
}
AXIS_NAMES = ["X", "Y", "Z", "A", "B", "C"]

DRO_FONT = "Consolas"
DRO_SIZE = 24


class _AxisRow(QFrame):
    """Single axis row: label, value, zero/half buttons."""

    zero_clicked = pyqtSignal(int)
    half_clicked = pyqtSignal(int)

    def __init__(self, axis_index: int, parent=None):
        super().__init__(parent)
        self._axis = axis_index
        self._color = AXIS_COLORS[axis_index]
        self._prev_pos = 0.0

        self.setStyleSheet(
            f"_AxisRow {{ background: {PANEL}; border: 1px solid {ACCENT}; "
            f"border-radius: 4px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Axis label
        self.label = QLabel(AXIS_NAMES[axis_index])
        self.label.setFixedWidth(40)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setFont(QFont(DRO_FONT, 18, QFont.Weight.Bold))
        self.label.setStyleSheet(
            f"color: {self._color}; background: transparent; border: none;"
        )
        layout.addWidget(self.label)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {ACCENT};")
        layout.addWidget(sep)

        # Position value
        self.value_label = QLabel(self._format_value(0.0))
        self.value_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.value_label.setFont(QFont(DRO_FONT, DRO_SIZE, QFont.Weight.Bold))
        self.value_label.setMinimumWidth(140)
        self.value_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.value_label.setStyleSheet(
            f"color: {GREEN}; background: #0a0a14; border: 1px solid {ACCENT}; "
            f"border-radius: 3px; padding: 2px 8px;"
        )
        layout.addWidget(self.value_label)

        # Units label
        self.units_label = QLabel("mm")
        self.units_label.setFixedWidth(32)
        self.units_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.units_label.setStyleSheet(
            f"color: {TEXT}; background: transparent; border: none; "
            f"font-size: 11px;"
        )
        layout.addWidget(self.units_label)

        # Zero button
        btn_style = (
            f"QPushButton {{ background: {ACCENT}; color: {TEXT}; border: 1px solid "
            f"{BLUE}; border-radius: 3px; padding: 4px 8px; font-size: 11px; "
            f"font-weight: bold; }}"
            f"QPushButton:hover {{ background: {BLUE}; }}"
            f"QPushButton:pressed {{ background: {HIGHLIGHT}; }}"
        )

        self.zero_btn = QPushButton("Zero")
        self.zero_btn.setFixedSize(50, 30)
        self.zero_btn.setStyleSheet(btn_style)
        self.zero_btn.clicked.connect(lambda: self.zero_clicked.emit(self._axis))
        layout.addWidget(self.zero_btn)

    # ------------------------------------------------------------------ #
    def _format_value(self, value: float) -> str:
        return f"{value:10.3f}"

    def set_position(self, value: float, moving: bool = False):
        self.value_label.setText(self._format_value(value))
        color = YELLOW if moving else GREEN
        self.value_label.setStyleSheet(
            f"color: {color}; background: #0a0a14; border: 1px solid {ACCENT}; "
            f"border-radius: 3px; padding: 2px 8px;"
        )
        self._prev_pos = value

    def set_units(self, metric: bool):
        self.units_label.setText("mm" if metric else "in")


class DROWidget(QWidget):
    """Digital Readout - large position display for 6 axes."""

    axis_clicked = pyqtSignal(int)  # emitted when user clicks an axis label/zero

    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_work = True
        self._metric = True
        self._prev_positions: list[float] = [0.0] * 6
        self._work_offsets: list[float] = [0.0] * 6

        self.setStyleSheet(f"DROWidget {{ background: {BG}; }}")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(3)

        # Header with mode toggle
        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("POSITION")
        title.setFont(QFont(DRO_FONT, 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {TEXT}; background: transparent;")
        header.addWidget(title)

        header.addStretch()

        toggle_style = (
            f"QPushButton {{ background: {ACCENT}; color: {TEXT}; border: 1px solid "
            f"{BLUE}; border-radius: 3px; padding: 4px 12px; font-size: 11px; "
            f"font-weight: bold; }}"
            f"QPushButton:checked {{ background: {BLUE}; color: white; }}"
        )

        self._work_btn = QPushButton("WORK")
        self._work_btn.setCheckable(True)
        self._work_btn.setChecked(True)
        self._work_btn.setStyleSheet(toggle_style)
        self._work_btn.clicked.connect(lambda: self.set_display_mode(True))
        header.addWidget(self._work_btn)

        self._machine_btn = QPushButton("MACHINE")
        self._machine_btn.setCheckable(True)
        self._machine_btn.setChecked(False)
        self._machine_btn.setStyleSheet(toggle_style)
        self._machine_btn.clicked.connect(lambda: self.set_display_mode(False))
        header.addWidget(self._machine_btn)

        main_layout.addLayout(header)

        # Axis rows
        self._rows: list[_AxisRow] = []
        for i in range(6):
            row = _AxisRow(i)
            row.zero_clicked.connect(self.axis_clicked.emit)
            row.half_clicked.connect(self.axis_clicked.emit)
            self._rows.append(row)
            main_layout.addWidget(row)

        main_layout.addStretch()

    # ------------------------------------------------------------------ #
    def update_positions(
        self, positions: list[float], work_offsets: list[float] | None = None
    ):
        """Update all axis positions.

        Args:
            positions: 6 machine-position floats in mm.
            work_offsets: 6 work-offset floats (subtracted from machine pos).
        """
        if work_offsets is not None:
            self._work_offsets = list(work_offsets)

        for i, row in enumerate(self._rows):
            mpos = positions[i] if i < len(positions) else 0.0
            if self._show_work:
                display = mpos - self._work_offsets[i]
            else:
                display = mpos

            if not self._metric:
                display /= 25.4

            moving = abs(mpos - self._prev_positions[i]) > 0.0005
            row.set_position(display, moving)

        self._prev_positions = list(positions[:6]) + [0.0] * max(0, 6 - len(positions))

    def set_display_mode(self, show_work: bool):
        self._show_work = show_work
        self._work_btn.setChecked(show_work)
        self._machine_btn.setChecked(not show_work)
        # Re-display with current data
        self.update_positions(self._prev_positions)

    def set_units(self, metric: bool):
        self._metric = metric
        for row in self._rows:
            row.set_units(metric)
        self.update_positions(self._prev_positions)

    def set_visible_axes(self, count: int):
        """Show only the first *count* axes (3 or 6)."""
        for i, row in enumerate(self._rows):
            row.setVisible(i < count)

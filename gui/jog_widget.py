"""Jog Control Widget - HORIZONTAL layout for wide placement below 3D view."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QButtonGroup, QRadioButton,
)

STEP_SIZES = [0.01, 0.1, 1.0, 10.0, 100.0]
AXIS_NAMES = ["X", "Y", "Z", "A", "B", "C"]

_KEY_MAP = {
    Qt.Key.Key_Right: (0, 1),
    Qt.Key.Key_Left:  (0, -1),
    Qt.Key.Key_Up:    (1, 1),
    Qt.Key.Key_Down:  (1, -1),
    Qt.Key.Key_PageUp:   (2, 1),
    Qt.Key.Key_PageDown: (2, -1),
}


class JogWidget(QWidget):
    """Jog control panel - horizontal layout with XY cross, Z, ABC, settings."""

    jog_requested = pyqtSignal(int, int, float, float)  # axis, dir, speed, step(0=cont)
    jog_stop_requested = pyqtSignal(int)
    home_requested = pyqtSignal(int)
    zero_all_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._continuous = False
        self._step_size = 1.0
        self._feed_rate = 1000
        self._keys_held: set[int] = set()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("""
            JogWidget {
                background: #16213e;
                border: 1px solid #0f3460;
                border-radius: 4px;
            }
            JogWidget QLabel {
                color: #e94560;
                font-size: 10px;
                font-weight: bold;
                background: transparent;
                border: none;
            }
            JogWidget QPushButton {
                background: #0f3460;
                color: #e0e0e0;
                border: 1px solid #4a9eff;
                border-radius: 3px;
                font-size: 12px;
                font-weight: bold;
                padding: 4px;
                min-width: 40px;
                min-height: 32px;
            }
            JogWidget QPushButton:hover {
                background: #4a9eff;
            }
            JogWidget QPushButton:pressed {
                background: #e94560;
            }
            JogWidget QPushButton:checked {
                background: #4a9eff;
                color: #fff;
            }
            JogWidget QPushButton#home_btn {
                color: #ffd700;
                border-color: #ffd700;
                font-size: 10px;
                min-height: 28px;
            }
            JogWidget QPushButton#home_btn:hover {
                background: #ffd700;
                color: #000;
            }
            JogWidget QRadioButton {
                color: #e0e0e0;
                font-size: 10px;
            }
            JogWidget QRadioButton::indicator { width: 10px; height: 10px; }
            JogWidget QSlider::groove:horizontal {
                background: #0f3460; height: 5px; border-radius: 2px;
            }
            JogWidget QSlider::handle:horizontal {
                background: #4a9eff; width: 12px; margin: -4px 0; border-radius: 6px;
            }
            JogWidget QSlider::sub-page:horizontal {
                background: #4a9eff; border-radius: 2px;
            }
            JogWidget QSpinBox {
                background: #0a0a14; color: #00ff41;
                border: 1px solid #0f3460; border-radius: 2px;
                padding: 1px 3px; font-family: Consolas; font-size: 10px;
            }
            JogWidget QSpinBox::up-button, JogWidget QSpinBox::down-button {
                background: #0f3460; border: none; width: 12px;
            }
        """)

        # ---- MAIN HORIZONTAL LAYOUT ----
        # [Mode] | [XY cross + Z] | [ABC] | [Step/Feed/Home]
        top = QHBoxLayout(self)
        top.setContentsMargins(6, 4, 6, 4)
        top.setSpacing(8)

        # === Section 1: Mode toggle (vertical) ===
        mode_col = QVBoxLayout()
        mode_col.setSpacing(3)
        mode_col.addWidget(QLabel("Mode"))
        self._step_btn = QPushButton("Step")
        self._cont_btn = QPushButton("Cont")
        self._step_btn.setCheckable(True)
        self._cont_btn.setCheckable(True)
        self._step_btn.setChecked(True)
        self._step_btn.clicked.connect(lambda: self._set_mode(False))
        self._cont_btn.clicked.connect(lambda: self._set_mode(True))
        mode_col.addWidget(self._step_btn)
        mode_col.addWidget(self._cont_btn)
        mode_col.addStretch()
        top.addLayout(mode_col)

        # === Section 2: XY cross pad ===
        xy_box = QVBoxLayout()
        xy_box.setSpacing(0)
        xy_box.addWidget(QLabel("XY"))
        xy_grid = QGridLayout()
        xy_grid.setSpacing(2)
        for c in range(3):
            xy_grid.setColumnStretch(c, 1)
            xy_grid.setColumnMinimumWidth(c, 44)
        for r in range(3):
            xy_grid.setRowStretch(r, 1)
            xy_grid.setRowMinimumHeight(r, 36)

        xy_grid.addWidget(self._jog_btn("Y+", 1, 1), 0, 1)
        xy_grid.addWidget(self._jog_btn("X-", 0, -1), 1, 0)
        xy0 = QPushButton("0")
        xy0.clicked.connect(self.zero_all_requested.emit)
        xy_grid.addWidget(xy0, 1, 1)
        xy_grid.addWidget(self._jog_btn("X+", 0, 1), 1, 2)
        xy_grid.addWidget(self._jog_btn("Y-", 1, -1), 2, 1)

        xy_box.addLayout(xy_grid)
        top.addLayout(xy_box)

        # === Section 3: Z column ===
        z_box = QVBoxLayout()
        z_box.setSpacing(0)
        z_box.addWidget(QLabel("Z"))
        z_grid = QVBoxLayout()
        z_grid.setSpacing(2)
        z_grid.addWidget(self._jog_btn("Z+", 2, 1))
        z0 = QPushButton("Z0")
        z_grid.addWidget(z0)
        z_grid.addWidget(self._jog_btn("Z-", 2, -1))
        z_box.addLayout(z_grid)
        top.addLayout(z_box)

        # === Section 4: ABC ===
        abc_box = QVBoxLayout()
        abc_box.setSpacing(0)
        abc_box.addWidget(QLabel("A/B/C"))
        abc_grid = QGridLayout()
        abc_grid.setSpacing(2)
        for i, ax in enumerate([3, 4, 5]):
            name = AXIS_NAMES[ax]
            abc_grid.addWidget(self._jog_btn(f"{name}-", ax, -1), i, 0)
            abc_grid.addWidget(self._jog_btn(f"{name}+", ax, 1), i, 1)
        abc_box.addLayout(abc_grid)
        top.addLayout(abc_box)

        # === Section 5: Step size + Feed rate ===
        settings_col = QVBoxLayout()
        settings_col.setSpacing(2)
        settings_col.addWidget(QLabel("Step (mm)"))

        step_grid = QGridLayout()
        step_grid.setSpacing(1)
        self._step_group = QButtonGroup(self)
        for i, sz in enumerate(STEP_SIZES):
            rb = QRadioButton(str(sz))
            if sz == self._step_size:
                rb.setChecked(True)
            rb.toggled.connect(
                lambda checked, s=sz: self._set_step(s) if checked else None)
            self._step_group.addButton(rb, i)
            step_grid.addWidget(rb, i // 3, i % 3)
        settings_col.addLayout(step_grid)

        settings_col.addWidget(QLabel("Feed"))
        self._feed_slider = QSlider(Qt.Orientation.Horizontal)
        self._feed_slider.setRange(10, 10000)
        self._feed_slider.setValue(self._feed_rate)
        self._feed_slider.valueChanged.connect(self._on_feed_slider)
        settings_col.addWidget(self._feed_slider)
        self._feed_spin = QSpinBox()
        self._feed_spin.setRange(10, 10000)
        self._feed_spin.setValue(self._feed_rate)
        self._feed_spin.setSuffix(" mm/min")
        self._feed_spin.valueChanged.connect(self._on_feed_spin)
        settings_col.addWidget(self._feed_spin)
        top.addLayout(settings_col)

        # === Section 6: Home buttons ===
        home_col = QVBoxLayout()
        home_col.setSpacing(2)
        home_col.addWidget(QLabel("Home"))
        for text, mask in [("All", 0x3F), ("X", 1), ("Y", 2), ("Z", 4)]:
            hb = QPushButton(text)
            hb.setObjectName("home_btn")
            hb.clicked.connect(
                lambda checked, m=mask: self.home_requested.emit(m))
            home_col.addWidget(hb)
        top.addLayout(home_col)

    # ------------------------------------------------------------------
    def _jog_btn(self, text: str, axis: int, direction: int) -> QPushButton:
        btn = QPushButton(text)
        btn.pressed.connect(
            lambda a=axis, d=direction: self._on_jog_pressed(a, d))
        btn.released.connect(
            lambda a=axis: self._on_jog_released(a))
        return btn

    def _set_mode(self, continuous: bool):
        self._continuous = continuous
        self._step_btn.setChecked(not continuous)
        self._cont_btn.setChecked(continuous)

    def _set_step(self, size: float):
        self._step_size = size

    def _on_feed_slider(self, value: int):
        self._feed_rate = value
        self._feed_spin.blockSignals(True)
        self._feed_spin.setValue(value)
        self._feed_spin.blockSignals(False)

    def _on_feed_spin(self, value: int):
        self._feed_rate = value
        self._feed_slider.blockSignals(True)
        self._feed_slider.setValue(value)
        self._feed_slider.blockSignals(False)

    # ------------------------------------------------------------------
    def _on_jog_pressed(self, axis: int, direction: int):
        if self._continuous:
            self.jog_requested.emit(axis, direction, float(self._feed_rate), 0.0)
        else:
            self.jog_requested.emit(
                axis, direction, float(self._feed_rate), self._step_size)

    def _on_jog_released(self, axis: int):
        if self._continuous:
            self.jog_stop_requested.emit(axis)

    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent | None):
        if event is None:
            return
        key = event.key()
        if key in _KEY_MAP and key not in self._keys_held:
            self._keys_held.add(key)
            axis, direction = _KEY_MAP[key]
            self._on_jog_pressed(axis, direction)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent | None):
        if event is None:
            return
        key = event.key()
        if key in _KEY_MAP and not event.isAutoRepeat():
            self._keys_held.discard(key)
            axis, _ = _KEY_MAP[key]
            self._on_jog_released(axis)
            event.accept()
            return
        super().keyReleaseEvent(event)

    # ------------------------------------------------------------------
    def get_step_size(self) -> float:
        return self._step_size

    def get_feed_rate(self) -> int:
        return self._feed_rate

    def set_enabled(self, enabled: bool):
        for child in self.findChildren(QPushButton):
            child.setEnabled(enabled)

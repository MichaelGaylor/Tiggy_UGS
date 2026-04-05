"""Control Widget - file ops, run controls, overrides, spindle/coolant."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QProgressBar,
)

STATE_COLORS = {
    "Idle": "#00ff41", "Run": "#4a9eff", "Hold": "#ffd700",
    "Jog": "#4a9eff", "Homing": "#ffd700", "Alarm": "#e94560",
    "E-Stop": "#e94560", "Probing": "#4a9eff",
}


class ControlWidget(QWidget):
    """Control panel - file operations, run controls, overrides, spindle/coolant."""

    file_open_requested = pyqtSignal()
    run_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    estop_requested = pyqtSignal()
    spindle_changed = pyqtSignal(int, int)       # state, rpm
    coolant_changed = pyqtSignal(int)             # state
    feed_override_changed = pyqtSignal(int)       # percent
    spindle_override_changed = pyqtSignal(int)    # percent
    rapid_override_changed = pyqtSignal(int)      # percent

    def __init__(self, parent=None):
        super().__init__(parent)

        # Scoped stylesheet - won't clash with the global one
        self.setStyleSheet("""
            ControlWidget {
                background: #1a1a2e;
            }
            ControlWidget QLabel {
                color: #e0e0e0;
                background: transparent;
            }
            ControlWidget QLabel#section {
                color: #e94560;
                font-size: 11px;
                font-weight: bold;
            }
            ControlWidget QPushButton {
                background: #0f3460;
                color: #e0e0e0;
                border: 1px solid #4a9eff;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
                padding: 4px 8px;
                min-height: 26px;
            }
            ControlWidget QPushButton:hover {
                background: #4a9eff;
            }
            ControlWidget QPushButton:pressed {
                background: #e94560;
            }
            ControlWidget QPushButton:checked {
                background: #4a9eff;
                color: #fff;
            }
            ControlWidget QPushButton#run_btn {
                background: #0a3d0a;
                color: #00ff41;
                border: 2px solid #00ff41;
                font-size: 14px;
                min-height: 36px;
            }
            ControlWidget QPushButton#run_btn:hover { background: #0f5f0f; }
            ControlWidget QPushButton#run_btn:pressed { background: #00ff41; color: #000; }
            ControlWidget QPushButton#pause_btn {
                background: #3d3d0a;
                color: #ffd700;
                border: 2px solid #ffd700;
                font-size: 14px;
                min-height: 36px;
            }
            ControlWidget QPushButton#pause_btn:hover { background: #5f5f0f; }
            ControlWidget QPushButton#pause_btn:pressed { background: #ffd700; color: #000; }
            ControlWidget QPushButton#stop_btn {
                background: #3d1a0a;
                color: #ff8c00;
                border: 2px solid #ff8c00;
                font-size: 14px;
                min-height: 36px;
            }
            ControlWidget QPushButton#stop_btn:hover { background: #5f2a0f; }
            ControlWidget QPushButton#stop_btn:pressed { background: #ff8c00; color: #000; }
            ControlWidget QPushButton#estop_btn {
                background: #e94560;
                color: white;
                border: 3px solid #ff2040;
                border-radius: 6px;
                font-size: 20px;
                font-weight: bold;
                min-height: 60px;
            }
            ControlWidget QPushButton#estop_btn:hover { background: #ff2040; }
            ControlWidget QPushButton#estop_btn:pressed { background: #cc0030; }
            ControlWidget QProgressBar {
                background: #0a0a14;
                border: 1px solid #0f3460;
                border-radius: 3px;
                text-align: center;
                color: #e0e0e0;
                font-size: 11px;
                min-height: 16px;
            }
            ControlWidget QProgressBar::chunk {
                background: #4a9eff;
                border-radius: 2px;
            }
            ControlWidget QSlider::groove:horizontal {
                background: #0f3460;
                height: 6px;
                border-radius: 3px;
            }
            ControlWidget QSlider::handle:horizontal {
                background: #4a9eff;
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            ControlWidget QSlider::sub-page:horizontal {
                background: #4a9eff;
                border-radius: 3px;
            }
            ControlWidget QSpinBox {
                background: #0a0a14;
                color: #00ff41;
                border: 1px solid #0f3460;
                border-radius: 3px;
                padding: 2px;
                font-family: Consolas;
                font-size: 11px;
            }
            ControlWidget QSpinBox::up-button, ControlWidget QSpinBox::down-button {
                background: #0f3460;
                border: none;
                width: 14px;
            }
        """)

        main = QVBoxLayout(self)
        main.setContentsMargins(6, 6, 6, 6)
        main.setSpacing(4)

        # ---- File section ----
        main.addWidget(self._sec("File"))
        row = QHBoxLayout()
        self._open_btn = QPushButton("Open File")
        self._open_btn.clicked.connect(self.file_open_requested.emit)
        row.addWidget(self._open_btn)
        self._file_label = QLabel("No file loaded")
        self._file_label.setStyleSheet("font-size: 10px;")
        row.addWidget(self._file_label, stretch=1)
        main.addLayout(row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        main.addWidget(self._progress)

        # ---- Run controls ----
        main.addWidget(self._sec("Run Control"))
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._run_btn = QPushButton("\u25b6 RUN")
        self._run_btn.setObjectName("run_btn")
        self._run_btn.clicked.connect(self.run_requested.emit)
        btn_row.addWidget(self._run_btn)
        self._pause_btn = QPushButton("\u275a\u275a PAUSE")
        self._pause_btn.setObjectName("pause_btn")
        self._pause_btn.clicked.connect(self.pause_requested.emit)
        btn_row.addWidget(self._pause_btn)
        self._stop_btn = QPushButton("\u25a0 STOP")
        self._stop_btn.setObjectName("stop_btn")
        self._stop_btn.clicked.connect(self.stop_requested.emit)
        btn_row.addWidget(self._stop_btn)
        main.addLayout(btn_row)

        self._estop_btn = QPushButton("E-STOP")
        self._estop_btn.setObjectName("estop_btn")
        self._estop_btn.clicked.connect(self.estop_requested.emit)
        main.addWidget(self._estop_btn)

        self._state_label = QLabel("IDLE")
        self._state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._state_label.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self._state_label.setStyleSheet(
            "color: #00ff41; background: #0a0a14; border: 1px solid #0f3460; "
            "border-radius: 3px; padding: 4px;")
        main.addWidget(self._state_label)

        # ---- Feed Override ----
        self._feed_label, self._feed_slider = self._add_override(
            main, "Feed Override", self.feed_override_changed,
            [25, 50, 100, 150, 200], 200)

        # ---- Spindle Override ----
        self._spindle_ovr_label, self._spindle_ovr_slider = self._add_override(
            main, "Spindle Override", self.spindle_override_changed,
            [25, 50, 100, 150, 200], 200)

        # ---- Rapid Override ----
        main.addWidget(self._sec("Rapid Override"))
        rap_row = QHBoxLayout()
        rap_row.setSpacing(4)
        self._rapid_btns: list[QPushButton] = []
        for pct in [25, 50, 100]:
            btn = QPushButton(f"{pct}%")
            btn.setCheckable(True)
            btn.setChecked(pct == 100)
            btn.clicked.connect(lambda ch, p=pct: self._on_rapid_preset(p))
            rap_row.addWidget(btn)
            self._rapid_btns.append(btn)
        main.addLayout(rap_row)

        # ---- Spindle Control ----
        main.addWidget(self._sec("Spindle"))
        sp_row = QHBoxLayout()
        sp_row.setSpacing(4)
        self._sp_cw = QPushButton("CW")
        self._sp_ccw = QPushButton("CCW")
        self._sp_off = QPushButton("OFF")
        for btn in (self._sp_cw, self._sp_ccw, self._sp_off):
            btn.setCheckable(True)
        self._sp_off.setChecked(True)
        self._sp_cw.clicked.connect(lambda: self._set_spindle(1))
        self._sp_ccw.clicked.connect(lambda: self._set_spindle(2))
        self._sp_off.clicked.connect(lambda: self._set_spindle(0))
        sp_row.addWidget(self._sp_cw)
        sp_row.addWidget(self._sp_ccw)
        sp_row.addWidget(self._sp_off)
        self._rpm_spin = QSpinBox()
        self._rpm_spin.setRange(0, 30000)
        self._rpm_spin.setValue(1000)
        self._rpm_spin.setSuffix(" RPM")
        sp_row.addWidget(self._rpm_spin)
        main.addLayout(sp_row)

        # ---- Coolant ----
        main.addWidget(self._sec("Coolant"))
        cool_row = QHBoxLayout()
        cool_row.setSpacing(4)
        self._cool_flood = QPushButton("Flood")
        self._cool_mist = QPushButton("Mist")
        self._cool_off = QPushButton("Off")
        for btn in (self._cool_flood, self._cool_mist, self._cool_off):
            btn.setCheckable(True)
        self._cool_off.setChecked(True)
        self._cool_flood.clicked.connect(lambda: self._set_coolant(1))
        self._cool_mist.clicked.connect(lambda: self._set_coolant(2))
        self._cool_off.clicked.connect(lambda: self._set_coolant(0))
        cool_row.addWidget(self._cool_flood)
        cool_row.addWidget(self._cool_mist)
        cool_row.addWidget(self._cool_off)
        main.addLayout(cool_row)

        main.addStretch()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _sec(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("section")
        return lbl

    def _add_override(self, layout, title, signal, presets, range_max):
        layout.addWidget(self._sec(title))
        top = QHBoxLayout()
        lbl = QLabel("100%")
        lbl.setFixedWidth(44)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        lbl.setStyleSheet("color: #00ff41;")
        top.addWidget(lbl)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, range_max)
        slider.setValue(100)
        slider.valueChanged.connect(
            lambda v, lb=lbl, sig=signal: (lb.setText(f"{v}%"), sig.emit(v)))
        top.addWidget(slider, stretch=1)
        layout.addLayout(top)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(3)
        for pct in presets:
            btn = QPushButton(f"{pct}%")
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda ch, v=pct, sl=slider: sl.setValue(v))
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)
        return lbl, slider

    # ------------------------------------------------------------------ actions
    def _on_rapid_preset(self, pct: int):
        for btn in self._rapid_btns:
            btn.setChecked(btn.text() == f"{pct}%")
        self.rapid_override_changed.emit(pct)

    def _set_spindle(self, state: int):
        self._sp_cw.setChecked(state == 1)
        self._sp_ccw.setChecked(state == 2)
        self._sp_off.setChecked(state == 0)
        self.spindle_changed.emit(state, self._rpm_spin.value())

    def _set_coolant(self, state: int):
        self._cool_flood.setChecked(state == 1)
        self._cool_mist.setChecked(state == 2)
        self._cool_off.setChecked(state == 0)
        self.coolant_changed.emit(state)

    # ------------------------------------------------------------------ public
    def update_state(self, state_str: str, alarm_code: int = 0):
        display = state_str.upper()
        if alarm_code:
            display = f"ALARM:{alarm_code}"
        color = STATE_COLORS.get(state_str, "#e0e0e0")
        self._state_label.setText(display)
        self._state_label.setStyleSheet(
            f"color: {color}; background: #0a0a14; border: 1px solid #0f3460; "
            f"border-radius: 3px; padding: 4px;")

    def update_io_state(self, spindle_state: int, spindle_rpm: int, coolant_state: int):
        """Update spindle/coolant button states from status reports."""
        # Update spindle buttons without emitting signals
        self._sp_cw.blockSignals(True)
        self._sp_ccw.blockSignals(True)
        self._sp_off.blockSignals(True)
        self._sp_cw.setChecked(spindle_state == 1)
        self._sp_ccw.setChecked(spindle_state == 2)
        self._sp_off.setChecked(spindle_state == 0)
        self._sp_cw.blockSignals(False)
        self._sp_ccw.blockSignals(False)
        self._sp_off.blockSignals(False)

        if spindle_rpm > 0:
            self._rpm_spin.blockSignals(True)
            self._rpm_spin.setValue(spindle_rpm)
            self._rpm_spin.blockSignals(False)

        # Update coolant buttons
        self._cool_flood.blockSignals(True)
        self._cool_mist.blockSignals(True)
        self._cool_off.blockSignals(True)
        self._cool_flood.setChecked(coolant_state == 1)
        self._cool_mist.setChecked(coolant_state == 2)
        self._cool_off.setChecked(coolant_state == 0)
        self._cool_flood.blockSignals(False)
        self._cool_mist.blockSignals(False)
        self._cool_off.blockSignals(False)

    def update_progress(self, current_line: int, total_lines: int):
        if total_lines > 0:
            pct = int(current_line * 100 / total_lines)
            self._progress.setValue(pct)
            self._progress.setFormat(f"{current_line} / {total_lines}  ({pct}%)")
        else:
            self._progress.setValue(0)

    def set_file_info(self, filename: str, total_lines: int, est_time: float):
        minutes = int(est_time)
        self._file_label.setText(f"{filename} | {total_lines} lines | ~{minutes}min")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)

    def set_overrides(self, feed_pct: int, spindle_pct: int, rapid_pct: int):
        if hasattr(self, "_feed_slider"):
            self._feed_slider.blockSignals(True)
            self._feed_slider.setValue(feed_pct)
            self._feed_label.setText(f"{feed_pct}%")
            self._feed_slider.blockSignals(False)
        if hasattr(self, "_spindle_ovr_slider"):
            self._spindle_ovr_slider.blockSignals(True)
            self._spindle_ovr_slider.setValue(spindle_pct)
            self._spindle_ovr_label.setText(f"{spindle_pct}%")
            self._spindle_ovr_slider.blockSignals(False)
        for btn in self._rapid_btns:
            btn.setChecked(btn.text() == f"{rapid_pct}%")

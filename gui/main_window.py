"""
TiggyUGS Main Window

The central application window that wires together all GUI widgets,
connection backends, the G-code sender, and the motion planner.
"""

import os
import sys
import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QMenuBar, QMenu, QToolBar, QFileDialog, QMessageBox,
    QDialog, QDialogButtonBox, QFormLayout, QComboBox, QLineEdit,
    QSpinBox, QLabel, QGroupBox, QTabWidget, QStatusBar,
    QPushButton, QApplication, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QFont

from gui.dro_widget import DROWidget
from gui.jog_widget import JogWidget
from gui.control_widget import ControlWidget
from gui.console_widget import ConsoleWidget
from gui.status_bar_widget import StatusBarWidget
from gui.visualizer_widget import VisualizerWidget

from core.gcode_parser import parse_file
from core.gcode_sender import GCodeSender
from core.planner import MotionPlanner

from connection.wifi_packet import WiFiPacketConnection
from connection.serial_grbl import SerialGrblConnection
from connection.wifi_grbl import WiFiGrblConnection

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Dark industrial theme stylesheet                                    #
# ------------------------------------------------------------------ #

DARK_THEME_CSS = """
/* ---- base colours ---- */
/* Background: #1a1a2e  Panel: #16213e  Accent: #0f3460
   Highlight: #e94560   Text: #e0e0e0  Green: #00ff41 */

QMainWindow, QDialog, QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
}

/* ---- menu bar ---- */
QMenuBar {
    background-color: #16213e;
    color: #e0e0e0;
    border-bottom: 1px solid #0f3460;
    padding: 2px;
}
QMenuBar::item:selected {
    background-color: #0f3460;
}
QMenu {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #0f3460;
}
QMenu::item:selected {
    background-color: #0f3460;
}
QMenu::separator {
    height: 1px;
    background: #0f3460;
    margin: 4px 8px;
}

/* ---- toolbar ---- */
QToolBar {
    background-color: #16213e;
    border-bottom: 1px solid #0f3460;
    spacing: 4px;
    padding: 2px;
}
QToolBar QToolButton {
    background-color: #0f3460;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    border-radius: 3px;
    padding: 4px 10px;
    min-width: 60px;
    font-weight: bold;
}
QToolBar QToolButton:hover {
    background-color: #1a3a6e;
    border-color: #e94560;
}
QToolBar QToolButton:pressed {
    background-color: #e94560;
}
QToolBar QToolButton:disabled {
    background-color: #1a1a2e;
    color: #555;
}

/* ---- push button ---- */
QPushButton {
    background-color: #0f3460;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    border-radius: 3px;
    padding: 5px 12px;
    min-height: 22px;
}
QPushButton:hover {
    background-color: #1a3a6e;
    border-color: #e94560;
}
QPushButton:pressed {
    background-color: #e94560;
}
QPushButton:disabled {
    background-color: #1a1a2e;
    color: #555;
    border-color: #333;
}

/* ---- labels ---- */
QLabel {
    color: #e0e0e0;
    background-color: transparent;
}

/* ---- line edit ---- */
QLineEdit {
    background-color: #111;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: #e94560;
}
QLineEdit:focus {
    border-color: #e94560;
}

/* ---- combo box ---- */
QComboBox {
    background-color: #0f3460;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    border-radius: 3px;
    padding: 3px 8px;
    min-height: 22px;
}
QComboBox:hover {
    border-color: #e94560;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #16213e;
    color: #e0e0e0;
    selection-background-color: #0f3460;
    border: 1px solid #0f3460;
}

/* ---- spin box ---- */
QSpinBox, QDoubleSpinBox {
    background-color: #111;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    border-radius: 3px;
    padding: 3px 6px;
}
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #e94560;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background-color: #0f3460;
    border: none;
    width: 16px;
}

/* ---- slider ---- */
QSlider::groove:horizontal {
    background: #0f3460;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #e94560;
    width: 14px;
    margin: -4px 0;
    border-radius: 7px;
}
QSlider::groove:vertical {
    background: #0f3460;
    width: 6px;
    border-radius: 3px;
}
QSlider::handle:vertical {
    background: #e94560;
    height: 14px;
    margin: 0 -4px;
    border-radius: 7px;
}

/* ---- progress bar ---- */
QProgressBar {
    background-color: #111;
    border: 1px solid #0f3460;
    border-radius: 3px;
    text-align: center;
    color: #e0e0e0;
    height: 18px;
}
QProgressBar::chunk {
    background-color: #00ff41;
    border-radius: 2px;
}

/* ---- tab widget ---- */
QTabWidget::pane {
    background-color: #16213e;
    border: 1px solid #0f3460;
}
QTabBar::tab {
    background-color: #1a1a2e;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    padding: 5px 12px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #0f3460;
    border-bottom-color: #0f3460;
}
QTabBar::tab:hover {
    background-color: #16213e;
}

/* ---- splitter ---- */
QSplitter::handle {
    background-color: #0f3460;
}
QSplitter::handle:horizontal {
    width: 4px;
}
QSplitter::handle:vertical {
    height: 4px;
}

/* ---- scroll bar ---- */
QScrollBar:vertical {
    background: #1a1a2e;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #0f3460;
    min-height: 20px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #1a1a2e;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #0f3460;
    min-width: 20px;
    border-radius: 4px;
    margin: 2px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ---- group box ---- */
QGroupBox {
    border: 1px solid #0f3460;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 12px;
    color: #e0e0e0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #e94560;
}

/* ---- tool tip ---- */
QToolTip {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #e94560;
    padding: 4px;
}

/* ---- message box / dialog ---- */
QMessageBox {
    background-color: #1a1a2e;
}
QMessageBox QLabel {
    color: #e0e0e0;
}

/* ---- text edit / plain text edit (used in console) ---- */
QTextEdit, QPlainTextEdit {
    background-color: #111;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    border-radius: 3px;
    selection-background-color: #e94560;
}

/* ---- check box ---- */
QCheckBox {
    color: #e0e0e0;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #0f3460;
    border-radius: 3px;
    background-color: #111;
}
QCheckBox::indicator:checked {
    background-color: #e94560;
}

/* ---- radio button ---- */
QRadioButton {
    color: #e0e0e0;
}
QRadioButton::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #0f3460;
    border-radius: 7px;
    background-color: #111;
}
QRadioButton::indicator:checked {
    background-color: #e94560;
}

/* ---- status bar ---- */
QStatusBar {
    background-color: #16213e;
    color: #e0e0e0;
    border-top: 1px solid #0f3460;
}

/* ---- header view (table/tree headers) ---- */
QHeaderView::section {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #0f3460;
    padding: 4px;
}
"""


# ------------------------------------------------------------------ #
#  Connection dialog                                                   #
# ------------------------------------------------------------------ #

class ConnectionDialog(QDialog):
    """Dialog for selecting and configuring a connection type."""

    # Indices matching the combo box order
    TYPE_WIFI_PACKET = 0
    TYPE_SERIAL_GRBL = 1
    TYPE_WIFI_GRBL = 2

    def __init__(self, parent=None, settings: QSettings | None = None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("Connect to Controller")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        # Connection type selector
        type_group = QGroupBox("Connection Type")
        type_layout = QFormLayout(type_group)
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "WiFi Packet (Tiggy)",
            "Serial GRBL",
            "WiFi GRBL",
        ])
        type_layout.addRow("Type:", self.type_combo)
        layout.addWidget(type_group)

        # -- WiFi Packet config --
        self._wp_group = QGroupBox("WiFi Packet Settings")
        wp_lay = QFormLayout(self._wp_group)
        self.wp_ip_edit = QLineEdit()
        self.wp_ip_edit.setPlaceholderText("IP address")
        self.wp_discover_btn = QPushButton("Discover")
        self.wp_discover_btn.clicked.connect(self._on_discover_wifi_packet)
        wp_lay.addRow("IP Address:", self.wp_ip_edit)
        wp_lay.addRow("", self.wp_discover_btn)
        layout.addWidget(self._wp_group)

        # -- Serial GRBL config --
        self._sg_group = QGroupBox("Serial GRBL Settings")
        sg_lay = QFormLayout(self._sg_group)
        self.sg_port_combo = QComboBox()
        self.sg_baud_spin = QSpinBox()
        self.sg_baud_spin.setRange(9600, 2_000_000)
        self.sg_baud_spin.setValue(115200)
        self.sg_refresh_btn = QPushButton("Refresh")
        self.sg_refresh_btn.clicked.connect(self._refresh_serial_ports)
        sg_lay.addRow("Port:", self.sg_port_combo)
        sg_lay.addRow("Baud Rate:", self.sg_baud_spin)
        sg_lay.addRow("", self.sg_refresh_btn)
        layout.addWidget(self._sg_group)

        # -- WiFi GRBL config --
        self._wg_group = QGroupBox("WiFi GRBL Settings")
        wg_lay = QFormLayout(self._wg_group)
        self.wg_ip_edit = QLineEdit()
        self.wg_ip_edit.setPlaceholderText("IP address")
        self.wg_port_spin = QSpinBox()
        self.wg_port_spin.setRange(1, 65535)
        self.wg_port_spin.setValue(23)
        self.wg_discover_btn = QPushButton("Discover")
        self.wg_discover_btn.clicked.connect(self._on_discover_wifi_grbl)
        wg_lay.addRow("IP Address:", self.wg_ip_edit)
        wg_lay.addRow("Port:", self.wg_port_spin)
        wg_lay.addRow("", self.wg_discover_btn)
        layout.addWidget(self._wg_group)

        # Restore saved connection settings
        if self._settings:
            self.wp_ip_edit.setText(
                self._settings.value("conn/wp_ip", "192.168.4.1"))
            self.wg_ip_edit.setText(
                self._settings.value("conn/wg_ip", "192.168.4.1"))
            self.sg_baud_spin.setValue(
                int(self._settings.value("conn/sg_baud", 115200)))
            self.wg_port_spin.setValue(
                int(self._settings.value("conn/wg_port", 23)))
        else:
            self.wp_ip_edit.setText("192.168.4.1")
            self.wg_ip_edit.setText("192.168.4.1")

        # Standard buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        # Wire type changes and restore saved type
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        saved_type = 0
        if self._settings:
            saved_type = int(self._settings.value("conn/type", 0))
        self.type_combo.setCurrentIndex(saved_type)
        self._on_type_changed(saved_type)

    # ---------- dynamic form ----------

    def _on_type_changed(self, index):
        self._wp_group.setVisible(index == self.TYPE_WIFI_PACKET)
        self._sg_group.setVisible(index == self.TYPE_SERIAL_GRBL)
        self._wg_group.setVisible(index == self.TYPE_WIFI_GRBL)
        if index == self.TYPE_SERIAL_GRBL:
            self._refresh_serial_ports()

    # ---------- helpers ----------

    def _refresh_serial_ports(self):
        self.sg_port_combo.clear()
        ports = SerialGrblConnection.list_ports()
        if ports:
            for port, desc in ports:
                self.sg_port_combo.addItem(f"{port} - {desc}", port)
        else:
            self.sg_port_combo.addItem("(no ports found)", "")

    def _on_discover_wifi_packet(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            results = WiFiPacketConnection.discover(timeout=3.0)
            if results:
                ip, info = results[0]
                self.wp_ip_edit.setText(ip)
                name = info.get("device_name", "unknown")
                QMessageBox.information(
                    self, "Discovery", f"Found device: {name} at {ip}"
                )
            else:
                QMessageBox.information(self, "Discovery", "No devices found.")
        except Exception as exc:
            QMessageBox.warning(self, "Discovery Error", str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def _on_discover_wifi_grbl(self):
        """WiFi GRBL discovery is not formally supported; just inform the user."""
        QMessageBox.information(
            self, "Discovery",
            "WiFi GRBL devices do not support automatic discovery.\n"
            "Enter the IP address manually."
        )

    # ---------- public ----------

    def get_connection_config(self) -> dict:
        """Return the chosen connection configuration."""
        idx = self.type_combo.currentIndex()
        if idx == self.TYPE_WIFI_PACKET:
            return {
                "type": "wifi_packet",
                "address": self.wp_ip_edit.text().strip(),
            }
        elif idx == self.TYPE_SERIAL_GRBL:
            port = self.sg_port_combo.currentData() or self.sg_port_combo.currentText()
            return {
                "type": "serial_grbl",
                "address": port,
                "baud": self.sg_baud_spin.value(),
            }
        elif idx == self.TYPE_WIFI_GRBL:
            return {
                "type": "wifi_grbl",
                "address": self.wg_ip_edit.text().strip(),
                "port": self.wg_port_spin.value(),
            }
        return {}


# ------------------------------------------------------------------ #
#  Main window                                                         #
# ------------------------------------------------------------------ #

class MainWindow(QMainWindow):
    APP_NAME = "TiggyUGS"
    APP_VERSION = "1.0.0"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{self.APP_NAME} v{self.APP_VERSION} - Universal G-Code Sender")
        self.setMinimumSize(1280, 800)

        # Core objects
        self.connection = None           # Current ConnectionBase instance
        self.gcode_sender = GCodeSender()
        self.planner = MotionPlanner()
        self.gcode_file = None           # Current loaded GCodeFile
        self.work_offsets = [0.0] * 6    # Work coordinate offsets
        self.last_status = {}

        # Settings persistence
        self.settings = QSettings("Tiggy", "TiggyUGS")

        # Build UI
        self._setup_theme()
        self._create_widgets()
        self._create_layout()
        self._create_menus()
        self._create_toolbar()
        self._connect_signals()
        self._restore_settings()

    # ================================================================
    # Theme
    # ================================================================

    def _setup_theme(self):
        """Apply dark industrial theme to entire application."""
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(DARK_THEME_CSS)

    # ================================================================
    # Widgets
    # ================================================================

    def _create_widgets(self):
        """Create all widget instances."""
        self.dro_widget = DROWidget()
        self.jog_widget = JogWidget()
        self.control_widget = ControlWidget()
        self.console_widget = ConsoleWidget()
        self.status_bar_widget = StatusBarWidget()
        self.visualizer_widget = VisualizerWidget()

    # ================================================================
    # Layout
    # ================================================================

    def _create_layout(self):
        """Build the main window layout.

        Top row:    DRO (left) | 3D Visualizer (center) | Control (right)
        Bottom row: Jog bar (spans under DRO + 3D) | Control continues
        Below:      Console (spans under DRO + 3D) | Control continues
        """
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Outer horizontal splitter: [left+center area] | [right control]
        h_splitter = QSplitter(Qt.Orientation.Horizontal)

        # -- LEFT+CENTER: vertical splitter --
        # Top: DRO | 3D view side by side
        # Middle: Jog bar (full width)
        # Bottom: Console (full width)
        left_center = QSplitter(Qt.Orientation.Vertical)

        # Top section: DRO + 3D side by side
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.dro_widget.setMinimumWidth(320)
        top_splitter.addWidget(self.dro_widget)
        top_splitter.addWidget(self.visualizer_widget)
        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setSizes([320, 600])

        left_center.addWidget(top_splitter)
        left_center.addWidget(self.jog_widget)
        left_center.addWidget(self.console_widget)
        left_center.setStretchFactor(0, 4)
        left_center.setStretchFactor(1, 0)
        left_center.setStretchFactor(2, 1)
        left_center.setSizes([420, 180, 120])

        # -- RIGHT: Control panel (scrollable, full height) --
        right_scroll = QScrollArea()
        right_scroll.setWidget(self.control_widget)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setMinimumWidth(260)

        h_splitter.addWidget(left_center)
        h_splitter.addWidget(right_scroll)
        h_splitter.setStretchFactor(0, 1)
        h_splitter.setStretchFactor(1, 0)
        h_splitter.setSizes([940, 340])

        main_layout.addWidget(h_splitter, 1)
        main_layout.addWidget(self.status_bar_widget)

    # ================================================================
    # Menus
    # ================================================================

    def _create_menus(self):
        """Create the menu bar with all menus and actions."""
        menubar = self.menuBar()

        # ---- File menu ----
        file_menu = menubar.addMenu("&File")

        self.action_open = QAction("&Open G-Code...", self)
        self.action_open.setShortcut(QKeySequence("Ctrl+O"))
        self.action_open.triggered.connect(self._on_open_file)
        file_menu.addAction(self.action_open)

        self.recent_menu = file_menu.addMenu("Recent Files")
        self._rebuild_recent_menu()

        file_menu.addSeparator()

        action_exit = QAction("E&xit", self)
        action_exit.setShortcut(QKeySequence("Ctrl+Q"))
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

        # ---- Connection menu ----
        conn_menu = menubar.addMenu("&Connection")

        self.action_connect = QAction("&Connect...", self)
        self.action_connect.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.action_connect.triggered.connect(self._on_connect)
        conn_menu.addAction(self.action_connect)

        self.action_disconnect = QAction("&Disconnect", self)
        self.action_disconnect.triggered.connect(self._on_disconnect)
        self.action_disconnect.setEnabled(False)
        conn_menu.addAction(self.action_disconnect)

        conn_menu.addSeparator()

        action_conn_settings = QAction("Connection &Settings...", self)
        action_conn_settings.triggered.connect(self._on_connect)
        conn_menu.addAction(action_conn_settings)

        # ---- Machine menu ----
        machine_menu = menubar.addMenu("&Machine")

        action_home = QAction("&Home All", self)
        action_home.triggered.connect(lambda: self._safe_conn_call("home", axis_mask=0x3F))
        machine_menu.addAction(action_home)

        action_reset = QAction("&Reset", self)
        action_reset.triggered.connect(lambda: self._safe_conn_call("reset"))
        machine_menu.addAction(action_reset)

        self.action_estop = QAction("&E-Stop", self)
        self.action_estop.setShortcut(QKeySequence("Escape"))
        self.action_estop.triggered.connect(self._on_estop)
        machine_menu.addAction(self.action_estop)

        machine_menu.addSeparator()

        action_zero_all = QAction("&Zero All Work Coords", self)
        action_zero_all.triggered.connect(self._on_zero_all)
        machine_menu.addAction(action_zero_all)

        # ---- View menu ----
        view_menu = menubar.addMenu("&View")

        action_top = QAction("&Top View", self)
        action_top.triggered.connect(self.visualizer_widget.set_view_top)
        view_menu.addAction(action_top)

        action_front = QAction("&Front View", self)
        action_front.triggered.connect(self.visualizer_widget.set_view_front)
        view_menu.addAction(action_front)

        action_right = QAction("&Right View", self)
        action_right.triggered.connect(self.visualizer_widget.set_view_right)
        view_menu.addAction(action_right)

        action_iso = QAction("&Isometric View", self)
        action_iso.triggered.connect(self.visualizer_widget.set_view_iso)
        view_menu.addAction(action_iso)

        action_fit = QAction("Fit to &View", self)
        action_fit.triggered.connect(self.visualizer_widget.fit_view)
        view_menu.addAction(action_fit)

        view_menu.addSeparator()

        self.action_show_rapids = QAction("Show &Rapids", self)
        self.action_show_rapids.setCheckable(True)
        self.action_show_rapids.setChecked(True)
        view_menu.addAction(self.action_show_rapids)

        self.action_show_grid = QAction("Show &Grid", self)
        self.action_show_grid.setCheckable(True)
        self.action_show_grid.setChecked(True)
        view_menu.addAction(self.action_show_grid)

        # ---- Help menu ----
        help_menu = menubar.addMenu("&Help")

        action_about = QAction("&About", self)
        action_about.triggered.connect(self._on_about)
        help_menu.addAction(action_about)

    def _rebuild_recent_menu(self):
        """Populate the Recent Files sub-menu from settings."""
        self.recent_menu.clear()
        recent = self.settings.value("recentFiles", []) or []
        if not recent:
            no_action = self.recent_menu.addAction("(no recent files)")
            no_action.setEnabled(False)
            return
        for filepath in recent:
            action = self.recent_menu.addAction(os.path.basename(filepath))
            # Capture filepath by default arg in lambda
            action.triggered.connect(lambda checked, fp=filepath: self._load_gcode_file(fp))

    # ================================================================
    # Toolbar
    # ================================================================

    def _create_toolbar(self):
        """Create the main toolbar."""
        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        self.tb_connect = toolbar.addAction("Connect")
        self.tb_connect.triggered.connect(self._on_connect)

        self.tb_disconnect = toolbar.addAction("Disconnect")
        self.tb_disconnect.triggered.connect(self._on_disconnect)
        self.tb_disconnect.setEnabled(False)

        toolbar.addSeparator()

        self.tb_open = toolbar.addAction("Open")
        self.tb_open.triggered.connect(self._on_open_file)

        toolbar.addSeparator()

        self.tb_run = toolbar.addAction("Run")
        self.tb_run.triggered.connect(self._on_run)

        self.tb_pause = toolbar.addAction("Pause")
        self.tb_pause.triggered.connect(self._on_pause)

        self.tb_stop = toolbar.addAction("Stop")
        self.tb_stop.triggered.connect(self._on_stop)

        toolbar.addSeparator()

        self.tb_estop = toolbar.addAction("E-STOP")
        self.tb_estop.triggered.connect(self._on_estop)
        # Style the E-Stop button red after it's added
        for widget in toolbar.findChildren(QWidget):
            # The last QToolButton contains E-STOP
            pass
        # Apply red style directly via the toolbar
        toolbar.setStyleSheet(
            toolbar.styleSheet() +
            """
            QToolBar QToolButton#estop_btn {
                background-color: #c0392b;
                color: white;
                font-weight: bold;
            }
            """
        )
        # Find the actual E-STOP button widget to name it
        buttons = toolbar.findChildren(QPushButton)
        # QToolBar uses QToolButton, so find all children of toolbar
        from PyQt6.QtWidgets import QToolButton
        for btn in toolbar.findChildren(QToolButton):
            if btn.text() == "E-STOP":
                btn.setObjectName("estop_btn")
                btn.setStyleSheet(
                    "background-color: #c0392b; color: white; font-weight: bold; "
                    "border: 2px solid #e74c3c; min-width: 70px;"
                )
                break

    # ================================================================
    # Signal wiring
    # ================================================================

    def _connect_signals(self):
        """Wire all signals between widgets and core objects."""

        # --- Control widget signals ---
        self.control_widget.file_open_requested.connect(self._on_open_file)
        self.control_widget.run_requested.connect(self._on_run)
        self.control_widget.pause_requested.connect(self._on_pause)
        self.control_widget.stop_requested.connect(self._on_stop)
        self.control_widget.estop_requested.connect(self._on_estop)
        self.control_widget.spindle_changed.connect(self._on_spindle_changed)
        self.control_widget.coolant_changed.connect(self._on_coolant_changed)
        self.control_widget.feed_override_changed.connect(self._on_feed_override_changed)
        self.control_widget.spindle_override_changed.connect(self._on_spindle_override_changed)
        self.control_widget.rapid_override_changed.connect(self._on_rapid_override_changed)

        # --- Jog widget signals ---
        self.jog_widget.jog_requested.connect(self._on_jog_requested)
        self.jog_widget.jog_stop_requested.connect(self._on_jog_stop_requested)
        self.jog_widget.home_requested.connect(self._on_home_requested)
        self.jog_widget.zero_all_requested.connect(self._on_zero_all)

        # --- Console signals ---
        self.console_widget.command_submitted.connect(self._on_command_submitted)

        # --- DRO signals ---
        self.dro_widget.axis_clicked.connect(self._on_axis_clicked)

        # --- Visualizer signals ---
        self.visualizer_widget.line_selected.connect(self._on_visualizer_line_selected)

        # --- Sender signals ---
        self.gcode_sender.progress_updated.connect(self._on_sender_progress)
        self.gcode_sender.line_sent.connect(self._on_sender_line_sent)
        self.gcode_sender.completed.connect(self._on_send_completed)
        self.gcode_sender.error_occurred.connect(self.console_widget.append_error)
        self.gcode_sender.state_changed.connect(self._on_sender_state_changed)

    # ================================================================
    # Connection signal management
    # ================================================================

    def _connect_connection_signals(self):
        """Connect signals from the current connection object."""
        if not self.connection:
            return
        self.connection.connected.connect(self._on_connected)
        self.connection.disconnected.connect(self._on_disconnected)
        self.connection.status_updated.connect(self._on_status_updated)
        self.connection.error_occurred.connect(self.console_widget.append_error)
        self.connection.response_received.connect(self.console_widget.append_response)

    def _disconnect_connection_signals(self):
        """Disconnect signals from the old connection."""
        if not self.connection:
            return
        try:
            self.connection.connected.disconnect()
            self.connection.disconnected.disconnect()
            self.connection.status_updated.disconnect()
            self.connection.error_occurred.disconnect()
            self.connection.response_received.disconnect()
        except (TypeError, RuntimeError):
            pass

    # ================================================================
    # Event handlers - connection
    # ================================================================

    def _on_connect(self):
        """Show connection dialog and connect."""
        dialog = ConnectionDialog(self, settings=self.settings)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        config = dialog.get_connection_config()
        conn_type = config.get("type", "")
        address = config.get("address", "")

        # Save connection settings for next time (use try/except because
        # Qt may have deleted widgets for non-selected connection types)
        self.settings.setValue("conn/type", dialog.type_combo.currentIndex())
        try:
            self.settings.setValue("conn/wp_ip", dialog.wp_ip_edit.text().strip())
        except RuntimeError:
            pass
        try:
            self.settings.setValue("conn/wg_ip", dialog.wg_ip_edit.text().strip())
        except RuntimeError:
            pass
        try:
            self.settings.setValue("conn/sg_baud", dialog.sg_baud_spin.value())
        except RuntimeError:
            pass
        try:
            self.settings.setValue("conn/wg_port", dialog.wg_port_spin.value())
        except RuntimeError:
            pass

        if not address:
            QMessageBox.warning(self, "Error", "No address specified.")
            return

        # Tear down any existing connection
        if self.connection and self.connection.is_connected:
            self._disconnect_connection_signals()
            self.connection.disconnect_from()

        # Create the appropriate connection backend
        if conn_type == "wifi_packet":
            self.connection = WiFiPacketConnection()
        elif conn_type == "serial_grbl":
            self.connection = SerialGrblConnection()
        elif conn_type == "wifi_grbl":
            self.connection = WiFiGrblConnection()
        else:
            QMessageBox.warning(self, "Error", f"Unknown connection type: {conn_type}")
            return

        # Wire up connection signals
        self._connect_connection_signals()

        # Configure sender with connection and planner
        self.gcode_sender.set_connection(self.connection)
        self.gcode_sender.set_planner(self.planner)

        # Attempt to connect
        self.console_widget.append_info(f"Connecting to {address} ({conn_type})...")
        try:
            kwargs = {}
            if conn_type == "serial_grbl":
                kwargs["baud"] = config.get("baud", 115200)
            elif conn_type == "wifi_grbl":
                kwargs["port"] = config.get("port", 23)
            self.connection.connect_to(address, **kwargs)
        except Exception as exc:
            self.console_widget.append_error(f"Connection failed: {exc}")
            QMessageBox.warning(self, "Connection Error", str(exc))

    def _on_disconnect(self):
        """Disconnect from the controller."""
        if self.connection and self.connection.is_connected:
            self.connection.disconnect_from()

    def _on_connected(self, device_info: dict):
        """Handle successful connection."""
        conn_type = self.connection.connection_type if self.connection else ""
        address = device_info.get("address", "")
        self.status_bar_widget.update_connection(True, conn_type, address)
        self.console_widget.append_info(f"Connected via {conn_type} to {address}")

        name = device_info.get("device_name", "")
        fw = device_info.get("firmware_version", "")
        axes = device_info.get("num_axes", 6)
        if name or fw:
            self.console_widget.append_info(f"Device: {name}, FW: {fw}, Axes: {axes}")
        self.dro_widget.set_visible_axes(axes)

        # Update toolbar / menu enabled states
        self.action_disconnect.setEnabled(True)
        self.tb_disconnect.setEnabled(True)
        self.action_connect.setEnabled(False)
        self.tb_connect.setEnabled(False)

        # If WiFi Packet, read steps_per_mm and configure the planner
        if isinstance(self.connection, WiFiPacketConnection):
            self._configure_planner_from_device()

        # Send reset + feed_resume to clear any Hold state from boot/reconnect
        QTimer.singleShot(500, self._clear_hold_state)

        # Auto-zero work offsets on connect so DRO starts at 0,0,0
        self._auto_zero_on_connect = True

    def _configure_planner_from_device(self):
        """Read steps_per_mm from a WiFi Packet device and configure planner."""
        if not isinstance(self.connection, WiFiPacketConnection):
            return
        steps = list(self.connection.steps_per_mm)
        self.planner.configure(steps_per_mm=steps)
        self.console_widget.append_info(
            f"Planner configured: steps/mm = "
            f"[{', '.join(f'{s:.1f}' for s in steps)}]"
        )

    def _on_disconnected(self):
        """Handle disconnection."""
        self.status_bar_widget.update_connection(False)
        self.console_widget.append_info("Disconnected")

        # Update toolbar / menu
        self.action_disconnect.setEnabled(False)
        self.tb_disconnect.setEnabled(False)
        self.action_connect.setEnabled(True)
        self.tb_connect.setEnabled(True)

    # ================================================================
    # Event handlers - status
    # ================================================================

    def _on_status_updated(self, status: dict):
        """Handle status update from connection."""
        self.last_status = status
        positions = status.get("positions", [0.0] * 6)
        pos_type = status.get("position_type", "MPos")

        # Auto-zero work offsets on first status after connect
        if getattr(self, '_auto_zero_on_connect', False):
            self._auto_zero_on_connect = False
            if pos_type != "WPos":
                self.work_offsets = list(positions)
                self.console_widget.append_info("Work offsets zeroed to current position")

        # DRO always gets machine positions + work offsets
        self.dro_widget.update_positions(positions, self.work_offsets)
        self.status_bar_widget.update_status(status)

        if len(positions) >= 3:
            if pos_type == "WPos":
                # GRBL WPos: already work coordinates, use directly
                self.visualizer_widget.set_tool_position(
                    positions[0], positions[1], positions[2])
            else:
                # MPos (WiFi Packet or GRBL MPos): subtract work offsets
                wx = positions[0] - self.work_offsets[0]
                wy = positions[1] - self.work_offsets[1]
                wz = positions[2] - self.work_offsets[2]
                self.visualizer_widget.set_tool_position(wx, wy, wz)

        state_str = status.get("state", "Unknown")
        alarm = status.get("alarm_code", 0)
        self.control_widget.update_state(state_str, alarm)

        # Update spindle/coolant display from actual controller state
        self.control_widget.update_io_state(
            status.get("spindle_state", 0),
            status.get("spindle_rpm", 0),
            status.get("coolant_state", 0),
        )

    # ================================================================
    # Event handlers - file
    # ================================================================

    def _on_open_file(self):
        """Open a G-code file via file dialog."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Open G-Code File",
            self.settings.value("lastDir", ""),
            "G-Code Files (*.nc *.gcode *.ngc *.tap *.txt *.gc *.cnc *.ncc);;All Files (*)",
        )
        if filepath:
            self.settings.setValue("lastDir", os.path.dirname(filepath))
            self._load_gcode_file(filepath)

    def _load_gcode_file(self, filepath):
        """Load and display a G-code file."""
        if not os.path.isfile(filepath):
            QMessageBox.warning(self, "Error", f"File not found:\n{filepath}")
            return
        try:
            self.gcode_file = parse_file(filepath)
            self.visualizer_widget.load_gcode(self.gcode_file)
            self.visualizer_widget.fit_view()
            self.control_widget.set_file_info(
                os.path.basename(filepath),
                self.gcode_file.total_lines,
                self.gcode_file.estimated_time,
            )
            self.gcode_sender.load_file(self.gcode_file)
            self.console_widget.append_info(
                f"Loaded: {os.path.basename(filepath)} "
                f"({self.gcode_file.total_lines} lines, "
                f"{self.gcode_file.motion_lines} moves)"
            )
            self._add_recent_file(filepath)
            self._rebuild_recent_menu()
            # Update window title
            self.setWindowTitle(
                f"{self.APP_NAME} v{self.APP_VERSION} - {os.path.basename(filepath)}"
            )
        except Exception as exc:
            logger.exception("Failed to load G-code file")
            QMessageBox.warning(self, "Error", f"Failed to load file:\n{exc}")

    # ================================================================
    # Event handlers - run / pause / stop
    # ================================================================

    def _clear_hold_state(self):
        """Send feed_resume to clear Hold state after connection."""
        if self.connection and self.connection.is_connected:
            state = self.last_status.get('state', '')
            if state == 'Hold':
                self.connection.feed_resume()
                self.console_widget.append_info("Sent feed resume to clear Hold state")

    def _on_run(self):
        """Start sending G-code."""
        if not self.connection or not self.connection.is_connected:
            QMessageBox.warning(self, "Not Connected", "Connect to a controller first.")
            return
        if not self.gcode_file:
            QMessageBox.warning(self, "No File", "Open a G-code file first.")
            return
        # Clear hold state before starting
        state = self.last_status.get('state', '')
        if state == 'Hold':
            self.connection.feed_resume()
        self.gcode_sender.start()

    def _on_pause(self):
        """Pause G-code sending and issue feed hold."""
        self.gcode_sender.pause()
        if self.connection and self.connection.is_connected:
            self.connection.feed_hold()

    def _on_stop(self):
        """Stop G-code sending and flush the controller's buffer."""
        self.gcode_sender.stop()
        if self.connection and self.connection.is_connected:
            # Reset flushes the motion buffer so the machine actually stops
            self.connection.reset()
            self.console_widget.append_info("Stop: reset sent to flush buffer")

    def _on_estop(self):
        """Emergency stop - highest priority."""
        if self.connection and self.connection.is_connected:
            self.connection.estop()
        self.gcode_sender.stop()
        self.console_widget.append_error("E-STOP activated!")

    # ================================================================
    # Event handlers - sender feedback
    # ================================================================

    def _on_sender_progress(self, current_line, total_lines):
        """Sender progress callback (already throttled by sender to ~4/sec)."""
        self.control_widget.update_progress(current_line, total_lines)
        self.visualizer_widget.set_current_line(current_line)

    def _on_sender_line_sent(self, line_number, line_text):
        """A line was sent (already throttled by sender to ~4/sec)."""
        self.console_widget.append_sent(f"N{line_number}: {line_text}")

    def _on_send_completed(self):
        """G-code sending completed."""
        self.console_widget.append_info("Program completed!")
        self.control_widget.update_state("Idle")

    def _on_sender_state_changed(self, state_str):
        """Sender state changed."""
        self.control_widget.update_state(state_str)

    # ================================================================
    # Event handlers - jog
    # ================================================================

    def _on_jog_requested(self, axis, direction, speed, step_size):
        """Handle jog request from the jog widget.

        step_size > 0: step mode - send a motion segment for precise distance.
        step_size == 0: continuous mode - use firmware jog command.
        """
        if not self.connection or not self.connection.is_connected:
            return

        # Check machine state before jogging
        state = self.last_status.get('state', 'Unknown')
        if state in ('E-Stop', 'Alarm'):
            self.connection.reset()
            self.console_widget.append_info(
                f"Sent reset to clear {state} state before jogging")
            return
        if state == 'Hold':
            self.connection.feed_resume()

        if step_size > 0 and isinstance(self.connection, WiFiPacketConnection):
            # Step mode: send a precise motion segment
            spm = self.connection.steps_per_mm[axis] if axis < 6 else 800.0
            steps = int(step_size * spm * direction)
            speed_stps = int(speed / 60.0 * spm)
            if steps == 0:
                return
            duration_us = max(1000, int(abs(steps) / max(speed_stps, 1) * 1_000_000))
            seg = {
                'steps': [(steps if i == axis else 0) for i in range(6)],
                'duration_us': duration_us,
                'entry_speed_sqr': 0,
                'exit_speed_sqr': 0,
                'acceleration': min(int(5000 * 100), 0xFFFFFFFF),
                'segment_id': 0,
                'flags': 0x0A,  # LAST | EXACT_STOP
            }
            try:
                self.connection.send_motion_segments([seg])
            except Exception as exc:
                self.console_widget.append_error(f"Jog error: {exc}")
        else:
            # Continuous mode: use firmware jog command
            self.connection.jog(axis, direction, speed)

    def _on_jog_stop_requested(self, axis):
        """Handle jog stop request."""
        if self.connection and self.connection.is_connected:
            self.connection.jog_stop(axis)

    def _on_home_requested(self, axis):
        """Handle home request from the jog widget."""
        if self.connection and self.connection.is_connected:
            # axis == -1 means home all, otherwise create a bitmask
            if axis < 0:
                self.connection.home(axis_mask=0x3F)
            else:
                self.connection.home(axis_mask=(1 << axis))

    # ================================================================
    # Event handlers - spindle / coolant / overrides
    # ================================================================

    def _on_spindle_changed(self, state, rpm):
        """Handle spindle state change from control widget."""
        if self.connection and self.connection.is_connected:
            coolant = self.last_status.get("coolant_state", 0)
            self.connection.set_io(
                spindle_state=state, spindle_rpm=rpm, coolant_state=coolant
            )

    def _on_coolant_changed(self, state):
        """Handle coolant state change from control widget."""
        if self.connection and self.connection.is_connected:
            sp_state = self.last_status.get("spindle_state", 0)
            sp_rpm = self.last_status.get("spindle_rpm", 0)
            self.connection.set_io(
                spindle_state=sp_state, spindle_rpm=sp_rpm, coolant_state=state
            )

    def _on_feed_override_changed(self, percent):
        """Handle feed override from control widget."""
        if self.connection and self.connection.is_connected:
            self.connection.set_feed_override(percent)
        self.gcode_sender.set_feed_override(percent)

    def _on_spindle_override_changed(self, percent):
        """Handle spindle override from control widget."""
        if self.connection and self.connection.is_connected:
            self.connection.set_spindle_override(percent)

    def _on_rapid_override_changed(self, percent):
        """Handle rapid override from control widget."""
        if self.connection and self.connection.is_connected:
            self.connection.set_rapid_override(percent)

    # ================================================================
    # Event handlers - console
    # ================================================================

    def _on_command_submitted(self, text):
        """Handle manual command from the console."""
        if not self.connection or not self.connection.is_connected:
            self.console_widget.append_error("Not connected")
            return
        self.connection.send_gcode_line(text)
        self.console_widget.append_sent(text)

    # ================================================================
    # Event handlers - DRO / visualizer
    # ================================================================

    def _on_axis_clicked(self, axis_index):
        """Handle axis label click in DRO (zero that axis work offset)."""
        positions = self.last_status.get("positions", [0.0] * 6)
        if 0 <= axis_index < len(self.work_offsets) and axis_index < len(positions):
            self.work_offsets[axis_index] = positions[axis_index]
            self.dro_widget.update_positions(positions, self.work_offsets)

    def _on_visualizer_line_selected(self, line_number):
        """Handle line selection in the 3D visualizer."""
        self.console_widget.append_info(f"Selected line: {line_number}")

    def _on_zero_all(self):
        """Zero all work coordinates."""
        positions = self.last_status.get("positions", [0.0] * 6)
        self.work_offsets = list(positions)
        self.dro_widget.update_positions(positions, self.work_offsets)
        self.console_widget.append_info("All work coordinates zeroed")

    # ================================================================
    # Helpers
    # ================================================================

    def _safe_conn_call(self, method_name, **kwargs):
        """Call a method on self.connection if connected."""
        if self.connection and self.connection.is_connected:
            method = getattr(self.connection, method_name, None)
            if method:
                try:
                    method(**kwargs)
                except Exception as exc:
                    self.console_widget.append_error(f"{method_name} failed: {exc}")
        else:
            self.console_widget.append_error("Not connected")

    def _on_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            f"About {self.APP_NAME}",
            f"<h2>{self.APP_NAME} v{self.APP_VERSION}</h2>"
            f"<p>Universal G-Code Sender for CNC controllers.</p>"
            f"<p>Supports WiFi Packet (Tiggy), Serial GRBL, and WiFi GRBL connections.</p>"
            f"<p>Built with PyQt6.</p>",
        )

    # ================================================================
    # Settings persistence
    # ================================================================

    def _restore_settings(self):
        """Restore window geometry and recent files from QSettings."""
        geom = self.settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)

    def _save_settings(self):
        """Save window geometry and settings."""
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())

    def _add_recent_file(self, filepath):
        """Add a file to the recent files list."""
        recent = self.settings.value("recentFiles", []) or []
        if isinstance(recent, str):
            recent = [recent]
        if filepath in recent:
            recent.remove(filepath)
        recent.insert(0, filepath)
        recent = recent[:10]
        self.settings.setValue("recentFiles", recent)

    # ================================================================
    # Window lifecycle
    # ================================================================

    def closeEvent(self, event):
        """Clean up on window close."""
        self._save_settings()
        # Stop any running send
        self.gcode_sender.stop()
        # Disconnect
        if self.connection and self.connection.is_connected:
            try:
                self.connection.disconnect_from()
            except Exception:
                pass
        event.accept()

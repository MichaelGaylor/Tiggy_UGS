"""
TiggyUGS - Universal G-Code Sender
Entry point for the application.
"""

import sys
import os
import signal
import logging
import atexit
import subprocess

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont

from gui.main_window import MainWindow

_window = None
_cleaned_up = False


def _cleanup():
    """Ensure connections are closed on exit."""
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True
    if _window is not None:
        try:
            if _window.connection and _window.connection.is_connected:
                _window.connection.disconnect_from()
        except Exception:
            pass


def _signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM gracefully."""
    _cleanup()
    sys.exit(0)


def _kill_zombie_sockets():
    """Kill any zombie Python processes holding our UDP status port (58428).
    This prevents the common issue where a crashed TiggyUGS leaves a process
    in CLOSE_WAIT state holding the port, blocking status updates."""
    if sys.platform != 'win32':
        return
    try:
        my_pid = os.getpid()
        result = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            if '58428' not in line:
                continue
            if 'UDP' not in line and 'CLOSE_WAIT' not in line:
                continue
            parts = line.split()
            if len(parts) >= 5:
                try:
                    pid = int(parts[-1])
                    if pid != my_pid and pid > 0:
                        subprocess.run(
                            ['taskkill', '/PID', str(pid), '/F'],
                            capture_output=True, timeout=5)
                        logging.getLogger(__name__).info(
                            "Killed zombie process %d holding port 58428", pid)
                except (ValueError, subprocess.TimeoutExpired):
                    pass
    except Exception:
        pass


def main():
    global _window

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Kill zombie processes from previous crashes
    _kill_zombie_sockets()

    # Register cleanup handlers
    atexit.register(_cleanup)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    app = QApplication(sys.argv)
    app.setApplicationName("TiggyUGS")
    app.setOrganizationName("Tiggy")
    app.setApplicationVersion("1.0.0")

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    _window = MainWindow()
    _window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

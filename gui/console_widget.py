"""Console Widget - command input and response log for manual G-code entry."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QLineEdit, QLabel,
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

MAX_LINES = 5000
HISTORY_SIZE = 50
FONT_FAMILY = "Consolas"
FONT_SIZE = 10


class ConsoleWidget(QWidget):
    """Console - command input and response log."""

    command_submitted = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._history_index = -1

        self.setStyleSheet(f"ConsoleWidget {{ background: {BG}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QLabel("CONSOLE")
        header.setStyleSheet(
            f"color: {TEXT}; font-size: 11px; font-weight: bold; "
            f"background: transparent; padding: 2px;"
        )
        layout.addWidget(header)

        # Log display
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(MAX_LINES)
        self._log.setFont(QFont(FONT_FAMILY, FONT_SIZE))
        self._log.setStyleSheet(
            f"QPlainTextEdit {{ background: #0a0a14; color: {TEXT}; "
            f"border: 1px solid {ACCENT}; border-radius: 3px; "
            f"selection-background-color: {ACCENT}; }}"
            f"QScrollBar:vertical {{ background: {PANEL}; width: 10px; "
            f"border-radius: 5px; }}"
            f"QScrollBar::handle:vertical {{ background: {ACCENT}; "
            f"border-radius: 5px; min-height: 20px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ "
            f"height: 0; }}"
        )
        layout.addWidget(self._log, stretch=1)

        # Input line
        input_row = QHBoxLayout()
        input_row.setSpacing(4)

        prompt = QLabel(">")
        prompt.setFixedWidth(16)
        prompt.setStyleSheet(
            f"color: {GREEN}; font-family: {FONT_FAMILY}; font-size: 13px; "
            f"font-weight: bold; background: transparent;"
        )
        prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        input_row.addWidget(prompt)

        self._input = QLineEdit()
        self._input.setFont(QFont(FONT_FAMILY, FONT_SIZE))
        self._input.setPlaceholderText("Type G-code command...")
        self._input.setStyleSheet(
            f"QLineEdit {{ background: #0a0a14; color: {GREEN}; "
            f"border: 1px solid {ACCENT}; border-radius: 3px; padding: 4px 6px; "
            f"selection-background-color: {ACCENT}; }}"
            f"QLineEdit:focus {{ border-color: {BLUE}; }}"
        )
        self._input.returnPressed.connect(self._on_submit)
        input_row.addWidget(self._input, stretch=1)

        layout.addLayout(input_row)

        # Pre-build text formats
        self._fmt_sent = self._make_format(TEXT)
        self._fmt_response = self._make_format(GREEN)
        self._fmt_error = self._make_format(HIGHLIGHT)
        self._fmt_info = self._make_format(BLUE)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _make_format(color: str) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        return fmt

    def _append(self, text: str, fmt: QTextCharFormat):
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n", fmt)
        self._log.setTextCursor(cursor)
        self._log.ensureCursorVisible()

    def _on_submit(self):
        text = self._input.text().strip()
        if not text:
            return
        # Add to history
        if not self._history or self._history[-1] != text:
            self._history.append(text)
            if len(self._history) > HISTORY_SIZE:
                self._history.pop(0)
        self._history_index = -1

        self.append_sent(f"> {text}")
        self.command_submitted.emit(text)
        self._input.clear()

    # ------------------------------------------------------------------ keyboard nav
    def keyPressEvent(self, event):
        if event is None:
            return
        # Only intercept when input has focus
        if self._input.hasFocus():
            if event.key() == Qt.Key.Key_Up:
                self._navigate_history(-1)
                return
            if event.key() == Qt.Key.Key_Down:
                self._navigate_history(1)
                return
        super().keyPressEvent(event)

    def _navigate_history(self, direction: int):
        if not self._history:
            return
        if self._history_index == -1:
            if direction == -1:
                self._history_index = len(self._history) - 1
            else:
                return
        else:
            self._history_index += direction
            if self._history_index < 0:
                self._history_index = 0
            elif self._history_index >= len(self._history):
                self._history_index = -1
                self._input.clear()
                return
        self._input.setText(self._history[self._history_index])

    # ------------------------------------------------------------------ public API
    def append_sent(self, text: str):
        """Append sent command text (white)."""
        self._append(text, self._fmt_sent)

    def append_response(self, text: str):
        """Append response text (green)."""
        self._append(text, self._fmt_response)

    def append_error(self, text: str):
        """Append error text (red)."""
        self._append(text, self._fmt_error)

    def append_info(self, text: str):
        """Append informational text (blue)."""
        self._append(text, self._fmt_info)

    def clear(self):
        """Clear the log display."""
        self._log.clear()

    def set_focus_input(self):
        """Set keyboard focus to the input line."""
        self._input.setFocus()

"""
TiggyUGS G-Code Sender

Streaming engine that sends G-code to a CNC controller via any
connection backend (serial/GRBL, WiFi packets, etc.).
"""

import logging
import time
from enum import Enum

from PyQt6.QtCore import QObject, QThread, pyqtSignal, QMutex, QMutexLocker, QWaitCondition

from core.gcode_parser import GCodeFile, GCodeLine

logger = logging.getLogger(__name__)


class SenderState(str, Enum):
    IDLE = 'idle'
    RUNNING = 'running'
    PAUSED = 'paused'
    STOPPING = 'stopping'


# GRBL RX buffer size in bytes (standard is 128, some builds use 256)
GRBL_RX_BUFFER_SIZE = 128
# Safety margin to leave in the GRBL buffer
GRBL_RX_BUFFER_MARGIN = 8
# Maximum time to wait for an 'ok' from GRBL before timing out (seconds)
GRBL_OK_TIMEOUT = 30.0
# WiFi buffer fill threshold (percentage) at which we pause sending.
# Keep this high (95%) to avoid motion stalls - the ESP32 has a 127 slot
# ring buffer and we want to keep it nearly full for smooth motion.
WIFI_BUFFER_HIGH_WATER = 95
# WiFi buffer fill threshold (percentage) at which we resume sending
WIFI_BUFFER_LOW_WATER = 50


class _SenderWorker(QObject):
    """Worker that runs in a background thread to send G-code lines.

    Supports two sending modes:
      - GRBL character-counting protocol (for serial connections)
      - WiFi packet protocol (converts to motion segments via planner)
    """

    progress_updated = pyqtSignal(int, int)
    line_sent = pyqtSignal(int, str)
    completed = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, connection, gcode_file: GCodeFile, start_line: int,
                 feed_override_func, planner=None):
        super().__init__()
        self.connection = connection
        self.gcode_file = gcode_file
        self.start_line = start_line
        self._feed_override_func = feed_override_func
        self.planner = planner

        self._mutex = QMutex()
        self._pause_condition = QWaitCondition()
        self._paused = False
        self._stop_requested = False

    def request_pause(self):
        with QMutexLocker(self._mutex):
            self._paused = True
        # Send feed hold to the controller if it supports it
        try:
            if hasattr(self.connection, 'send_realtime'):
                self.connection.send_realtime('!')
        except Exception:
            pass

    def request_resume(self):
        with QMutexLocker(self._mutex):
            self._paused = False
            self._pause_condition.wakeAll()
        # Send cycle start to the controller if it supports it
        try:
            if hasattr(self.connection, 'send_realtime'):
                self.connection.send_realtime('~')
        except Exception:
            pass

    def request_stop(self):
        with QMutexLocker(self._mutex):
            self._stop_requested = True
            self._paused = False
            self._pause_condition.wakeAll()

    def _is_paused(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._paused

    def _is_stop_requested(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._stop_requested

    def _wait_if_paused(self):
        """Block until un-paused or stop requested."""
        self._mutex.lock()
        while self._paused and not self._stop_requested:
            self._pause_condition.wait(self._mutex)
        self._mutex.unlock()

    def run(self):
        """Main sending loop. Called when the worker thread starts."""
        try:
            self._send_loop()
        except Exception as exc:
            logger.exception("Sender worker error")
            self.error_occurred.emit(str(exc))

    def _send_loop(self):
        """Iterate through G-code lines and send them."""
        lines = self.gcode_file.lines
        total = len(lines)
        use_wifi = self.planner is not None and hasattr(self.connection, 'send_segment')

        if use_wifi:
            self._send_loop_wifi(lines, total)
        else:
            self._send_loop_grbl(lines, total)

    # ------------------------------------------------------------------
    # GRBL character-counting protocol
    # ------------------------------------------------------------------

    def _send_loop_grbl(self, lines: list, total: int):
        """Send using GRBL character-counting streaming protocol.

        We track how many bytes are sitting in GRBL's RX buffer.  We can
        keep sending as long as the next line fits.  Each 'ok' response
        frees up the bytes from the oldest pending line.
        """
        pending_lengths = []  # lengths of lines waiting for 'ok'
        buffer_fill = 0
        max_fill = GRBL_RX_BUFFER_SIZE - GRBL_RX_BUFFER_MARGIN

        for idx in range(self.start_line, total):
            if self._is_stop_requested():
                break
            self._wait_if_paused()
            if self._is_stop_requested():
                break

            line: GCodeLine = lines[idx]

            # Skip empty and pure comment lines
            if line.is_empty or line.is_comment:
                self.progress_updated.emit(idx + 1, total)
                continue

            send_text = line.cleaned
            if not send_text:
                self.progress_updated.emit(idx + 1, total)
                continue

            # Apply feed override to F-words
            override = self._feed_override_func()
            if override != 100 and 'F' in line.params:
                send_text = self._apply_feed_override(send_text, line.params['F'], override)

            # The line as sent over serial includes the newline character
            line_bytes = len(send_text) + 1  # +1 for \n

            # Wait until there is room in the buffer
            while buffer_fill + line_bytes > max_fill:
                if self._is_stop_requested():
                    return
                # Read responses to free buffer space
                ok_count = self._drain_ok_responses(timeout=GRBL_OK_TIMEOUT)
                if ok_count == 0:
                    # Timeout waiting for ok
                    self.error_occurred.emit(
                        f"Timeout waiting for controller response at line {idx + 1}")
                    return
                for _ in range(ok_count):
                    if pending_lengths:
                        freed = pending_lengths.pop(0)
                        buffer_fill -= freed

            # Send the line
            try:
                self.connection.send_line(send_text)
            except Exception as exc:
                self.error_occurred.emit(f"Send error at line {idx + 1}: {exc}")
                return

            pending_lengths.append(line_bytes)
            buffer_fill += line_bytes

            self.line_sent.emit(idx + 1, send_text)
            self.progress_updated.emit(idx + 1, total)

        # Drain remaining ok responses
        timeout_end = time.monotonic() + GRBL_OK_TIMEOUT
        while pending_lengths and time.monotonic() < timeout_end:
            ok_count = self._drain_ok_responses(timeout=1.0)
            for _ in range(ok_count):
                if pending_lengths:
                    pending_lengths.pop(0)

        if not self._is_stop_requested():
            self.completed.emit()

    def _drain_ok_responses(self, timeout: float = 1.0) -> int:
        """Read responses from the controller, counting 'ok' replies.

        Also watches for 'error:' responses and 'ALARM' states.
        Returns the number of 'ok' responses received.
        """
        ok_count = 0
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                if hasattr(self.connection, 'read_line'):
                    resp = self.connection.read_line(timeout=min(0.1, deadline - time.monotonic()))
                else:
                    break
            except Exception:
                break

            if resp is None:
                continue

            resp = resp.strip()
            if not resp:
                continue

            if resp.lower() == 'ok':
                ok_count += 1
                break  # got at least one, return quickly
            elif resp.lower().startswith('error'):
                logger.warning("Controller error: %s", resp)
                ok_count += 1  # error still frees a buffer slot in GRBL
                break
            elif 'alarm' in resp.lower():
                self.error_occurred.emit(f"ALARM: {resp}")
                self.request_stop()
                return ok_count
            # Other messages (status reports, etc.) are ignored here

        return ok_count

    # ------------------------------------------------------------------
    # WiFi packet protocol
    # ------------------------------------------------------------------

    def _send_loop_wifi(self, lines: list, total: int):
        """Send using WiFi CNC packet protocol.

        Converts G-code lines into motion segments via the planner,
        sends them in batches, and paces sending to keep the buffer
        half-full (not flooding, not starving).
        """
        BATCH_SIZE = 8
        # Target: keep ~60 segments in the buffer (out of ~127 total).
        # This gives ~5s of buffered motion while leaving room for new data.
        BUFFER_TARGET = 60
        last_progress_time = time.monotonic()

        for idx in range(self.start_line, total):
            if self._is_stop_requested():
                break
            self._wait_if_paused()
            if self._is_stop_requested():
                break

            line: GCodeLine = lines[idx]

            if line.is_empty or line.is_comment:
                continue

            # Apply feed override via planner (affects segment duration)
            if self.planner is not None:
                self.planner.feed_override_pct = self._feed_override_func()

            # Convert to motion segments
            try:
                segments = self.planner.process_line(line)
            except Exception as exc:
                logger.warning("Planner error at line %d: %s", idx + 1, exc)
                continue

            # Send IO control if spindle/coolant changed (M3/M4/M5/M7/M8/M9)
            if getattr(self.planner, '_io_changed', False):
                self.planner._io_changed = False
                try:
                    self.connection.set_io(
                        spindle_state=self.planner.spindle_dir,
                        spindle_rpm=int(self.planner.spindle_speed),
                        coolant_state=self.planner.coolant_state,
                    )
                except Exception as exc:
                    logger.warning("IO control error: %s", exc)

            # Send each segment, pacing to keep buffer at target level
            for segment in segments:
                if self._is_stop_requested():
                    return

                # Wait if buffer is full enough
                self._pace_wifi_buffer(BUFFER_TARGET)
                if self._is_stop_requested():
                    return

                try:
                    self.connection.send_motion_segments([segment])
                except Exception as exc:
                    self.error_occurred.emit(f"Send error at line {idx + 1}: {exc}")
                    return

                # Always yield CPU after each segment so UI stays responsive
                time.sleep(0.002)

            # Throttle UI updates to ~4/sec
            now = time.monotonic()
            if now - last_progress_time >= 0.25:
                last_progress_time = now
                self.progress_updated.emit(idx + 1, total)
                if line.cleaned:
                    self.line_sent.emit(idx + 1, line.cleaned)

        if not self._is_stop_requested():
            self.completed.emit()

    def _pace_wifi_buffer(self, target_fill: int):
        """Wait until the buffer has room. Uses available slot count
        from status reports rather than percentage."""
        while not self._is_stop_requested():
            try:
                avail = self.connection._last_buffer_available
                total = self.connection._last_buffer_total
            except Exception:
                avail = 127
                total = 127

            # Buffer has room if available slots > (total - target)
            used = total - avail
            if used < target_fill:
                return

            # Buffer is full enough, wait for controller to consume segments
            time.sleep(0.025)

    @staticmethod
    def _apply_feed_override(text: str, original_f: float, override_pct: int) -> str:
        """Replace F-word in text with overridden value."""
        new_f = original_f * override_pct / 100.0
        import re
        return re.sub(
            r'F[\d.]+',
            f'F{new_f:.1f}',
            text,
            flags=re.IGNORECASE
        )


class GCodeSender(QObject):
    """High-level G-code sender that manages a worker thread.

    Usage:
        sender = GCodeSender()
        sender.set_connection(my_connection)
        sender.load_file(parsed_gcode_file)
        sender.start()
    """

    # Signals
    progress_updated = pyqtSignal(int, int)   # current_line, total_lines
    line_sent = pyqtSignal(int, str)          # line_number, line_text
    completed = pyqtSignal()
    error_occurred = pyqtSignal(str)
    state_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.connection = None
        self.gcode_file: GCodeFile | None = None
        self.current_line = 0
        self.state = SenderState.IDLE
        self.feed_override = 100  # percent
        self.planner = None  # set externally for WiFi mode

        self._worker: _SenderWorker | None = None
        self._worker_thread: QThread | None = None

    def set_connection(self, connection):
        """Set the connection backend.

        The connection object must implement at minimum:
          - send_line(text: str)         for GRBL mode
          - read_line(timeout: float)    for GRBL mode
        And optionally for WiFi mode:
          - send_segment(segment: dict)
          - get_buffer_fill() -> int     (0-100 percentage)
        And optionally:
          - send_realtime(char: str)     for feed hold / cycle start
        """
        if self.state != SenderState.IDLE:
            raise RuntimeError("Cannot change connection while sending")
        self.connection = connection

    def set_planner(self, planner):
        """Set the motion planner for WiFi packet mode."""
        if self.state != SenderState.IDLE:
            raise RuntimeError("Cannot change planner while sending")
        self.planner = planner

    def load_file(self, gcode_file: GCodeFile):
        """Load a parsed G-code file for sending."""
        if self.state != SenderState.IDLE:
            raise RuntimeError("Cannot load file while sending")
        self.gcode_file = gcode_file
        self.current_line = 0

    def start(self, from_line: int = 0):
        """Start sending G-code from the given line index (0-based).

        Creates a worker thread and begins streaming.
        """
        if self.connection is None:
            self.error_occurred.emit("No connection set")
            return

        if self.gcode_file is None:
            self.error_occurred.emit("No G-code file loaded")
            return

        if self.state == SenderState.RUNNING:
            logger.warning("Already running")
            return

        if self.state == SenderState.PAUSED:
            self.resume()
            return

        self.current_line = from_line
        self._set_state(SenderState.RUNNING)

        # Create worker and thread
        self._worker_thread = QThread()
        self._worker = _SenderWorker(
            connection=self.connection,
            gcode_file=self.gcode_file,
            start_line=from_line,
            feed_override_func=lambda: self.feed_override,
            planner=self.planner,
        )
        self._worker.moveToThread(self._worker_thread)

        # Connect signals
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.line_sent.connect(self._on_line_sent)
        self._worker.completed.connect(self._on_completed)
        self._worker.error_occurred.connect(self._on_error)

        self._worker_thread.started.connect(self._worker.run)
        self._worker_thread.start()

    def pause(self):
        """Pause sending. Sends feed hold to the controller."""
        if self.state != SenderState.RUNNING:
            return
        self._set_state(SenderState.PAUSED)
        if self._worker:
            self._worker.request_pause()

    def resume(self):
        """Resume sending after pause."""
        if self.state != SenderState.PAUSED:
            return
        self._set_state(SenderState.RUNNING)
        if self._worker:
            self._worker.request_resume()

    def stop(self):
        """Stop sending. Cannot be resumed - must start again."""
        if self.state == SenderState.IDLE:
            return

        self._set_state(SenderState.STOPPING)

        if self._worker:
            self._worker.request_stop()

        self._cleanup_thread()
        self._set_state(SenderState.IDLE)

    def set_feed_override(self, percent: int):
        """Set feed rate override percentage (1-200).
        Updates both the cached value and the planner directly."""
        self.feed_override = max(1, min(200, percent))
        # Also update the planner directly so it takes effect immediately
        if self.planner is not None:
            self.planner.feed_override_pct = self.feed_override

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _set_state(self, state: SenderState):
        self.state = state
        self.state_changed.emit(state.value)

    def _on_progress(self, current: int, total: int):
        self.current_line = current
        self.progress_updated.emit(current, total)

    def _on_line_sent(self, line_num: int, text: str):
        self.line_sent.emit(line_num, text)

    def _on_completed(self):
        self._cleanup_thread()
        self._set_state(SenderState.IDLE)
        self.completed.emit()

    def _on_error(self, message: str):
        logger.error("Sender error: %s", message)
        self._cleanup_thread()
        self._set_state(SenderState.IDLE)
        self.error_occurred.emit(message)

    def _cleanup_thread(self):
        """Stop and clean up the worker thread."""
        if self._worker_thread is not None:
            if self._worker_thread.isRunning():
                self._worker_thread.quit()
                if not self._worker_thread.wait(5000):  # 5 second timeout
                    logger.warning("Worker thread did not stop, terminating")
                    self._worker_thread.terminate()
                    self._worker_thread.wait(2000)
            self._worker_thread.deleteLater()
            self._worker_thread = None

        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

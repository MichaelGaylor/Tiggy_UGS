"""
WiFi/Ethernet packet-protocol connection backend for TiggyUGS.

Uses the binary WiFi CNC protocol:
  - TCP (port 58429) for handshake, config, and keepalive
  - UDP (port 58427) for motion commands (PC -> ESP32)
  - UDP (port 58428) for status reports (ESP32 -> PC)
"""

import socket
import struct
import threading
import time
import logging

from .base import ConnectionBase, ConnectionState
from core.protocol import (
    WCNC_MAGIC, WCNC_VERSION, MAX_AXES,
    UDP_MOTION_PORT, UDP_STATUS_PORT, TCP_CONTROL_PORT,
    HEADER_SIZE, STATES,
    PacketType, ConfigKey, ValueType, CONFIG_KEYS,
    crc16_ccitt, build_header, finalize_packet, validate_packet,
    parse_header, parse_status_report, parse_handshake_resp, parse_config_resp,
    build_jog_packet, build_jog_stop_packet, build_estop_packet,
    build_feed_hold_packet, build_feed_resume_packet, build_reset_packet,
    build_home_packet, build_io_control_packet, build_handshake_req,
    build_motion_segment_packet, build_config_get, build_config_set,
    build_config_save, build_ping,
    tcp_frame, tcp_unframe,
)

log = logging.getLogger(__name__)


class WiFiPacketConnection(ConnectionBase):
    """Connection backend using the native WiFi CNC binary protocol."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tcp_sock: socket.socket | None = None
        self._udp_motion_sock: socket.socket | None = None
        self._udp_status_sock: socket.socket | None = None

        self._address: str = ""
        self._device_info: dict = {}
        self._sequence = 0
        self._seq_lock = threading.Lock()

        self._tcp_lock = threading.Lock()
        self._tcp_recv_buf = b''

        self._status_thread: threading.Thread | None = None
        self._keepalive_thread: threading.Thread | None = None
        self._running = False

        self._last_pong_time = 0.0
        self._ping_id = 0

        self._last_buffer_available = 0   # Start as FULL to prevent flooding
        self._last_buffer_total = 128
        self._first_status_received = False

    # ----- Sequence counter -----

    def _next_seq(self) -> int:
        with self._seq_lock:
            self._sequence += 1
            return self._sequence

    # ----- Connection lifecycle -----

    @property
    def connection_type(self) -> str:
        return "WiFi Packet"

    def connect_to(self, address: str, **kwargs):
        """Connect to the ESP32 at the given IP address."""
        if self.state != ConnectionState.DISCONNECTED:
            self.disconnect_from()

        self.state = ConnectionState.CONNECTING
        self._address = address
        self._running = True

        try:
            # 1. TCP control connection
            self._tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp_sock.settimeout(5.0)
            self._tcp_sock.connect((address, TCP_CONTROL_PORT))
            self._tcp_sock.settimeout(2.0)

            # 2. Handshake
            req = build_handshake_req()
            self._tcp_send(req)
            resp_data = self._tcp_recv()
            if resp_data is None or not validate_packet(resp_data):
                raise ConnectionError("Invalid handshake response")
            if resp_data[5] != PacketType.HANDSHAKE_RESP:
                raise ConnectionError(
                    f"Expected HANDSHAKE_RESP, got 0x{resp_data[5]:02X}")

            self._device_info = parse_handshake_resp(resp_data)

            # 3. UDP sockets
            self._udp_motion_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_status_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # On Windows, use SO_EXCLUSIVEADDRUSE to prevent zombie processes
            # from stealing our status packets via SO_REUSEADDR
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self._udp_status_sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                self._udp_status_sock.setsockopt(
                    socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._udp_status_sock.bind(('0.0.0.0', UDP_STATUS_PORT))
            except OSError as bind_err:
                raise ConnectionError(
                    f"Cannot bind UDP port {UDP_STATUS_PORT} - "
                    f"is another TiggyUGS instance running? ({bind_err})")
            self._udp_status_sock.settimeout(1.0)

            # 4. Start background threads
            self._last_pong_time = time.monotonic()
            self._status_thread = threading.Thread(
                target=self._status_listener, daemon=True, name="wcnc-status")
            self._status_thread.start()

            self._keepalive_thread = threading.Thread(
                target=self._keepalive_loop, daemon=True, name="wcnc-keepalive")
            self._keepalive_thread.start()

            # 5. Send RESET to clear any E-Stop/Alarm/Hold from previous session
            reset_pkt = build_reset_packet(self._next_seq())
            self._send_udp(reset_pkt)

            # 6. Wait for first status report so buffer state is known
            deadline = time.monotonic() + 3.0
            while not self._first_status_received and time.monotonic() < deadline:
                time.sleep(0.05)
            if not self._first_status_received:
                log.warning("No status report within 3s, proceeding anyway")

            # 7. Try to read steps_per_mm from device config
            self._read_steps_per_mm()

            self.state = ConnectionState.CONNECTED
            self._device_info['address'] = address
            self.connected.emit(self._device_info)
            self.response_received.emit(
                f"Connected to {self._device_info.get('device_name', address)} "
                f"(FW {self._device_info.get('firmware_version', '?')})")

        except Exception as exc:
            log.exception("WiFi packet connect failed")
            self._cleanup_sockets()
            self.state = ConnectionState.DISCONNECTED
            self.error_occurred.emit(f"Connection failed: {exc}")

    def disconnect_from(self):
        """Disconnect and clean up."""
        self._running = False

        # Wait for threads to finish
        for t in (self._status_thread, self._keepalive_thread):
            if t is not None and t.is_alive():
                t.join(timeout=3.0)
        self._status_thread = None
        self._keepalive_thread = None

        self._cleanup_sockets()
        self.state = ConnectionState.DISCONNECTED
        self._device_info = {}
        self.disconnected.emit()

    def __del__(self):
        """Ensure sockets are closed if the object is garbage collected."""
        self._running = False
        self._cleanup_sockets()

    def _cleanup_sockets(self):
        for sock in (self._tcp_sock, self._udp_motion_sock, self._udp_status_sock):
            if sock is not None:
                try:
                    # Set linger to 0 for immediate close (no TIME_WAIT/CLOSE_WAIT)
                    import struct as _st
                    sock.setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER,
                        _st.pack('ii', 1, 0))
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass
        self._tcp_sock = None
        self._udp_motion_sock = None
        self._udp_status_sock = None
        self._tcp_recv_buf = b''

    # ----- TCP helpers -----

    def _tcp_send(self, packet: bytes):
        """Send a length-prefixed packet over TCP."""
        with self._tcp_lock:
            if self._tcp_sock is None:
                raise ConnectionError("TCP socket not connected")
            self._tcp_sock.sendall(tcp_frame(packet))

    def _tcp_recv(self, timeout: float = 5.0) -> bytes | None:
        """Receive one length-prefixed packet from TCP. Returns None on timeout."""
        deadline = time.monotonic() + timeout
        with self._tcp_lock:
            while True:
                pkt, self._tcp_recv_buf = tcp_unframe(self._tcp_recv_buf)
                if pkt is not None:
                    return pkt
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                if self._tcp_sock is None:
                    return None
                self._tcp_sock.settimeout(min(remaining, 2.0))
                try:
                    chunk = self._tcp_sock.recv(4096)
                except socket.timeout:
                    return None
                except OSError:
                    return None
                if not chunk:
                    return None
                self._tcp_recv_buf += chunk

    # ----- UDP send helpers -----

    def _send_udp(self, packet: bytes):
        """Send a UDP packet to the motion port."""
        if self._udp_motion_sock is None:
            return
        try:
            self._udp_motion_sock.sendto(
                packet, (self._address, UDP_MOTION_PORT))
        except OSError as exc:
            log.warning("UDP send error: %s", exc)

    # ----- Background threads -----

    def _status_listener(self):
        """Background thread: listen for UDP status reports."""
        while self._running:
            try:
                data, addr = self._udp_status_sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    log.warning("Status socket error")
                break

            if not validate_packet(data):
                continue
            pkt_type = data[5]
            if pkt_type == PacketType.STATUS_REPORT:
                status = parse_status_report(data)
                # Convert step positions to mm
                positions_mm = []
                for i in range(MAX_AXES):
                    spm = self.steps_per_mm[i] if self.steps_per_mm[i] != 0 else 1.0
                    positions_mm.append(status['positions'][i] / spm)
                status['positions'] = positions_mm
                self._last_buffer_available = status.get('buffer_available', 0)
                self._last_buffer_total = status.get('buffer_total', 128)
                self._first_status_received = True
                self._status_count = getattr(self, '_status_count', 0) + 1
                self.status_updated.emit(status)
            elif pkt_type == PacketType.ALARM:
                status = parse_status_report(data)
                alarm = status.get('alarm_code', 0)
                self.error_occurred.emit(f"ALARM {alarm}: {status.get('state', '')}")
                self.status_updated.emit(status)
            elif pkt_type == PacketType.HOME_COMPLETE:
                self.response_received.emit("Homing complete")
            elif pkt_type == PacketType.PROBE_RESULT:
                self.response_received.emit("Probe result received")
            elif pkt_type == PacketType.ACK:
                pass  # ACKs handled implicitly

    def _keepalive_loop(self):
        """Background thread: monitor connection health.
        UDP status reports are the primary health indicator.
        TCP ping/pong is secondary - if TCP dies but UDP is alive, we stay connected."""
        last_status_count = 0
        while self._running:
            time.sleep(5.0)
            if not self._running:
                break

            # Primary check: are status reports still arriving?
            current_count = getattr(self, '_status_count', 0)
            if current_count > last_status_count:
                # Status reports flowing - connection is healthy
                last_status_count = current_count
                self._last_pong_time = time.monotonic()

                # Try TCP ping, but don't care if it fails
                try:
                    self._ping_id += 1
                    ping_pkt = build_ping(self._ping_id, self._next_seq())
                    self._tcp_send(ping_pkt)
                    resp = self._tcp_recv(timeout=2.0)
                    if resp is not None and validate_packet(resp):
                        if resp[5] == PacketType.PONG:
                            self._last_pong_time = time.monotonic()
                except Exception:
                    pass  # TCP may be dead but UDP still works - that's OK
                continue

            # No new status reports - check timeout
            if time.monotonic() - self._last_pong_time > 30.0:
                log.warning("No status reports for 30s - disconnecting")
                self.error_occurred.emit("Connection lost (no status reports)")
                self._running = False
                self.state = ConnectionState.DISCONNECTED
                self.disconnected.emit()
                break

    # ----- Read device config -----

    def _read_steps_per_mm(self):
        """Read steps/mm for all axes from device config."""
        keys = [
            ConfigKey.STEPS_PER_MM_X, ConfigKey.STEPS_PER_MM_Y,
            ConfigKey.STEPS_PER_MM_Z, ConfigKey.STEPS_PER_MM_A,
            ConfigKey.STEPS_PER_MM_B, ConfigKey.STEPS_PER_MM_C,
        ]
        for i, key in enumerate(keys):
            try:
                val = self.read_config(key, ValueType.FLOAT)
                if val is not None and val > 0:
                    self.steps_per_mm[i] = val
            except Exception:
                pass

    # ----- Public control methods -----

    def send_gcode_line(self, line: str):
        """G-code line sending requires a planner to convert to motion segments.
        For now, emit to console to acknowledge receipt."""
        self.response_received.emit(f"[WiFi Packet mode does not directly accept "
                                    f"G-code. Use the motion planner.] {line}")

    def jog(self, axis: int, direction: int, speed: float):
        """Start jogging. speed is in mm/min, converted to steps/sec."""
        spm = self.steps_per_mm[axis] if axis < MAX_AXES else 800.0
        speed_steps = int(speed / 60.0 * spm)
        pkt = build_jog_packet(axis, direction, speed_steps, self._next_seq())
        self._send_udp(pkt)

    def jog_stop(self, axis: int = -1):
        ax = 0xFF if axis < 0 else axis
        pkt = build_jog_stop_packet(ax, self._next_seq())
        self._send_udp(pkt)

    def home(self, axis_mask: int = 0x3F):
        pkt = build_home_packet(axis_mask, self._next_seq())
        self._send_udp(pkt)
        self.response_received.emit(f"Home command sent (mask=0x{axis_mask:02X})")

    def estop(self):
        """Send E-Stop 3 times for redundancy."""
        for _ in range(3):
            pkt = build_estop_packet(self._next_seq())
            self._send_udp(pkt)
        self.response_received.emit("E-STOP sent (3x)")

    def feed_hold(self):
        pkt = build_feed_hold_packet(self._next_seq())
        self._send_udp(pkt)

    def feed_resume(self):
        pkt = build_feed_resume_packet(self._next_seq())
        self._send_udp(pkt)

    def reset(self):
        pkt = build_reset_packet(self._next_seq())
        self._send_udp(pkt)
        self.response_received.emit("Reset sent")

    def set_io(self, spindle_state: int = 0, spindle_rpm: int = 0,
               coolant_state: int = 0, misc_outputs: int = 0):
        pkt = build_io_control_packet(
            misc_outputs, spindle_state, spindle_rpm, coolant_state,
            self._next_seq())
        self._send_udp(pkt)

    def send_motion_segments(self, segments: list):
        """Send motion segments to the controller via UDP.
        segments: list of dicts (see build_motion_segment_packet)."""
        # Send in chunks of 8
        for i in range(0, len(segments), 8):
            chunk = segments[i:i + 8]
            pkt = build_motion_segment_packet(chunk, self._next_seq())
            self._send_udp(pkt)

    def send_segment(self, segment: dict):
        """Send a single motion segment (used by GCodeSender)."""
        self.send_motion_segments([segment])

    def get_buffer_fill(self) -> int:
        """Return buffer fill percentage (0-100) from latest status.
        Used by GCodeSender to throttle sending."""
        avail = self._last_buffer_available
        total = self._last_buffer_total
        if total <= 0:
            return 0
        return int(100 * (total - avail) / total)

    # ----- Config read/write (TCP) -----

    def read_config(self, key: int, value_type: int):
        """Read a config value from the device. Returns the decoded value or None."""
        pkt = build_config_get(key, value_type)
        self._tcp_send(pkt)
        resp = self._tcp_recv(timeout=3.0)
        if resp is None or not validate_packet(resp):
            return None
        if resp[5] != PacketType.CONFIG_RESP:
            return None
        parsed = parse_config_resp(resp)
        return parsed.get('value')

    def write_config(self, key: int, value_type: int, value):
        """Write a config value to the device. Returns True on ACK."""
        pkt = build_config_set(key, value_type, value)
        self._tcp_send(pkt)
        resp = self._tcp_recv(timeout=3.0)
        if resp is None or not validate_packet(resp):
            return False
        return resp[5] == PacketType.ACK

    def save_config(self) -> bool:
        """Save config to NVS. Returns True on ACK."""
        pkt = build_config_save()
        self._tcp_send(pkt)
        resp = self._tcp_recv(timeout=5.0)
        if resp is None or not validate_packet(resp):
            return False
        return resp[5] == PacketType.ACK

    # ----- Discovery -----

    @staticmethod
    def discover(timeout: float = 5.0) -> list:
        """Broadcast discovery and return list of (ip, device_info) tuples.

        Sends a JOG_STOP broadcast on the motion port and listens for
        status reports on the status port.
        """
        # Build a harmless JOG_STOP packet
        pkt = build_jog_stop_packet(0xFF)

        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx.bind(('0.0.0.0', UDP_STATUS_PORT))
        rx.settimeout(1.0)

        found = {}
        start = time.monotonic()

        try:
            tx.sendto(pkt, ('255.255.255.255', UDP_MOTION_PORT))
            while time.monotonic() - start < timeout:
                try:
                    data, addr = rx.recvfrom(512)
                except socket.timeout:
                    # Re-broadcast
                    tx.sendto(pkt, ('255.255.255.255', UDP_MOTION_PORT))
                    continue

                if not validate_packet(data):
                    continue
                if data[5] != PacketType.STATUS_REPORT:
                    continue

                ip = addr[0]
                if ip not in found:
                    status = parse_status_report(data)
                    found[ip] = {
                        'ip': ip,
                        'state': status.get('state', 'Unknown'),
                        'uptime_ms': status.get('uptime_ms', 0),
                    }
        finally:
            tx.close()
            rx.close()

        # Try TCP handshake for each discovered device to get full info
        results = []
        for ip, basic_info in found.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect((ip, TCP_CONTROL_PORT))
                req = build_handshake_req()
                sock.sendall(tcp_frame(req))
                # Receive length prefix + data
                len_buf = b''
                while len(len_buf) < 2:
                    chunk = sock.recv(2 - len(len_buf))
                    if not chunk:
                        break
                    len_buf += chunk
                if len(len_buf) == 2:
                    pkt_len = struct.unpack('<H', len_buf)[0]
                    data = b''
                    while len(data) < pkt_len:
                        chunk = sock.recv(pkt_len - len(data))
                        if not chunk:
                            break
                        data += chunk
                    if validate_packet(data) and data[5] == PacketType.HANDSHAKE_RESP:
                        info = parse_handshake_resp(data)
                        info['ip'] = ip
                        results.append((ip, info))
                    else:
                        results.append((ip, basic_info))
                else:
                    results.append((ip, basic_info))
                sock.close()
            except Exception:
                results.append((ip, basic_info))

        return results

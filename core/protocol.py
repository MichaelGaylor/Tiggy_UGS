"""
WiFi CNC Protocol - Python implementation.

Translated from wifi_cnc_protocol.h. Provides packet building, parsing,
CRC computation, and all protocol constants for the WiFi CNC controller.
"""

import struct
import time
from enum import IntEnum

# ===================================================================
# Protocol Constants
# ===================================================================

WCNC_MAGIC = 0x574D4333          # "WMC3" little-endian
WCNC_VERSION = 1
MAX_AXES = 6
MAX_SEGMENTS_PER_PACKET = 8

# Network ports
UDP_MOTION_PORT = 58427           # PC -> ESP32: motion segments
UDP_STATUS_PORT = 58428           # ESP32 -> PC: status reports
TCP_CONTROL_PORT = 58429          # Bidirectional: config, handshake

# Device name / config max lengths
DEVICE_NAME_LEN = 32
CONFIG_VALUE_LEN = 64

# Header struct: magic(4) + version(1) + type(1) + payload_len(2) +
#                sequence(4) + timestamp_us(4) + checksum(2) = 18 bytes
HEADER_FORMAT = '<IBBHIIH'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)   # 18


# ===================================================================
# Packet Types
# ===================================================================

class PacketType(IntEnum):
    MOTION_SEGMENT  = 0x01
    JOG_COMMAND     = 0x02
    JOG_STOP        = 0x03
    ESTOP           = 0x04
    FEED_HOLD       = 0x05
    FEED_RESUME     = 0x06
    RESET           = 0x07
    HOME_COMMAND    = 0x08
    IO_CONTROL      = 0x09

    STATUS_REPORT   = 0x20
    ALARM           = 0x21
    HOME_COMPLETE   = 0x22
    PROBE_RESULT    = 0x23
    ACK             = 0x24

    HANDSHAKE_REQ   = 0x40
    HANDSHAKE_RESP  = 0x41
    CONFIG_GET      = 0x42
    CONFIG_SET      = 0x43
    CONFIG_RESP     = 0x44
    CONFIG_SAVE     = 0x45
    FIRMWARE_INFO   = 0x46
    PING            = 0x50
    PONG            = 0x51


# ===================================================================
# Machine States
# ===================================================================

class MachineState(IntEnum):
    IDLE          = 0
    RUN           = 1
    HOLD          = 2
    JOG           = 3
    HOMING        = 4
    PROBING       = 5
    ALARM         = 6
    ESTOP         = 7
    DISCONNECTED  = 8

STATES = {
    0: "Idle",   1: "Run",    2: "Hold",    3: "Jog",
    4: "Homing", 5: "Probing", 6: "Alarm",  7: "E-Stop",
    8: "Disconnected",
}


# ===================================================================
# Alarm Codes
# ===================================================================

class AlarmCode(IntEnum):
    NONE             = 0
    LIMIT_X          = 1
    LIMIT_Y          = 2
    LIMIT_Z          = 3
    LIMIT_A          = 4
    LIMIT_B          = 5
    LIMIT_C          = 6
    PROBE_FAIL       = 10
    BUFFER_UNDERRUN  = 11
    ESTOP_ACTIVE     = 20
    WATCHDOG         = 30

ALARMS = {
    0:  "None",
    1:  "Limit X", 2: "Limit Y", 3: "Limit Z",
    4:  "Limit A", 5: "Limit B", 6: "Limit C",
    10: "Probe fail",
    11: "Buffer underrun",
    20: "E-Stop active",
    30: "Watchdog",
}


# ===================================================================
# Segment Flags
# ===================================================================

SEG_FLAG_RAPID      = 0x01
SEG_FLAG_LAST       = 0x02
SEG_FLAG_PROBE      = 0x04
SEG_FLAG_EXACT_STOP = 0x08


# ===================================================================
# Status Flags
# ===================================================================

STATUS_WIFI_CONNECTED  = 0x01
STATUS_HOST_CONNECTED  = 0x02
STATUS_MOTION_ACTIVE   = 0x04
STATUS_HOMING_ACTIVE   = 0x08


# ===================================================================
# Capability Flags
# ===================================================================

CAP_CHARGE_PUMP     = 0x01
CAP_MISC_OUTPUTS    = 0x02
CAP_MISC_INPUTS     = 0x04
CAP_SPINDLE_PWM     = 0x08
CAP_SPINDLE_ENCODER = 0x10
CAP_IO_MODULE       = 0x20


# ===================================================================
# Value Types
# ===================================================================

class ValueType(IntEnum):
    UINT8  = 0
    UINT16 = 1
    UINT32 = 2
    INT32  = 3
    FLOAT  = 4
    STRING = 5


# ===================================================================
# Configuration Keys
# ===================================================================

class ConfigKey(IntEnum):
    STEPS_PER_MM_X    = 0x0001
    STEPS_PER_MM_Y    = 0x0002
    STEPS_PER_MM_Z    = 0x0003
    STEPS_PER_MM_A    = 0x0004
    STEPS_PER_MM_B    = 0x0005
    STEPS_PER_MM_C    = 0x0006
    MAX_RATE_X        = 0x0010
    MAX_RATE_Y        = 0x0011
    MAX_RATE_Z        = 0x0012
    MAX_RATE_A        = 0x0013
    MAX_RATE_B        = 0x0014
    MAX_RATE_C        = 0x0015
    ACCEL_X           = 0x0020
    ACCEL_Y           = 0x0021
    ACCEL_Z           = 0x0022
    ACCEL_A           = 0x0023
    ACCEL_B           = 0x0024
    ACCEL_C           = 0x0025
    STEP_PULSE_US     = 0x0100
    DIR_SETUP_US      = 0x0101
    STEP_IDLE_DELAY_MS = 0x0102
    STATUS_INTERVAL_MS = 0x0103
    WIFI_SSID         = 0x0200
    WIFI_PASSWORD     = 0x0201
    IP_MODE           = 0x0210
    STATIC_IP         = 0x0211
    STATIC_GATEWAY    = 0x0212
    STATIC_NETMASK    = 0x0213
    INVERT_STEP       = 0x0300
    INVERT_DIR        = 0x0301
    INVERT_ENABLE     = 0x0302
    INVERT_LIMIT      = 0x0310
    INVERT_HOME       = 0x0311
    INVERT_ESTOP      = 0x0312
    INVERT_PROBE      = 0x0313
    HOMING_DIR_MASK   = 0x0320
    HOMING_SEEK_RATE  = 0x0321
    HOMING_FEED_RATE  = 0x0322
    HOMING_PULLOFF    = 0x0323
    CHARGE_PUMP_FREQ  = 0x0400
    SPINDLE_PWM_FREQ  = 0x0430
    SPINDLE_MAX_RPM   = 0x0431
    PIN_STEP_X        = 0x0500
    PIN_STEP_Y        = 0x0501
    PIN_STEP_Z        = 0x0502
    PIN_STEP_A        = 0x0503
    PIN_STEP_B        = 0x0504
    PIN_STEP_C        = 0x0505
    PIN_DIR_X         = 0x0506
    PIN_DIR_Y         = 0x0507
    PIN_DIR_Z         = 0x0508
    PIN_DIR_A         = 0x0509
    PIN_DIR_B         = 0x050A
    PIN_DIR_C         = 0x050B
    PIN_ENABLE        = 0x050C
    PIN_LIMIT_X       = 0x050D
    PIN_LIMIT_Y       = 0x050E
    PIN_LIMIT_Z       = 0x050F
    PIN_LIMIT_A       = 0x0510
    PIN_LIMIT_B       = 0x0511
    PIN_LIMIT_C       = 0x0512
    PIN_PROBE         = 0x0513
    PIN_ESTOP         = 0x0514
    PIN_SPINDLE       = 0x0515
    PIN_LED           = 0x0516
    PIN_CHARGE_PUMP   = 0x0517
    PIN_MISC_OUT0     = 0x0518
    PIN_MISC_OUT1     = 0x0519
    PIN_ENCODER_A     = 0x0520
    PIN_ENCODER_B     = 0x0521
    PIN_ENCODER_INDEX = 0x0522
    ENCODER_PPR       = 0x0523
    ENCODER_MODE      = 0x0524
    ENCODER_FILTER_NS = 0x0525
    PIN_MISC_IN0      = 0x0530
    PIN_MISC_IN1      = 0x0531
    PIN_MISC_IN2      = 0x0532
    PIN_MISC_IN3      = 0x0533
    DEVICE_MODE       = 0x0600
    IO_PIN_COUNT      = 0x0610
    IO_DIR_MASK       = 0x0611
    IO_PULLUP_MASK    = 0x0612
    IO_INVERT_MASK    = 0x0613
    IO_PIN_BASE       = 0x0620
    PIN_ETH_MOSI      = 0x0700
    PIN_ETH_MISO      = 0x0701
    PIN_ETH_SCLK      = 0x0702
    PIN_ETH_INT       = 0x0703
    PIN_ETH_SPI_HOST  = 0x0704


# (name, value_type) for each config key
CONFIG_KEYS = {
    ConfigKey.STEPS_PER_MM_X:    ("Steps/mm X",        ValueType.FLOAT),
    ConfigKey.STEPS_PER_MM_Y:    ("Steps/mm Y",        ValueType.FLOAT),
    ConfigKey.STEPS_PER_MM_Z:    ("Steps/mm Z",        ValueType.FLOAT),
    ConfigKey.STEPS_PER_MM_A:    ("Steps/mm A",        ValueType.FLOAT),
    ConfigKey.STEPS_PER_MM_B:    ("Steps/mm B",        ValueType.FLOAT),
    ConfigKey.STEPS_PER_MM_C:    ("Steps/mm C",        ValueType.FLOAT),
    ConfigKey.MAX_RATE_X:        ("Max rate X",        ValueType.UINT32),
    ConfigKey.MAX_RATE_Y:        ("Max rate Y",        ValueType.UINT32),
    ConfigKey.MAX_RATE_Z:        ("Max rate Z",        ValueType.UINT32),
    ConfigKey.MAX_RATE_A:        ("Max rate A",        ValueType.UINT32),
    ConfigKey.MAX_RATE_B:        ("Max rate B",        ValueType.UINT32),
    ConfigKey.MAX_RATE_C:        ("Max rate C",        ValueType.UINT32),
    ConfigKey.ACCEL_X:           ("Accel X",           ValueType.UINT32),
    ConfigKey.ACCEL_Y:           ("Accel Y",           ValueType.UINT32),
    ConfigKey.ACCEL_Z:           ("Accel Z",           ValueType.UINT32),
    ConfigKey.ACCEL_A:           ("Accel A",           ValueType.UINT32),
    ConfigKey.ACCEL_B:           ("Accel B",           ValueType.UINT32),
    ConfigKey.ACCEL_C:           ("Accel C",           ValueType.UINT32),
    ConfigKey.STEP_PULSE_US:     ("Step pulse us",     ValueType.UINT16),
    ConfigKey.DIR_SETUP_US:      ("Dir setup us",      ValueType.UINT16),
    ConfigKey.STEP_IDLE_DELAY_MS:("Idle delay ms",     ValueType.UINT16),
    ConfigKey.STATUS_INTERVAL_MS:("Status interval ms",ValueType.UINT16),
    ConfigKey.WIFI_SSID:         ("WiFi SSID",         ValueType.STRING),
    ConfigKey.WIFI_PASSWORD:     ("WiFi Password",     ValueType.STRING),
    ConfigKey.IP_MODE:           ("IP mode",           ValueType.UINT8),
    ConfigKey.STATIC_IP:         ("Static IP",         ValueType.UINT32),
    ConfigKey.STATIC_GATEWAY:    ("Static gateway",    ValueType.UINT32),
    ConfigKey.STATIC_NETMASK:    ("Static netmask",    ValueType.UINT32),
    ConfigKey.INVERT_STEP:       ("Invert step",       ValueType.UINT8),
    ConfigKey.INVERT_DIR:        ("Invert dir",        ValueType.UINT8),
    ConfigKey.INVERT_ENABLE:     ("Invert enable",     ValueType.UINT8),
    ConfigKey.INVERT_LIMIT:      ("Invert limit",      ValueType.UINT8),
    ConfigKey.INVERT_HOME:       ("Invert home",       ValueType.UINT8),
    ConfigKey.INVERT_ESTOP:      ("Invert E-Stop",     ValueType.UINT8),
    ConfigKey.INVERT_PROBE:      ("Invert probe",      ValueType.UINT8),
    ConfigKey.HOMING_DIR_MASK:   ("Homing dir mask",   ValueType.UINT8),
    ConfigKey.HOMING_SEEK_RATE:  ("Homing seek rate",  ValueType.UINT32),
    ConfigKey.HOMING_FEED_RATE:  ("Homing feed rate",  ValueType.UINT32),
    ConfigKey.HOMING_PULLOFF:    ("Homing pulloff",    ValueType.UINT32),
    ConfigKey.CHARGE_PUMP_FREQ:  ("Charge pump freq",  ValueType.UINT16),
    ConfigKey.SPINDLE_PWM_FREQ:  ("Spindle PWM freq",  ValueType.UINT16),
    ConfigKey.SPINDLE_MAX_RPM:   ("Spindle max RPM",   ValueType.UINT32),
    ConfigKey.PIN_STEP_X:        ("Pin Step X",        ValueType.UINT8),
    ConfigKey.PIN_STEP_Y:        ("Pin Step Y",        ValueType.UINT8),
    ConfigKey.PIN_STEP_Z:        ("Pin Step Z",        ValueType.UINT8),
    ConfigKey.PIN_STEP_A:        ("Pin Step A",        ValueType.UINT8),
    ConfigKey.PIN_STEP_B:        ("Pin Step B",        ValueType.UINT8),
    ConfigKey.PIN_STEP_C:        ("Pin Step C",        ValueType.UINT8),
    ConfigKey.PIN_DIR_X:         ("Pin Dir X",         ValueType.UINT8),
    ConfigKey.PIN_DIR_Y:         ("Pin Dir Y",         ValueType.UINT8),
    ConfigKey.PIN_DIR_Z:         ("Pin Dir Z",         ValueType.UINT8),
    ConfigKey.PIN_DIR_A:         ("Pin Dir A",         ValueType.UINT8),
    ConfigKey.PIN_DIR_B:         ("Pin Dir B",         ValueType.UINT8),
    ConfigKey.PIN_DIR_C:         ("Pin Dir C",         ValueType.UINT8),
    ConfigKey.PIN_ENABLE:        ("Pin Enable",        ValueType.UINT8),
    ConfigKey.PIN_LIMIT_X:       ("Pin Limit X",       ValueType.UINT8),
    ConfigKey.PIN_LIMIT_Y:       ("Pin Limit Y",       ValueType.UINT8),
    ConfigKey.PIN_LIMIT_Z:       ("Pin Limit Z",       ValueType.UINT8),
    ConfigKey.PIN_LIMIT_A:       ("Pin Limit A",       ValueType.UINT8),
    ConfigKey.PIN_LIMIT_B:       ("Pin Limit B",       ValueType.UINT8),
    ConfigKey.PIN_LIMIT_C:       ("Pin Limit C",       ValueType.UINT8),
    ConfigKey.PIN_PROBE:         ("Pin Probe",         ValueType.UINT8),
    ConfigKey.PIN_ESTOP:         ("Pin E-Stop",        ValueType.UINT8),
    ConfigKey.PIN_SPINDLE:       ("Pin Spindle",       ValueType.UINT8),
    ConfigKey.PIN_LED:           ("Pin LED",           ValueType.UINT8),
    ConfigKey.PIN_CHARGE_PUMP:   ("Pin Charge Pump",   ValueType.UINT8),
    ConfigKey.PIN_MISC_OUT0:     ("Pin Misc Out 0",    ValueType.UINT8),
    ConfigKey.PIN_MISC_OUT1:     ("Pin Misc Out 1",    ValueType.UINT8),
    ConfigKey.PIN_ENCODER_A:     ("Pin Encoder A",     ValueType.UINT8),
    ConfigKey.PIN_ENCODER_B:     ("Pin Encoder B",     ValueType.UINT8),
    ConfigKey.PIN_ENCODER_INDEX: ("Pin Encoder Index",  ValueType.UINT8),
    ConfigKey.ENCODER_PPR:       ("Encoder PPR",       ValueType.UINT16),
    ConfigKey.ENCODER_MODE:      ("Encoder Mode",      ValueType.UINT8),
    ConfigKey.ENCODER_FILTER_NS: ("Encoder Filter ns", ValueType.UINT16),
    ConfigKey.PIN_MISC_IN0:      ("Pin Misc In 0",     ValueType.UINT8),
    ConfigKey.PIN_MISC_IN1:      ("Pin Misc In 1",     ValueType.UINT8),
    ConfigKey.PIN_MISC_IN2:      ("Pin Misc In 2",     ValueType.UINT8),
    ConfigKey.PIN_MISC_IN3:      ("Pin Misc In 3",     ValueType.UINT8),
    ConfigKey.DEVICE_MODE:       ("Device Mode",       ValueType.UINT8),
    ConfigKey.IO_PIN_COUNT:      ("IO Pin Count",      ValueType.UINT8),
    ConfigKey.IO_DIR_MASK:       ("IO Dir Mask",       ValueType.UINT16),
    ConfigKey.IO_PULLUP_MASK:    ("IO Pullup Mask",    ValueType.UINT16),
    ConfigKey.IO_INVERT_MASK:    ("IO Invert Mask",    ValueType.UINT16),
    ConfigKey.IO_PIN_BASE:       ("IO Pin 0 GPIO",     ValueType.UINT8),
    ConfigKey.PIN_ETH_MOSI:      ("Pin ETH MOSI",     ValueType.UINT8),
    ConfigKey.PIN_ETH_MISO:      ("Pin ETH MISO",     ValueType.UINT8),
    ConfigKey.PIN_ETH_SCLK:      ("Pin ETH SCLK",     ValueType.UINT8),
    ConfigKey.PIN_ETH_INT:       ("Pin ETH INT",      ValueType.UINT8),
    ConfigKey.PIN_ETH_SPI_HOST:  ("ETH SPI Host",     ValueType.UINT8),
}


# ===================================================================
# CRC-16/CCITT (initial=0xFFFF, poly=0x1021)
# ===================================================================

def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT matching the C firmware implementation."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


# ===================================================================
# Header helpers
# ===================================================================

def _timestamp_us() -> int:
    """Return current time as microseconds, truncated to uint32."""
    return int(time.time() * 1_000_000) & 0xFFFFFFFF


def build_header(pkt_type: int, payload_len: int, sequence: int = 0) -> bytes:
    """Build an 18-byte packet header with checksum set to 0."""
    return struct.pack(
        HEADER_FORMAT,
        WCNC_MAGIC,
        WCNC_VERSION,
        pkt_type,
        payload_len,
        sequence,
        _timestamp_us(),
        0,  # checksum placeholder
    )


def finalize_packet(packet: bytes) -> bytes:
    """Compute CRC-16 over the full packet (with checksum field zeroed)
    and insert it into the header checksum field at offset 16."""
    buf = bytearray(packet)
    buf[16] = 0
    buf[17] = 0
    crc = crc16_ccitt(bytes(buf))
    struct.pack_into('<H', buf, 16, crc)
    return bytes(buf)


def validate_packet(data: bytes) -> bool:
    """Check magic, version, and CRC of a received packet."""
    if len(data) < HEADER_SIZE:
        return False
    magic, version = struct.unpack_from('<IB', data, 0)
    if magic != WCNC_MAGIC or version != WCNC_VERSION:
        return False
    received_crc = struct.unpack_from('<H', data, 16)[0]
    buf = bytearray(data)
    buf[16] = 0
    buf[17] = 0
    return crc16_ccitt(bytes(buf)) == received_crc


def parse_header(data: bytes) -> dict:
    """Parse the 18-byte header into a dict."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Data too short for header ({len(data)} < {HEADER_SIZE})")
    magic, version, pkt_type, payload_length, sequence, timestamp_us, checksum = \
        struct.unpack_from(HEADER_FORMAT, data, 0)
    return {
        'magic': magic,
        'version': version,
        'packet_type': pkt_type,
        'payload_length': payload_length,
        'sequence': sequence,
        'timestamp_us': timestamp_us,
        'checksum': checksum,
    }


# ===================================================================
# Status report parsing
# ===================================================================

def parse_status_report(data: bytes) -> dict:
    """Parse a full status packet (header + status report payload).
    Handles both base and v1.1 extended fields gracefully."""
    hdr = parse_header(data)
    off = HEADER_SIZE
    available = len(data) - off

    result = {
        'packet_type': hdr['packet_type'],
        'sequence': hdr['sequence'],
        'positions': [0] * MAX_AXES,
        'state': 'Disconnected',
        'state_id': MachineState.DISCONNECTED,
        'alarm_code': 0,
        'buffer_available': 0,
        'buffer_total': 0,
        'limits': 0,
        'home_switches': 0,
        'estop': False,
        'probe': False,
        'feed_rate': 0.0,
        'spindle_state': 0,
        'spindle_rpm': 0,
        'coolant_state': 0,
        'misc_outputs': 0,
        'misc_inputs': 0,
        'homing_state': 0,
        'flags': 0,
        'current_segment_id': 0,
        'uptime_ms': 0,
        'spindle_position': 0,
        'spindle_index_count': 0,
        'io_inputs': 0,
        'io_outputs': 0,
    }

    if available < 46:
        return result

    # Base status fields (46 bytes)
    positions = struct.unpack_from('<6i', data, off)
    result['positions'] = list(positions)
    off += 24

    buf_avail, buf_total = struct.unpack_from('<HH', data, off)
    result['buffer_available'] = buf_avail
    result['buffer_total'] = buf_total
    off += 4

    state, alarm, limits, probe, homing, home_sw, estop_in, flags = \
        struct.unpack_from('<8B', data, off)
    result['state_id'] = state
    result['state'] = STATES.get(state, f"Unknown({state})")
    result['alarm_code'] = alarm
    result['limits'] = limits
    result['probe'] = bool(probe)
    result['homing_state'] = homing
    result['home_switches'] = home_sw
    result['estop'] = bool(estop_in)
    result['flags'] = flags
    off += 8

    seg_id = struct.unpack_from('<H', data, off)[0]
    result['current_segment_id'] = seg_id
    off += 2

    uptime = struct.unpack_from('<I', data, off)[0]
    result['uptime_ms'] = uptime
    off += 4

    feed_rate = struct.unpack_from('<i', data, off)[0]
    result['feed_rate'] = float(feed_rate)
    off += 4

    # v1.1 extended: misc_outputs, misc_inputs, spindle_state, coolant_state (4 bytes)
    remaining = len(data) - off
    if remaining >= 4:
        misc_out, misc_in, spindle_st, coolant_st = struct.unpack_from('<4B', data, off)
        result['misc_outputs'] = misc_out
        result['misc_inputs'] = misc_in
        result['spindle_state'] = spindle_st
        result['coolant_state'] = coolant_st
        off += 4

    # v1.1: spindle encoder (8 bytes)
    remaining = len(data) - off
    if remaining >= 8:
        enc_rpm, enc_pos, enc_idx = struct.unpack_from('<HHI', data, off)
        result['spindle_rpm'] = enc_rpm
        result['spindle_position'] = enc_pos
        result['spindle_index_count'] = enc_idx
        off += 8

    # v1.1: I/O module (4 bytes)
    remaining = len(data) - off
    if remaining >= 4:
        io_in, io_out = struct.unpack_from('<HH', data, off)
        result['io_inputs'] = io_in
        result['io_outputs'] = io_out

    return result


# ===================================================================
# Packet builders
# ===================================================================

def build_jog_packet(axis: int, direction: int, speed: int, seq: int = 0) -> bytes:
    """Build a jog command packet. direction is -1 or +1, speed in steps/sec."""
    payload = struct.pack('<bbxxI', axis, direction, speed)
    header = build_header(PacketType.JOG_COMMAND, len(payload), seq)
    return finalize_packet(header + payload)


def build_jog_stop_packet(axis: int = 0xFF, seq: int = 0) -> bytes:
    """Build a jog stop packet. axis=0xFF stops all axes."""
    payload = struct.pack('<Bxxx', axis)
    header = build_header(PacketType.JOG_STOP, len(payload), seq)
    return finalize_packet(header + payload)


def build_estop_packet(seq: int = 0) -> bytes:
    """Build an E-Stop packet (header only, no payload)."""
    header = build_header(PacketType.ESTOP, 0, seq)
    return finalize_packet(header)


def build_feed_hold_packet(seq: int = 0) -> bytes:
    """Build a feed hold packet (header only)."""
    header = build_header(PacketType.FEED_HOLD, 0, seq)
    return finalize_packet(header)


def build_feed_resume_packet(seq: int = 0) -> bytes:
    """Build a feed resume packet (header only)."""
    header = build_header(PacketType.FEED_RESUME, 0, seq)
    return finalize_packet(header)


def build_reset_packet(seq: int = 0) -> bytes:
    """Build a reset packet (header only)."""
    header = build_header(PacketType.RESET, 0, seq)
    return finalize_packet(header)


def build_home_packet(axis_mask: int, seq: int = 0) -> bytes:
    """Build a home command. axis_mask is a bitmask (bit0=X .. bit5=C)."""
    payload = struct.pack('<Bxxx', axis_mask)
    header = build_header(PacketType.HOME_COMMAND, len(payload), seq)
    return finalize_packet(header + payload)


def build_io_control_packet(misc_outputs: int, spindle_state: int,
                            spindle_rpm: int, coolant_state: int,
                            seq: int = 0) -> bytes:
    """Build an I/O control packet (UDP)."""
    payload = struct.pack('<BBHBxxx',
                          misc_outputs, spindle_state, spindle_rpm, coolant_state)
    header = build_header(PacketType.IO_CONTROL, len(payload), seq)
    return finalize_packet(header + payload)


def build_handshake_req(host_version: int = 0x01000000,
                        host_name: str = "TiggyUGS") -> bytes:
    """Build a TCP handshake request."""
    name_bytes = host_name.encode('ascii')[:DEVICE_NAME_LEN - 1]
    name_padded = name_bytes + b'\x00' * (DEVICE_NAME_LEN - len(name_bytes))
    payload = struct.pack('<I', host_version) + name_padded
    header = build_header(PacketType.HANDSHAKE_REQ, len(payload))
    return finalize_packet(header + payload)


def parse_handshake_resp(data: bytes) -> dict:
    """Parse a handshake response packet."""
    hdr = parse_header(data)
    off = HEADER_SIZE

    fw_ver = struct.unpack_from('<I', data, off)[0]
    off += 4
    num_axes = data[off]; off += 1
    caps = data[off]; off += 1
    buf_cap = struct.unpack_from('<H', data, off)[0]; off += 2
    max_rate = struct.unpack_from('<I', data, off)[0]; off += 4
    dev_name_raw = data[off:off + DEVICE_NAME_LEN]
    dev_name = dev_name_raw.split(b'\x00')[0].decode('ascii', errors='replace')
    off += DEVICE_NAME_LEN

    result = {
        'firmware_version': f"{(fw_ver >> 24) & 0xFF}.{(fw_ver >> 16) & 0xFF}.{fw_ver & 0xFFFF}",
        'firmware_version_raw': fw_ver,
        'num_axes': num_axes,
        'capabilities': caps,
        'buffer_capacity': buf_cap,
        'max_step_rate': max_rate,
        'device_name': dev_name,
        'device_mode': 0,
        'encoder_ppr': 0,
        'io_channel_count': 0,
    }

    # v1.1 extended fields (4 more bytes)
    remaining = len(data) - off
    if remaining >= 4:
        result['device_mode'] = data[off]
        result['encoder_ppr'] = (data[off + 1] << 8) | data[off + 2]
        result['io_channel_count'] = data[off + 3]

    return result


def build_motion_segment_packet(segments_list: list, seq: int = 0) -> bytes:
    """Build a motion segment packet containing up to 8 segments.

    Each segment is a dict with keys:
        steps: list of 6 ints (signed step counts per axis)
        duration_us: int
        entry_speed_sqr: int
        exit_speed_sqr: int
        acceleration: int
        segment_id: int
        flags: int
    """
    count = min(len(segments_list), MAX_SEGMENTS_PER_PACKET)
    parts = [struct.pack('<Bxxx', count)]

    for i in range(count):
        seg = segments_list[i]
        steps = seg.get('steps', [0] * MAX_AXES)
        while len(steps) < MAX_AXES:
            steps.append(0)
        parts.append(struct.pack(
            '<6iIIIIHBB',
            *steps[:MAX_AXES],
            seg.get('duration_us', 0),
            seg.get('entry_speed_sqr', 0),
            seg.get('exit_speed_sqr', 0),
            seg.get('acceleration', 0),
            seg.get('segment_id', 0),
            seg.get('flags', 0),
            0,  # reserved
        ))

    payload = b''.join(parts)
    header = build_header(PacketType.MOTION_SEGMENT, len(payload), seq)
    return finalize_packet(header + payload)


def build_config_get(key: int, value_type: int) -> bytes:
    """Build a CONFIG_GET request (TCP)."""
    payload = struct.pack('<HH', key, value_type) + b'\x00' * CONFIG_VALUE_LEN
    header = build_header(PacketType.CONFIG_GET, len(payload))
    return finalize_packet(header + payload)


def build_config_set(key: int, value_type: int, value) -> bytes:
    """Build a CONFIG_SET request (TCP).
    value: int, float, or str depending on value_type."""
    value_bytes = _encode_config_value(value_type, value)
    payload = struct.pack('<HH', key, value_type) + value_bytes
    header = build_header(PacketType.CONFIG_SET, len(payload))
    return finalize_packet(header + payload)


def build_config_save() -> bytes:
    """Build a CONFIG_SAVE request (TCP, header only)."""
    header = build_header(PacketType.CONFIG_SAVE, 0)
    return finalize_packet(header)


def _encode_config_value(value_type: int, value) -> bytes:
    """Encode a value into CONFIG_VALUE_LEN bytes."""
    buf = b'\x00' * CONFIG_VALUE_LEN
    if value_type == ValueType.UINT8:
        buf = struct.pack('<B', int(value)) + b'\x00' * (CONFIG_VALUE_LEN - 1)
    elif value_type == ValueType.UINT16:
        buf = struct.pack('<H', int(value)) + b'\x00' * (CONFIG_VALUE_LEN - 2)
    elif value_type == ValueType.UINT32:
        buf = struct.pack('<I', int(value)) + b'\x00' * (CONFIG_VALUE_LEN - 4)
    elif value_type == ValueType.INT32:
        buf = struct.pack('<i', int(value)) + b'\x00' * (CONFIG_VALUE_LEN - 4)
    elif value_type == ValueType.FLOAT:
        buf = struct.pack('<f', float(value)) + b'\x00' * (CONFIG_VALUE_LEN - 4)
    elif value_type == ValueType.STRING:
        s = str(value).encode('utf-8')[:CONFIG_VALUE_LEN - 1] + b'\x00'
        buf = s.ljust(CONFIG_VALUE_LEN, b'\x00')[:CONFIG_VALUE_LEN]
    return buf


def _decode_config_value(value_type: int, data: bytes):
    """Decode a config value from raw bytes."""
    if value_type == ValueType.UINT8:
        return data[0]
    elif value_type == ValueType.UINT16:
        return struct.unpack_from('<H', data, 0)[0]
    elif value_type == ValueType.UINT32:
        return struct.unpack_from('<I', data, 0)[0]
    elif value_type == ValueType.INT32:
        return struct.unpack_from('<i', data, 0)[0]
    elif value_type == ValueType.FLOAT:
        return struct.unpack_from('<f', data, 0)[0]
    elif value_type == ValueType.STRING:
        return data.split(b'\x00')[0].decode('utf-8', errors='replace')
    return None


def parse_config_resp(data: bytes) -> dict:
    """Parse a CONFIG_RESP packet. Returns dict with key, value_type, value, raw."""
    hdr = parse_header(data)
    off = HEADER_SIZE
    if len(data) < off + 4 + CONFIG_VALUE_LEN:
        return {'key': 0, 'value_type': 0, 'value': None, 'raw': b''}
    key, vtype = struct.unpack_from('<HH', data, off)
    off += 4
    raw = data[off:off + CONFIG_VALUE_LEN]
    value = _decode_config_value(vtype, raw)
    key_info = CONFIG_KEYS.get(key)
    name = key_info[0] if key_info else f"0x{key:04X}"
    return {
        'key': key,
        'key_name': name,
        'value_type': vtype,
        'value': value,
        'raw': raw,
    }


def build_ping(ping_id: int, seq: int = 0) -> bytes:
    """Build a PING packet (TCP keepalive)."""
    payload = struct.pack('<I', ping_id)
    header = build_header(PacketType.PING, len(payload), seq)
    return finalize_packet(header + payload)


# ===================================================================
# TCP framing helpers
# ===================================================================

def tcp_frame(packet: bytes) -> bytes:
    """Wrap a packet with a 2-byte little-endian length prefix for TCP."""
    return struct.pack('<H', len(packet)) + packet


def tcp_unframe(buffer: bytes) -> tuple:
    """Extract one packet from a TCP buffer.
    Returns (packet_bytes_or_None, remaining_buffer).
    If not enough data, returns (None, original_buffer)."""
    if len(buffer) < 2:
        return None, buffer
    pkt_len = struct.unpack_from('<H', buffer, 0)[0]
    if len(buffer) < 2 + pkt_len:
        return None, buffer
    packet = buffer[2:2 + pkt_len]
    remaining = buffer[2 + pkt_len:]
    return packet, remaining

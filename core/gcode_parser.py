"""
TiggyUGS G-Code Parser

A tolerant G-code parser that handles multiple controller formats
including Mach3, LinuxCNC, GRBL, and various CAM post-processors.
"""

import re
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Regex to split a G-code line into individual words like G1, X10.5, F200
# Handles cases with and without spaces between words.
_WORD_RE = re.compile(r'([A-Za-z])[#\-+]?(\d*\.?\d*)')

# G-codes that are motion commands
_MOTION_CODES = {'G0', 'G00', 'G1', 'G01', 'G2', 'G02', 'G3', 'G03'}
_RAPID_CODES = {'G0', 'G00'}
_ARC_CODES = {'G2', 'G02', 'G3', 'G03'}

# G-codes that set modal motion mode
_MODAL_MOTION = {'G0', 'G00', 'G1', 'G01', 'G2', 'G02', 'G3', 'G03',
                 'G38.2', 'G38.3', 'G38.4', 'G38.5',
                 'G80', 'G81', 'G82', 'G83', 'G84', 'G85', 'G86', 'G87', 'G88', 'G89'}

# Parameter letters (axes, offsets, feed, etc.)
_PARAM_LETTERS = set('XYZABCIJKRFSPQHLED')

# Letters that indicate an axis move (used for implicit motion detection)
_AXIS_LETTERS = set('XYZABC')


@dataclass
class GCodeLine:
    """Represents a single parsed G-code line."""
    line_number: int = 0
    original: str = ''
    cleaned: str = ''
    command: str = ''
    params: dict = field(default_factory=dict)
    is_motion: bool = False
    is_rapid: bool = False
    is_arc: bool = False
    is_comment: bool = False
    is_empty: bool = False
    comment: str = ''


@dataclass
class GCodeFile:
    """Represents a loaded G-code file."""
    lines: list = field(default_factory=list)
    filename: str = ''
    total_lines: int = 0
    motion_lines: int = 0
    bounds: dict = field(default_factory=lambda: {
        'x_min': 0.0, 'x_max': 0.0,
        'y_min': 0.0, 'y_max': 0.0,
        'z_min': 0.0, 'z_max': 0.0,
    })
    estimated_time: float = 0.0


def _strip_non_ascii(text: str) -> str:
    """Remove non-ASCII characters, keeping printable ASCII."""
    return text.encode('ascii', errors='ignore').decode('ascii')


def _extract_comments(text: str) -> tuple[str, str]:
    """Extract and remove comments from a G-code line.

    Handles:
      - Semicolon comments: everything after ';'
      - Parenthesis comments: text inside (...)
      - Keeps track of all comment text found.

    Returns (code_part, comment_text).
    """
    comment_parts = []

    # First strip semicolon comment (takes everything to end of line)
    semi_idx = text.find(';')
    if semi_idx != -1:
        comment_parts.append(text[semi_idx + 1:].strip())
        text = text[:semi_idx]

    # Strip parenthesis comments - handle nested/multiple
    result = []
    depth = 0
    current_comment = []
    for ch in text:
        if ch == '(':
            if depth == 0:
                current_comment = []
            depth += 1
        elif ch == ')' and depth > 0:
            depth -= 1
            if depth == 0:
                comment_parts.append(''.join(current_comment).strip())
        elif depth > 0:
            current_comment.append(ch)
        else:
            result.append(ch)

    code_part = ''.join(result)
    comment_text = ' '.join(c for c in comment_parts if c)
    return code_part, comment_text


def normalize_line(text: str) -> str:
    """Clean up a raw G-code line.

    - Strips non-ASCII characters
    - Normalizes whitespace
    - Converts to uppercase
    - Removes line number N-words
    - Removes block delete '/' prefix
    - Removes '%' program delimiters
    - Removes O-words (program numbers)
    - Strips comments (returned separately by _extract_comments)
    """
    # Strip non-ASCII
    text = _strip_non_ascii(text)

    # Strip whitespace and line endings
    text = text.strip()

    if not text:
        return ''

    # Block delete character
    if text.startswith('/'):
        text = text[1:].strip()

    # Program delimiter
    if text.strip() == '%':
        return ''

    # Uppercase
    text = text.upper()

    # Remove comments for the normalized form
    text, _ = _extract_comments(text)

    # Remove O-words (program numbers) like O100, O0200
    text = re.sub(r'\bO\d+\b', '', text, count=1).strip()

    # Remove N-words (line numbers) like N100, N0050
    text = re.sub(r'\bN\d+\b', '', text, count=1).strip()

    # Normalize whitespace
    text = ' '.join(text.split())

    return text


def _parse_words(text: str) -> list[tuple[str, str]]:
    """Parse a cleaned G-code line into a list of (letter, value_str) tuples.

    Handles cases with no spaces between words, e.g. 'G1X10Y20F100'.
    """
    words = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == ' ' or ch == '\t':
            i += 1
            continue
        if ch.isalpha():
            letter = ch.upper()
            i += 1
            # Collect the numeric value (may include -, +, .)
            val_start = i
            while i < len(text) and (text[i] in '0123456789.+-' or
                                     (text[i] == '-' and i == val_start)):
                i += 1
            val_str = text[val_start:i]
            words.append((letter, val_str))
        else:
            i += 1  # skip unexpected characters
    return words


def _safe_float(val_str: str) -> Optional[float]:
    """Safely convert a string to float, returning None on failure."""
    if not val_str:
        return None
    try:
        return float(val_str)
    except (ValueError, OverflowError):
        return None


def parse_line(text: str, line_number: int = 0) -> GCodeLine:
    """Parse a single G-code line into a GCodeLine object.

    This is the main entry point for line-by-line parsing. It handles
    all the tolerance features: comments, whitespace, case, missing
    spaces, N-words, block delete, O-words, etc.
    """
    result = GCodeLine(line_number=line_number, original=text)

    # Handle line endings and strip
    text = _strip_non_ascii(text).strip()

    if not text:
        result.is_empty = True
        return result

    # Check for pure % delimiter
    if text.strip() == '%':
        result.is_empty = True
        result.cleaned = ''
        return result

    # Block delete
    raw_for_comment = text
    if text.startswith('/'):
        raw_for_comment = text[1:].strip()

    # Extract comments from original (before normalizing)
    _, comment_text = _extract_comments(raw_for_comment.upper() if raw_for_comment else '')
    # Re-extract with original case for comment storage
    _, result.comment = _extract_comments(raw_for_comment)

    # Check if this is a pure comment line
    cleaned = normalize_line(text)
    result.cleaned = cleaned

    if not cleaned:
        if result.comment:
            result.is_comment = True
        else:
            result.is_empty = True
        return result

    # Parse words from cleaned line
    words = _parse_words(cleaned)

    if not words:
        result.is_empty = True
        return result

    # Separate G/M commands from parameters
    g_commands = []
    m_commands = []
    params = {}

    for letter, val_str in words:
        if letter == 'G':
            val = _safe_float(val_str)
            if val is not None:
                # Format as canonical G-code: G0, G1, G28, G92, etc.
                if val == int(val):
                    g_commands.append(f'G{int(val)}')
                else:
                    g_commands.append(f'G{val}')
        elif letter == 'M':
            val = _safe_float(val_str)
            if val is not None:
                if val == int(val):
                    m_commands.append(f'M{int(val)}')
                else:
                    m_commands.append(f'M{val}')
        elif letter == 'T':
            val = _safe_float(val_str)
            if val is not None:
                params['T'] = val
        elif letter in _PARAM_LETTERS:
            val = _safe_float(val_str)
            if val is not None:
                params[letter] = val

    result.params = params

    # Determine the primary command
    # Priority: last motion G-code > last non-motion G-code > last M-code
    motion_cmd = None
    non_motion_g = None

    for gc in g_commands:
        canonical = gc.replace('G00', 'G0').replace('G01', 'G1').replace('G02', 'G2').replace('G03', 'G3')
        if canonical in _MOTION_CODES or gc in _MOTION_CODES:
            motion_cmd = gc
        else:
            non_motion_g = gc

    if motion_cmd:
        result.command = motion_cmd
        result.is_motion = True
        canonical = motion_cmd
        # Normalize for comparison
        canonical = canonical.replace('G00', 'G0').replace('G01', 'G1')
        canonical = canonical.replace('G02', 'G2').replace('G03', 'G3')
        result.is_rapid = canonical in _RAPID_CODES
        result.is_arc = canonical in _ARC_CODES
    elif non_motion_g:
        result.command = non_motion_g
    elif m_commands:
        result.command = m_commands[-1]
    elif any(letter in _AXIS_LETTERS for letter in params):
        # Implicit motion: axis words without a G command
        # This will be resolved to the active modal motion mode by the caller
        result.command = ''  # empty means implicit
        result.is_motion = True
    else:
        # Only parameters, no command (e.g., just "F100")
        if params:
            # Pick first parameter letter as a pseudo-command
            result.command = ''

    return result


def parse_file(filepath: str) -> GCodeFile:
    """Load and parse an entire G-code file.

    Returns a GCodeFile with all lines parsed, bounds calculated,
    and estimated run time computed.
    """
    filepath = Path(filepath)
    result = GCodeFile(filename=filepath.name)

    # Read file with flexible encoding
    raw_text = None
    for encoding in ('utf-8', 'latin-1', 'cp1252', 'ascii'):
        try:
            raw_text = filepath.read_text(encoding=encoding)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if raw_text is None:
        # Last resort: read as bytes and decode leniently
        raw_bytes = filepath.read_bytes()
        raw_text = raw_bytes.decode('utf-8', errors='replace')

    # Normalize line endings and split
    raw_text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
    raw_lines = raw_text.split('\n')

    # Parse all lines
    parsed_lines = []
    for i, raw_line in enumerate(raw_lines):
        parsed = parse_line(raw_line, line_number=i + 1)
        parsed_lines.append(parsed)

    result.lines = parsed_lines
    result.total_lines = len(parsed_lines)
    result.motion_lines = sum(1 for ln in parsed_lines if ln.is_motion)

    # Calculate bounds and estimated time
    _calculate_bounds_and_time(result)

    return result


def _calculate_bounds_and_time(gcode_file: GCodeFile) -> None:
    """Walk through all lines tracking position to compute bounds and time estimate.

    Handles G90 (absolute) and G91 (incremental) positioning modes.
    """
    pos = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
    absolute_mode = True
    feed_rate = 1000.0  # mm/min default
    rapid_rate = 5000.0  # mm/min for rapids
    modal_motion = 'G0'  # default modal motion mode

    x_min = x_max = 0.0
    y_min = y_max = 0.0
    z_min = z_max = 0.0
    total_time = 0.0

    for line in gcode_file.lines:
        if line.is_empty or line.is_comment:
            continue

        cmd = line.command.upper() if line.command else ''

        # Handle modal state changes
        if cmd == 'G90':
            absolute_mode = True
            continue
        elif cmd == 'G91':
            absolute_mode = False
            continue
        elif cmd == 'G92':
            # Set position - update current pos to given values
            for axis in ('X', 'Y', 'Z'):
                if axis in line.params:
                    pos[axis] = line.params[axis]
            continue
        elif cmd == 'G28':
            # Home - move to zero (simplified)
            pos = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
            continue

        # Update feed rate if present
        if 'F' in line.params:
            f_val = line.params['F']
            if f_val > 0:
                feed_rate = f_val

        # Determine effective motion command
        effective_cmd = cmd
        if not effective_cmd and line.is_motion:
            effective_cmd = modal_motion

        # Normalize
        norm = effective_cmd.replace('G00', 'G0').replace('G01', 'G1')
        norm = norm.replace('G02', 'G2').replace('G03', 'G3')

        # Update modal motion if this is a motion command
        if norm in _MOTION_CODES:
            modal_motion = norm

        if not line.is_motion and norm not in _MOTION_CODES:
            continue

        # Calculate target position
        prev_pos = dict(pos)
        for axis in ('X', 'Y', 'Z'):
            if axis in line.params:
                if absolute_mode:
                    pos[axis] = line.params[axis]
                else:
                    pos[axis] += line.params[axis]

        # Update bounds
        x_min = min(x_min, pos['X'])
        x_max = max(x_max, pos['X'])
        y_min = min(y_min, pos['Y'])
        y_max = max(y_max, pos['Y'])
        z_min = min(z_min, pos['Z'])
        z_max = max(z_max, pos['Z'])

        # Estimate time for this move
        dx = pos['X'] - prev_pos['X']
        dy = pos['Y'] - prev_pos['Y']
        dz = pos['Z'] - prev_pos['Z']
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        if dist > 0:
            if norm in _RAPID_CODES:
                rate = rapid_rate
            else:
                rate = feed_rate if feed_rate > 0 else 1000.0

            # rate is mm/min, time in seconds
            move_time = (dist / rate) * 60.0
            total_time += move_time

    gcode_file.bounds = {
        'x_min': x_min, 'x_max': x_max,
        'y_min': y_min, 'y_max': y_max,
        'z_min': z_min, 'z_max': z_max,
    }
    gcode_file.estimated_time = total_time

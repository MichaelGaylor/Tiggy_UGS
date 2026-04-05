# TiggyUGS - Universal G-Code Sender

A full-featured Universal G-Code Sender for CNC machines, built with Python and PyQt6. Designed for the Tiggy WiFi CNC Controller but also supports standard GRBL controllers via serial and WiFi.

![TiggyUGS Screenshot](https://github.com/MichaelGaylor/Tiggy_UGS/blob/main/resources/screenshot.png?raw=true)

## Download

**[Download TiggyUGS.exe (Windows)](https://github.com/MichaelGaylor/Tiggy_UGS/releases)**

No installation required - just download and run.

## Features

- **3 Connection Methods**
  - **WiFi Packet (Tiggy)** - Native binary protocol for Tiggy WiFi CNC Controllers (TCP + UDP)
  - **Serial GRBL** - Standard GRBL over USB/COM port (115200 baud)
  - **WiFi GRBL** - GRBL over WiFi telnet (port 23)

- **3D Toolpath Visualizer**
  - OpenGL 3D view of loaded G-code
  - Real-time tool position tracking
  - Left-drag to rotate, right-drag to pan, scroll to zoom
  - Progress coloring (completed/current/upcoming)

- **6-Axis Support** (X, Y, Z, A, B, C)
  - Digital Readout (DRO) with work/machine coordinate toggle
  - Per-axis zero buttons

- **Jog Controls**
  - Step mode (precise distance via motion segments)
  - Continuous mode (hold to jog, release to stop)
  - XY cross pad + Z column + ABC buttons
  - Configurable step sizes: 0.01, 0.1, 1.0, 10.0, 100.0 mm
  - Keyboard shortcuts: Arrow keys (XY), Page Up/Down (Z)

- **Run Controls**
  - Run / Pause / Stop / E-STOP
  - Real-time progress bar
  - Feed rate override (0-200%)
  - Spindle speed override (0-200%)
  - Rapid override (25%, 50%, 100%)

- **Spindle & Coolant**
  - CW (M3) / CCW (M4) / OFF (M5) control
  - RPM setting
  - Flood (M7) / Mist (M8) / Off (M9) coolant control
  - Real-time status display from controller

- **Tolerant G-Code Parser**
  - Handles Mach3, LinuxCNC, GRBL, and other formats
  - Missing spaces, mixed case, N-words, comments, % delimiters
  - G90/G91 absolute/incremental, G20/G21 inch/metric
  - Arc linearization (G2/G3 with I/J/K or R format)

- **Console**
  - Manual G-code command entry
  - Color-coded output (sent/response/error/info)
  - Command history (up/down arrows)

- **Connection Settings Saved**
  - IP address, port, baud rate remembered between sessions
  - Auto-discovery for Tiggy WiFi controllers

## Requirements

- Python 3.10+
- Windows 10/11 (for the pre-built EXE)

### Python Dependencies

```
PyQt6>=6.6.0
PyOpenGL>=3.1.7
numpy>=1.24.0
pyserial>=3.5
```

## Running from Source

```bash
# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

## Building the EXE

```bash
# Run the build script (creates venv, installs deps, builds EXE)
build.bat

# Output: dist/TiggyUGS.exe
```

## Project Structure

```
TiggyUGS/
  main.py                  # Application entry point
  build.bat                # PyInstaller build script
  requirements.txt         # Python dependencies
  core/
    protocol.py            # Tiggy WiFi CNC binary protocol
    gcode_parser.py        # Tolerant G-code parser
    gcode_sender.py        # G-code streaming engine
    planner.py             # Motion planner (G-code to segments)
  connection/
    base.py                # Abstract connection interface
    wifi_packet.py         # Tiggy WiFi packet protocol (TCP+UDP)
    serial_grbl.py         # Serial GRBL connection
    wifi_grbl.py           # WiFi GRBL telnet connection
  gui/
    main_window.py         # Main application window
    dro_widget.py          # Digital Readout display
    jog_widget.py          # Jog control panel
    control_widget.py      # Run controls, overrides, spindle/coolant
    console_widget.py      # Command console
    status_bar_widget.py   # Connection and machine status bar
    visualizer_widget.py   # OpenGL 3D toolpath viewer
  resources/               # Icons and assets
```

## Tiggy WiFi CNC Protocol

The WiFi Packet connection mode uses a custom binary protocol:
- **TCP port 58429** - Handshake, configuration, keepalive
- **UDP port 58427** - Motion segments, jog, E-stop, I/O control (PC to controller)
- **UDP port 58428** - Status reports, alarms (controller to PC)

Compatible with all Tiggy controller boards:
- Tiggy Standard (ESP32-S3-Zero)
- Tiggy Pro Octal (ESP32-S3-DevKitC-1 N16R8)
- Tiggy Pro Quad (ESP32-S3-DevKitC-1 N8)
- Tiggy Classic (ESP32-WROOM-32)

## License

MIT License

## Author

Michael Gaylor

@echo off
REM ============================================================
REM  TiggyUGS Build Script
REM  Builds the Python application into a standalone Windows EXE
REM ============================================================

echo.
echo  ===================================
echo   TiggyUGS Build System
echo  ===================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

REM Check if venv exists, create if not
if not exist "venv" (
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install/upgrade dependencies
echo [INFO] Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

REM Clean previous build
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build

echo [INFO] Building TiggyUGS executable...
echo.

REM Build icon argument only if icon file exists
set ICON_ARG=
if exist "resources\tiggy_icon.ico" (
    set ICON_ARG=--icon "resources\tiggy_icon.ico"
    echo [INFO] Using custom icon: resources\tiggy_icon.ico
) else (
    echo [INFO] No icon file found, building without custom icon.
)

pyinstaller ^
    --name "TiggyUGS" ^
    --onefile ^
    --windowed ^
    %ICON_ARG% ^
    --add-data "resources;resources" ^
    --hidden-import "PyQt6.QtOpenGLWidgets" ^
    --hidden-import "OpenGL.platform.win32" ^
    --hidden-import "OpenGL.GL" ^
    --hidden-import "OpenGL.GLU" ^
    --hidden-import "numpy" ^
    --hidden-import "serial" ^
    --hidden-import "serial.tools.list_ports" ^
    --collect-all "PyQt6" ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo  ===================================
echo   BUILD SUCCESSFUL!
echo   Output: dist\TiggyUGS.exe
echo  ===================================
echo.

REM Copy resources to dist if needed
if not exist "dist\resources" mkdir "dist\resources"
xcopy /s /y "resources\*" "dist\resources\" >nul 2>&1

pause

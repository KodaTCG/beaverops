@echo off
title BeaverOps Agent
color 0A

echo.
echo  ==========================================
echo   BEAVEROPS AGENT
echo  ==========================================
echo.

REM ── Check for Python ──
python --version >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON_CMD=python
    goto :found_python
)

py --version >nul 2>&1
if %errorlevel% == 0 (
    set PYTHON_CMD=py
    goto :found_python
)

color 0C
echo  ERROR: Python is not installed.
echo.
echo  1. Go to https://www.python.org/downloads/
echo  2. Install Python
echo  3. CHECK "Add Python to PATH" during install
echo  4. Restart your computer
echo  5. Double-click start-agent.bat again
echo.
pause >nul
start https://www.python.org/downloads/
exit /b 1

:found_python
echo  Starting BeaverOps Agent...
echo.
%PYTHON_CMD% agent.py

if %errorlevel% neq 0 (
    color 0C
    echo.
    echo  Something went wrong. Check the error above.
    pause
)

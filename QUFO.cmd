@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run SETUP.cmd first.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "scripts\launch.py"

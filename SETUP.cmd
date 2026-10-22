@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv --system-site-packages .venv
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\configure_gpu.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\prepare_models.py
if errorlevel 1 goto failed
.venv\Scripts\python.exe scripts\import_microsoft.py
if errorlevel 1 goto failed
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-shortcut.ps1
if errorlevel 1 goto failed
echo QUFO is ready. Use the desktop shortcut to open your workspace.
pause
exit /b 0
:failed
echo Setup did not finish. Read the message above and try again.
pause
exit /b 1

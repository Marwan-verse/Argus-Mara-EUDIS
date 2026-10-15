@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo Python 3.10 or newer is required.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts/start_soc_forwarded.py %*
if errorlevel 1 (
  pause
  exit /b 1
)
pause

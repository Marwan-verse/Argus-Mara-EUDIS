@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run RUN-GUI-WINDOWS.bat once to create the project Python environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info < (3, 12))"
if errorlevel 1 (
  echo The optional satellite readers need Python 3.12 or newer.
  echo The existing offline desktop can still run with its current Python.
  pause
  exit /b 1
)
echo Installing the optional satellite image and AIS archive readers...
".venv\Scripts\python.exe" -m pip install -r requirements-satellite.txt -r recorder/requirements.txt
if errorlevel 1 (
  echo Installation failed. Check the connection and try again.
  pause
  exit /b 1
)
echo Ready. Open Satellite analysis. Start scan enables automatic image cycles under the pilot limit.
pause

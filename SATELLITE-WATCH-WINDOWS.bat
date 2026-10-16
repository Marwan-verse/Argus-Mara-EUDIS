@echo off
rem Double-click to compare fresh satellite images with AIS: update, install the
rem satellite image readers once, connect the TensorX and team database keys once
rem (hidden, saved in Windows Credential Manager), then open the app on Satellite
rem analysis with Coast Watch running.
setlocal
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
  echo Git is not installed, so the version already on this computer will start.
) else (
  echo Fetching the latest version of this branch...
  git pull --ff-only
  if errorlevel 1 echo Update failed, so the version already on this computer will start.
)
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if not errorlevel 1 py -3 -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  where python >nul 2>nul
  if not errorlevel 1 python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  echo Python 3.12 or newer with Tkinter is required.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import sys; raise SystemExit(sys.version_info < (3, 12))"
if errorlevel 1 (
  echo The satellite image readers need Python 3.12 or newer.
  echo Install it from python.org, delete the .venv folder and try again.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import customtkinter, PIL, cryptography, keyring, numpy, rasterio, pyarrow, websockets" >nul 2>nul
if errorlevel 1 (
  echo Installing the app and the satellite image readers. First time only, a few minutes...
  ".venv\Scripts\python.exe" -m pip install -r requirements-satellite.txt -r recorder/requirements.txt
  if errorlevel 1 (
    echo Install failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
)
echo.
".venv\Scripts\python.exe" scripts\satellite_watch.py
if errorlevel 1 (
  pause
  exit /b 1
)
echo.
echo Opening the app. Coast Watch works while the app stays open; Stop in the app pauses it.
".venv\Scripts\python.exe" run_gui.py --coast-watch
if errorlevel 1 pause

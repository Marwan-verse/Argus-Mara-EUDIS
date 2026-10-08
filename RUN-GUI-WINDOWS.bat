@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if not errorlevel 1 py -3 -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  where python >nul 2>nul
  if not errorlevel 1 python -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
  if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m venv .venv
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo Python 3.10 or newer with Tkinter is required.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import customtkinter, PIL" >nul 2>nul
if errorlevel 1 (
  echo Installing the desktop UI dependency...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Install failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" run_gui.py
if errorlevel 1 pause

@echo off
cd /d "%~dp0.."
title Argus Mara - ship recorder

echo ==========================================
echo    ARGUS MARA - ship recorder
echo ==========================================
echo.

set PY=py
%PY% --version >nul 2>&1
if %errorlevel%==0 goto haspython
set PY=python
%PY% --version >nul 2>&1
if %errorlevel%==0 goto haspython
goto nopython

:haspython
if exist .venv\Scripts\python.exe goto ready
echo Setting up. First time only, about a minute...
%PY% -m venv .venv
if not %errorlevel%==0 goto venvfailed
.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check --upgrade pip
.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r recorder\requirements.txt
if not %errorlevel%==0 goto pipfailed

:ready
echo.
echo LEAVE THIS WINDOW OPEN. That is all it needs.
echo To stop: close the window.
echo.
.venv\Scripts\python.exe recorder\recorder.py
echo.
echo Recorder stopped.
pause
exit /b 0

:nopython
echo Python is not installed on this computer.
echo.
echo   1. Open https://www.python.org/downloads/
echo   2. Download and run the installer
echo   3. IMPORTANT: tick "Add python.exe to PATH" on the first screen
echo   4. Then double-click this file again
echo.
pause
exit /b 1

:venvfailed
echo.
echo Could not set up Python in this folder.
echo Send a screenshot of this window to the team chat.
echo.
pause
exit /b 1

:pipfailed
echo.
echo Could not download the two libraries it needs.
echo Check your internet connection and run this file again.
echo.
pause
exit /b 1

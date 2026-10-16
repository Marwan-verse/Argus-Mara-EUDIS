@echo off
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
call "%~dp0RUN-GUI-OLD-WINDOWS.bat"

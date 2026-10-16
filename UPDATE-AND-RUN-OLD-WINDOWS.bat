@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
  echo Git is not installed, so the version already on this computer will start.
) else (
  for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
  if /i not "!BRANCH!"=="main" (
    echo You are on branch "!BRANCH!". The newest version of the app is on "main".
    choice /c YN /m "Switch to main now"
    if not errorlevel 2 (
      git checkout main
      if errorlevel 1 echo Could not switch to main ^(uncommitted changes?^). Staying on "!BRANCH!".
    )
  )
  echo Fetching the latest version of this branch...
  git pull --ff-only
  if errorlevel 1 echo Update failed, so the version already on this computer will start.
)
call "%~dp0RUN-GUI-OLD-WINDOWS.bat"

@echo off
setlocal
cd /d "%~dp0.."
where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\serve_demo.py
  goto :done
)
python --version >nul 2>nul
if not errorlevel 1 (
  python scripts\serve_demo.py
  goto :done
)
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\serve_demo.py
  goto :done
)
echo Python 3 is required. Install it from https://www.python.org/downloads/
echo Then double-click this launcher again.
:done
pause

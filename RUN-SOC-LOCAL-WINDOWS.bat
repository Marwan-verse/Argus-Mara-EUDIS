@echo off
setlocal
cd /d "%~dp0"
set "ARGUS_SOC_URL=https://localhost:8443"
set "ARGUS_SOC_CA_FILE=%~dp0data\soc-local\caddy-root.crt"
if not exist "%ARGUS_SOC_CA_FILE%" (
  echo Run scripts\start_soc_local.ps1 first. See soc\LOCAL-DEMO.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run_gui.py --soc-login
if errorlevel 1 pause

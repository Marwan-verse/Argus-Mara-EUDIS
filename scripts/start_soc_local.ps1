param([switch]$OpenClients)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRepo
$taskDocker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $taskDocker) {
    foreach ($taskCandidate in @((Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'), 'C:\Program Files\Docker\Docker\resources\bin\docker.exe')) {
        if (Test-Path -LiteralPath $taskCandidate) { $taskDocker = Get-Item -LiteralPath $taskCandidate; break }
    }
}
if (-not $taskDocker) { throw 'Install and start Docker Desktop first. See soc/LOCAL-DEMO.md.' }
$taskDockerPath = if ($taskDocker.Source) { $taskDocker.Source } else { $taskDocker.FullName }
& $taskDockerPath info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is not ready. Start Docker Desktop and wait for it to say Running.' }
$taskPrivate = Join-Path $taskRepo 'data\soc-local'
New-Item -ItemType Directory -Path $taskPrivate -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $taskPrivate 'demo.env'))) {
    throw 'Private demo.env is missing. Follow soc/LOCAL-DEMO.md to create the sample credentials.'
}
$taskCompose = @('compose','-f','soc/compose.local.yml')
& $taskDockerPath @taskCompose up -d --build relay https
if ($LASTEXITCODE -ne 0) { throw 'Container startup failed. Read Docker output above.' }
& $taskDockerPath @taskCompose run --rm seed
if ($LASTEXITCODE -ne 0) { throw 'Account seeding failed.' }
$taskCaPath = Join-Path $taskPrivate 'caddy-root.crt'
$taskCopied = $false
for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
    & $taskDockerPath @taskCompose cp 'https:/data/caddy/pki/authorities/local/root.crt' $taskCaPath 2>$null
    if ($LASTEXITCODE -eq 0) { $taskCopied = $true; break }
    Start-Sleep -Seconds 1
}
if (-not $taskCopied) { throw 'Caddy did not create its local CA. Inspect the https container logs.' }
$taskPython = Join-Path $taskRepo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { py -3 -m venv .venv }
& $taskPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Client dependency installation failed.' }
& $taskPython scripts/smoke_soc_local.py --ca $taskCaPath
if ($LASTEXITCODE -ne 0) { throw 'HTTPS/E2EE smoke check failed.' }
Write-Host 'Local SOC is ready at https://localhost:8443. The relay port is private.'
Write-Host 'Start RUN-SOC-LOCAL-WINDOWS.bat and sign in with your local sample accounts.'
if ($OpenClients) {
    $env:ARGUS_SOC_URL = 'https://localhost:8443'
    $env:ARGUS_SOC_CA_FILE = $taskCaPath
    Start-Process -FilePath $taskPython -WorkingDirectory $taskRepo -ArgumentList 'run_gui.py','--soc-login'
    Start-Process -FilePath $taskPython -WorkingDirectory $taskRepo -ArgumentList 'run_gui.py','--soc-login'
}

param([switch]$InstallDocker)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $Python)) { throw 'Project .venv is missing.' }
$Docker = Get-Command docker -ErrorAction SilentlyContinue
if (!$Docker) {
    foreach ($Candidate in @("$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe")) {
        if (Test-Path -LiteralPath $Candidate) { $Docker = Get-Item -LiteralPath $Candidate; break }
    }
}
if (!$Docker -and $InstallDocker) {
    & winget install --id Docker.DockerDesktop --exact --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Docker installation failed. Install Docker Desktop in your own Windows session, then rerun this script.' }
    throw 'Finish Docker Desktop first-run setup (WSL2/reboot if requested), reopen PowerShell, then rerun without -InstallDocker.'
}
if (!$Docker) { throw 'Docker Desktop not found. Run this script with -InstallDocker in your own Windows session.' }
$DockerExe = if ($Docker.Source) { $Docker.Source } else { $Docker.FullName }
& $DockerExe info --format '{{.ServerVersion}}' 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and finish WSL2 setup before continuing.' }
& $Python -m pip install -e "$Root[storage]"
if ($LASTEXITCODE -ne 0) { throw 'Storage dependency installation failed.' }
& $Python (Join-Path $PSScriptRoot 'storage_services.py') init
if ($LASTEXITCODE -ne 0) { throw 'Service configuration failed.' }
$ComposeArgs = @('compose', '--env-file', (Join-Path $Root '.env.services'), '-f', (Join-Path $Root 'compose.storage.yaml'))
& $DockerExe @ComposeArgs config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration invalid; no services were started.' }
Write-Host 'Pulling PostgreSQL, Redis and Qdrant images...'
& $DockerExe @ComposeArgs pull postgres redis qdrant
if ($LASTEXITCODE -ne 0) { throw 'Image download failed; no storage backend was changed. Check the named image and registry connectivity.' }
Write-Host 'Building MinIO from pinned upstream source; first build may take several minutes...'
& $DockerExe @ComposeArgs build minio
if ($LASTEXITCODE -ne 0) { throw 'MinIO source build failed; no storage backend was changed. Do not delete data volumes.' }
& $DockerExe @ComposeArgs up -d --no-build --pull never
if ($LASTEXITCODE -ne 0) { throw 'Service startup failed; no storage backend was changed.' }
& $Python (Join-Path $PSScriptRoot 'storage_services.py') connect
if ($LASTEXITCODE -ne 0) { throw 'Connection/migration failed; existing source data was preserved.' }
Write-Host 'Services connected. Restart the PolicyPilot API to load .env.storage.'

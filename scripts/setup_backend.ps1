# Create a local Python virtual environment for the backend and install
# runtime + dev dependencies. Windows PowerShell.
#
# Usage (from anywhere):  .\scripts\setup_backend.ps1
#   Optional:             .\scripts\setup_backend.ps1 -Python "C:\Path\To\python.exe"
# Then:                   .\backend\.venv\Scripts\Activate.ps1
#                         cd backend; pytest
#
# Conda alternative:      conda env create -f backend/environment.yml
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot "backend"
$VenvDir = Join-Path $BackendDir ".venv"

# The backend targets Python 3.12 (matches the Docker image and CI).
& $Python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python 3.12+ is required. Pass -Python with the path to a 3.12 interpreter."
    exit 1
}

Write-Host "Creating virtual environment in $VenvDir"
& $Python -m venv $VenvDir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $VenvPython -m pip install -r (Join-Path $BackendDir "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Done. Activate with: .\backend\.venv\Scripts\Activate.ps1"
Write-Host 'Run the API (mock mode): cd backend; $env:LLM_PROVIDER="mock"; $env:DATA_DIR="./data"; uvicorn app.main:app --reload'

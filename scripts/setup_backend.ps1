# Create a local Python virtual environment for the backend and install
# runtime + dev dependencies. Windows PowerShell.
#
# If script execution is blocked, first allow it for this PowerShell session only:
#                         Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
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
Write-Host "Done."
Write-Host "Note: if activation is blocked by execution policy, run first (this session only):"
Write-Host "  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass"
Write-Host "Activate with: .\backend\.venv\Scripts\Activate.ps1"
Write-Host 'Run the API (mock mode): cd backend; $env:LLM_PROVIDER="mock"; $env:DATA_DIR="./data"; uvicorn app.main:app --reload'
Write-Host "Then open http://127.0.0.1:8000/api/health (use 127.0.0.1, not localhost: localhost may resolve to IPv6, which uvicorn does not listen on)."
Write-Host "API docs: http://127.0.0.1:8000/api/docs"
Write-Host ""
Write-Host "Real model (native Ollama instead of Docker):"
Write-Host '  - Point the backend at it: $env:OLLAMA_BASE_URL="http://127.0.0.1:11434" (the default http://ollama:11434 is the Docker hostname).'
Write-Host "  - Run Ollama with flash attention and a q8_0 KV cache, so the 16k context fits in 8 GB of VRAM (docs/DECISIONS.md D-023):"
Write-Host "      setx OLLAMA_FLASH_ATTENTION 1"
Write-Host "      setx OLLAMA_KV_CACHE_TYPE q8_0"
Write-Host "    then fully quit Ollama (tray icon > Quit, and check no ollama.exe is left in Task Manager) and start it again."
Write-Host "    Check: %LOCALAPPDATA%\Ollama\server.log should show '--flash-attn on'; 'ollama ps' shows ~4.4 GB, not 5.5 GB."
Write-Host "  - Live model tests (opt-in): cd backend; pytest -m ollama"

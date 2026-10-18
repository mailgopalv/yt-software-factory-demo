# Starts the AI Software Factory server and dashboard on http://localhost:8000
#   .\run-factory.ps1          real agents (your Claude subscription)
#   .\run-factory.ps1 -Demo    demo mode: replays the recordings in demo\, no Claude usage
# Press Ctrl+C to stop the server. A run already in progress keeps going in the background.
param([switch]$Demo)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating Python virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    & $python -m pip install --quiet --upgrade pip
}
& $python -m pip install --quiet -r requirements.txt

if ($Demo) { $env:DEMO_MODE = "1" } else { Remove-Item Env:DEMO_MODE -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "  Factory dashboard: http://localhost:8000" -ForegroundColor Green
Write-Host "  Factory API docs:  http://localhost:8000/docs" -ForegroundColor Green
if ($Demo) { Write-Host "  DEMO MODE: replaying recordings, no Claude usage" -ForegroundColor Yellow }
Write-Host ""
& $python -m uvicorn server.app:app --host 127.0.0.1 --port 8000

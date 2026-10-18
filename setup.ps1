# One-time setup on Windows. Run from this folder:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Safe to run again: it skips anything already done.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Need($command, $hint) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        Write-Host "Missing: $command. $hint" -ForegroundColor Red
        exit 1
    }
}
Need git "Install Git from https://git-scm.com"
Need python "Install Python 3.11 or newer from https://www.python.org"
Need node "Install Node.js 20 or newer from https://nodejs.org"
$pyVersion = python -c "import sys; print(sys.version_info >= (3, 11))"
if ($pyVersion -ne "True") { Write-Host "Python 3.11 or newer is needed." -ForegroundColor Red; exit 1 }

# 1. The store is its own git repo (the factory branches, merges and tags it), shipped as store.bundle.
if (-not (Test-Path "store\.git")) {
    Write-Host "Unpacking the Corner Shop store repo from store.bundle..." -ForegroundColor Cyan
    git clone --quiet store.bundle store
    git -C store remote remove origin
}

# 2. The store's Python and Node packages, the Playwright browser and the database.
& .\store\setup-store.ps1
Set-Location $PSScriptRoot   # setup-store changes the current folder

# 3. The factory's Python packages.
Set-Location software-factory
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating the factory's Python environment..." -ForegroundColor Cyan
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
}
& .\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
Set-Location ..

Write-Host ""
Write-Host "Setup complete. Next, in two terminals:" -ForegroundColor Green
Write-Host "  1) cd store;            .\run-store.ps1          (store: http://localhost:5173)"
Write-Host "  2) cd software-factory; .\run-factory.ps1 -Demo  (dashboard: http://localhost:8000)"

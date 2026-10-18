# Restores the store code, its database and the factory's runs to a checkpoint, for re-shooting a scene.
#   .\reset-to.ps1 checkpoint-2-factory-added
# Run without a name to list the checkpoints.
param([string]$Checkpoint)
Set-Location $PSScriptRoot
$python = ".\.venv\Scripts\python.exe"
if (-not $Checkpoint) {
    & $python -m factory checkpoints
    exit 0
}
& $python -m factory reset-to $Checkpoint

param([string]$Python = '3.12')
$ErrorActionPreference = 'Stop'
$taskBrainDirectory = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskBrainDirectory
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'Install uv first: winget install --id=astral-sh.uv -e'
    }
    if (-not (Test-Path -LiteralPath '.venv')) {
        & uv venv --python $Python .venv
        if ($LASTEXITCODE -ne 0) { throw 'Creating the Python 3.12 environment failed.' }
    }
    $taskPython = Join-Path $taskBrainDirectory '.venv\Scripts\python.exe'
    & $taskPython -c "import sys; assert sys.version_info[:2] == (3, 12), 'Use Python 3.12'"
    if ($LASTEXITCODE -ne 0) { throw 'Wrong Python version in .venv.' }
    & uv pip sync --python $taskPython requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Installing the locked packages failed.' }
    & uv pip install --python $taskPython --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw 'Installing the editable CIVIS package failed.' }
    if (-not (Test-Path -LiteralPath '.env')) {
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
    }
    & $taskPython scripts/doctor.py
    if ($LASTEXITCODE -ne 0) { throw 'Environment verification failed.' }
} finally { Pop-Location }

param([string]$EnvFile = '.env.partner')
$ErrorActionPreference = 'Stop'
$brainDirectory = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $brainDirectory
try {
    $python = Join-Path $brainDirectory '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Run brain/scripts/setup.ps1 first.'
    }
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        throw 'Missing partner environment. Obtain the separate .env.partner from Elyes.'
    }
    # Validate the explicit file without printing credentials.
    & $python -c "import sys; from civis_brain.settings import Settings; s=Settings(_env_file=sys.argv[1]); assert s.peer_mode=='live', 'Partner launcher requires PEER_MODE=live'; assert s.llm_mode=='gemini' and s.gemini_api_key, 'Configure Gemini in the selected file'; assert s.twin_feed_enabled, 'Partner launcher requires TWIN_FEED_ENABLED=true'" $EnvFile
    if ($LASTEXITCODE -ne 0) { throw 'Partner environment validation failed.' }
    & $python -m civis_brain --env-file $EnvFile
    if ($LASTEXITCODE -ne 0) { throw 'Brain stopped with an error.' }
} finally { Pop-Location }

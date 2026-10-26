param(
    [switch]$IncludeBrainTests,
    [string]$TwinTag = 'twin-mock-3',
    [string]$GuardianTag = 'guardian_mock_v3',
    [switch]$DiagnosticsOnly
)
$ErrorActionPreference = 'Stop'
$brainDirectory = Split-Path -Parent $PSScriptRoot
$repoDirectory = Split-Path -Parent $brainDirectory
$runId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$auditDirectory = Join-Path $repoDirectory ('.interop\tagged-v3\' + $runId)
$environmentDirectory = Join-Path $repoDirectory '.interop\tagged-v3\venv'
$testPython = Join-Path $environmentDirectory 'Scripts\python.exe'
$artifacts = Join-Path $brainDirectory ('.artifacts\tagged-v3\' + $runId)
$environmentNames = @(
    'CIVIS_TEST_TWIN_ROOT', 'CIVIS_TEST_GUARDIAN_ROOT', 'CIVIS_TEST_GUARDIAN_PYTHON',
    'CIVIS_TEST_ARTIFACT_DIR', 'GUARDIAN_TOKEN_PRIVATE_KEY', 'GUARDIAN_TOKEN_PUBLIC_KEY',
    'GUARDIAN_AUDIT_DIR', 'PYTHONUTF8'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
Push-Location -LiteralPath $repoDirectory
try {
    $brainPython = Join-Path $brainDirectory '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $brainPython)) { throw 'Run Brain setup first.' }
    # Fresh extraction avoids ghost files; annotated and lightweight tags resolve alike.
    @'
import hashlib, io, json, subprocess, sys, tarfile
from datetime import datetime, timezone
from pathlib import Path
root = Path.cwd().resolve()
dest, artifacts = (Path(value).resolve() for value in sys.argv[1:3])
assert dest.is_relative_to(root/'.interop') and not dest.exists()
assert artifacts.is_relative_to(root/'brain/.artifacts') and not artifacts.exists()
dest.mkdir(parents=True); artifacts.mkdir(parents=True)
manifest = {'created_at': datetime.now(timezone.utc).isoformat(),
    'brain_commit': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
    'brain_worktree': subprocess.check_output(['git','status','--short','--','brain'], text=True).splitlines(),
    'partner_source_modified': False, 'planner': 'recorded test planner, not live Gemini',
    'diagnostic_ingestion': 'manual ingestion tests are diagnostic; acceptance uses Guardian own bridge',
    'partners': []}
for tag, folder in [(sys.argv[3], 'twin'), (sys.argv[4], 'guardian')]:
    ref = 'refs/tags/' + tag
    tag_object = subprocess.check_output(['git','rev-parse','--verify',ref], text=True).strip()
    commit = subprocess.check_output(['git','rev-parse','--verify',ref+'^{commit}'], text=True).strip()
    data = subprocess.check_output(['git','archive',commit,folder])
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for item in archive.getmembers():
            path = (dest/item.name).resolve()
            if not path.is_relative_to(dest) or item.issym() or item.islnk():
                raise SystemExit('Unsafe archive entry')
            if item.isdir(): path.mkdir(parents=True, exist_ok=True)
            elif item.isfile():
                content = archive.extractfile(item).read()
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
                files[item.name] = hashlib.sha256(content).hexdigest()
    manifest['partners'].append({'layer': folder, 'tag': tag, 'tag_object': tag_object,
        'commit': commit, 'files': files})
    print('Exact source snapshot:', tag, commit, '('+str(len(files))+' files)')
manifest['brain_files'] = {}
for name in subprocess.check_output(['git','ls-files','--','brain'], text=True).splitlines():
    path = root/name
    if path.is_file(): manifest['brain_files'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
(artifacts/'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
'@ | & $brainPython - $auditDirectory $artifacts $TwinTag $GuardianTag
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare exact tagged sources.' }
    if (-not (Test-Path -LiteralPath $testPython)) {
        & uv venv --python 3.12 $environmentDirectory
        if ($LASTEXITCODE -ne 0) { throw 'Could not create integration environment.' }
    }
    # Always sync rather than trusting a cached environment. Keep all Brain pins.
    $combinedLock = Join-Path $artifacts 'combined-requirements.txt'
    & uv pip compile --python $testPython brain/requirements-lock.txt `
        (Join-Path $auditDirectory 'twin\requirements.txt') `
        (Join-Path $auditDirectory 'guardian\src\requirements.txt') --output-file $combinedLock --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Declared partner dependencies conflict with the Brain lock.' }
    & uv pip sync --python $testPython $combinedLock
    if ($LASTEXITCODE -ne 0) { throw 'Dependency synchronization failed; Brain pins were not relaxed.' }
    & uv pip install --python $testPython --no-deps -e brain
    if ($LASTEXITCODE -ne 0) { throw 'Editable Brain installation failed.' }
    & $testPython brain/scripts/doctor.py
    if ($LASTEXITCODE -ne 0) { throw 'Brain lock verification failed.' }
    @'
import importlib.metadata, json, platform, sys
from pathlib import Path
data = {'python': sys.version, 'platform': platform.platform(),
    'packages': sorted(({'name': d.metadata['Name'], 'version': d.version}
        for d in importlib.metadata.distributions()), key=lambda item: item['name'].casefold())}
(Path(sys.argv[1])/'environment-manifest.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
'@ | & $testPython - $artifacts
    if ($LASTEXITCODE -ne 0) { throw 'Could not record installed dependency evidence.' }
    $privateDirectory = Join-Path $artifacts 'private'
    New-Item -ItemType Directory -Force -Path $privateDirectory | Out-Null
    $privateKey = Join-Path $privateDirectory 'guardian.pem'
    $publicKey = Join-Path $privateDirectory 'guardian-public.pem'
    & $testPython (Join-Path $auditDirectory 'guardian\src\generate_token_keys.py') --private $privateKey --public $publicKey
    if ($LASTEXITCODE -ne 0) { throw 'Local test key generation failed.' }
    $env:CIVIS_TEST_TWIN_ROOT = Join-Path $auditDirectory 'twin'
    $env:CIVIS_TEST_GUARDIAN_ROOT = Join-Path $auditDirectory 'guardian'
    $env:CIVIS_TEST_GUARDIAN_PYTHON = $testPython
    $env:CIVIS_TEST_ARTIFACT_DIR = $artifacts
    $env:GUARDIAN_TOKEN_PRIVATE_KEY = $privateKey
    $env:GUARDIAN_TOKEN_PUBLIC_KEY = $publicKey
    $env:GUARDIAN_AUDIT_DIR = Join-Path $artifacts 'guardian-logs'
    $env:PYTHONUTF8 = '1'
    $brainExit = 0
    if ($IncludeBrainTests) {
        & $testPython -m pytest -c brain/pyproject.toml brain/tests -q --tb=short "--junitxml=$artifacts\brain.xml"
        $brainExit = $LASTEXITCODE
    }
    $targets = @(
        'brain/interop/test_partner_acceptance.py::test_twin_enforces_signed_claim_semantics',
        'brain/interop/test_v3_joint.py'
    )
    if (-not $DiagnosticsOnly) { $targets += 'brain/interop/test_v3_shipped_acceptance.py' }
    & $testPython -m pytest -c brain/pyproject.toml @targets -q --tb=short "--junitxml=$artifacts\partners.xml"
    $partnerExit = $LASTEXITCODE
    @{
        brain_exit = $brainExit; partner_exit = $partnerExit
        complete_gate_requested = (-not $DiagnosticsOnly)
        acceptance_passed = (-not $DiagnosticsOnly -and $brainExit -eq 0 -and $partnerExit -eq 0)
        evidence_directory = $artifacts
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $artifacts 'result.json') -Encoding UTF8
    Write-Output "Evidence: $artifacts"
    Write-Output "Brain exit: $brainExit; required partner acceptance exit: $partnerExit"
    if ($DiagnosticsOnly) { Write-Output 'Diagnostics only: this cannot certify complete integration.' }
    if ($brainExit -ne 0 -or $partnerExit -ne 0) { exit 1 }
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
    Pop-Location
}

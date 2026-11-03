param([switch]$DiagnosticGuardianLayout, [switch]$LiveGemini)
$ErrorActionPreference = 'Stop'
$brainDirectory = Split-Path -Parent $PSScriptRoot
$repoDirectory = Split-Path -Parent $brainDirectory
$auditDirectory = Join-Path $repoDirectory '.interop\oct23'
$python = Join-Path $auditDirectory 'venv\Scripts\python.exe'
Push-Location -LiteralPath $repoDirectory
try {
    if (-not (Test-Path -LiteralPath $python)) {
        & uv venv --python 3.12 (Join-Path $auditDirectory 'venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python 3.12 integration environment.' }
        & uv pip install --python $python --cache-dir (Join-Path $auditDirectory 'uv-cache') -r brain/requirements-lock.txt -r twin/requirements.txt -r guardian/src/requirements.txt -e brain
        if ($LASTEXITCODE -ne 0) { throw 'Could not install the declared integration dependencies.' }
    }
    $actualTwin = (& git rev-parse 'twin-mock-2^{}').Trim()
    $actualGuardian = (& git rev-parse 'guardian_mock_v2^{}').Trim()
    if ($actualTwin -ne '9cc2ab02ff30462061169fb3c0ca4e8003aa52d1' -or $actualGuardian -ne '6482a4601872e2449cc30e0e0edc02421e38a96e') {
        throw 'Unexpected partner tags. Review the new snapshots before running this frozen audit.'
    }
    @'
import subprocess,tarfile,io,hashlib
from pathlib import Path
r=Path.cwd();count=0
for tag,folder in [('twin-mock-2','twin'),('guardian_mock_v2','guardian')]:
 data=subprocess.check_output(['git','archive',tag,folder])
 with tarfile.open(fileobj=io.BytesIO(data)) as t:
  for m in t.getmembers():
   if m.isfile():
    p=r/m.name
    assert p.is_file() and p.read_bytes()==t.extractfile(m).read(), 'Partner source changed: '+m.name
    count+=1
print('Verified exact tagged source files:',count)
'@ | & $python -
    if ($LASTEXITCODE -ne 0) { throw 'Partner sources differ from the reviewed tag.' }
    $guardianDirectory = Join-Path $repoDirectory 'guardian'
    if ($DiagnosticGuardianLayout) {
        $guardianDirectory = Join-Path $auditDirectory 'guardian-diagnostic'
        # Fresh diagnostic copies come from Git, never from local secrets or modified source.
        @'
import subprocess,tarfile,io,shutil,hashlib,json
from pathlib import Path
r=Path.cwd().resolve();d=r/'.interop/oct23/guardian-diagnostic'
archive=subprocess.check_output(['git','archive','guardian_mock_v2','guardian'])
with tarfile.open(fileobj=io.BytesIO(archive)) as t:
 for m in t.getmembers():
  p=(d/Path(m.name).relative_to('guardian')).resolve();assert p.is_relative_to(d.resolve())
  assert not m.issym() and not m.islnk()
  if m.isdir():p.mkdir(parents=True,exist_ok=True)
  elif m.isfile():
   p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(t.extractfile(m).read())
for name in ['models','guardian_layer']:
 shutil.copytree(d/'src'/name,d/name,dirs_exist_ok=True)
print('Diagnostic only: duplicated tagged assets at expected legacy paths; no source edits.')
'@ | & $python -
        if ($LASTEXITCODE -ne 0) { throw 'Diagnostic copy preparation failed.' }
    } elseif (-not (Test-Path -LiteralPath (Join-Path $guardianDirectory 'models\model_metadata.json'))) {
        throw 'Exact Guardian tag cannot start: model path mismatch. See INTEROPERABILITY_2026-10-23.md. Use -DiagnosticGuardianLayout only to reproduce deeper defects; this is not clean-tag acceptance.'
    }
    $artifacts = Join-Path $brainDirectory '.artifacts\interop-oct23'
    New-Item -ItemType Directory -Path (Join-Path $artifacts 'private') -Force | Out-Null
    $privateKey = Join-Path $artifacts 'private\guardian.pem'
    $publicKey = Join-Path $artifacts 'private\guardian-public.pem'
    if (-not (Test-Path -LiteralPath $privateKey)) {
        & $python (Join-Path $guardianDirectory 'src\generate_token_keys.py') --private $privateKey --public $publicKey
        if ($LASTEXITCODE -ne 0) { throw 'Could not generate local test signing keys.' }
    }
    $env:CIVIS_TEST_TWIN_ROOT = Join-Path $repoDirectory 'twin'
    $env:CIVIS_TEST_GUARDIAN_ROOT = $guardianDirectory
    $env:CIVIS_TEST_GUARDIAN_PYTHON = $python
    $env:CIVIS_TEST_GUARDIAN_ENTRYPOINT = 'src/run.py'
    $env:CIVIS_TEST_ARTIFACT_DIR = $artifacts
    $env:GUARDIAN_API_BEARER_KEY = 'integration-guardian-http-only'
    $env:GUARDIAN_TOKEN_PRIVATE_KEY = $privateKey
    $env:GUARDIAN_TOKEN_PUBLIC_KEY = $publicKey
    $env:GUARDIAN_AUDIT_DIR = Join-Path $artifacts 'guardian-logs'
    $env:PYTHONUTF8 = '1'
    Set-Location -LiteralPath $brainDirectory
    & $python -m pytest -q --junitxml=.artifacts/interop-oct23/brain-final.xml
    $brainExit = $LASTEXITCODE
    & $python -m pytest interop/test_partners.py interop/test_partner_acceptance.py interop/test_v2_joint.py interop/test_v2_acceptance.py -q --tb=short --junitxml=.artifacts/interop-oct23/tagged-partners-final.xml
    $partnerExit = $LASTEXITCODE
    $liveExit = 0
    if ($LiveGemini) {
        $env:CIVIS_RUN_LIVE_GEMINI = '1'
        & $python -m pytest interop/test_v2_live_gemini.py -q --tb=short --junitxml=.artifacts/interop-oct23/live-gemini.xml
        $liveExit = $LASTEXITCODE
    }
    Write-Output "Brain exit: $brainExit; required partner acceptance exit: $partnerExit; live smoke exit: $liveExit"
    if ($brainExit -ne 0 -or $partnerExit -ne 0 -or $liveExit -ne 0) { exit 1 }
} finally { Pop-Location }

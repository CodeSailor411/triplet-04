param([switch]$IncludeBrainTests)
$ErrorActionPreference = 'Stop'
$brainDirectory = Split-Path -Parent $PSScriptRoot
$repoDirectory = Split-Path -Parent $brainDirectory
$auditDirectory = Join-Path $repoDirectory '.interop\oct25'
$testPython = Join-Path $auditDirectory 'venv\Scripts\python.exe'
Push-Location -LiteralPath $repoDirectory
try {
    # Extract only versioned partner source into an ignored diagnostic workspace.
    # The repository's partner folders and all local .env files stay untouched.
    @'
import io, subprocess, tarfile
from pathlib import Path
root=Path.cwd().resolve(); dest=root/'.interop/oct25'
for tag,folder,expected in [
 ('twin-mock-3','twin','b012c94e4a63652c7fbe9b6baf62ce59b4a1ac9c'),
 ('guardian_mock_v3','guardian','526f8f64970ded02319cf0763cf03a8159f085f0')]:
 actual=subprocess.check_output(['git','rev-parse',tag+'^{}'],text=True).strip()
 if actual != expected: raise SystemExit('Unexpected tag: '+tag)
 data=subprocess.check_output(['git','archive',tag,folder])
 with tarfile.open(fileobj=io.BytesIO(data)) as archive:
  for item in archive.getmembers():
   path=(dest/item.name).resolve()
   assert path.is_relative_to(dest.resolve()) and not item.issym() and not item.islnk()
   if item.isdir(): path.mkdir(parents=True,exist_ok=True)
   elif item.isfile():
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(archive.extractfile(item).read())
 print('Exact source snapshot:',tag,actual)
'@ | & (Join-Path $brainDirectory '.venv\Scripts\python.exe') -
    if ($LASTEXITCODE -ne 0) { throw 'Could not prepare exact partner snapshots. Run Brain setup first.' }
    if (-not (Test-Path -LiteralPath $testPython)) {
        & uv venv --python 3.12 (Join-Path $auditDirectory 'venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create integration environment.' }
        & uv pip install --python $testPython -r brain/requirements-lock.txt `
            -r .interop/oct25/twin/requirements.txt -r .interop/oct25/guardian/src/requirements.txt -e brain
        if ($LASTEXITCODE -ne 0) { throw 'Partner dependency installation failed.' }
    }
    $artifacts = Join-Path $brainDirectory '.artifacts\interop-oct25'
    New-Item -ItemType Directory -Force -Path (Join-Path $artifacts 'private') | Out-Null
    $privateKey = Join-Path $artifacts 'private\guardian.pem'
    $publicKey = Join-Path $artifacts 'private\guardian-public.pem'
    if (-not (Test-Path -LiteralPath $privateKey)) {
        & $testPython .interop/oct25/guardian/src/generate_token_keys.py --private $privateKey --public $publicKey
        if ($LASTEXITCODE -ne 0) { throw 'Test key generation failed.' }
    }
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
        & $testPython -m pytest -c brain/pyproject.toml brain/tests -q --tb=short --junitxml=brain/.artifacts/interop-oct25/brain.xml
        $brainExit = $LASTEXITCODE
    }
    & $testPython -m pytest -c brain/pyproject.toml `
        brain/interop/test_partner_acceptance.py::test_twin_enforces_signed_claim_semantics `
        brain/interop/test_v3_joint.py -q --tb=short --junitxml=brain/.artifacts/interop-oct25/partners.xml
    $partnerExit = $LASTEXITCODE
    Write-Output "Brain exit: $brainExit; required v3 partner acceptance exit: $partnerExit"
    if ($brainExit -ne 0 -or $partnerExit -ne 0) { exit 1 }
} finally { Pop-Location }

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = 'python'
$localPython = Join-Path $root '.venv\Scripts\python.exe'
if (Test-Path $localPython) {
  $python = (Resolve-Path $localPython).Path
}
& $python (Join-Path $root 'backend\run.py')

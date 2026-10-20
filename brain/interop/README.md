# Opt-in partner tests

These tests start local copies of the actual Twin and Guardian. They never contact Gemini. Source paths must point to the reviewed snapshots. Python 3.12 is required.

Use a separate integration environment containing Brain's requirements-lock.txt, an editable Brain install, and Twin's requirements.txt. Do not replace Brain's agreed pins with Guardian's broad dependencies. Guardian runs in its own environment with its backend requirements. The test fixtures supply temporary local keys; do not use real partner secrets.

From brain, set these variables in PowerShell (replace paths for your machine):

~~~powershell
$env:CIVIS_TEST_TWIN_ROOT = 'C:\path\to\reviewed\twin'
$env:CIVIS_TEST_GUARDIAN_ROOT = 'C:\path\to\reviewed\guardian\Guardian_Unified'
$env:CIVIS_TEST_GUARDIAN_PYTHON = 'C:\path\to\guardian-env\Scripts\python.exe'
& 'C:\path\to\integration-env\Scripts\python.exe' -m pytest interop/test_partners.py -q --junitxml=.artifacts/interop-oct19/partner-junit.xml
~~~

The default Brain pytest suite excludes this directory. Partner runs are explicit opt-in because they start servers and load Guardian's model. All processes started by these tests are shut down afterward.

The five scenario tests use real Twin readings, public fault injection and real MCP. Their Guardian and planner are explicitly simulated controls. The real-Guardian tests separately inspect its actual tools, reproduce incompatible ingestion and assert that Brain blocks missing authorization. A passing blocker test is not a successful three-layer action.

The Twin clock runs continuously at speed 1. No source patch or frozen clock is used. Fake-reading faults are supplied through its authorized scenario tool. Water's test-only valve choice is not a hydraulic safety claim. Latency and packet-loss faults are not injected.

Reviewed partner main: cf6f1dcb25796e64d22e96b3fe6ab8779f00a0b0. If Guardian supplies new tools or changes ingestion, update the recorded blocker expectations only after reviewing and testing that new contract.

## Required partner acceptance checks

Run `python -m pytest interop/test_partner_acceptance.py -q` with the same environment and source variables. These assert the required behavior instead of accepting known defects. The reviewed revision has **eight failing assertions and one passing control**: five invalid signed claim variants accepted by Twin, plus Guardian unauthenticated mutation, caller-controlled signature checking and stale trust after rollback. These tests are not skipped or marked xfail. Keep them failing until the responsible partner corrects the behavior.

Running `python -m pytest interop -q` includes both the working controls and these acceptance failures. Do not call that combined suite green while the defects remain.

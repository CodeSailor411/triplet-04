# CIVIS Brain

**7 November 2026:** [current source pins and verification](docs/mock-team/JOINT_FIX_2026-11-07.md). The 14-check actual-service gate passes for the reviewed Twin and Guardian sources, including S02/S05 and real containment notification. Planning was recorded; full production readiness and live Gemini are not certified. Public schemas and `ready:false` are unchanged.

Branch **codex/civis-elyes**, following checkpoint **brain-mock-3**. Updated 6 November 2026. Brain maps Guardian v3's `describe_capabilities`, `get_trust_verdict` and `authorize_action`, and keeps Guardian's original `g1` token unchanged.

## What Brain does

Brain is the decision layer between Twin and Guardian:

1. Reads Twin evidence (readings, clock, containment state).
2. Detects and validates incidents against policy.
3. Asks Guardian for a trust verdict and for exact approval of the specific action.
4. Asks Twin to execute the approved action.

Brain never signs tokens and never performs containment.

## Primary capabilities

| ID | Capability | Original owner | Response |
| --- | --- | --- | --- |
| S01 | Traffic | Yassine | R1 signal plan after persistent congestion |
| S02 | Water virtual command | Meriem | R3 virtual valve request with a required safe preview; not a hydraulic model |
| S03 | Power alert | Elyes | Evidence/uncertainty alert; no grid switching |
| S04 | Air Quality alert | Elyes | Sustained PM2.5 alert; no actuator |
| S05 | Medical dispatch | Maram | R2 ambulance dispatch to the reported destination |

One FastAPI/MCP service, one Gemini adapter and one shared validation/approval/execution path serve all five.

## GNN (optional, shadow only)

The optional Traffic forecast is implemented in the Brain runtime and disabled by default. It uses synthetic Twin telemetry and a separate read-only Gemini interpretation. It never supplies action evidence, approval or risk changes; no learned actuation is enabled. See [experiment limits](experiments/traffic_gnn/README.md).

## Local setup and run

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). `setup.ps1` creates `.venv` with Python 3.12 and installs exactly the committed `requirements-lock.txt`. From the repository root (Windows):

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src mocks tests scripts
.\.venv\Scripts\python.exe scripts/doctor.py
.\.venv\Scripts\python.exe scripts/setup_peer_keys.py
.\.venv\Scripts\python.exe -m civis_brain
~~~

This runs with simulated peers (the defaults `PEER_MODE=fixture`, `LLM_MODE=fixture`). Brain serves `http://127.0.0.1:8001/`; the debug page there always uses simulated Twin and Guardian. For an offline replay of one case:

~~~powershell
.\.venv\Scripts\python.exe scripts/run_case.py --scenario S01 --case base
~~~

Use S01 to S05 and `base` or `refusal`.

**Live partner run:** use a private `.env.partner` based on `config/partner.env.example` (obtain credentials privately, never commit them), then `scripts/start_partner.ps1` on Windows, or `python -m civis_brain --env-file .env.partner` from `brain`. See the [joint setup](docs/mock-team/JOINT_ACCEPTANCE_2026-10-26.md) and [partner gaps](docs/mock-team/PARTNER_GAPS.md).

Health: `/health`. MCP: `/mcp`, protocol 2026-07-28. Shared event logs go to ignored `logs/<scenario>-<run_id>.city_brain.jsonl`; debug traces to ignored `.artifacts/`. See [debugging](docs/mock-team/DEBUGGING.md).

## Limitation

The current 14-check actual-service gate passes for the source revisions in the linked report. The planner is recorded, the optional RF advisory was unavailable in the temporary source snapshot, and this does not certify wider Test Book completion, live Gemini or production readiness.

Member PRs target `codex/civis-elyes`; main and layer branches remain separate.

## Documents

- [INTERFACE.md](INTERFACE.md): MCP tools, caller permissions, workflow, time bases
- [INTEGRATION.md](../INTEGRATION.md)
- [TESTBOOK.md](../TESTBOOK.md)
- [Release handover](docs/mock-team/BRAIN_MOCK_3.md), [Windows setup](docs/mock-team/SETUP.md)
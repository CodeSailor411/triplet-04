# CIVIS Brain: primary mock development

The shared environment and transport scaffold are ready for team development. Business logic is assigned to Elyes, Yassine, Meriem and Maram and is deliberately not implemented by this setup.

Start with the [team meeting/work plan](docs/mock-team/README.md), [exact software setup](docs/mock-team/SETUP.md) and [frozen module contract](docs/mock-team/CONTRACT.md).

| Member | Task | Branch |
| --- | --- | --- |
| Elyes | Integration, trust gate, peer adapters, MCP callbacks, logging and release | `codex/civis-elyes` |
| Yassine | Input validation, normalization and incident candidates | `codex/civis-yassine` |
| Meriem | Free Gemini adapter and constrained action proposals | `codex/civis-meriem` |
| Maram | Fake peers, recorded AI outputs and workflow tests | `codex/civis-maram` |

Members submit PRs to `codex/civis-elyes`. Elyes reviews and merges. The release candidate goes to `brain` before 10 October 2026.

## Windows setup

From the repository root, after installing Git, VS Code and uv:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m civis_brain
```

Health: `http://127.0.0.1:8001/health`. MCP: `http://127.0.0.1:8001/mcp`. The scaffold reports `ready=false`; workflow tools return `NOT_IMPLEMENTED` until the assigned code lands. Never treat the bootstrap tests as proof of completed partner workflows.

All members use Python 3.12 and the committed lock file. `.env` and `.venv` are ignored. Local tests must not need API keys or network. Live free Gemini testing is separate. Current partner disagreements and implementation gaps are in [PARTNER_GAPS.md](docs/mock-team/PARTNER_GAPS.md).

The earlier CIVIS technical checkpoint is in [docs/oct05](docs/oct05/README.md). The development plan records newer unmerged Twin code separately; it does not silently replace triplet agreements.

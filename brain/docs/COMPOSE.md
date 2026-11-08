# Run the real Triplet 04 stack

Use Docker Desktop with Docker Compose **2.24.4 or newer**, Git, and Python 3.12. Start Docker Desktop before launching the stack.

If Docker Desktop shows the old `triplet04-civis-…` project, stop that project in Containers first so the new project can bind the same ports. The new group is named `triplet04-…`, and the images identify CIVIS, Trinity and 9antra separately.

From the repository root on `main`:

```powershell
python brain/scripts/compose_stack.py init
notepad brain/.env.compose
```

Fill in **only** `GEMINI_API_KEY` with your existing valid key and save. The other keys are generated for this local stack. The launcher will not overwrite an existing private settings file.

```powershell
python brain/scripts/compose_stack.py up
python brain/scripts/compose_stack.py check
```

Open [the live dashboard](http://127.0.0.1:8080). The check probes the three published health endpoints and the dashboard from your machine, then confirms Brain can talk to Twin and Guardian, Brain is evaluating the live feed, and Guardian scored a Twin reading. It does not call Gemini or exercise actuators.

| Service | Where it runs |
| --- | --- |
| Trinity Twin API and city feed | `http://127.0.0.1:8000` |
| 9antra Guardian API | `http://127.0.0.1:5000`; its own feed reader is a separate Compose service |
| CIVIS Brain MCP | `https://127.0.0.1:8001/mcp`; the local certificate is generated at startup |
| Trinity dashboard | `http://127.0.0.1:8080` |

Use `python brain/scripts/compose_stack.py ps` for service status, `logs` for recent output, and `down` to stop. The launcher prints the local snapshot path. The snapshot keeps original Twin, Guardian and Brain logs under `twin/run-logs/`, `guardian/run-logs/` and `brain/logs/`. Dashboard-ready Brain and Guardian part files are written to `brain/run-logs/` in that same snapshot. These are projections of actual logged decisions, verdicts and approvals, including the source evidence and authorization IDs. Original logs stay intact. Run Test Book scenarios against the live stack with their `--layers real` option where supported; the default stand-in mode is for standalone demos.

## Source and ownership

The launcher combines the **committed** `brain/` directory at your current Git HEAD with the root Compose file and sibling services from [PR #35 at a374e9d](https://github.com/CodeSailor411/triplet-04/commit/a374e9d5fce2d63739ee1b00a361b744f011262a). That revision includes Twin and Guardian MCP hostname allowlists and Guardian's current audit log format. It runs the actual Twin, Guardian and dashboard code from those folders.

Use the launcher commands above to apply `brain/compose.override.yml`. The PR's root Compose file points Guardian to an HTTP Brain URL. Guardian requires HTTPS for authenticated containment notices over the Docker network.

The override follows the PR's Python 3.12 and pinned dependency setup and builds Brain from its own folder. It enables the live MCP/SSE connections and Gemini, disables the fixture browser routes, and keeps Guardian's signed approval and Twin's verification. Guardian calls Brain on the private Compose network with HTTPS and trusts only the mounted public Brain certificate for that callback. It never receives Brain's TLS private key. The Phase 1 standalone mocks remain available outside this stack.

## Verification

`up` waits for the dashboard to serve HTTP as well as for the layers to report healthy. `check` verifies the published ports and live integration. To check a scenario commit, exercise that scenario with your own Gemini key and inspect the recorded Brain decision, Guardian authorization, and Twin outcome for the same action.

Run `python brain/scripts/compose_stack.py t2` to reset Twin and start a fresh SH-05 jam with a 180-tick hold. The launcher reconnects the Guardian feed reader after reset and waits up to 30 seconds for a new SH-05 score in the reset run. It schedules the jam when that score is within five ticks of the Twin clock. The launcher uses the scenario client and credentials inside the running Twin container. Use the returned `run_id` to follow the trial in the dashboard or the mounted logs. `status: started` confirms the trigger. An action commit is recorded separately in `twin/run-logs/<run_id>.twin.jsonl`.

The Reading lane includes one summary per Twin SSE batch observed by Brain, with its original reading IDs. Trinity's native part adds individual incident and fault readings. Guardian verdicts use the tick they scored and carry separate simulation and wall timestamps. CIVIS keeps its routine S03 unconfirmed-power notices in the raw audit log so they do not fill the Decision lane. Twin's native log supplies the Action lane.

If the last 60 ticks have no verdicts, run `check` again while the gap is visible. Compare `twin_clock`, `guardian_scored` and `guardian_on_dashboard` in the timeline summary. A gap at `guardian_scored` points to Guardian ingestion or scoring. A gap between the two Guardian ticks points to the dashboard projection.

`guardian_live_lookup` reports the exact reading ID requested by the health probe. If that lookup fails, `check` also tries a recent congestion reading already scored in Guardian's audit log for the same run. A successful audited lookup confirms Guardian's MCP retrieval path. Readiness for fresh evidence still requires the live lookup to pass.

# Run CIVIS with the real Triplet 04 services

Use Docker Desktop with Docker Compose **2.24.4 or newer**, Git, and Python 3.12. Start Docker Desktop before launching the stack.

From the repository root on `codex/civis-elyes`:

```powershell
python brain/scripts/compose_stack.py init
notepad brain/.env.compose
```

Fill in **only** `GEMINI_API_KEY` with your existing valid key and save. The other keys are generated for this local stack. The launcher will not overwrite an existing private settings file.

```powershell
python brain/scripts/compose_stack.py up
python brain/scripts/compose_stack.py check
```

Open [the live dashboard](http://127.0.0.1:8080). The check confirms Brain can talk to the real Twin and Guardian, Brain is evaluating the live feed, and Guardian scored an actual Twin reading. It does not call Gemini or exercise actuators.

| Service | Where it runs |
| --- | --- |
| Twin API and city feed | `http://127.0.0.1:8000` |
| Guardian API | `http://127.0.0.1:5000`; its own feed reader is a separate Compose service |
| Brain MCP | `https://127.0.0.1:8001/mcp`; the local certificate is generated at startup |
| Twin dashboard | `http://127.0.0.1:8080` |

Use `python brain/scripts/compose_stack.py ps` for service status, `logs` for recent output, and `down` to stop. The launcher prints the local snapshot path. The snapshot keeps original Twin, Guardian and Brain logs under `twin/run-logs/`, `guardian/run-logs/` and `brain/logs/`. Dashboard-ready Brain and Guardian part files are written to `brain/run-logs/` in that same snapshot. These are projections of actual logged decisions, verdicts and approvals, including the source evidence and authorization IDs. Original logs stay intact. Run Test Book scenarios against the live stack with their `--layers real` option where supported; the default stand-in mode is for standalone demos.

## Source and ownership

The launcher combines the **committed** `brain/` directory at your current Git HEAD with the root Compose file and actual sibling services from [PR #35 at e00e6c3](https://github.com/CodeSailor411/triplet-04/commit/e00e6c3a45e665aa48c9523f11119abf7f127a02). The reviewed Twin runtime/config matches `twin-real-jam` at `768b24f`, and Guardian application code matches `main` at `45e0ccb`. PR #35 already includes the Guardian API, signing-key setup and separate Twin feed reader despite its older title. Use the current Guardian code; do not substitute the historical `guardian_final_version` snapshot.

No merge into `main`, changes to a teammate's folder, or manual copy of private credentials into an image is needed. If the reviewed root Compose file and sibling Dockerfiles are already present in the same checkout, you can also run from that root:

```powershell
docker compose --env-file brain/.env.compose -f docker-compose.yml -f brain/compose.override.yml up --build -d --wait
```

The override follows the PR's Python 3.12 and pinned dependency setup and builds Brain from its own folder. It enables the live MCP/SSE connections and Gemini, disables the fixture browser routes, and keeps Guardian's signed approval and Twin's verification. Guardian calls Brain on the private Compose network with HTTPS and trusts only the mounted public Brain certificate for that callback. It never receives Brain's TLS private key. The Phase 1 standalone mocks remain available outside this stack.

## Verification

The eight-service configuration passed Docker Compose v2.40.3 validation. The CIVIS suite passed all 576 tests and Ruff. In a process-level check using the same reviewed sources and live configuration, Brain evaluated Twin's SSE feed, Guardian scored a real reading with the bundled model available, and an actual Twin quarantine reached Brain over the authenticated HTTPS callback. The Twin dashboard parser accepted all three layers from the recorded actual-service S02 run and linked Brain's request and Guardian's approval to Twin's commit.

The check did not build or start Docker containers because the validation workspace has no Docker daemon. It did not call Gemini. Run `up` and `check` on Docker Desktop, then exercise a live scenario with your own key.

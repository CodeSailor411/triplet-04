# brain-mock-2 partner handover

20 October 2026. Branch: `codex/civis-elyes`. Tag: `brain-mock-2`.

This is a live integration candidate for the five reduced scenarios. Full three-layer acceptance is **blocked**, not certified. Guardian cannot yet provide the required evidence assessment and exact-action approval through its published MCP interface. No simulated approval replaces it in live mode.

Use this tag for **brain/** only. Run Twin and Guardian from their own reviewed branches. The copies of other folders in this branch are not their latest releases. Main and both partner layers are unchanged.

## Windows startup

1. Check out `brain-mock-2` in a separate working copy, or copy its `brain/` into your integration workspace. Do not overwrite a teammate's uncommitted work.
2. From the repository root, run:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File brain/scripts/setup.ps1
cd brain
~~~

3. Obtain the private `.env.partner` from Elyes and put it in `brain/`. It is ignored by Git. The public format is `config/partner.env.example`.
4. Start the actual Twin and Guardian. Match the outbound credentials with the receiving service. Localhost URLs assume all three services run on the same computer.
5. Check connections, then start Brain:

~~~powershell
.\.venv\Scripts\python.exe -m civis_brain.preflight --env-file .env.partner
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_partner.ps1
~~~

Preflight is read-only. Exit 2 means a listed prerequisite is missing; it does not inject data, approve or actuate. With the current Guardian it correctly reports an unconfirmed contract. Brain can still start, receive the Twin feed and expose MCP, but refuses unauthorized decisions.

Brain MCP: `http://127.0.0.1:8001/mcp`. Health/feed status: `http://127.0.0.1:8001/health`. The `/` browser presets are isolated developer replays, even while the service uses live peers. They are not the joint integration driver. Inspect `/health` and `run-logs/<run_id>.brain.jsonl` for the actual run.

For separate computers, set the three peer URLs to their actual addresses and bind Brain to the agreed interface using `BRAIN_HOST`. Browser controls remain loopback-only. Run one Brain instance and one input driver per run: the partner profile already enables SSE, so do not also push every tick through `evaluate_tick`.

## What changed in CIVIS

- Live startup no longer opens fixture case files or permits recorded fixture plans. It connects directly to both peers and uses Gemini.
- Continuous authenticated SSE reception continues while Gemini plans. Gaps, reconnects and reset invalidate queued evidence.
- Twin's advancing simulated clock, `lat`/`lon`, percent units, real preview fields, caps, idempotency and token bindings are checked.
- Failed trust recovery has three bounded steps: collect advertised matching neighbour readings, obtain the same sensors on a later simulated tick with a maximum 3-real-second wait, then obtain a fresh Guardian verdict for original plus supporting evidence. The whole recovery has a 10-real-second deadline. Missing neighbours are recorded as absent, never invented. Missing later data or insufficient fresh trust blocks the action and exhausts that recovery budget.
- Live mode spends no more AI calls on a successfully completed incident episode. Later ticks report its original receipt. A clear observation followed by a new incident creates a new episode. Start a new run after changing response policy.
- Medical planning advertises exactly one ambulance to Gemini. Unsupported proposals get a clear explanation.
- Confirmation is supported only when the configured Twin tool is advertised. There is no assumed `commit_action` endpoint.

The partner mock profile explicitly opts into illustrative scenario policies and allows evidence up to **60 simulated seconds** old to accommodate Gemini latency. The ordinary developer setting remains 10. This mock allowance is not an agreed physical safety threshold. Current incident/availability, containment, fresh authorization time and token validity are still checked. Plans older than the configured limit are refused. Discuss the final reaction-time budget before v1.0.

## Small partner fix list

**9antra**

- Provide authenticated MCP evidence scores and exact-action approval tokens; publish cutoffs and the field mapping.
- Accept native Twin reading IDs, units and timestamps; connect its SSE feed and real containment callbacks.
- Require authentication on mutations, make signature verification server-controlled, and invalidate trust after rollback.

**Trinity**

- Provide `congestion_index` for Traffic, or agree a conversion with CIVIS.
- Reject signed tokens with future `iat`, lifetime over 60 simulated seconds, nonfinite/out-of-range score or empty `jti`.
- Keep two-step off until `commit_action` is available and jointly tested.

**Joint configuration**

- Match peer keys and URLs; exchange them privately. Supply Guardian's actual mapping before setting `GUARDIAN_CONTRACT_CONFIRMED=true`.
- Supply reviewed Water `safe_valve_choices` via `SCENARIO_POLICY_FILE`. Without them Water is alert-only. Preview success proves caps/containment checks, not hydraulic safety.

## Scope and evidence

S01 Traffic, S02 high Water, S03 Power alerts, S04 Air Quality alerts and S05 Medical are implemented. Power switching, Telecom/Waste incidents, durable restart recovery and pushed Guardian verdicts are outside this reduced mock. Brain requests verdicts through the documented adapter; Guardian owns approval and containment.

The working controls use real Twin MCP/SSE and an explicitly identified test Guardian. The required acceptance suite preserves partner failures as failures, not skips or expected failures. Live Gemini is tested separately from recorded plans. Final counts and that result are in `RELEASE_VALIDATION.md` alongside this handover.

Do not advertise full three-layer success until the actual Guardian path and all partner acceptance checks pass. For the earlier detailed security findings, see `INTEROPERABILITY_2026-10-19.md`; this handover supersedes its outstanding CIVIS recovery/setup notes.

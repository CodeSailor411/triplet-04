# Twin layer (Trinity, Triplet 04)

The Twin is the simulated city: sensors that report readings, actuators that act on the city, and a set of tools
the City Brain and the Guardian call. It runs on its own. This README only covers the Twin. How the three layers
fit together is in the root `INTEGRATION.md`. What the Twin sends and receives is in `INTERFACE.md`.

**Status (16 Oct 2026): 325 tests passing, plus 8 that need a PostgreSQL database and 10 that need a Redis server, skipped without them (with both: 343).** The app starts, partners log in with their own key, the city is generated from a seed, a simulated clock ticks, and every tick the 109 sensor readings go out on the live feed and through `get_readings`. `actuate` works behind the token gate, with idempotency and caps. Containment tools, attack scenarios, the run log and the dashboard (dark theme, node style spec) are built. History storage is built (memory by default, TimescaleDB optional; see "History storage"). Redis action state is built (14 Oct, optional, off by default). Dry-run preview is built (16 Oct, `preview_action`). Not built yet: two-step commit, actuator effects on the city, signed-token check turned on (see the table at the bottom).

## Run it

You need Python 3.12.

```
cd twin
python -m venv .venv
# Windows:  .venv\Scripts\activate        Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pip install -e . --no-deps
# Windows:  copy .env.example .env        Linux/macOS:  cp .env.example .env
python -m twin
```

Then open http://127.0.0.1:8000/health. The three keys in `.env` are fake development keys. Change them for anything
you show to other people. Never commit `.env`.

Try a call as another layer would make it:

```
python mocks/example_client.py --key dev-city-brain-key-change-me
python mocks/example_client.py --key dev-city-brain-key-change-me --tool list_nodes --args '{"domain": "water"}'
```

## Command the Twin by hand (practice for the demo)

Use two terminals, both inside `twin/` with the venv active. Commands use bash quoting (Linux, macOS, Git Bash).
`dev-city-brain-key-change-me` is the fake Brain key from `.env`. Guardian's is `dev-guardian-key-change-me`, the scenario one is `dev-scenario-key-change-me`.

**Terminal 1: start the Twin and leave it running**

```
python -m twin
```

You should see "38 nodes" and a warning that tokens are unsigned (that is expected for now). Stop it with Ctrl+C.

**Terminal 2: look around**

```
K=dev-city-brain-key-change-me
python mocks/example_client.py --key $K                                   # get_capabilities: who am I, which tools
python mocks/example_client.py --key $K --tool get_clock                  # run id, tick, simulated time
python mocks/example_client.py --key $K --tool list_nodes --args '{"domain": "water"}'
python mocks/example_client.py --key $K --tool get_readings --args '{"node_id": "WAT-01"}'
python mocks/example_client.py --key $K --tool list_actions               # actions, risk, caps, which nodes can carry them
curl http://127.0.0.1:8000/health                                         # no key needed
curl -N -H "Authorization: Bearer $K" http://127.0.0.1:8000/events        # the live feed, one event per second (Ctrl+C to stop)
```

Add `?max_events=3` to the feed address to make it stop by itself. Without a key the feed answers HTTP 401.

**Make the Twin act (`actuate`)**

The Twin refuses every action that has no token from Guardian. While Guardian's mock does not exist yet, make test tokens yourself.
Ask the clock for the `run_id`, then:

```
T=$(python mocks/token_tool.py make --run-id run-42-001 --action set_valve_position --targets WAT-01 --params '{"position": 40}' --ttl 3600)
python mocks/example_client.py --key $K --tool actuate --args "{\"action\":\"set_valve_position\",\"targets\":[\"WAT-01\"],\"params\":{\"position\":40},\"token\":\"$T\",\"idempotency_key\":\"try-1\"}"
```

* **Always pass `--ttl 3600`.** The tool's default is 30 simulated seconds counted from the Twin's start time, so once the Twin has been
  running for half a minute a default token comes back `TOKEN_EXPIRED`. (The expiry uses the simulated clock, not your wall clock.)
* A token works once. Make a new token and use a new `idempotency_key` for each new action. Sending the same key again with the same
  request gives back the first answer with `"replayed": true` (this is what a retry looks like).
* Good things to show: no token (`TOKEN_MISSING`), same token twice (`TOKEN_REUSED`), a token for 10 % used on 40 % (`TOKEN_MISMATCH`),
  three valves in one request (`CAP_EXCEEDED`, the cap for water is 2), a valve at 150 (`INVALID_PARAMS`, this one fails as an error, not a rejection).
* Try the same call with Guardian's key: `FORBIDDEN: 'guardian' may not call actuate`. Only the Brain asks for actions, Guardian only approves them.

**The hidden scenario tool** (works since 7 Oct)

```
python mocks/example_client.py --key dev-scenario-key-change-me --tool run_scenario --args '{"name": "list"}'
python mocks/example_client.py --key dev-scenario-key-change-me --tool run_scenario --args '{"name": "fake_reading"}'
python mocks/example_client.py --key dev-scenario-key-change-me --tool run_scenario --args '{"name": "stuck_sensor", "params": {"device_id": "AIR-01.pm25", "duration_ticks": 60}}'
```

One command starts an attack. With no `params` each one has a default sensor, so `fake_reading` is the spec's T5 case: `WAT-01.water_level` reports 180 cm while the real level stays about 40.

| Name | What the sensor does |
|---|---|
| `fake_reading` | Reports a made-up `value`. The true value does not change. |
| `stuck_sensor` | Keeps repeating the last value it reported before the fault. |
| `replay_exact` | Re-sends an old reading exactly as it was (same `reading_id`, old tick and time), `lag_ticks` old. |
| `list`, `stop`, `reset` | List the scenarios. Stop one (`{"scenario_id": "sc-0001"}`). Start a new run (new run id, clock at 0, everything forgotten). |

Params for the attacks: `device_id`, `channel` (only for sensors with channels), `delay_ticks` (at least 1, default 2: a fault never changes readings that were already sent), `duration_ticks` (default: until stopped), plus `value` or `lag_ticks`. Two faults on the same sensor at the same time are refused. A replay needs `lag_ticks` of history first, so at the very start of a run it answers `START_TOO_EARLY`.

It only shows up for the scenario key (try `get_capabilities` with each key and compare).

## What you can see today

| You want to | Works now? | How |
|---|---|---|
| See that the Twin is alive, which seed, which tick | Yes | `/health` |
| Watch live readings | Yes, as text | `/events` with curl (109 readings per tick) |
| List nodes, readings, actions, the clock | Yes | `example_client.py` tools above |
| Make the Twin act through the trust gate | Yes, with test tokens | `token_tool.py` plus `actuate` |
| See the city as a map and a timeline screen (R3) | **Yes** | `python -m twin.dashboard`, see "The dashboard" below. It shows logged events only, so a quiet Twin looks empty |
| Start a scenario with one command or button (R2) | **Yes, one command** | `run_scenario` starts an attack. There is no button yet |
| A log file for every run (R2) | **Yes, the Twin's part** | see "The run log" below. The shared format was reviewed with the partners on 9 Oct (JSON Lines, one part file per layer), and the merged file only holds the other layers' events once they write their parts |
| Mock Brain and mock Guardian that call the Twin on their own (R1) | **Not by us.** The Brain and Guardian teams' mocks are the stand-ins (agreed 9 Oct) | `example_client.py` is only a one-shot caller |
| Faults and attacks | **Yes**, fake reading, stuck sensor, exact replay | `run_scenario` above. The recycled-values replay comes 28 Oct |
| An actuator changing a sensor | **No**, 15 Oct | `actuate` stores the commanded value and nothing reacts |

The generator (see below) also writes `topology.json` with every node's position.

## The run log

Every run leaves a log (R2). Two steps, so three layers never write into one file at the same time:

1. While the Twin runs, it writes its **own part file**: `run-logs/<run_id>.twin.jsonl` (one JSON object per line, git-ignored). A second file, `run-logs/<run_id>.twin-private.jsonl`, holds the **true values** behind faked readings. It is never merged and never shared.
2. A **merge** puts all the parts in time order into one file for the repo: `../logs/<run_id>.jsonl`. The Twin does this by itself when a scenario is stopped, on `reset`, and on Ctrl+C. You can also run it by hand, and add the partners' part files:

```
python -m twin.logmerge run-42-001
python -m twin.logmerge run-42-001 --parts ../brain/run-logs/run-42-001.brain.jsonl ../guardian/run-logs/run-42-001.guardian.jsonl
```

Running it again is safe, the file is rebuilt from the parts every time. A new run (a new `run_id`) starts with `run_scenario` `reset`, and gets its own file.

What the Twin writes: `scenario` (run started, scenario started or stopped), `reading` (only readings that a scenario fault touched, 109 per tick would be huge), `action` (what `actuate` answered, with the token's ID, never the token) and `containment` (isolate, quarantine, rollback, release). Every line has `run_id`, `event_id`, `timestamp` (simulated time), `tick`, `wall` (real clock, orders events inside one tick), `layer`, `event_type`, `caused_by`, `data`.

Limits: normal readings are not logged, so a verdict that points at one will not find it in the log. A restart reuses the run id, so the part file continues (numbering carries on, the tick goes back to 0). The log is for reading afterwards, layers must not read it to decide anything.

## The dashboard (R3)

A live screen with a **city map** and a **timeline** of reading → verdict → decision → action. It only reads the run logs, it never calls the Twin.

```
python -m twin.dashboard --sample     # look at a made-up run first (needs no Twin and no partners)
python -m twin.dashboard              # the real thing: reads the folders in config/twin.yaml (dashboard.sources)
```

Then open http://127.0.0.1:8080. It needs no internet (no CDN, no fonts loaded from outside; Lato is bundled), so it works with the Wi-Fi off.

The page is black, white and grey; colour only appears on domains, trust and attacks. The one font is Lato (SIL Open Font License, files and licence in `src/twin/dashboard/fonts/`), served by the dashboard itself, so it also works offline.

The dashboard does **not** connect to the Twin. It has no key and sends no request. Once a second (`dashboard.refresh_seconds`) it re-reads the log folders listed in `dashboard.sources` (in `config/twin.yaml`) and draws what is new. So start it from the `twin/` folder (the folders are relative to where you start it), and a layer shows up as soon as it writes a log part there. Logs of a partner on another computer only show if you copy them into one of those folders.

What you see:
- **City map.** A black and white wireframe map section drawn in code around the node positions: one connected street network (every node sits on a street), outskirt streets that run off the edge, and a map frame with tick marks that cuts them off. Roads, nodes and the frame glow. It has no colour of its own and no district names. Colour only appears where it means something (the same positions always give the same map; the Twin's zones and `layout.json` are not changed). Every node is a hexagon from the node style spec, in its domain colour. **The shape is the trust state:** closed hexagon with a dot = Trusted, top and bottom sides missing = Degraded, an X = Untrusted, a padlock with corner brackets = Isolated (also used for quarantined, which adds a Q badge). Dimmer nodes have no Guardian verdict yet. A shared node (two domains) shows two colours. A pulsing red ring with ! means an attack is running there. Node names only show where something is going on, or on the node you click. **Layers** buttons switch a domain off (its nodes fade to grey, an isolated node keeps its lock). \"Connections\" draws the links between nodes (the selected node's links are always drawn). Click a node for its sensors and latest events. A legend under the map uses the same node pictures.
- **Timeline.** A row of steps (Reading, Verdict, Decision, Action) shows how many events each step has and which layer is still missing. Four lanes (Twin readings, Guardian verdicts, Brain decisions, Twin actions) with simulated time. Arrows show what caused what. Click an event and its whole chain lights up. Many events on one tick are grouped into one numbered circle.
- **Side panels.** Running scenarios, "Needs a person" (escalations from the Brain), partner failures.
- **Table.** Every event, newest first. Click a row for its details.

How the arrows work: the Twin cannot know who asked it to do something, so the others say it in their own events. Verdict: `caused_by` holds the `reading_id` it judged. Guardian's approval event carries the same `token_id` as the Twin's `action` event, and the Brain's decision carries the same `idempotency_key`. The containment tools take an optional `caused_by` (for example Guardian's verdict id). If a link is missing, that event simply has no arrow. Nothing is guessed.

Limits: the trust cut-offs (0.8 and 0.5) are placeholders until Guardian publishes its own. The Guardian and Brain lanes stay empty until they write log parts in the same format (`--sample` shows how it looks when they do). The dashboard never reads `*-private.jsonl`. It shows what the layers LOGGED. The Twin does not log normal readings (109 per tick), so with no scenario running the map shows no verdicts or attacks, only the city. Live node values are not shown yet. It was tested without a real browser (NiceGUI's simulated user, plus pictures of the drawings), so open it once in a browser and look for anything odd.

## Test it

```
python -m pytest
```

The tests start a real Twin on a free port. They cover the generator, the settings, the per-caller keys, the hidden
scenario tool, `actuate` (token gate, idempotency, caps, signed and unsigned tokens), the clock, the sensor model (including a leak test: the true value never leaves the Twin) and the live feed.

## Generate the city alone

```
python -m twin.generator --out generated
```

Writes `generated/topology.json` (nodes) and `generated/layout.json` (zones and roads only, no nodes). The same seed
always gives the same city. Change the seed with `TWIN_SEED=7` or in `config/twin.yaml`.

## History storage (13 Oct)

The Twin can keep a history of what happened: every reading the live feed showed (the reported value, never the true
one) and every run-log line. It is for asking later ("what did WAT-01 report between tick 100 and 200?"). The run log
files (R2) are written either way. This is an addition, not a replacement.

| Setting in `config/twin.yaml` | What happens |
|---|---|
| `storage.history: memory` (default) | History lives in memory and is gone when the Twin stops. Nothing to install. Use this for the demo and for any machine without a database |
| `storage.history: timescale` | History goes to TimescaleDB. The connection string comes from the environment variable `TWIN_TIMESCALE_DSN` (put it in `twin/.env`, never in the config file) |

How it behaves:
* A background thread writes in batches, so a slow database never slows the clock, the feed or the tools.
* If the database is down, the Twin keeps running. Rows wait in memory (at most `queue_max`, then the oldest are dropped and counted) and are sent again when the database is back. Sending twice is safe: the database skips rows it already has.
* `/health` shows `history`: backend, healthy or not, and counts of rows written, waiting and dropped. No error text, because it can contain host names.
* Setting `timescale` without the environment variable stops the start with a message that says what to set.

Start a TimescaleDB for development (needs Docker; the tag is pinned, never use `latest`):

```
docker run -d --name twin-history -p 5432:5432 -e POSTGRES_USER=twin -e POSTGRES_PASSWORD=twin-dev-password \
  -e POSTGRES_DB=twin timescale/timescaledb:2.26.1-pg17
```

then in `twin/.env`: `TWIN_TIMESCALE_DSN=postgresql://twin:twin-dev-password@127.0.0.1:5432/twin`, and set
`storage.history: timescale`. The Twin creates its two tables (`readings`, `events`) on first connect.

**What is and is not verified.** The tests ran against plain PostgreSQL 16. The TimescaleDB-only step (turning
`readings` into a hypertable, a table cut into time chunks) runs only when the extension exists and has NOT been run
by us yet. On a real TimescaleDB the Twin logs nothing special if it worked. Check it once with
`docker exec twin-history psql -U twin -d twin -c "select hypertable_name from timescaledb_information.hypertables"`
(it must list `readings`). Run the database tests with
`TWIN_TEST_PG_DSN=postgresql://twin:twin-dev-password@127.0.0.1:5432/twin python -m pytest tests/test_storage.py`.

## Action state in Redis (14 Oct)

`actuate` must remember two things: which tokens were already **used** (a token works once) and the **first answer** to
each idempotency key. If the Twin forgets them on a restart, an old token can be replayed. Redis is a fast key-value
store that runs as its own program and keeps its data when the Twin stops. This is an addition of ours (Redis is not
in the challenge spec), and it is optional.

| Setting in `config/twin.yaml` | What happens |
|---|---|
| `storage.state: memory` (default) | Used tokens and answers live in the Twin's memory and are gone on a restart. Nothing to install. Use this for the demo unless you need the restart protection |
| `storage.state: redis` | They go to Redis. The address comes from the environment variable `TWIN_REDIS_URL` (in `twin/.env`) |

How it behaves:
* **Fail safe.** If Redis cannot be reached, `actuate` refuses the request with the code `STATE_UNAVAILABLE`. It never lets a token through because it could not check. Nothing changes, and the same request works when Redis is back. `/health` shows `action_state` (`ok: false` while it is down).
* **Spending a token and storing its answer happen in one step** (a small Lua script that runs inside Redis). Either both are saved or neither, so a crash cannot leave a spent token with no answer.
* **Keys expire** after `state_ttl_seconds` (default one day), so Redis does not fill up.
* **Action numbers (`ac-00001`...) keep counting after a restart**, because the counter lives in Redis too.
* A Redis that is down at start does not stop the Twin. A missing `TWIN_REDIS_URL` does, with a message.

**What Redis does NOT keep (that would be option B, only if time is left):** the commanded actuator state (what each
valve or switch was last told to do) and the containment state (which devices are isolated or quarantined). After a
restart those are empty again.

Start a Redis for development (needs Docker; the tag is pinned, never use `latest`):

```
docker run -d --name twin-state -p 6379:6379 redis:7.4-alpine
```

then in `twin/.env`: `TWIN_REDIS_URL=redis://127.0.0.1:6379/0`, and set `storage.state: redis`. Run the Redis tests with
`TWIN_TEST_REDIS_URL=redis://127.0.0.1:6379/15 python -m pytest tests/test_action_state.py`.
**Verified:** the tests ran against Redis 7.0 (installed with apt), plus a live run with real processes (hard kill of the
Twin, token replay refused, Redis stopped and restarted). The Docker image tag above was NOT run by us.

## GPS positions (12 Oct)

Every node has a fixed `lat` and `lon` (WGS84 degrees, 5 decimals, about 1 m steps), and every reading, corrected
reading and quarantine-lane reading carries the same two numbers. The city is invented, so the anchor is one
arbitrary round-number point: the map centre is 36.0 N, 10.0 E, and 1 map unit (1 canvas pixel) is 5 m on the
ground, so the city is about 9.6 km wide and 5.4 km high. Both numbers are in `config/twin.yaml` under
`generator.geo`. Change them and every lat/lon follows. `topology.json` has a `geo` block that says how the
numbers were made. The maths is in `src/twin/geo.py` (north is up; `distance_m` gives straight-line metres).
This is reference data: no tool and no cap checks distances.

## Where things are

| Path | What |
|---|---|
| `config/twin.yaml` | Every setting: port, seed, sensors and units, actuators, caps, how the city is generated |
| `.env` (from `.env.example`) | The three secrets, one per caller |
| `src/twin/app.py` | The FastAPI app: `/health`, `/events` (live feed), MCP mounted at `/mcp` |
| `src/twin/mcp_server.py` | The MCP tools |
| `src/twin/auth.py` | Who is calling, and who may call what |
| `src/twin/generator.py` | Seeded city generator |
| `src/twin/storage/` | History store: interface, memory and TimescaleDB backends, background writer |
| `src/twin/geo.py` | Map position to GPS, and straight-line distance in metres |
| `src/twin/clock.py`, `sim.py` | The simulated clock (tick to time) and the running simulation (which tick we are at, readings for any tick) |
| `src/twin/actions.py` | `actuate`: request checks, idempotency, token checks, caps, commit. Order of the checks is written at the top of the file |
| `src/twin/tokens.py` | Reads and verifies Guardian's token (unsigned or Ed25519-signed, chosen by config only) |
| `mocks/token_tool.py` | Makes test tokens and key pairs for mocks and tests |
| `src/twin/sensors.py` | Sensor model: true value, and observed value = truth + device bias + noise. Pure functions of seed, device and tick |
| `src/twin/settings.py` | Reads and checks config and secrets, with clear error messages |
| `mocks/` | Mock Brain and mock Guardian (small example client for now, real mocks on 9 Oct) |
| `tests/` | Automated tests |
| `requirements.txt` | Exact versions we use. `requirements-lock.txt` freezes everything installed, including pulled-in packages |

## What works and what comes next

| Part | State |
|---|---|
| App, MCP at `/mcp`, `/health`, `/events` | Done |
| One key per caller, hidden scenario tool | Done and tested |
| Seeded city (38 nodes, 6 shared, layout file) | Done |
| Sensor model, simulated clock, readings on the live feed, `get_readings`, `get_clock` | Done 6 Oct |
| `actuate` with the trust gate, idempotency, caps, `list_actions` | Done 6 Oct |
| Scenario engine (fake reading, stuck sensor, exact replay) | **Done 7 Oct** |
| Run log: part file, private file, merge (R2) | **Done 7 Oct**, format reviewed with partners 9 Oct |
| Containment tools (isolate, quarantine, rollback, release) | **Done 7 Oct** |
| Shared log format, dashboard (dark look, node style spec, made-up map) | **Done 7 Oct, restyled 10 Oct** |
| Dry-run preview (`preview_action`) and the `PREVIEW_REQUIRED` rule | **Done 16 Oct** |
| Two-step commit, undo, actuator effects | Planned |
| TimescaleDB history | **Done 12-13 Oct** (real hypertable step not verified) |
| Redis action state (option A: used token IDs, idempotency answers) | **Done 14 Oct** |
| Ed25519 token check turned on | 18 Oct |

## Known limits right now

* Wall-clock timestamps are used only for `/health` and the feed's hello and heartbeat. Readings use the simulated clock.
* Sensor values wander slowly (waves of 5 to 20 simulated minutes), not through a realistic day. At real speed a daily cycle
  would never be visible in a demo. Incidents come from scenarios, not from the background pattern.
* Nothing changes the city yet: `actuate` stores the commanded value but no sensor reacts to it. Actuator effects come 15 Oct.
  Readings are a pure function of (seed, tick) until then.
* `tokens.mode` is `unsigned` for now, with a loud warning at startup. Signed mode (Ed25519) is built and tested but waits for 9antra's answer on
  format and key. `tokens.min_score` is empty because nobody has agreed a number.
* `preview_required` is enforced (`actions.preview_enforced: true`). Previews are remembered in memory only, so a restart forgets them and the Brain just previews again. `actions.preview_valid_ticks: 60` was agreed on 16 Oct (D9). Only the Brain may preview. Previews are not written to the run log (no new event type was agreed).
* The action cap is per request. The isolation and rollback pools are cumulative and hold until `release_device` or a new run.
* Used token ids are remembered until they expire, in memory only. A restart forgets them. A restarted Twin starts again at tick 0 with the SAME run id
  (`run-42-001` for seed 42), so a token that was already used and has not expired yet would be accepted a second time. Only a scenario reset
  (8 Oct) creates a new run id. Not a problem for the demo, but do not claim restarts protect against replay.
* A feed reader that falls more than 100 ticks behind skips ahead. The first `readings` event after the jump has a `skipped_ticks` number. Fixed 17 Oct: before, a reader that was stuck while the clock ran lost ticks with no warning (`tests/test_feed_stream.py`).
* Reconnecting to `/events` starts at the current tick. Ticks missed while disconnected are not replayed, and the `Last-Event-ID` header is ignored. Use `get_readings` after a reconnect if you need the latest state.
* `tools/list` shows every tool except the hidden scenario tool to every caller, but `get_capabilities` now lists only the tools the caller can really call.
* `mocks/token_tool.py make` defaults to a 30-second token issued at the clock's start time, so it expires quickly. Pass `--ttl 3600` (or `--now` from `get_clock`).
* `ServerMiddleware` in the `mcp` SDK is marked provisional by its authors. We pin `mcp==2.3.0`, so it cannot change
  under us, but upgrading needs a re-test.

## Error codes and extra detail (moved here from the Interface Card on 10 Oct, so the card fits one page)

**Refusals** (a normal result with `status: "rejected"` and a `code`): `TOKEN_MISSING`, `TOKEN_INVALID`, `TOKEN_WRONG_RUN`, `TOKEN_EXPIRED`, `TOKEN_REUSED`, `TOKEN_MISMATCH`, `TOKEN_SCORE_TOO_LOW`, `IDEMPOTENCY_CONFLICT`, `PREVIEW_REQUIRED`, `CAP_EXCEEDED`, `DEVICE_QUARANTINED`. Containment refusals: `CAP_EXCEEDED`, `NO_TRUSTED_VALUE`.

**Errors for a wrong request** (the call fails, text `CODE: message`): `UNKNOWN_ACTION`, `UNKNOWN_NODE`, `INVALID_TARGETS`, `INVALID_PARAMS`, `INVALID_IDEMPOTENCY_KEY`, `PREVIEW_NOT_AVAILABLE` (preview of an action that has no preview). Containment: `UNKNOWN_DEVICE`, `INVALID_DEVICE_IDS`, `INVALID_REASON`, `UNKNOWN_READING`, `READING_NOT_PUBLISHED`. Feed without a key: HTTP 401, wrong caller 403.

**Token payload in full:** `iss` "guardian", `aud` "twin", `jti` (unique, single use), `run_id`, `iat`, `exp` (both in simulated time, issue them from `get_clock`, not your wall clock), `action`, `targets`, `params`, `score`.

**Containment rules:** a device is one sensor at one node. `isolate_sensor` removes the device's readings from the feed and from `get_readings` from the current tick on. `quarantine_device` does the same, and an `actuate` aimed at that node is refused with `DEVICE_QUARANTINED` (token not spent, the command is recorded in the quarantine lane). `rollback_reading` returns the last value the sensor reported that was not already known bad and never uses the true value. The feed is not rewritten. Isolate and quarantine share one cap pool, rollback has its own. Repeating isolate or quarantine is harmless, `release_device` frees the slots. `release_device`, `get_containment_state` and `get_quarantine_lane` are our additions, not in the spec.

**Units:** congestion 0-100 %, water cm above the sensor's own zero, power kW, PM2.5 ug/m3. `channel` is set only for sensors split by type (`emergency_calls`: accident, fire, flood, medical; `units_free`: police, ambulance, fire). A reading's `timestamp` may be a few ms off its tick.

**Planned (from the old card):** undo, emergency events with transcript, `congestion_index`.

# Twin layer (Trinity, Triplet 04)

The Twin is the simulated city: sensors that report readings, actuators that act on the city, and a set of tools
the City Brain and the Guardian call. It runs on its own. This README only covers the Twin. How the three layers
fit together is in the root `INTEGRATION.md`. What the Twin sends and receives is in `INTERFACE.md`.

**Status (6 Oct 2026): 105 tests passing, and the running app was checked by hand (health, live feed, every tool, a full token and `actuate` round trip).** The app starts, partners can log in with their own key, the city is generated
from a seed, a simulated clock ticks, and every tick the 109 sensor readings go out on the live feed and through `get_readings`. `actuate` works behind the token gate, with idempotency and caps. Containment, two-step commit, scenarios, the log files, the timeline screen and actuator effects on the city are not built yet (see "What you can see today" and the table at the bottom).

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
| See the city as a map or a timeline screen (R3) | **No**, comes 9 Oct | nothing to open in a browser yet |
| Start a scenario with one command or button (R2) | **Partly** | `run_scenario` starts an attack. The log file per run comes 9 Oct, and there is no button yet |
| A log file for every run (R2) | **No**, shared log format 9 Oct | the Twin writes no log files yet, only console output |
| Mock Brain and mock Guardian that call the Twin on their own (R1) | **No**, 9 Oct | `example_client.py` is only a one-shot caller |
| Faults and attacks | **Yes**, fake reading, stuck sensor, exact replay | `run_scenario` above. The recycled-values replay comes 28 Oct |
| An actuator changing a sensor | **No**, 15 Oct | `actuate` stores the commanded value and nothing reacts |

To see the nodes as a picture before the dashboard exists, the generator (see below) writes `topology.json` with every node's position.

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

## Where things are

| Path | What |
|---|---|
| `config/twin.yaml` | Every setting: port, seed, sensors and units, actuators, caps, how the city is generated |
| `.env` (from `.env.example`) | The three secrets, one per caller |
| `src/twin/app.py` | The FastAPI app: `/health`, `/events` (live feed), MCP mounted at `/mcp` |
| `src/twin/mcp_server.py` | The MCP tools |
| `src/twin/auth.py` | Who is calling, and who may call what |
| `src/twin/generator.py` | Seeded city generator |
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
| Containment tools (isolate, quarantine, rollback, release) | **Done 7 Oct** |
| Shared log format, timeline dashboard, mocks | 9 Oct |
| TimescaleDB and Redis storage, Ed25519 token check | 14-15 Oct, 18 Oct |

## Known limits right now

* Wall-clock timestamps are used only for `/health` and the feed's hello and heartbeat. Readings use the simulated clock.
* Sensor values wander slowly (waves of 5 to 20 simulated minutes), not through a realistic day. At real speed a daily cycle
  would never be visible in a demo. Incidents come from scenarios, not from the background pattern.
* Nothing changes the city yet: `actuate` stores the commanded value but no sensor reacts to it. Faults and actuator effects come 8 and 15 Oct.
  Readings are a pure function of (seed, tick) until then.
* `tokens.mode` is `unsigned` for now, with a loud warning at startup. Signed mode (Ed25519) is built and tested but waits for 9antra's answer on
  format and key. `tokens.min_score` is empty because nobody has agreed a number.
* `preview_required` is published but not enforced until the preview tool exists (15 Oct).
* The action cap is per request. The isolation and rollback pools are cumulative and hold until `release_device` or a new run.
* Used token ids are remembered until they expire, in memory only. A restart forgets them. A restarted Twin starts again at tick 0 with the SAME run id
  (`run-42-001` for seed 42), so a token that was already used and has not expired yet would be accepted a second time. Only a scenario reset
  (8 Oct) creates a new run id. Not a problem for the demo, but do not claim restarts protect against replay.
* A feed reader that falls more than 100 ticks behind skips ahead (the event says how many it skipped).
* `tools/list` shows every tool except the hidden scenario tool to every caller, but `get_capabilities` now lists only the tools the caller can really call.
* `mocks/token_tool.py make` defaults to a 30-second token issued at the clock's start time, so it expires quickly. Pass `--ttl 3600` (or `--now` from `get_clock`).
* `ServerMiddleware` in the `mcp` SDK is marked provisional by its authors. We pin `mcp==2.3.0`, so it cannot change
  under us, but upgrading needs a re-test.

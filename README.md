# Triplet 04

> A city that can lie. A brain that acts. A guardian that doubts.

Trinity (Twin) · CIVIS (City Brain) · 9antra (Guardian), for the TSYP14 City Brain Convergence challenge.

**Jump to:** [The idea](#the-idea-in-one-minute) · [Meet the three](#meet-the-three) · [How they talk](#how-they-talk) · [The city](#the-city-we-built) · [One jam](#one-jam-start-to-finish) · [How trust works](#how-trust-works) · [Start it](#start-it) · [Run a scenario](#run-a-scenario) · [Logs and dashboard](#logs-and-the-dashboard) · [Status](#what-works-today-and-what-doesnt-yet) · [Extras](#extras-beyond-the-challenge) · [Tech stack](#tech-stack) · [Repo map](#where-things-live) · [House rules](#house-rules) · [Glossary](#glossary)

## The idea in one minute

A smart city runs on sensors. A traffic camera says the road is jammed, so a signal plan changes. A water sensor says the level is high, so a valve moves. Most projects stop at the question "what should we do?". We think there is one question before it: **is this data telling the truth?**

If a sensor is broken, or someone is faking it, the most dangerous thing a city can do is act on it. So we split the job into three programs, written by three teams, that can only work together through a clear interface.

The rule that holds the whole thing together is simple: **nothing in the city moves without a permission from the Guardian, which the Twin checks on its own.** The permission is only handed out after the readings were checked. In signed mode the Twin verifies the Guardian's Ed25519 signature on it. The Twin's stand-alone default has that check switched off and accepts an unsigned test token, so it can run without the Guardian. Two programs have to agree before an action happens, and neither of them is the one that decided to act.

## Meet the three

| Layer | Team | What it does | Folder |
|---|---|---|---|
| **Twin** | Trinity | The simulated city: 38 nodes with sensors and actuators in five domains (Traffic, Water, Power, Air Quality, Emergency). It makes up the readings, can start a real incident or make a sensor lie, and checks a permission token before it changes anything (in signed mode, it verifies the Guardian's signature). | [`twin/`](twin/) |
| **City Brain** | CIVIS | The decision layer between the other two. It reads the Twin's evidence, finds and validates incidents, asks the Guardian for a trust verdict and for approval of the exact action, then asks the Twin to carry it out. It never signs tokens and never performs containment. | [`brain/`](brain/) |
| **Guardian** | 9antra | Trust, authorization and containment. It scores the readings with deterministic rules, checks what an action is and how risky it is, and signs a one-use token (`g1`, Ed25519) when it approves. | [`guardian/`](guardian/) |

Each folder runs on its own and has its own `README.md` and Interface Card (`INTERFACE.md`, the one-page description of what the layer sends and receives).

### Who is allowed to do what

This table is the contract. Each layer is only allowed what its row says, and the Twin refuses anything else.

| Layer | Read sensors | Make decisions | Move actuators | Cut sensors off (containment) |
|---|---|---|---|---|
| Twin | Its own data | No | Yes, but only with a valid token | No |
| City Brain | Yes | Yes | No, it asks the Twin through `actuate` | No |
| Guardian | Yes | Trust only | Security actions | Yes, and only the Guardian |

Why we split it like this: if the layer that decides could also sign its own permission, one bug in the Brain would be enough to move the city. With the split, a bug has to happen in two places at once.

## How they talk

Nobody sits in the middle. The three layers call each other directly:

```
TWIN     ──── readings ────────────────▶  BRAIN
TWIN     ──── readings ────────────────▶  GUARDIAN
BRAIN    ──── "may I act on this?" ────▶  GUARDIAN
GUARDIAN ──── verdict + signed token ──▶  BRAIN
BRAIN    ──── action + token ──────────▶  TWIN     (the Twin checks the token, then commits or refuses)
GUARDIAN ┈┈┈┈ containment ┈┈┈┈┈┈┈┈┈┈┈┈┈▶  TWIN     (the Twin side is built; see guardian/README.md for the Guardian side)
```

The Twin never calls anybody. It only answers.

Some words used on this page, in plain terms:

- **MCP** (Model Context Protocol, version 2026-07-28 for all three layers): a standard way for a program to publish a list of "tools" that other programs can list and call. It is the form every call between our layers takes.
- **Live feed (SSE)**: Server-Sent Events. The Twin keeps one HTTP connection open and pushes a batch of readings down it every tick. One-off questions ("what are the nodes?", "do this action") are normal MCP calls instead.
- **Key**: every call carries a secret, one per layer, in the header `Authorization: Bearer <key>`. This is how the Twin knows who is asking. The keys live in the root `.env` file and never in the repo.
- **Tick**: one step of the simulated clock. By default 1 tick is 1 simulated second, running at real speed.

Messages follow one rule: be strict in what we send, forgiving in what we receive. A layer ignores fields it does not know, and rejects a message with a missing or wrong required field with a clear error message.

[`INTEGRATION.md`](INTEGRATION.md) has the details: diagram, protocol, and one scenario end to end.

## The city we built

The Twin is an invented city. It is generated from a config file and a seed number, so the same seed always gives the same city (we use seed 42).

- 38 nodes, 6 shared between two domains (for example a pump station that is also a power consumer)
- 6 zones, 10 roads and 67 links between neighbouring nodes
- 120 readings per tick
- The city is about 9.6 km by 5.4 km. Every node has a fixed GPS position (an invented place, WGS84 format, 5 decimals)

| Domain | Sensors | Actuator action | Risk level | Needs a dry-run preview first |
|---|---|---|---|---|
| Traffic | `vehicle_count`, `avg_speed`, `congestion_index` | `set_signal_plan`: normal / favor_main_road / all_red | R1 | No |
| Water | `water_level`, `flow_rate` | `set_valve_position`: 0 to 100 % | R3 | Yes |
| Power | `load_kw`, `voltage_v` | `set_grid_switch`: closed / open | none given | Yes |
| Air Quality | `pm25`, `co_ppm`, `temperature_c` | none, alert only | n/a | n/a |
| Emergency | `emergency_calls`, `units_free` | `dispatch` (unit type, `destination`, units) | R2 | No |

Risk levels go from R1 (low) to R3 (high). The higher the level, the higher the trust score the Guardian needs before it signs.

**Two numbers per sensor.** The Twin knows the *true* value of everything. What it publishes is the *reported* value: the true value plus the sensor's own bias and noise. The true value never leaves the Twin. A test checks the feed and the logs for leaks. This is what makes a lying sensor possible: an attack changes only the reported number, and the true number stays where it was.

**Time.** The Twin has its own clock. Every reading has an RFC 3339 UTC timestamp and a whole-number `tick`. A missing value is `null`. A reading has these fields: `run_id`, `reading_id`, `device_id`, `node_id`, `timestamp`, `tick`, `sensor`, `channel`, `value`, `unit`, `lat`, `lon`.

## One jam, start to finish

Scenario T2, the real traffic jam. The Twin starts it with the scenario `real_jam`. At one traffic node (default `SH-05`) the true values move towards a jam: `congestion_index` towards 90, `vehicle_count` towards 120, `avg_speed` towards 8. The nodes linked to it follow at 35 % of the way. The jam waits 2 ticks, builds up over 10 ticks, holds for 40 ticks, fades over 10 ticks, then ends by itself. It builds up slowly on purpose: a sudden jump would look fake to any rate-of-change check.

1. Readings from that node flow out on the Twin's live feed.
2. The Brain sees a congestion index of 80 or more on two ticks in a row and asks the Guardian for permission.
3. The Guardian judges the readings and signs a token for exactly one action, a signal plan change, valid for 60 simulated seconds.
4. The Brain sends the action with the token. The Twin checks everything and commits it.

Scenario T3 is the same jam, but fake: a sensor lies (`fake_reading`) and the real value stays calm. This time the Guardian refuses, the Brain sends nothing, and the case goes to a person. Nothing in the city moves. That second story is the reason the project exists.

Between the two stories sits a third one, T6: a sensor gets stuck and keeps repeating its last value. The Guardian notices and asks the Twin to isolate it (cut it off the feed). The Brain then reads the Twin's containment state and knows the sensor is out.

## How trust works

### Trust states

The Guardian gives each reading a score from 0 to 1. Its published cut-offs:

| State | How a reading gets there |
|---|---|
| Trusted | score 0.7 or more |
| Degraded | score above 0.3 |
| Untrusted | score 0.3 or less |
| Isolated | not a score: the Guardian ordered the sensor cut off |

The score is only a number. It is not a permission. Permission is a separate signed token.

### The token

A token says: "this one action, this score, until this time". The rules the Twin applies to every token:

- It is signed with Ed25519 (a modern signature scheme). The Guardian signs with a private key, the Twin only has the public key, so the Twin can check but not forge.
- It is for exactly one action and one `idempotency_key`. The same token with a different key is refused.
- It lives at most 60 simulated seconds.
- It can be used once. A second use is refused, even a valid-looking one.
- The score must be a real number from 0 to 1 and must reach the minimum for the action's risk level: R1 0.5, R2 0.7, R3 0.85.
- The token must be addressed from the Guardian to the Twin and must not be issued in the future.

If any of these fail, nothing changes. The Twin answers `TOKEN_INVALID`, `TOKEN_MISMATCH`, `TOKEN_EXPIRED` or `TOKEN_REUSED`. A token is only spent when the action actually commits.

An **idempotency key** is a label the Brain puts on a command. If the same key arrives twice, the Twin runs the command once and answers the second time with the first answer. This is how a resent command (a network retry) does not move a valve twice. If the same key comes with a changed request, it is rejected.

### The caps ("blast radius")

Even with a valid token, one request can only touch so many nodes. This limits the damage a wrong decision can do.

| Domain | Action cap (nodes per request) | Isolation cap (nodes cut off at once) |
|---|---|---|
| Traffic | 3 | 5 |
| Water | 2 | 4 |
| Power | 2 | 9 |
| Air Quality | no actuator | 4 |
| Emergency | 2 | 3 |

The formula is the size of the domain times a percentage (30 % for actions, 50 % for isolation), rounded down, with a minimum of 2. Power has one named exception: after a big threat all nine power sensors may be isolated. That only cuts data. It never opens a grid switch.

A request over the cap is refused completely with `CAP_EXCEEDED`, and the answer says the domain, the cap, how many are in use, how many were asked for and how many are left.

### Containment

Only the Guardian can call these tools (the Twin refuses anyone else):

- `isolate_sensor`: the device's readings leave the feed.
- `quarantine_device`: same, and any command aimed at that node is refused (`DEVICE_QUARANTINED`) and written to a side lane for the Guardian to read.
- `rollback_reading`: replaces a bad reading with the last value that sensor reported and that was not already known bad. The answer is marked `corrected`. It never shows the Twin's true value.
- `release_device`: frees an isolated or quarantined device again.

### Other safety measures on the Twin side

- The scenario tool (the one that makes sensors lie) is hidden from everyone without the scenario key. Calling it without access gives exactly the same error as calling a tool that does not exist, so you cannot even find out it is there.
- Every input is checked, and a bad input gets a clear error.
- Logs never hold tokens (only the token id), keys, secrets or true values.
- Text coming from logs is escaped before the dashboard shows it, so a log line cannot inject anything into the page.

## Start it

There are two ways to start the layers. Use the first one for everything, and the second one only for the live runs of T2 and T3.

### Main way: root Docker Compose (all three layers and the dashboard)

You need Docker with Compose v2.24 or newer. From a fresh clone:

```
git clone https://github.com/CodeSailor411/triplet-04.git
cd triplet-04
cp .env.example .env
docker compose up --build
```

The `.env` file in the repo root holds the keys for all three layers. The example file has fake keys that are only fine for running on your own machine. Put a real Gemini API key in `.env` (`GEMINI_API_KEY`) before you ask the Brain to plan anything, because the default is a placeholder.

The stack starts the Twin in signed mode. On the first start a small helper service creates the Guardian's key pair, so the Twin can verify the Guardian's signatures without any setup from you. A further service, `guardian-feed`, forwards the Twin's live feed to the Guardian. It has no port of its own.

When it is up:

- The Twin answers at <http://127.0.0.1:8000/health>. You should get a small JSON answer saying it is ok.
- The Brain's tools are at <http://127.0.0.1:8001/mcp>.
- The Guardian is at <http://127.0.0.1:5000>.
- The dashboard (city map and timeline) is at <http://127.0.0.1:8080>.

Stop it with `Ctrl+C`, then `docker compose down`.

Starting the stack only proves that the layers start. It does not prove that they work together. For that, run a scenario (see [Run a scenario](#run-a-scenario)).

### Live scenarios T2 and T3: the Compose launcher

For the live runs of T2 and T3 with the real Twin, Guardian and Brain, we use a launcher script from the Brain's folder. It starts the same layers, but it adds an override file on top of the Compose file. The override sets up the HTTPS callback and the volume (a shared folder) where the Guardian saves its audit records. The live evidence we have comes from this launcher, tested on **Windows**. We have not checked it on Linux or macOS.

You need Docker with Compose, Python 3.12 and a Gemini API key (the Brain uses it to plan, so this path needs internet).

```
python brain/scripts/compose_stack.py init
```

`init` sets up the launcher's files. Open `brain/.env.compose` and put your Gemini key in it. Never commit this file. Then:

```
python brain/scripts/compose_stack.py up
python brain/scripts/compose_stack.py check
python brain/scripts/compose_stack.py t2
python brain/scripts/compose_stack.py t3
python brain/scripts/compose_stack.py down
```

`up` starts the stack and `check` tests that the layers are reachable. `t2` and `t3` run those two scenarios against the real layers. The launcher has no command for the other scenarios. `down` stops everything. Always go through the launcher for these runs, and do not call `docker compose` yourself in the same session.

Run only one of the two ways at a time. Both start the same layers, so their ports can clash. Stop one (`docker compose down`, or the launcher's `down`) before you start the other.

The launcher's addresses, options and full steps are in [`brain/docs/COMPOSE.md`](brain/docs/COMPOSE.md).

### Both ways

To run one layer alone without Docker, see [`twin/README.md`](twin/README.md), [`brain/README.md`](brain/README.md) and [`guardian/README.md`](guardian/README.md).

No internet is needed for the Twin or its dashboard. The dashboard ships its own font files and makes no outside requests. Only the Brain's Gemini calls need internet.

## Run a scenario

There are two kinds of run, and the Test Book says which one each result came from.

### Stand-in runs (scripts in `scenarios/`)

With the Twin running (for example after the root `docker compose up`), from the repo root:

```
python scenarios/T2_real_jam.py
```

By default our scripted stand-ins play the Brain and the Guardian. It is the quick way to test the Twin on its own. It is not a live run. The scripts use Python 3.12 with the Twin's packages installed (`twin/requirements.txt`).

Each script follows the same four steps: reset the run, pull one trigger, save the merged log as `logs/<ID>-<n>.jsonl` (for example `logs/T3-1.jsonl`, and the next run `T3-2`), check the expected result and print PASS or FAIL. The script never starts the Twin. If it cannot reach it, it says so and stops.

| ID | Script | Scenario | What must happen |
|---|---|---|---|
| T1 | `T1_calm_day.py` | Calm day | No incident, no action |
| T2 | `T2_real_jam.py` | Real jam | One signal change is committed |
| T3 | `T3_fake_jam_refused.py` | Fake jam | The Guardian refuses, nothing is committed |
| T4 | `T4_guardian_silent.py` | Guardian silent | No answer, nothing is committed, a person is called |
| T5 | `T5_token_replay.py` | Token reuse | The second use is refused |
| T6 | `T6_stuck_sensor_isolated.py` | Stuck sensor | The sensor is isolated |
| T7 | `T7_repeated_command_once.py` | Repeated command | Sent twice, runs once |
| T8 | `T8_tampered_token.py` | Tampered token | One valid control request commits; the same kind of request with a changed signature is refused with `TOKEN_INVALID` |

Exit codes: `0` passed, `1` the check failed, `2` the setup is wrong (for example the Twin is not running).

**Stand-ins or real layers.** `--layers real` uses the real layers for T1, T2, T3 and T6 (the real Brain and Guardian must already be running). T4 and T7 only run with stand-ins. T5 and T8 talk to the real Guardian (no Brain involved). [`logs/INDEX.md`](logs/INDEX.md) says, for every saved log, which layers were stand-ins, which were real, and which were mixed. More details are in [`scenarios/README.md`](scenarios/README.md).

### Live runs (T2 and T3 through the launcher)

With the launcher's stack up (see [Start it](#start-it)):

```
python brain/scripts/compose_stack.py t2
python brain/scripts/compose_stack.py t3
```

These talk to the real Twin, Guardian and Brain. Our recorded evidence for them is listed under [What works today](#what-works-today-and-what-doesnt-yet).

The full test book is [`TESTBOOK.md`](TESTBOOK.md).

## Logs and the dashboard

### The log

Every layer writes its own events as JSON Lines (one JSON object per line) to `run-logs/<run_id>.<layer>.jsonl` inside its own folder. Those files are git-ignored. They are merged into one file per run in `logs/`. The merge is rebuilt from the parts every time, so running it twice is safe.

Each line has: `run_id`, `event_id`, `timestamp` (simulated), `tick`, `wall` (real clock), `layer`, `event_type`, `caused_by` and `data`.

`caused_by` is how cause and effect is recorded. A verdict points at the reading it judged (by `reading_id`). The Guardian's approval and the Twin's action share a `token_id`. The Brain's decision and the Twin's action share an `idempotency_key`. Nothing is guessed: if a layer does not write these fields, the chain on the dashboard has no arrow there.

The Twin does not log normal readings (about 120 per tick would flood the file). It logs the readings an attack or a real incident touched, every action, every containment call and the scenario events.

### The dashboard

It has the live timeline screen the challenge asks for. Four lanes, left to right in time: **reading → Guardian verdict → Brain decision → actuator action**, with timestamps. Click any event and the whole chain it belongs to lights up.

Also on the screen:

- The city map: each node drawn as a hexagon in its domain colour, with its trust state (Trusted, Degraded, Untrusted, Isolated). A red marker shows a running attack.
- Layer switches to dim whole domains, and a node card with the sensors of the node you click.
- A "Needs a person" panel for cases the Brain handed to a human, and a panel for partner failures.
- A live values card, read from the Twin's feed.
- An amber `STAND-IN LAYERS` chip when any shown event came from a stand-in, so nobody mistakes it for the real layers.

The map streets are a drawing around the node positions. They are an illustration, not city data.

Start the dashboard on its own with `python -m twin.dashboard` from the `twin/` folder. Add `--sample` to see a made-up run (it is marked SAMPLE DATA).

## What works today, and what doesn't yet

We would rather you hear it from us.

**Numbers**

- **Twin:** 550 tests pass and 18 are skipped (they need a PostgreSQL or Redis server). The scenario scripts run.
- **Guardian:** 81 tests pass and 2 are skipped in its own local run. The skipped ones need a live Twin.
- **Brain:** see [`brain/README.md`](brain/README.md) for its status.
- **Together, connectivity check:** on 29 Oct we ran a check with the partners' packages and no changes to their code: 28 checks passed, 0 failed, 1 skipped. It covered the live feed, the tools, the city graph, the Brain's start-up checks, and a real Guardian token that the Twin accepted, then refused on reuse and refused with a different key.

**Verified live runs (Windows, Compose launcher, real Twin, Guardian and Brain)**

- **T2, run `run-42-004`:** the Guardian authorized the action, the Brain (CIVIS) sent it, and the Twin committed it once, at tick 22.
- **T3, run `run-42-003`:** the first injected (fake) reading was denied, the Brain blocked the action, and the Twin did zero actions. The saved evidence for this run is in PR #43.

**Partial or expected, with no full trace yet**

- **T1:** the saved calm-day log holds Twin events only and no Brain events, so it supports a Twin-only baseline. The Test Book marks it Partial.
- **T3 human escalation:** we expect the Brain to hand the case to a person, but we have no saved trace of that step.

**Twin and Guardian only (no Brain)**

- **T5 and T8:** run against the real Guardian on 8 Nov 2026. T5 shows one commit and a `TOKEN_REUSED` rejection. T8 shows one valid control commit and a `TOKEN_INVALID` rejection for the tampered signature.

**Not complete**

- Full joint acceptance across all three real layers is not complete. Each layer's README lists its own gaps.

**Known limits**

- Most logs saved in `logs/` come from stand-ins for at least one layer. The stand-in Guardian runs inside the stand-in Brain, so the network call from the Brain to the Guardian is not tested by those runs. Only a run with the real layers (the T2 and T3 runs above) shows that call. [`logs/INDEX.md`](logs/INDEX.md) says which logs are which.
- The root `docker compose up` starts all three layers and the dashboard, but starting the stack does not prove they work together. Our verified live evidence comes from the launcher path.
- A committed action is stored by the Twin but the city does not react to it. After a `set_signal_plan` the jam keeps following its own script. We built the real jam only as the thing to detect, not as something an action can fix.
- The only real incident is the traffic jam. There is no flood or power surge scenario.
- A restart of the Twin keeps the same run id and forgets used tokens, so an old unexpired token could work again. A `reset` from the scenario tool starts a clean run. With the optional Redis storage on, used tokens survive a restart.
- Containment tools need no token. The Guardian's key is their only protection, and the caps limit the damage.
- A rollback skips readings known to be faulty, so it never restores a fake value. The side effect: the tick it restores from hints at when the fault began.
- A command sent to a quarantined node is refused and written to the side lane. It is not queued for later.
- Distances in the city graph are straight lines, not along roads or pipes.
- The two-step confirm (the Twin answers "pending" and a second call commits) is not built. Telecom and Waste domains were cut by agreement.

## Extras beyond the challenge

These are ours. The challenge does not ask for them and they earn no points by themselves. Most of them are off by default.

- **Dry-run preview** (`preview_action`): ask the Twin what an action would do without doing it. Valve and grid-switch actions need it first.
- **`congestion_index`**: a traffic number from 0 to 100 that the Twin derives from the reported car count and speed (never from true values).
- **City graph for the Brain**: `get_city_graph` and `get_nearest_nodes`. Positions, links, distances and zones in one call.
- **GPS in every reading.**
- **`release_device`, `get_containment_state`, `get_quarantine_lane`**: extra containment tools.
- **History storage** (TimescaleDB, a time-series database) and **action state storage** (Redis, an in-memory store). Both optional and off by default. Nothing needs them.
- **"Needs a person" screen** on the dashboard.

## Tech stack

All three layers use Python 3.12 and FastAPI. The Twin pins these versions exactly (in `twin/requirements.txt`):

| Part | Tool and version | Why |
|---|---|---|
| Language | Python 3.12 | One language for the triplet |
| MCP | official `mcp` SDK 2.3.0 | Protocol 2026-07-28, the version we agreed on |
| Web | FastAPI 0.142.2 on Uvicorn 0.54.0 | Routes for the feed, the health check and MCP |
| Checks | Pydantic 2.13.5 | Every tool input is checked with a clear error |
| Config | pydantic-settings 2.15.0, PyYAML 6.0.3 | Partner addresses and secrets in config, never hard-coded |
| Live feed | sse-starlette 3.5.0 | Pushes readings every tick |
| Signatures | cryptography 50.0.2 | Ed25519 check of the Guardian's tokens |
| Dashboard | NiceGUI 3.18.0 | Python-only screen, no JavaScript to write |
| Tests | pytest 9.1.1, pytest-asyncio 1.4.0 | Unit tests, leak test, scenario tests |

Each layer lists its own choices in its README.

## Where things live

```
triplet-04/
├── README.md          you are here
├── INTEGRATION.md     how the three layers connect
├── TESTBOOK.md        the scenarios and their expected results
├── docker-compose.yml starts the three layers and the dashboard (main way)
├── twin/              Trinity: the simulated city
├── brain/             CIVIS: the decision layer (also holds the Compose launcher for live T2 and T3 runs)
├── guardian/          9antra: trust and authorization
├── scenarios/         one trigger script per scenario (T1 to T8)
├── logs/              one log file per scenario run, plus INDEX.md
├── docs/              report, pitch deck and diagrams
├── mockups/testing/   extra folder, not part of the challenge layout
└── .github/           CODEOWNERS
```

Every layer folder has the same shape: `README.md` (how to run it alone), `INTERFACE.md` (the Interface Card), `src/`, `mocks/` (stand-ins for the other two layers) and `tests/`.

## House rules

- Each team commits only inside its own folder, and CODEOWNERS enforces it. Anything in the shared root, such as `scenarios/` or `logs/`, needs approval from the other two teams.
- Work on your own branch and open a pull request into `main`. A teammate reviews and merges. No direct pushes to `main`, no force pushes.
- Branch names use dashes, never slashes (`twin-sensor-model`, not `twin/sensor-model`).
- Commit messages start with the team (`twin: add sensor model`).
- Never run `git add .` from the root. Add your own folder (`git add twin/`).
- Secrets never go in the repo. Public keys may. Example configs hold fake development keys only. `.env` and `brain/.env.compose` hold real keys on your machine, so both must stay git-ignored.

## Glossary

- **Actuator**: a device that changes something in the city (a signal, a valve, a grid switch).
- **Blast radius / cap**: the most nodes one request may touch.
- **CODEOWNERS**: a GitHub file that says who must approve changes to which folder.
- **Containment**: cutting a suspicious sensor off, without waiting for a person.
- **Docker Compose**: a tool that starts several programs (containers) together from one config file.
- **Ed25519**: a signature scheme. One side signs with a private key, the other side checks with the public key.
- **Idempotency key**: a label on a command so a repeated command runs only once.
- **JSON Lines**: a text file with one JSON object per line.
- **MCP**: Model Context Protocol, the standard our layers use to call each other's tools.
- **Node**: one point in the city with sensors, actuators or both.
- **SSE**: Server-Sent Events, a one-way stream from server to client over HTTP.
- **Stand-in (mock)**: a small fake version of another layer, so a layer can run alone.
- **Tick**: one step of the simulated clock.
- **Token**: a one-use permission for exactly one action. In signed mode it carries the Guardian's signature.
- **Twin**: a software copy of a real system, here a simulated city.
- **Volume**: a folder shared between a container and your machine, so files survive a restart.
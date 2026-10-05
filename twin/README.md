# Twin layer (Trinity, Triplet 04)

The Twin is the simulated city: sensors that report readings, actuators that act on the city, and a set of tools
the City Brain and the Guardian call. It runs on its own. This README only covers the Twin. How the three layers
fit together is in the root `INTEGRATION.md`. What the Twin sends and receives is in `INTERFACE.md`.

**Status (5 Oct 2026): skeleton, 39 tests passing.** The app starts, partners can log in with their own key, the city is generated
from a seed, and the live feed opens. Readings and actuators are not built yet (see the table at the bottom).

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

## Test it

```
python -m pytest
```

The tests start a real Twin on a free port. They cover the generator, the settings, the per-caller keys, the hidden
scenario tool and the live feed.

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
| Sensor model, readings on the live feed, read tools | 6 Oct |
| `actuate` with the trust gate, idempotency, caps | 7 Oct |
| Containment tools, scenario engine | 8 Oct |
| Shared log format, timeline dashboard, mocks | 9 Oct |
| TimescaleDB and Redis storage, Ed25519 token check | 14-15 Oct, 18 Oct |

## Known limits right now

* Wall-clock timestamps are used only for `/health` and the feed hello. Readings will use the simulated clock
  CIVIS asked for (6 Oct). Node ids look like `TRF-01` and live in `generator.make_node_id`.
* `ServerMiddleware` in the `mcp` SDK is marked provisional by its authors. We pin `mcp==2.3.0`, so it cannot change
  under us, but upgrading needs a re-test.
* No readings yet, so there is nothing for the leak test to catch beyond the node list. The full leak test comes with the sensor model.

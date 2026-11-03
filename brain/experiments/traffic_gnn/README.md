# CIVIS traffic graph forecast experiment

## Purpose

This is a research prototype for S01. It forecasts Twin-reported `vehicle_count` and `avg_speed` five simulated ticks ahead from the previous five ticks. A shared GraphSAGE-style mean-neighbour aggregator combines each node's own history with the mean history of its Twin Traffic neighbours, then a small MLP predicts the two values.

The model was trained from scratch with NumPy. It was not downloaded from Hugging Face. For example, DCRNN checkpoints are trained against a particular road graph and traffic-speed dataset, while this Twin mock has 11 Traffic nodes, synthetic `cars/min` and `km/h` sensor reports, and geographic neighbour links rather than road connectivity. Reusing those weights would not be a valid project-specific transfer.

## Data and evaluation

Training data comes from the checked-in Twin simulator and configuration. It is deterministic synthetic telemetry, not measurements from a city. The training target is a future sensor value, not an incident label. Seeds 100 to 107 are used for training, 108 to 109 for validation, and 110 to 111 for held-out testing. The saved [evaluation](artifacts/evaluation.json) records the source hash, data split, units, and metrics.

| Held-out MAE | GraphSAGE-style model | Temporal MLP without graph | Persistence |
|---|---:|---:|---:|
| `vehicle_count` (cars/min) | 1.8781 | 1.8767 | 2.3199 |
| `avg_speed` (km/h) | 1.0617 | 1.0621 | 1.3693 |

The graph input did not produce a meaningful improvement over the same temporal model without neighbours. This experiment therefore does not establish that spatial message passing helps this Twin mock, and it does not validate real-world forecasts. The prototype is opt-in and shadow-only. It cannot create incidents, change a plan, assign a risk tier, authorize an action, or issue an actuator call.

## Runtime boundary

The Brain uses Twin `list_nodes` neighbour links only among discovered Traffic nodes. These links are a geographic proxy. Twin's mock does not expose a road-routing or traffic-propagation graph. Inference requires the same discovered Traffic node set as training, correct units, and five complete ticks for both sensors across all Traffic nodes. Invalid, blocked, duplicate, incomplete, or mismatched inputs do not produce a forecast.

When enabled, the optional forecast is recorded in the Brain run journal and exposed through `/debug/state`. The existing Gemini Flash-Lite provider can produce one bounded, schema-checked, read-only interpretation per run, using one call from the existing AI budget and the configured real-time AI timeout, 60 seconds by default. Its output is displayed separately in the developer console. Neither forecast nor interpretation is passed to scenario planning or Guardian/Twin calls. The feature is disabled by default and adds no Brain MCP tool or runtime ML package.

## Reproduction on Windows

From `brain`, install the experiment-only dependencies into an ignored artifact directory, then train using the checked-in Twin simulator:

```powershell
uv pip install --python .venv/Scripts/python.exe --target .artifacts/gnn-site-packages -r experiments/traffic_gnn/requirements.txt
$env:PYTHONPATH = (Resolve-Path .artifacts/gnn-site-packages).Path
.\.venv\Scripts\python.exe experiments\traffic_gnn\train.py
.\.venv\Scripts\python.exe experiments\traffic_gnn\smoke.py
Remove-Item Env:PYTHONPATH
```

This does not add NumPy or PyYAML to the Brain service lock or runtime environment. Training rewrites `src/civis_brain/context_graph/traffic_gnn_v1.json` and `experiments/traffic_gnn/artifacts/evaluation.json`.

To make a one-time live Gemini check using only the generated synthetic forecast, select the private config and run `& .\.venv\Scripts\python.exe experiments\traffic_gnn\smoke.py --gemini`. For example, in PowerShell set `$env:CIVIS_ENV_FILE = ".env.partner"` first. The key is read locally and is never printed. The default smoke run uses a stub interpreter and makes no cloud call.

For an opt-in live graph check against the exact tagged Twin and Guardian services, run the full tagged gate with `-LiveGeminiGraph`. It reads the Brain timeout from `.env` (`AI_TIMEOUT_SECONDS`, default 60 seconds), verifies Twin-fed graph forecasts and Gemini's separate interpretation, and keeps action planning recorded. This confirms the graph-to-Gemini path only; it does not certify Guardian approval or Twin actuation. A failed live model call remains visible as a failure.

To enable the read-only shadow view locally, set `TRAFFIC_GNN_SHADOW_ENABLED=true` in the private Brain environment file, start the Brain with Twin's feed connected, and open `/debug/state` or the developer console. Allow five consecutive complete Twin ticks to fill the input window. Gemini interpretation also requires the existing Gemini configuration and an available AI-call budget. Keep the flag off for joint acceptance unless every partner agrees to include this advisory experiment.

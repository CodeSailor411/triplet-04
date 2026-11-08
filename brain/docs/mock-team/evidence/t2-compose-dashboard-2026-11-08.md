# T2 real jam on Windows Compose

**Observed on 8 November 2026.** The dashboard shows a committed Twin signal-plan action during the reported T2 trial. This record is based on the [captured timeline](t2-compose-dashboard-2026-11-08.png). The successful trial's native JSONL files are pending.

T2 is the Twin Test Book's `real_jam` scenario at SH-05. It exercises CIVIS S01 persistent traffic congestion, whose authorized action is `set_signal_plan` at risk level R1. See the [Compose launcher instructions](../../COMPOSE.md) and the [S01 scenario contract](../SCENARIOS.md).

| Timeline evidence | Observation |
| --- | --- |
| Twin readings | Two linked percentage readings, 82.1% and 90.7%, feed the selected decision. |
| Guardian verdicts | The Verdict lane contains recorded events. The selected view leaves the matching scores and authorization ID unconfirmed. |
| CIVIS decision | The selected Decision marker is labeled `set_signal_plan`, near tick 17 on the plot. |
| Twin action | The linked Action marker is labeled `signal_plan ok`, near tick 21. Trinity renders this label when an action event records `status: committed`. |

Marker positions give approximate simulation ticks. Confirm the exact ticks, reading IDs, action target and parameters, Guardian approval, Brain decision ID, and Twin action ID by matching the three native logs from the same Compose snapshot and run ID.

- `twin/run-logs/<run_id>.twin.jsonl`
- `guardian/run-logs/<run_id>.guardian.jsonl`
- `brain/logs/s01-<run_id>.city_brain.jsonl`

The earlier uploaded `run-42-002.zip` records the blocked trial with no Twin action. The repository's `logs/T2-1.jsonl` is the separate stand-in run listed in the [Test Book index](../../../../logs/INDEX.md).

# logs/

One file per scenario run, named `<scenario ID>-<run number>.jsonl`. Entries come from the scripts in `scenarios/` or from reviewed live Compose captures.
The label says whether each layer's events come from a stand-in or from the real layer. Run IDs can repeat after a Twin restart. Use the file and capture time to identify a run.

| File | Scenario | When (UTC) | Twin run id | Layers | Result |
|---|---|---|---|---|---|
| T1-1.jsonl | T1 Calm day | 2026-11-03 19:44 | run-42-002 | brain: no events, guardian: no events | PASS |
| T2-1.jsonl | T2 Real jam (stand-in) | 2026-11-03 19:45 | run-42-004 | brain: stand-in, guardian: stand-in | PASS |
| [T2-2.jsonl](T2-2.jsonl) | T2 Real jam / S01 Persistent Traffic Congestion (live) | 2026-11-08 18:32 | run-42-004 | twin: real, guardian: real, brain: real | PASS |
| T3-1.jsonl | T3 Fake jam refused | 2026-11-03 19:45 | run-42-005 | brain: stand-in, guardian: stand-in | PASS |
| [T3-2.jsonl](T3-2.jsonl) | T3 Fake jam / S01 Persistent Traffic Congestion (live) | 2026-11-08 18:55 | run-42-003 | twin: real, guardian: real, brain: real | [PASS — no action committed](T3-2.md) |
| T4-1.jsonl | T4 Guardian silent | 2026-11-03 19:45 | run-42-006 | brain: stand-in, guardian: no events | PASS |
| T5-1.jsonl | T5 Token replay | 2026-11-03 19:45 | run-42-007 | brain: no events, guardian: stand-in | PASS |
| T6-1.jsonl | T6 Stuck sensor isolated | 2026-11-03 19:45 | run-42-008 | brain: no events, guardian: stand-in | PASS |
| T7-1.jsonl | T7 Repeated command runs once | 2026-11-03 19:45 | run-42-009 | brain: stand-in, guardian: stand-in | PASS |
| T5-2.jsonl | T5 Token replay | 2026-11-08 15:55 | run-42-003 | brain: no events, guardian: real | PASS |
| T8-1.jsonl | T8 Forged token | 2026-11-08 16:01 | run-42-005 | brain: no events, guardian: real | PASS |

[`T2-2.jsonl`](T2-2.jsonl) is a redacted 10-event extract from the Windows Compose capture. Twin committed `set_signal_plan` on SH-05 with `plan: favor_main_road` at tick 22. The [run report](../brain/docs/mock-team/evidence/t2-compose-dashboard-2026-11-08.md) links the native evidence.

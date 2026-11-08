# logs/

One file per scenario run, named `<scenario ID>-<run number>.jsonl`. Entries come from the scripts in `scenarios/` or from reviewed live Compose captures.
The label says whether each layer's events come from a stand-in or from the real layer.

| File | Scenario | When (UTC) | Twin run id | Layers | Result |
|---|---|---|---|---|---|
| T1-1.jsonl | T1 Calm day | 2026-11-03 19:44 | run-42-002 | brain: no events, guardian: no events | PASS |
| T2-1.jsonl | T2 Real jam | 2026-11-03 19:45 | run-42-004 | brain: stand-in, guardian: stand-in | PASS |
| T3-1.jsonl | T3 Fake jam refused | 2026-11-03 19:45 | run-42-005 | brain: stand-in, guardian: stand-in | PASS |
| [T3-2.jsonl](T3-2.jsonl) | T3 Fake jam refused / S01 Persistent Traffic Congestion | 2026-11-08 18:55 | run-42-003 | twin: real, guardian: real, brain: real | [PASS](T3-2.md) |
| T4-1.jsonl | T4 Guardian silent | 2026-11-03 19:45 | run-42-006 | brain: stand-in, guardian: no events | PASS |
| T5-1.jsonl | T5 Token replay | 2026-11-03 19:45 | run-42-007 | brain: no events, guardian: stand-in | PASS |
| T6-1.jsonl | T6 Stuck sensor isolated | 2026-11-03 19:45 | run-42-008 | brain: no events, guardian: stand-in | PASS |
| T7-1.jsonl | T7 Repeated command runs once | 2026-11-03 19:45 | run-42-009 | brain: stand-in, guardian: stand-in | PASS |

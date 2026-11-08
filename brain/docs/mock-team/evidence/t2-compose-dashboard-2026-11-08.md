# T2 Real Jam on Windows Compose

**Passed for `run-42-004` on 8 November 2026.** The three native logs show the Twin's T2 `real_jam` scenario at SH-05 exercising CIVIS **S01 Persistent Traffic Congestion**. Guardian approved the R1 request and Twin committed `set_signal_plan` with target `SH-05` and `plan: favor_main_road` exactly once in the capture. The action ID is `ac-00001`. See the [redacted native log excerpts](t2-compose-run-42-004.jsonl), [Compose launcher](../../COMPOSE.md), and [S01 scenario contract](../SCENARIOS.md).

| Simulation tick | Evidence | Native event or sequence |
| --- | --- | --- |
| 7 | Twin scheduled `real_jam` as scenario `sc-0001`, incident `inc-0001`. The jam began at tick 9. It affected SH-05, SH-06, TRF-02, TRF-06, and TRF-08, with a 10-tick ramp, 180-tick hold, and 10-tick fade. | `twin-000002` |
| 17 | SH-05 congestion measured **83.7%**. Guardian scored `rd0000017-SH-05.congestion_index` **1.0**, trusted, **0.617 s** after Twin logged the reading. | `twin-000125`, `guardian-001047` |
| 18 | SH-05 congestion measured **92.2%**. Guardian scored `rd0000018-SH-05.congestion_index` **1.0**, trusted, **0.633 s** after Twin logged the reading. CIVIS detected S01 and retrieved both fresh verdicts. | `twin-000140`, `guardian-001111`, Brain seq 20, 26–30 |
| 18–20 | CIVIS generated a plan using those readings. The configured planner returned successfully in **1,316.7 ms**. CIVIS submitted both reading IDs with the exact action, target, plan, and R1 classification. | Brain seq 31–33, 46–47 |
| 21 | Guardian approved the action at **18:32:18.641 UTC**. CIVIS validated the authorization and requested the same action from Twin. | `guardian-001294`, Brain seq 48, 58–59 |
| 22 | Twin recorded `committed` at **18:32:19.267 UTC** and CIVIS received the matching outcome. The final Brain record `dec-8ff85ae0265c3cf6f0e279dd` has sequence 65 and carries the evidence-context tick 18. | `twin-000213`, Brain seq 62, 64–65 |
| 200 | CIVIS cleared the incident after usable readings showed it had ended. | Brain seq 424 |

The commit arrived **15.037 s** after Twin logged the scenario trigger, **4.367 s** after the second supporting reading, and **0.626 s** after Guardian logged its approval. Guardian's approval, CIVIS's validated authorization, and Twin's commit share the same authorization and idempotency identifiers. The excerpts redact these identifiers and retain the event IDs and Brain sequence numbers.

The capture contains one Guardian approval and one Twin action. CIVIS recorded a further detection for the same incident at tick 22. Guardian recorded one startup tick gap from 4 to 6, before the jam began. Each recorded S01 peer response in the capture succeeded.

## Evidence sources

The uploaded `T2-success-run-42-004.zip` contains 3,003 Twin rows, 13,442 Guardian rows, and 434 S01 Brain rows. Its SHA-256 is `f39db045203b803c1a9e48ecc5e368caa4c4a6884311fe234b9be0959bc3d211`.

- `twin/run-logs/run-42-004.twin.jsonl`
- `guardian/run-logs/run-42-004.guardian.jsonl`
- `brain/logs/s01-run-42-004.city_brain.jsonl`

The [earlier dashboard capture](t2-compose-dashboard-2026-11-08.png) shows a separate T2 observation with linked readings of 82.1% and 90.7%. The earlier `run-42-002.zip` captures the blocked live trial. The repository's `logs/T2-1.jsonl` is the stand-in trial listed in the [Test Book index](../../../../logs/INDEX.md).

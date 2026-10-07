# Questions Elyes must close before the joint smoke test

Review basis: final meeting report, CIVIS checkpoint, cap proposal supplied in chat, and actual remote branches fetched on 7 October 2026. The remote implementation is useful evidence but is not automatically a new triplet agreement.

| Item | Actual evidence | Required leader decision |
| --- | --- | --- |
| Guardian interface | `guardian` is still a scaffold in this checkout; tool names/score scale are unavailable | Obtain Houssem's endpoint, Brain caller key, score/approval tools and schemas, cut-offs, token sample, errors, and protocol version. Freeze the adapter mapping. |
| Action format | Current Twin uses string `action` plus separate `params`, not the older nested action object | Confirm this wire format; keep any internal proposal translation inside Elyes's adapter. |
| Dispatch location | Twin uses `destination`; targets are dispatch carriers | Confirm name and semantics. Fetch carrier IDs and allowed unit types from discovery. |
| Preview | Twin flags valve/grid preview required but does not provide/enforce preview yet; plans 15-17 Oct | Request a minimal mock preview or agree an explicit mock exception with partners. Until confirmed, live high-risk requests remain blocked. Fixtures can test both safe preview and missing preview. |
| Two-step commit | Final report has a working default; Twin plans it for 8 Oct, off by default | Discover feature support. Test both immediate commit and pending/commit; never assume a second call always exists. |
| Cap discovery | Current `get_capabilities` reports tools, not numeric caps; `list_actions` exposes an action cap | Use the manifest for current action limits and ask Trinity to expose the complete agreed cap map. Do not infer all-domain shared-node limits from one action row. |
| Containment lifecycle | Earlier message says reset-only; `twin-containment` already adds Guardian-only `release_device` | Treat release as a discovered optional feature. Brain must not invoke it. Confirm notify/recovery payload with Guardian. |
| Rollback cap | Earlier message says uncapped; current branch adds a separate rollback pool marked not confirmed | Ask Trinity and 9antra to settle this. CIVIS must not hardcode either rule or claim confirmation. |
| Cap confirmation | Twin config comments say confirmed on 5 Oct; supplied message asks for confirmation | Verify with 9antra. A code comment alone is not proof of partner approval. |
| Traffic metric | Current branch has speeds/counts, congestion index scheduled 8 Oct | Use an explicit congestion fixture for tests. Until the metric is available, return unsupported rather than inventing a conversion. |
| Emergency feed | Numeric channels exist; full transcripts planned later | The mock can detect channel events. Detailed injuries, victims and prompt-injection transcripts use clearly synthetic fixtures only. |
| Power/Water response | No public safe hydraulic/topology model or power thresholds | Keep defaults conservative. Demonstrate positive valve preview only with a declared safe fixture. Live low-load/high-level readings alone cannot justify a topology-changing command. |
| Shared log | Final report assigns a draft to Trinity and review by all on 9 Oct | Map CIVIS JSONL to that draft; preserve evidence/status/code, and keep secrets out. |

The API examples and test-only thresholds in this scaffold are development choices. They are not signed-off triplet safety settings. The free AI API must not choose or relax those settings.

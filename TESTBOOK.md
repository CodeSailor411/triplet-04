# Test Book

The triplet chooses its scenarios. Together they must exercise all layers and interactions. The following are proposed cases, not organizer-mandated scenarios.

| ID | Name | Layers | Trigger | Expected outcome | Status |
| --- | --- | --- | --- | --- | --- |
| scaffold-smoke | Synthetic trusted-reading fixture | All, mocked | `python scenarios/run.py scaffold-smoke` | Ordered fixture events saved under logs; no live services | Scaffold only |
| T1 | Real traffic incident | All | To implement | Guardian trusts data, Brain responds, Twin confirms action | Planned |
| T2 | Spoofed reading | All | To implement | Guardian rejects data, Brain avoids unsafe command | Planned |
| T3 | Partner unavailable | All | To implement | Clear timeout and safe fallback; mocks prove independence | Planned |

For every real scenario document: ID, name, layers, description, single trigger, expected Twin behavior, expected Guardian behavior, expected Brain behavior, verification steps, timing thresholds, and log filename.

Do not label fixture output as live integration evidence.

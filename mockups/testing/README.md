# Triplet mock checkpoints

The repository tag identifies a complete repository snapshot. Each layer's runnable source stays in its designated root folder; do not duplicate it under this testing index.

| Layer | Location | Checkpoint | Status |
| --- | --- | --- | --- |
| Twin, Trinity | twin/ | twin-mock-1, commit 9170ee2404face946a346711e1739d0c405052c1 | Published by Trinity; copied unchanged from the tag into this local integration branch |
| Brain, CIVIS | brain/ | brain-mock-1 requested | Local candidate; release held for joint interoperability gaps |
| Guardian, 9antra | guardian/ | Not supplied | Scaffold only; no partner mock to import |

brain/mocks/ contains CIVIS test stand-ins and synthetic cases. These are not Houssem's implementation. Twin's own mocks/ contains its example clients/test token tooling.

From brain/, use .\.venv\Scripts\python.exe -m civis_brain for the local console and MCP endpoint. Follow [the Brain handover](../../brain/docs/mock-team/HANDOVER.md) and [audit](../../brain/docs/mock-team/HANDOVER_AUDIT_2026-10-11.md). The opt-in scripts/smoke_partner_twin.py --twin-root ..\twin requires Twin's declared dependencies as well.

Publish immutable checkpoint tags only after naming the tested scope and unresolved dependencies. A tag records a snapshot, so later fixes should receive a new tag such as brain-mock-2; do not move a tag that partners may already use. Do not tag main or merge unrelated changes to produce a layer release.

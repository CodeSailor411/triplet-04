# G7 numeric policy

Generated from `src/guardian_policy.json`.

- Trusted cutoff: `trust_score >= 0.7` → Trusted
- Degraded range: `0.3 < trust_score < 0.7` → Degraded
- Untrusted range: `trust_score <= 0.3` → Untrusted
- Minimum scores: R1 `0.5`, R2 `0.7`, R3 `0.85`
- Values provisional: `True`

Startup validation rejects R2/R3 minima below the Trusted cutoff. `compute_trust_score` retains its numeric penalties and thresholds; the trusted boundary is inclusive to match action authorization.

# CONFIRM: CIVIS and Guardian owners to approve final cut-offs and risk minima.

## Synthetic Twin-shaped flood check (2026-10-23)

A local-only check submitted 14 sequential water-level readings through the
Twin event ingestion route, ending at 180 cm. The final/focus reading scored
0.75 (Trusted) against the provisional R3 minimum of 0.85, a 0.10 shortfall.
This is one synthetic sequence, not a live Twin result or a proven maximum
reachable score. The R3 minimum was not lowered to fit the scenario.

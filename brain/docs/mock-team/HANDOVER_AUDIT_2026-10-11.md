# Brain mock handover audit

11 October 2026. Branch: codex/civis-elyes. Scope: five-scenario mock and available Twin interoperability, with a test Guardian. No real Guardian service was available.

## Corrections

- Kept the three-attempt trust limit stable when a detector changes its incident ID each tick.
- Converted malformed Guardian verdict rows into a controlled refusal.
- Rechecked clock and containment before optional pending confirmation.
- Preserved pending status and the original key after a lost confirmation response.
- Rejected boolean/numeric substitution in approval parameters and oversized tokens.
- Let a single Guardian field mapping handle both approved and denied requests without requiring a token on denial.
- Added local caller-key setup that preserves custom credentials and the Gemini key.

## Evidence

- Full Brain suite: 280 tests, including scenario, API, real HTTP/MCP, authentication, normalization, containment, token binding, idempotency and error-handling checks.
- Ruff and all 55 applicable dependency pins verified; installed dependencies are compatible.
- Real Twin source: twin-mock-1, commit 9170ee2404face946a346711e1739d0c405052c1, imported unchanged into twin/.
- Six real-MCP Twin checks: unsigned Medical approval, denial, signed approval, corrupted signature, missing Water preview and missing Traffic metric.
- Both approved Medical checks committed exactly once. Replaying the same command/key returned the original result; changing the command with that key was rejected; reusing the token with a new key was rejected.
- All six duplicate Brain tick requests returned their saved result.
- Twin's real log merger accepted Brain logs.
- Previous integration verification also exercised live Gemini planning for Traffic, Water and Medical; this audit did not spend additional API calls because the provider was unchanged.

The Twin checks use synthetic readings, recorded plans, a test Guardian and a frozen simulated clock. A correct refusal verifies safe handling of a missing feature, not a completed live Traffic/Water workflow.

## Release status

Brain and the available Twin are placed in their designated layer folders. Guardian remains an empty partner scaffold. Do not invent or label a stand-in as 9antra's deliverable.

brain-mock-1 is the requested release name. Publication remains gated by the user's requirement for complete interoperability. Real Guardian, live Traffic/Water dependencies and continuous-clock execution are unresolved. A mock-only preview could be published with these limits if Elyes explicitly changes that release scope.

See [Guardian contract](GUARDIAN_CONTRACT.md), [partner gaps](PARTNER_GAPS.md), and [handover](HANDOVER.md).

# Tagged v2 audit results

23 October 2026. See `INTEROPERABILITY_2026-10-23.md` for fixed source revisions, the Guardian packaging workaround, scenario outcomes and corrections by owner.

| Check | Final result | Interpretation |
|---|---|---|
| Original Brain baseline | 336 passed | Existing release before CIVIS changes |
| Final Brain regression suite | 357 passed | Includes 21 HTTP-adapter/security tests; no external AI in this suite |
| Tagged partner controls + required acceptance | 25 passed, 13 failed | 38 ordinary tests, no errors/skips/xfails; failures remain required failures |
| Actual Guardian/Twin v2 controls | 10 passed | Five individual workflows, mixed workflows, actual token refusal, authenticated ingestion boundary, real Guardian SSE bridge and missing-evidence refusal |
| Earlier partner controls | 14 passed | Some positive actions explicitly use a test Guardian; not actual three-layer approval acceptance |
| Valid signed-claim control | 1 passed | Local test signer, not actual Guardian |
| Actual Gemini + actual peers | 1 passed | Water request, 5.97 real seconds; actual Guardian evidence, actual Twin preview; safe block at incompatible authorization contract, zero effects |
| Ruff | Passed | Brain source, tests, mocks, integration checks and scripts |
| Partner source verification | 126 of 126 match tags | No Guardian/Twin source patch |

The 13 required failures are five Twin token-claim checks; three existing Guardian security checks; plus actual cross-layer token compatibility, Guardian run binding, multi-channel identity, shared timeline format and real containment propagation. Guardian's clean-tag startup failure is recorded separately before those tests can run.

The mixed test uses all five reduced modules on one actual Twin batch stream. It preserves alerts and refusals without unauthorized effects. It does not certify positive physical actions while approvals remain incompatible.

During development the mixed test initially had a missing test-harness import. That was fixed and the complete 38-test partner suite was rerun. The final result above includes only the 13 reproducible partner acceptance failures, not that corrected harness error.

The diagnostic layout adds copies of tagged model/layer assets at legacy expected paths outside the imported partner folder. The exact Guardian tag remains broken. All controls using that layout are labelled diagnostic; no fresh-clone success is inferred.

Evidence: `brain/.artifacts/interop-oct23/brain-final.xml`, `tagged-partners-final.xml`, `live-gemini.xml`, scenario JSON and source manifests. The shareable evidence package contains sanitized summaries and outcomes, not credentials, PEM private keys, `.env` files or full approval tokens.

Changes are local to `codex/civis-elyes`; the existing `brain-mock-2` tag and remote branches were not updated. Partner folders are exact imported snapshots; all integration fixes are under `brain/`.

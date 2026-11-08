"""T5 Token replay: one permission slip must work once.

Layers: Guardian -> Twin (the Twin's trust gate), with the Brain's role played by this script.
Trigger: the Guardian issues one token, the script sends `actuate` twice with that SAME token (second time with a new
idempotency key, so it is a new command and not a repeat of the first).
Expected: the first `actuate` is committed, the second is rejected with TOKEN_REUSED. The Twin logs one of each.

Two ways to run it:
    python scenarios/T5_token_replay.py                  stand-in Guardian signs the token (needs a Twin you started yourself)
    python scenarios/T5_token_replay.py --layers real    the REAL Guardian issues the token. Start the whole stack first
                                                         (docker compose up). The Twin then checks the real signature.
The log label says which one it was (read from the events, never from a flag).
"""
import _kit as kit
import _real_guardian as rg

run = kit.begin("T5", "Token replay", __doc__, real_ok=True, extra=rg.add_args)
what = {"action": "set_signal_plan", "targets": ["TRF-01"], "params": {"plan": "normal"}}

if run.real:
    token, why = rg.ask_token(run, rg.pick_reading(run), "T5-first")
    if token is None:                                   # no token, no test: save the run as a FAIL so the evidence stays
        rg.no_token(run, why)
else:
    token = run.stand_in("mock_guardian.py", "token", "--action", what["action"], "--targets", "TRF-01",
                         "--params", '{"plan": "normal"}', "--idempotency-key", "T5-first")["token"]

first = run.call("city_brain", "actuate", {**what, "token": token, "idempotency_key": "T5-first"})
second = run.call("city_brain", "actuate", {**what, "token": token, "idempotency_key": "T5-second"})
print(f"  first send: {first['status']}   second send with the same token: {second['status']} {second.get('code')}")


def checks(events):
    out = [
        (first["status"] == "committed", "first use of the token: committed"),
        (second["status"] == "rejected" and second.get("code") == "TOKEN_REUSED", "second use of the same token: rejected with TOKEN_REUSED"),
        (len(kit.actions(events, "committed")) == 1, "the Twin log holds exactly one committed action"),
        (len(kit.actions(events, "rejected", "TOKEN_REUSED")) == 1, "the Twin log holds the TOKEN_REUSED refusal"),
    ]
    if run.real:
        out.append((kit.layer_label(events, "guardian") == "real", "the Guardian's events in the log come from the real Guardian"))
    else:
        out.append((bool(kit.of(events, "guardian", "verdict")), "Guardian's verdict for the token is in the log"))
    return out


kit.finish(run, {"first": first, "second": second}, checks)
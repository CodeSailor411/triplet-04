"""T5 Token replay: one permission slip must work once.

Layers: Guardian -> Twin (the Twin's trust gate), with the Brain's role played by this script.
Trigger: the stand-in Guardian signs one token, the script sends `actuate` twice with that SAME token (second time with a new
idempotency key, so it is a new command and not a repeat of the first).
Expected: the first `actuate` is committed, the second is rejected with TOKEN_REUSED. The Twin logs one of each.

Stand-ins only: the Twin owns the trust gate, and this test needs a token we control.

    python scenarios/T5_token_replay.py
"""
import _kit as kit

run = kit.begin("T5", "Token replay", __doc__)
what = {"action": "set_signal_plan", "targets": ["TRF-01"], "params": {"plan": "normal"}}
token = run.stand_in("mock_guardian.py", "token", "--action", what["action"], "--targets", "TRF-01",
                     "--params", '{"plan": "normal"}', "--idempotency-key", "T5-first")
first = run.call("city_brain", "actuate", {**what, "token": token["token"], "idempotency_key": "T5-first"})
second = run.call("city_brain", "actuate", {**what, "token": token["token"], "idempotency_key": "T5-second"})
print(f"  first send: {first['status']}   second send with the same token: {second['status']} {second.get('code')}")


def checks(events):
    return [
        (first["status"] == "committed", "first use of the token: committed"),
        (second["status"] == "rejected" and second.get("code") == "TOKEN_REUSED", "second use of the same token: rejected with TOKEN_REUSED"),
        (len(kit.actions(events, "committed")) == 1, "the Twin log holds exactly one committed action"),
        (len(kit.actions(events, "rejected", "TOKEN_REUSED")) == 1, "the Twin log holds the TOKEN_REUSED refusal"),
        (bool(kit.of(events, "guardian", "verdict")), "Guardian's verdict for the token is in the log"),
    ]


kit.finish(run, {"first": first, "second": second}, checks)

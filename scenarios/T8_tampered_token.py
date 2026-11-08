"""T8 Tampered token: a permission slip with a changed signature must be refused.

Layers: Guardian -> Twin (the Twin's trust gate), with the Brain's role played by this script.
Trigger: the Guardian issues two tokens. The first one is sent as it is (the control). The second one is tampered with: one
character of its signature is changed. Both are sent with `actuate`.
Expected: the control is committed, the tampered token is rejected with TOKEN_INVALID. The Twin log holds one committed
action and one TOKEN_INVALID refusal.

The Twin must check signatures (tokens.mode: signed). In unsigned mode a tampered token may get through and this script says FAIL.

Two ways to run it:
    python scenarios/T8_tampered_token.py                  stand-in Guardian signs the tokens (needs a Twin in signed mode that
                                                         you started yourself, with the stand-in's key pair)
    python scenarios/T8_tampered_token.py --layers real    the REAL Guardian issues the tokens. Start the whole stack first
                                                         (docker compose up). That stack already runs the Twin in signed mode.
The log label says which one it was (read from the events, never from a flag).
"""
import _kit as kit
import _real_guardian as rg

run = kit.begin("T8", "Tampered token", __doc__, real_ok=True, extra=rg.add_args)
what = {"action": "set_signal_plan", "targets": ["TRF-01"], "params": {"plan": "normal"}}
reading = rg.pick_reading(run) if run.real else None


def get_token(idem: str) -> str:
    """One valid token for the command above, from the real Guardian or from the stand-in."""
    if run.real:
        token, why = rg.ask_token(run, reading, idem)
        if token is None:                               # no token, no test: save the run as a FAIL so the evidence stays
            rg.no_token(run, why)
        return token
    return run.stand_in("mock_guardian.py", "token", "--action", what["action"], "--targets", "TRF-01",
                        "--params", '{"plan": "normal"}', "--idempotency-key", idem)["token"]


def forge(token: str) -> str:
    """Change the first character of the signature (the part after the last dot). The rest stays the same."""
    head, dot, sig = token.rpartition(".")
    if not dot or not sig:
        kit.setup_exit("the token has no signature to change. Usually the Twin is not in signed mode (tokens.mode: signed).")
    return head + "." + ("B" if sig[0] == "A" else "A") + sig[1:]


good = get_token("T8-valid")
bad = forge(get_token("T8-tampered"))
control = run.call("city_brain", "actuate", {**what, "token": good, "idempotency_key": "T8-valid"})
forged = run.call("city_brain", "actuate", {**what, "token": bad, "idempotency_key": "T8-tampered"})
print(f"  valid token: {control['status']}   tampered token: {forged['status']} {forged.get('code')}")
if forged["status"] == "committed":
    print("  hint: the tampered token was accepted. The Twin is probably not in signed mode (check tokens.mode).")


def checks(events):
    out = [
        (control["status"] == "committed", "valid token (control): committed"),
        (forged["status"] == "rejected" and forged.get("code") == "TOKEN_INVALID", "tampered token: rejected with TOKEN_INVALID"),
        (len(kit.actions(events, "committed")) == 1, "the Twin log holds exactly one committed action (the control)"),
        (len(kit.actions(events, "rejected", "TOKEN_INVALID")) == 1, "the Twin log holds the TOKEN_INVALID refusal"),
    ]
    if run.real:
        out.append((kit.layer_label(events, "guardian") == "real", "the Guardian's events in the log come from the real Guardian"))
    else:
        out.append((bool(kit.of(events, "guardian", "verdict")), "Guardian's verdict for the token is in the log"))
    return out


kit.finish(run, {"control": control, "forged": forged}, checks)
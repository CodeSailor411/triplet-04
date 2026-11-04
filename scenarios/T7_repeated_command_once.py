"""T7 Repeated command: the same command sent twice must run once.

Layers: Brain -> Twin (the Twin's idempotency key), with the stand-in Guardian handing out the token.
Trigger: the stand-in Brain sends the same `actuate` twice with the same idempotency key (a network retry).
Expected: the first send is committed, the second one gets the first answer back (replayed = true, same action id),
and the Twin log holds ONE committed action.

Stand-ins only: the Twin owns idempotency, and the test needs one exact repeated request.

    python scenarios/T7_repeated_command_once.py
"""
import _kit as kit

run = kit.begin("T7", "Repeated command runs once", __doc__)
out = run.stand_in("mock_brain.py", "act", "--action", "set_signal_plan", "--targets", "TRF-01", "--params", '{"plan": "normal"}',
                   "--idempotency-key", "T7-repeat", "--sends", "2")
answers = out.get("twin_answers", [])


def checks(events):
    one = [e for e in kit.actions(events, "committed") if e["data"].get("idempotency_key") == "T7-repeat"]
    return [
        (len(answers) == 2, "the Brain sent the command twice"),
        (len(answers) == 2 and answers[0]["status"] == "committed" and not answers[0]["replayed"], "first send: committed"),
        (len(answers) == 2 and answers[1]["replayed"], "second send: answered from the first (replayed = true)"),
        (len(answers) == 2 and answers[0]["action_id"] == answers[1]["action_id"], "both answers carry the same action id"),
        (len(one) == 1, "the Twin log holds exactly one committed action for that key"),
    ]


kit.finish(run, out, checks)

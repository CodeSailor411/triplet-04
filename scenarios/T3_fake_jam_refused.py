"""T3 Fake jam: a sensor lies about a jam, Guardian refuses, nothing is sent.

Layers: Twin -> Guardian -> Brain.
Trigger: the Twin starts scenario `fake_reading` (SH-05 REPORTS a congestion index of 95, the true value does not move).
Expected: Guardian does not trust the reading and refuses the token, the Brain sends nothing and hands the case to a person,
the Twin commits no action.

    python scenarios/T3_fake_jam_refused.py                 # our stand-in Guardian is told to refuse
    python scenarios/T3_fake_jam_refused.py --layers real   # the real Guardian must judge the lie by itself
"""
import _kit as kit


def more_args(ap):
    ap.add_argument("--wait", type=float, default=30, help="real seconds to wait for the real layers to react (default 30)")


run = kit.begin("T3", "Fake jam refused", __doc__, real_ok=True, extra=more_args)
out = {}
if run.real:
    run.scenario("fake_reading", {"device_id": "SH-05.congestion_index", "value": 95.0})
    run.wait(run.args.wait, "the real Guardian and Brain react to the fake reading")
else:
    out = run.stand_in("mock_brain.py", "incident", "--fake-jam", "--guardian-mode", "refuse")


def checks(events):
    fake = [e for e in kit.of(events, "twin", "scenario") if e["data"].get("phase") == "started"]
    verdicts = kit.of(events, "guardian", "verdict")
    results = [
        (bool(fake), "the Twin started the fake reading"),
        (not kit.actions(events, "committed"), "the Twin committed no action"),
        (bool(verdicts), "Guardian wrote a verdict"),
    ]
    if not run.real:
        results += [
            (out.get("reason") == "GUARDIAN_REFUSED", "the Brain was refused (GUARDIAN_REFUSED) and sent nothing"),
            (all(e["data"].get("score", 1) < 0.5 for e in verdicts) and bool(verdicts), "the verdict score is low (below 0.5)"),
            (bool(kit.of(events, "brain", "escalation")), "the Brain escalated the case to a person"),
        ]
    else:
        results.append((bool(kit.of(events, "brain")), "the Brain wrote events"))
    return results


kit.finish(run, out, checks)

"""T1 Calm day: nothing happens, so nobody should act.

Layers: Twin -> Brain (and Guardian, only if it is asked).
Trigger: the script resets the Twin and lets the Brain watch a calm city for a while.
Expected: the Brain sees no incident, so no action is sent, nothing is escalated to a person.

    python scenarios/T1_calm_day.py                 # our stand-in Brain watches
    python scenarios/T1_calm_day.py --layers real   # the real Brain must be running already, we only wait and read the log
"""
import _kit as kit


def more_args(ap):
    ap.add_argument("--wait", type=float, default=20, help="how many real seconds to watch the calm city (default 20)")


run = kit.begin("T1", "Calm day", __doc__, real_ok=True, extra=more_args)
run.close_run = True          # a calm run logs nothing by itself: end it at the end so the Twin writes its log file
out = {}
if run.real:
    run.wait(run.args.wait, "the real Brain is watching a calm city")
else:
    out = run.stand_in("mock_brain.py", "incident", "--wait-seconds", str(run.args.wait))


def checks(events):
    started = [e for e in kit.of(events, "twin", "scenario") if e["data"].get("phase") == "started"]
    return [
        (run.real or out.get("outcome") == "no_incident", "the Brain saw no incident" if not run.real else "(real Brain: judged from the log below)"),
        (not started, "no fault and no incident was started on the Twin"),
        (not kit.actions(events), "the Twin received no action at all"),
        (not kit.of(events, None, "escalation"), "nothing was escalated to a person"),
    ]


kit.finish(run, out, checks)

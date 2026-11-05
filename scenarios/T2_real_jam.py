"""T2 Real jam: a real traffic jam happens, so the action must go through.

Layers: Twin -> Guardian -> Brain -> Twin (all three).
Trigger: the Twin starts scenario `real_jam` (the TRUE value of the congestion sensor at SH-05 rises, and its neighbours follow).
Expected: the Brain sees the jam, Guardian trusts the readings and signs a token, the Brain sends `set_signal_plan`,
the Twin commits it.

    python scenarios/T2_real_jam.py                 # our stand-ins play Brain and Guardian
    python scenarios/T2_real_jam.py --layers real   # the real Brain and Guardian must be running already
"""
import _kit as kit


def more_args(ap):
    ap.add_argument("--wait", type=float, default=45, help="real seconds to wait for the real layers to react (default 45)")


run = kit.begin("T2", "Real jam", __doc__, real_ok=True, extra=more_args)
out = {}
if run.real:
    run.scenario("real_jam", {"node_id": "SH-05"})
    run.wait(run.args.wait, "jam builds up, the real Brain and Guardian react")
else:
    out = run.stand_in("mock_brain.py", "incident", "--real-jam")


def checks(events):
    jam = [e for e in kit.of(events, "twin", "scenario") if e["data"].get("name") == "real_jam" and e["data"].get("phase") == "started"]
    readings = [e for e in kit.of(events, "twin", "reading") if jam and jam[0]["event_id"] in e.get("caused_by", [])]
    verdicts, decisions = kit.of(events, "guardian", "verdict"), kit.of(events, "brain", "decision")
    done = kit.actions(events, "committed")
    first = lambda items: min((e["tick"] for e in items), default=None)                       # noqa: E731
    ticks = [first(readings), first(verdicts), first(decisions), first(done)]
    in_order = None not in ticks and ticks == sorted(ticks)
    return [
        (bool(jam), "the Twin started the real jam"),
        (bool(readings), "the jam's readings are in the log, linked to the start"),
        (bool(verdicts), "Guardian wrote a verdict"),
        (bool(decisions), "the Brain wrote a decision"),
        (bool(done), "the Twin committed an action"),
        (in_order, f"order in time is reading -> verdict -> decision -> action (first ticks: {ticks})"),
    ]


kit.finish(run, out, checks)

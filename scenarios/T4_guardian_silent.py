"""T4 Guardian silent: a partner stops answering, the Brain must not act on its own.

Layers: Twin -> Brain -> Guardian (Guardian is the broken one).
Trigger: the Twin starts scenario `fake_reading`, and the stand-in Guardian never answers.
Expected: the Brain waits, gives up after its timeout, logs a partner failure, escalates to a person and sends no action.
The Twin commits nothing.

Stand-ins only: the stand-in Guardian lives inside the stand-in Brain, so it cannot be paired with the real Brain.

    python scenarios/T4_guardian_silent.py
"""
import _kit as kit

run = kit.begin("T4", "Guardian silent", __doc__)
out = run.stand_in("mock_brain.py", "incident", "--fake-jam", "--guardian-mode", "silent")


def checks(events):
    failures = [e for e in kit.of(events, "brain", "partner_failure") if e["data"].get("partner") == "guardian"]
    return [
        (out.get("reason") == "GUARDIAN_TIMEOUT", "the Brain gave up waiting (GUARDIAN_TIMEOUT)"),
        (bool(failures), "the Brain logged a partner failure for Guardian"),
        (bool(kit.of(events, "brain", "escalation")), "the Brain escalated to a person"),
        (not kit.actions(events, "committed"), "the Twin committed no action"),
        (not kit.of(events, "guardian", "verdict"), "Guardian wrote no verdict (it was silent)"),
    ]


kit.finish(run, out, checks)

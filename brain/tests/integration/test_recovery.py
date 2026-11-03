import asyncio
import copy

import pytest

from civis_brain.contracts import ReadingsBatch

from .test_member_integration import case_for, harness
from .test_oct19 import advance


def setup(tmp_path, *, cleared=False, missing=False, fresh_score=100.0):
    case = case_for("emergency")
    case["batches"][0]["tick_seconds"] = 1.0
    runtime, twin, guardian, provider = harness(case, tmp_path)
    runtime.features["evidence_recovery_enabled"] = True
    batch = ReadingsBatch.model_validate(case["batches"][0])
    later = advance(case["batches"][0], 1)
    if cleared:
        later["readings"][0]["value"] = 0
    if missing:
        later["readings"][0]["value"] = None
    later = ReadingsBatch.model_validate(later)
    twin.advance(later)
    runtime.observe_feed(later)
    original = guardian.call_tool
    score_calls = []

    async def call(name, args):
        result = await original(name, args)
        if name == "fixture_score":
            score_calls.append(copy.deepcopy(args))
            for row in result["scores"]:
                row["score"] = .1 if len(score_calls) == 1 else fresh_score
        return result

    guardian.call_tool = call
    return runtime, twin, guardian, batch, later, score_calls


async def test_recovery_requires_later_evidence_and_fresh_verdict(tmp_path):
    runtime, twin, _, batch, later, calls = setup(tmp_path)
    result = await runtime.evaluate_tick(batch)
    assert result.decisions[0].status == "committed", result
    assert len(calls) == 2
    assert calls[1]["tick"] == later.tick
    old_ids = {r.reading_id for r in batch.readings}
    new_ids = {r.reading_id for r in later.readings}
    assert old_ids | new_ids == {r["reading_id"] for r in calls[1]["readings"]}
    assert len(twin.effects) == 1
    events = [e["event"] for e in runtime.journal.events]
    assert events.index("recovery_neighbours") < events.index("recovery_later_tick") < events.index("recovery_fresh_verdict")


@pytest.mark.parametrize("missing,cleared,score,code", [
    (True, False, 100.0, "RECOVERY_EVIDENCE_MISSING"),
    (False, True, 100.0, "EVIDENCE_CHANGED"),
    (False, False, .1, "TRUST_INSUFFICIENT"),
])
async def test_recovery_never_overrides_missing_cleared_or_untrusted_evidence(
        tmp_path, missing, cleared, score, code):
    runtime, twin, _, batch, _, _ = setup(tmp_path, missing=missing, cleared=cleared,
                                        fresh_score=score)
    result = await runtime.evaluate_tick(batch)
    assert result.decisions[0].peer_code == code, result
    assert not twin.effects


async def test_recovery_stops_after_exhaustion_instead_of_retrying_each_tick(tmp_path):
    runtime, twin, _, batch, later, calls = setup(tmp_path, fresh_score=.1)
    await runtime.evaluate_tick(batch)
    result = await runtime.evaluate_tick(later)
    assert result.decisions[0].peer_code == "TRUST_RETRIES_EXHAUSTED", result
    assert len(calls) == 2 and not twin.effects


async def test_recovery_same_tick_timeout_has_no_fresh_verdict_or_action(tmp_path):
    runtime, twin, _, batch, _, calls = setup(tmp_path)
    runtime.observe_feed(batch)
    twin.advance(batch)
    result = await runtime.evaluate_tick(batch)
    assert result.decisions[0].peer_code == "RECOVERY_NEXT_TICK_TIMEOUT"
    assert len(calls) == 1 and not twin.effects


async def test_recovery_run_reset_refuses_before_fresh_verdict(tmp_path):
    runtime, twin, _, batch, later, calls = setup(tmp_path)
    changed = later.model_copy(deep=True)
    changed.run_id = "changed-run"
    for row in changed.readings:
        row.run_id = changed.run_id
    runtime.latest_feed = changed
    result = await runtime.evaluate_tick(batch)
    assert result.decisions[0].peer_code == "CLOCK_MISMATCH", result
    assert len(calls) == 1 and not twin.effects


async def test_recovery_disconnect_refuses_before_fresh_verdict(tmp_path):
    runtime, twin, _, batch, _, calls = setup(tmp_path)
    runtime.feed_connected = False
    result = await runtime.evaluate_tick(batch)
    assert result.decisions[0].peer_code == "FEED_DISCONNECTED"
    assert len(calls) == 1 and not twin.effects


@pytest.mark.parametrize("unit,included", [("calls/min", True), ("wrong-unit", False)])
async def test_recovery_neighbours_are_supplementary_and_unit_matched(tmp_path, unit, included):
    runtime, twin, _, batch, later, calls = setup(tmp_path)
    twin.case["nodes"][0]["neighbours"] = ["NEIGHBOUR-01"]
    twin.case["nodes"].append({"node_id": "NEIGHBOUR-01", "domains": ["emergency"],
                               "role": "sensor", "actuators": []})
    neighbour = later.readings[0].model_copy(update={"node_id": "NEIGHBOUR-01",
        "device_id": "NEIGHBOUR-DEVICE", "reading_id": "neighbour-reading", "unit": unit})
    later.readings.append(neighbour)
    later.count += 1
    result = await runtime.evaluate_tick(batch)
    assert result.decisions[0].status == "committed", result
    sent = {r["reading_id"] for r in calls[1]["readings"]}
    assert ("neighbour-reading" in sent) == included
    assert "neighbour-reading" not in result.decisions[0].source_reading_ids


async def test_recovery_total_deadline_includes_fresh_guardian_call(tmp_path, monkeypatch):
    from civis_brain.integration import recovery
    runtime, twin, guardian, batch, _, calls = setup(tmp_path)
    original_call = guardian.call_tool
    original_timeout = asyncio.timeout
    deadlines = []

    def deadline(seconds):
        deadlines.append(seconds)
        return original_timeout(.02 if seconds == 10 else seconds)

    async def slow(name, args):
        if name == "fixture_score" and calls:
            await asyncio.sleep(.2)
        return await original_call(name, args)

    monkeypatch.setattr(recovery.asyncio, "timeout", deadline)
    guardian.call_tool = slow
    result = await runtime.evaluate_tick(batch)
    assert result.decisions[0].peer_code == "RECOVERY_TIMEOUT"
    assert 10 in deadlines and 3 in deadlines and not twin.effects


async def test_completed_episode_does_not_spend_another_ai_call(tmp_path):
    runtime, twin, _, batch, later, _ = setup(tmp_path)
    runtime.features["one_response_per_episode"] = True
    first = await runtime.evaluate_tick(batch)
    count = runtime.ai_calls
    second = await runtime.evaluate_tick(later)
    assert second.decisions[0].decision_id == first.decisions[0].decision_id
    assert runtime.ai_calls == count == 1 and len(twin.effects) == 1

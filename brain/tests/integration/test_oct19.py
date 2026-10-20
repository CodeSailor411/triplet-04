"""Regressions for the 16 October agreements and the three-layer audit."""

import asyncio
import copy
from datetime import timedelta

import pytest

from civis_brain.contracts import Node, ReadingsBatch
from civis_brain.inputs.service import utc_time
from civis_brain.integration.feed import TwinFeed

from .test_member_integration import case_for, evaluate, harness


def advance(raw, ticks=1):
    raw = copy.deepcopy(raw)
    raw["tick"] += ticks
    raw["time"] = (utc_time(raw["time"]) + timedelta(seconds=ticks * raw["tick_seconds"])).isoformat().replace("+00:00", "Z")
    for row in raw["readings"]:
        row.update(tick=raw["tick"], timestamp=raw["time"], reading_id=f'{row["device_id"]}:{row["channel"]}:{raw["tick"]}')
    return raw


@pytest.mark.parametrize("delay,expected", [(1, "committed"), (9, "committed"), (11, "blocked")])
async def test_moving_clock_and_fresh_authorization(delay, expected, tmp_path):
    case = case_for("emergency")
    case["batches"][0]["tick_seconds"] = 1.0
    runtime, twin, guardian, provider = harness(case, tmp_path)
    original = provider.generate

    async def slow_plan(context):
        result = await original(context)
        twin.advance(advance(twin.clock, delay))
        return result
    provider.generate = slow_plan
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].status == expected
    assert len(twin.effects) == int(expected == "committed")
    approvals = [c for c in guardian.calls if c["name"] == "fixture_approve"]
    if approvals:
        assert approvals[0]["arguments"]["tick"] == twin.clock["tick"]
        assert approvals[0]["arguments"]["time"] == twin.clock["time"]
    else:
        assert result.decisions[0].peer_code == "EVIDENCE_STALE"


@pytest.mark.parametrize("domain", ["emergency", "water", "traffic"])
@pytest.mark.parametrize("one_response", [False, True])
async def test_new_episode_after_clear_uses_new_key(domain, one_response, tmp_path):
    case = case_for(domain)
    runtime, twin, guardian, provider = harness(case, tmp_path)
    runtime.features["one_response_per_episode"] = one_response
    await evaluate(case, runtime, twin)
    assert len(twin.effects) == 1
    last = case["batches"][-1]
    primary = case["policy"]["sensor"]
    clear = advance(last)
    for row in clear["readings"]:
        if row["sensor"] == primary:
            row["value"] = 0.0
    twin.advance(clear)
    await runtime.evaluate_tick(ReadingsBatch.model_validate(clear))
    sources = []
    for _ in range(case["policy"]["persistence_ticks"]):
        fresh = advance(last, clear["tick"] - last["tick"] + 1)
        sources.extend(row["reading_id"] for row in fresh["readings"])
        provider.case["ai_plan"]["proposals"][0]["source_reading_ids"] = sources
        twin.advance(fresh)
        result = await runtime.evaluate_tick(ReadingsBatch.model_validate(fresh))
        clear = fresh
    assert result.decisions[-1].status == "committed", result
    assert len(twin.effects) == 2
    sent = [c["arguments"]["idempotency_key"] for c in twin.calls if c["name"] == "actuate"]
    assert len(set(sent)) == 2


async def test_percent_symbol_keeps_original_wire_evidence(tmp_path):
    case = case_for("traffic")
    for raw in case["batches"]:
        for row in raw["readings"]:
            row.update(unit="%", lat=36.12345, lon=10.12345)
    runtime, twin, guardian, _ = harness(case, tmp_path)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[-1].status == "committed"
    scored = next(c for c in guardian.calls if c["name"] == "fixture_score")
    assert all(r["unit"] == "%" and r["lat"] == 36.12345 and r["lon"] == 10.12345
               for r in scored["arguments"]["readings"])


async def test_future_domains_do_not_break_existing_scenarios(tmp_path):
    case = case_for("emergency")
    case["nodes"].append({"node_id": "TEL-1", "domains": ["telecom", "waste"],
                          "role": "sensor", "lat": 36.1, "lon": 10.2})
    runtime, twin, _, _ = harness(case, tmp_path)
    assert (await evaluate(case, runtime, twin))[-1].decisions[0].status == "committed"
    assert Node.model_validate(case["nodes"][-1]).lon == 10.2


@pytest.mark.parametrize("event", ["disconnect", "gap", "reset"])
async def test_feed_changes_invalidate_queued_plan(event, tmp_path):
    case = case_for("emergency")
    runtime, twin, _, provider = harness(case, tmp_path)
    original = provider.generate

    async def interrupted(context):
        result = await original(context)
        batch = context.batch.model_copy(deep=True)
        if event == "reset":
            batch.run_id = "new-run"
        runtime.observe_feed(batch, discontinuity=event == "gap", connected=event != "disconnect")
        return result
    provider.generate = interrupted
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].status == "blocked"
    assert not twin.effects


async def test_feed_receives_during_slow_evaluation_and_bounds_queue():
    entered, resume = asyncio.Event(), asyncio.Event()

    class SlowRuntime:
        def __init__(self):
            self.seen = []
            self.gaps = []

        def observe_feed(self, batch=None, **kwargs):
            self.seen.append(batch.tick if batch else None)
            self.gaps.append(kwargs.get("discontinuity", False))

        async def evaluate_tick(self, batch):
            entered.set()
            await resume.wait()
            return type("Result", (), {"decisions": []})()

    runtime = SlowRuntime()
    feed = TwinFeed(runtime, "http://unused", "test-only", queue_size=2)
    raw = case_for("emergency")["batches"][0]
    feed.accept("readings", raw)
    task = asyncio.create_task(feed.consume())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        for _ in range(4):
            raw = advance(raw)
            feed.accept("readings", raw)
        assert len(runtime.seen) == 5 and feed.queue.qsize() <= 2
        assert feed.status["dropped"] == 2 and any(runtime.gaps)
        resume.set()
        await asyncio.wait_for(feed.queue.join(), 1)
        assert feed.status["evaluated"] == 3
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_preview_uses_real_twin_shape_and_exact_arguments(tmp_path):
    case = case_for("water")
    runtime, twin, guardian, _ = harness(case, tmp_path)
    runtime.features["preview_tool"] = "preview_action"
    original = twin.call_tool

    async def real_preview(name, args):
        if name == "get_capabilities":
            result = await original(name, args)
            result["tools_you_can_call"].append("preview_action")
            return result
        if name == "preview_action":
            assert set(args) == {"action", "targets", "params"}
            return {"run_id": twin.clock["run_id"], **args, "would_pass_checks": True,
                    "blocked_by": [], "valid_until_tick": twin.clock["tick"] + 60}
        return await original(name, args)
    twin.call_tool = real_preview
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].status == "committed"
    assert len(twin.effects) == 1


async def test_expired_token_after_approval_is_blocked(tmp_path):
    case = case_for("emergency")
    case["batches"][0]["tick_seconds"] = 1.0
    case["guardian"]["token_lifetime_seconds"] = 1
    runtime, twin, guardian, _ = harness(case, tmp_path)
    original = guardian.call_tool

    async def delayed_reply(name, args):
        response = await original(name, args)
        if name == "fixture_approve":
            twin.advance(advance(twin.clock, 2))
        return response
    guardian.call_tool = delayed_reply
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "TOKEN_BINDING_INVALID"
    assert not twin.effects


@pytest.mark.parametrize("change", ["cleared", "missing", "no_ambulance"])
async def test_new_feed_can_withdraw_old_plan(change, tmp_path):
    case = case_for("emergency")
    case["batches"][0]["tick_seconds"] = 1.0
    runtime, twin, _, provider = harness(case, tmp_path)
    original = provider.generate

    async def newer_evidence(context):
        plan = await original(context)
        raw = advance(context.batch.model_dump())
        for row in raw["readings"]:
            if row["sensor"] == "emergency_calls" and change in {"cleared", "missing"}:
                row["value"] = 0.0 if change == "cleared" else None
            if row["sensor"] == "units_free" and change == "no_ambulance":
                row["value"] = 0.0
        twin.advance(raw)
        runtime.observe_feed(ReadingsBatch.model_validate(raw))
        return plan
    provider.generate = newer_evidence
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "EVIDENCE_CHANGED"
    assert not twin.effects


async def test_mismatched_receipt_is_not_success(tmp_path):
    case = case_for("emergency")
    runtime, twin, _, _ = harness(case, tmp_path)
    original = twin.call_tool

    async def wrong_receipt(name, args):
        result = await original(name, args)
        return {**result, "run_id": "wrong-run"} if name == "actuate" else result
    twin.call_tool = wrong_receipt
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].status == "pending"
    assert result.decisions[0].peer_code == "RECEIPT_MISMATCH"
    assert len(twin.effects) == 1  # Unknown to Brain, never reported as confirmed.


async def test_gap_does_not_rearm_persistent_water_operation(tmp_path):
    case = case_for("water")
    runtime, twin, _, provider = harness(case, tmp_path)
    await evaluate(case, runtime, twin)
    last = case["batches"][-1]
    raw = advance(last, 4)
    ids = []
    for _ in range(2):
        ids.extend(r["reading_id"] for r in raw["readings"])
        provider.case["ai_plan"]["proposals"][0]["source_reading_ids"] = ids
        twin.advance(raw)
        result = await runtime.evaluate_tick(ReadingsBatch.model_validate(raw))
        raw = advance(raw)
    assert result.decisions[0].status == "committed"
    assert len(twin.effects) == 1


async def test_expired_pending_deadline_does_not_extend_or_resend(tmp_path, monkeypatch):
    from .helpers import harness as core_harness
    from .helpers import make_case
    case = make_case()
    case["twin_outcome"] = {"status": "pending", "commit_available": True}
    runtime, twin, _, _ = core_harness(case, tmp_path)
    original = twin.call_tool

    async def delayed_pending(name, args):
        result = await original(name, args)
        if name == "actuate":
            runtime.pending_started[args["idempotency_key"]] -= 11
        return result
    twin.call_tool = delayed_pending
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == "CONFIRMATION_TIMEOUT"
    assert not twin.effects
    assert not any(c["name"] == "fixture_commit" for c in twin.calls)


@pytest.mark.parametrize("field,value", [("lat", 91), ("lon", 181), ("lat", float("nan"))])
def test_invalid_coordinates_rejected(field, value):
    from pydantic import ValidationError
    raw = case_for("emergency")["batches"][0]
    raw["readings"][0][field] = value
    with pytest.raises(ValidationError):
        ReadingsBatch.model_validate(raw)


def test_live_mock_policy_override_is_explicit_and_guardian_stays_unconfirmed(tmp_path):
    import json

    from civis_brain.integration.bootstrap import configured_runtime
    from civis_brain.settings import Settings

    policy = tmp_path / "policies.json"
    policy.write_text(json.dumps({"S02": {"safe_valve_choices": [
        {"incident_node_id": "WAT-01", "targets": ["WAT-01"], "params": {"position": 30}}
    ]}}))
    runtime = configured_runtime(Settings(_env_file=None, peer_mode="live",
        llm_mode="gemini", gemini_api_key="test-only-not-a-real-key",
        scenario_policy_file=str(policy), mock_integration_profile=True))
    assert runtime.policies["S02"]["safe_valve_choices"][0]["params"] == {"position": 30}
    assert runtime.policies["S02"]["fixture_only"] is True
    assert runtime.features["guardian_contract_confirmed"] is False


@pytest.mark.parametrize("contents", ['[]', '{"S99": {}}', '{"S01": 12}'])
def test_bad_policy_override_stops_startup(contents, tmp_path):
    from civis_brain.integration.bootstrap import configured_runtime
    from civis_brain.settings import Settings

    path = tmp_path / "policies.json"
    path.write_text(contents)
    with pytest.raises(ValueError, match="known S01-S05"):
        configured_runtime(Settings(_env_file=None, peer_mode="live", scenario_policy_file=str(path)))


@pytest.mark.parametrize("variant", ["future_iat", "long_lifetime", "score_above_one",
                                    "nonfinite_score", "empty_token_id"])
async def test_brain_blocks_claims_accepted_by_partner_twin(variant, tmp_path):
    case = case_for("emergency")
    now = utc_time(case["batches"][0]["time"])
    override = {
        "future_iat": {"iat": (now + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")},
        "long_lifetime": {"exp": (now + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")},
        "score_above_one": {"score": 2.0},
        "nonfinite_score": {"score": float("nan")},
        "empty_token_id": {"jti": ""},
    }[variant]
    case["guardian"]["claim_overrides"] = override
    runtime, twin, _, _ = harness(case, tmp_path)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "TOKEN_BINDING_INVALID"
    assert not twin.effects
    assert not any(call["name"] == "actuate" for call in twin.calls)

"""Partner contract regressions found during the handover audit."""
import copy
from datetime import timedelta

import pytest

from civis_brain.contracts import ReadingsBatch
from civis_brain.inputs.service import utc_time

from .test_member_integration import case_for, evaluate, harness


@pytest.mark.parametrize("domain", ["traffic", "water", "emergency"])
async def test_real_detectors_bound_untrusted_verdict_attempts(domain, tmp_path):
    case = case_for(domain)
    case["guardian"]["score"] = 0
    runtime, twin, guardian, provider = harness(case, tmp_path)
    await evaluate(case, runtime, twin)
    last = copy.deepcopy(case["batches"][-1])
    for _ in range(4):
        last["tick"] += 1
        last["time"] = (utc_time(last["time"]) + timedelta(
            seconds=last["tick_seconds"])).isoformat().replace("+00:00","Z")
        for row in last["readings"]:
            row.update(tick=last["tick"], timestamp=last["time"],
                       reading_id=row["reading_id"]+"-next")
        twin.advance(last)
        result = await runtime.evaluate_tick(ReadingsBatch.model_validate(last))
    assert result.decisions[0].peer_code == "TRUST_RETRIES_EXHAUSTED"
    assert sum(row["name"] == "fixture_score" for row in guardian.calls) == 3
    assert not provider.calls and not twin.effects


@pytest.mark.parametrize("row", [None, "not-an-object", [], 1,
                                 {"reading_id": [], "score": 95},
                                 {"reading_id": "", "score": 95}])
async def test_malformed_guardian_row_returns_blocked_without_exception(row, tmp_path):
    case = case_for("emergency")
    runtime, twin, guardian, _ = harness(case, tmp_path)
    original = guardian.call_tool

    async def verdict(name, args):
        if name == "fixture_score":
            return {"scores": [row]}
        return await original(name, args)
    guardian.call_tool = verdict
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "PEER_SCHEMA_INVALID"
    assert not twin.effects


async def test_pending_confirmation_checks_clock_again(tmp_path):
    case = case_for("emergency")
    case["twin_outcome"] = {"status": "pending", "commit_available": True}
    runtime, twin, guardian, provider = harness(case, tmp_path)
    first = (await evaluate(case, runtime, twin))[-1]
    assert first.decisions[0].status == "pending"
    raw = copy.deepcopy(case["batches"][-1])
    raw["tick"] += 1
    raw["time"] = (utc_time(raw["time"]) + timedelta(seconds=raw["tick_seconds"])).isoformat().replace("+00:00","Z")
    for row in raw["readings"]:
        row.update(tick=raw["tick"],timestamp=raw["time"],reading_id=row["reading_id"]+"-next")
    provider.case["ai_plan"]["proposals"][0]["source_reading_ids"] = [r["reading_id"] for r in raw["readings"]]
    original = provider.generate

    async def advance_during_planning(context):
        plan = await original(context)
        twin.clock["tick"] += 1
        return plan
    provider.generate = advance_during_planning
    twin.advance(raw)
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(raw))
    assert result.decisions[0].peer_code == "CLOCK_CHANGED"
    assert not twin.effects
    assert not any(call["name"] == "fixture_commit" for call in twin.calls)


async def test_lost_pending_confirmation_retains_pending_and_same_key(tmp_path):
    from .helpers import harness as core_harness
    from .helpers import make_case, next_batch
    case = make_case()
    case["twin_outcome"] = {"status": "pending", "commit_available": True}
    runtime, twin, _, provider = core_harness(case, tmp_path)
    await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    original = twin.call_tool
    lost_once = True

    async def lose_confirmation(name, args):
        nonlocal lost_once
        result = await original(name, args)
        if name == "fixture_commit" and lost_once:
            lost_once = False
            raise TimeoutError
        return result
    twin.call_tool = lose_confirmation
    result = await runtime.evaluate_tick(next_batch(case, twin, provider))
    assert result.decisions[0].status == "pending"
    assert len(twin.effects) == 1
    result = await runtime.evaluate_tick(next_batch(case, twin, provider, 3))
    assert result.decisions[0].status == "committed"
    assert len(twin.effects) == 1
    calls = [c for c in twin.calls if c["name"] in {"actuate","fixture_commit"}]
    assert len({c["arguments"]["idempotency_key"] for c in calls}) == 1


async def test_boolean_is_not_equivalent_to_integer_in_guardian_approval(tmp_path):
    case = case_for("emergency")
    params = copy.deepcopy(case["ai_plan"]["proposals"][0]["params"])
    params["units"] = True
    case["guardian"]["claim_overrides"] = {"params": params}
    runtime, twin, _, _ = harness(case, tmp_path)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "TOKEN_BINDING_INVALID"
    assert not twin.effects

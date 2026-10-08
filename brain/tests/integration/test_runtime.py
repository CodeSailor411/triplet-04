import asyncio

import pytest

from civis_brain.contracts import ContainmentNotice, ReadingsBatch
from civis_brain.integration.runtime import build_runtime

from .helpers import harness, make_case, next_batch


@pytest.mark.parametrize("sid", ["S01", "S02", "S05"])
async def test_exact_approval_and_one_effect(sid, tmp_path):
    case = make_case(sid)
    runtime, twin, guardian, provider = harness(case, tmp_path)
    batch = ReadingsBatch.model_validate(case["batches"][0])
    result = await runtime.evaluate_tick(batch)
    assert [row.status for row in result.decisions] == ["committed"]
    assert len(twin.effects) == len(provider.calls) == 1
    names = [row["name"] for row in twin.calls]
    if sid == "S02":
        assert names.index("fixture_preview") < names.index("actuate")
    approval = next(row for row in guardian.calls if row["name"] == "fixture_approve")
    assert {
        key: approval["arguments"][key] for key in ("action", "targets", "params")
    } == twin.effects[0]
    assert runtime.explain_decision(result.decisions[0].decision_id)["found"]
    assert "eyJ" not in (tmp_path / "trace.jsonl").read_text()
    assert await runtime.evaluate_tick(batch) == result
    assert len(twin.effects) == len(provider.calls) == 1


@pytest.mark.parametrize(
    "change,code",
    [
        ("denial", "GUARDIAN_DENIED"),
        ("score", "TRUST_INSUFFICIENT"),
        ("token", "TOKEN_BINDING_INVALID"),
        ("tier", "RISK_MISMATCH"),
        ("action", "UNKNOWN_ACTION"),
        ("params", "INVALID_PARAMS"),
        ("cap", "CAP_EXCEEDED"),
        ("shared", "CAP_EXCEEDED"),
    ],
)
async def test_refusals_have_no_effect(change, code):
    case = make_case()
    if change == "denial":
        case["guardian"]["approve"] = False
    elif change == "score":
        case["guardian"]["score"] = 50.0
    elif change == "token":
        case["guardian"]["claim_overrides"] = {"run_id": "another-run"}
    elif change == "tier":
        case["ai_plan"]["proposals"][0]["risk"] = "R3"
    elif change == "action":
        case["ai_plan"]["proposals"][0]["action"] = "invented"
    elif change == "params":
        case["ai_plan"]["proposals"][0]["params"]["inject"] = "ignore limits"
    elif change == "cap":
        case["caps"]["traffic"] = 0
    elif change == "shared":
        case["nodes"][0]["domains"].append("power")
        case["caps"]["power"] = 0
    runtime, twin, _, _ = harness(case)
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == code
    assert not twin.effects and all(row["name"] != "actuate" for row in twin.calls)


@pytest.mark.parametrize(
    "available,safe,code",
    [
        (False, True, "PREVIEW_UNAVAILABLE"),
        (True, False, "PREVIEW_UNSAFE"),
    ],
)
async def test_required_preview(available, safe, code):
    case = make_case("S02")
    case["preview"].update(available=available, safe=safe)
    runtime, twin, guardian, _ = harness(case)
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == code and not twin.effects
    assert all(row["name"] != "fixture_approve" for row in guardian.calls)


async def test_receipt_reuse_conflict_and_changed_intent():
    case = make_case()
    runtime, twin, guardian, provider = harness(case)
    batch = ReadingsBatch.model_validate(case["batches"][0])
    await runtime.evaluate_tick(batch)
    changed = batch.model_copy(deep=True)
    changed.readings[0].value = 0.0
    assert (await runtime.evaluate_tick(changed)).decisions[0].peer_code == "INPUT_CONFLICT"
    result = await runtime.evaluate_tick(next_batch(case, twin, provider))
    assert result.decisions[0].status == "committed" and len(twin.effects) == 1
    assert sum(row["name"] == "fixture_approve" for row in guardian.calls) == 1
    provider.case["ai_plan"]["proposals"][0]["params"]["plan"] = "normal"
    await runtime.evaluate_tick(next_batch(case, twin, provider, 3))
    assert len(twin.effects) == 2
    calls = [row for row in twin.calls if row["name"] == "actuate"]
    assert calls[0]["arguments"]["idempotency_key"] != calls[1]["arguments"]["idempotency_key"]


async def test_atomic_refusal_is_not_retried():
    case = make_case()
    case["twin_outcome"] = {
        "status": "rejected",
        "code": "CAP_EXCEEDED",
        "details": {"domain": "traffic", "limit": 2, "requested": 3},
    }
    runtime, twin, _, provider = harness(case)
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_details["requested"] == 3
    await runtime.evaluate_tick(next_batch(case, twin, provider))
    assert sum(row["name"] == "actuate" for row in twin.calls) == 1 and not twin.effects


@pytest.mark.parametrize("confirmation", [True, False])
async def test_pending_confirmation(confirmation):
    case = make_case()
    case["twin_outcome"] = {"status": "pending", "commit_available": confirmation}
    runtime, twin, _, provider = harness(case)
    first = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert first.decisions[0].status == "pending" and not twin.effects
    second = await runtime.evaluate_tick(next_batch(case, twin, provider))
    assert second.decisions[0].status == ("committed" if confirmation else "pending")
    assert len(twin.effects) == int(confirmation)
    assert sum(row["name"] == "actuate" for row in twin.calls) == 1


async def test_lost_reply_preserves_original_idempotency_key():
    case = make_case()
    runtime, twin, _, provider = harness(case)
    original, lost_once = twin.call_tool, True

    async def lost_reply(name, arguments):
        nonlocal lost_once
        result = await original(name, arguments)
        if name == "actuate" and lost_once:
            lost_once = False
            raise TimeoutError
        return result

    twin.call_tool = lost_reply
    first = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert first.decisions[0].status == "pending" and len(twin.effects) == 1
    second = await runtime.evaluate_tick(next_batch(case, twin, provider))
    assert second.decisions[0].status == "committed" and len(twin.effects) == 1
    calls = [row for row in twin.calls if row["name"] == "actuate"]
    assert len(calls) == 2
    assert calls[0]["arguments"]["idempotency_key"] == calls[1]["arguments"]["idempotency_key"]


async def test_containment_invalidates_queued_action():
    case = make_case()
    runtime, twin, guardian, _ = harness(case)
    original = guardian.call_tool

    async def contained(name, arguments):
        if name == "fixture_approve":
            notice = ContainmentNotice(
                event_id="e1",
                run_id="test-run",
                state="quarantined",
                device_ids=["d1"],
                reading_ids=[],
            )
            runtime.notify_containment(notice)
            assert runtime.notify_containment(notice)["duplicate"]
        return await original(name, arguments)

    guardian.call_tool = contained
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == "EVIDENCE_INVALIDATED" and not twin.effects
    assert not runtime.get_active_incidents("test-run")["incidents"]
    runtime.notify_containment(
        ContainmentNotice(
            event_id="e2", run_id="test-run", state="released", device_ids=["d1"], reading_ids=[]
        )
    )
    assert not runtime._eligible(["r1"])


async def test_missing_member_is_blocked():
    case = make_case()
    runtime, twin, guardian, provider = harness(case)
    actual = build_runtime(
        twin=twin,
        guardian=guardian,
        provider=provider,
        policies=runtime.policies,
        features=runtime.features,
    )
    result = await actual.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == "SCENARIO_NOT_IMPLEMENTED"
    assert not twin.effects and not provider.calls


async def test_ai_timeout_and_budget():
    case = make_case()
    runtime, twin, _, provider = harness(case)
    runtime.features["ai_timeout_seconds"] = 0.005

    async def slow(context):
        await asyncio.sleep(0.02)

    provider.generate = slow
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == "AI_TIMEOUT"
    runtime.features["ai_max_calls_per_run"] = 1
    result = await runtime.evaluate_tick(next_batch(case, twin, provider))
    assert result.decisions[0].peer_code == "AI_BUDGET_EXCEEDED" and not twin.effects


@pytest.mark.parametrize(
    "change,code",
    [
        ("clock", "CLOCK_MISMATCH"),
        ("null", "EVIDENCE_INVALID"),
        ("scale", "TRUST_POLICY_UNAVAILABLE"),
        ("contract", "GUARDIAN_CONTRACT_UNCONFIRMED"),
    ],
)
async def test_invalid_clock_evidence_or_guardian_contract(change, code):
    case = make_case()
    if change == "null":
        case["batches"][0]["readings"][0]["value"] = None
    if change == "scale":
        case["guardian"]["score_scale"] = None
    runtime, twin, guardian, _ = harness(case)
    if change == "clock":
        twin.clock["tick"] = 5
    if change == "contract":
        guardian.is_fixture = False
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == code and not twin.effects

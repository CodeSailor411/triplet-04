import copy
import json

import pytest

from civis_brain.contracts import ReadingsBatch
from civis_brain.errors import BrainError
from civis_brain.integration.journal import Journal

from .helpers import harness, make_case, next_batch


@pytest.mark.parametrize(
    "override",
    [
        {"exp": 1},
        {"iat": 5},
        {"targets": ["invented"]},
        {"params": {"plan": "normal"}},
        {"score": 0.0},
        {"score_scale": 1.0},
    ],
)
async def test_exact_token_binding(override):
    case = make_case()
    case["guardian"]["claim_overrides"] = override
    runtime, twin, _, _ = harness(case)
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == "TOKEN_BINDING_INVALID" and not twin.effects


async def test_approval_without_token_is_blocked():
    case = make_case()
    runtime, twin, guardian, _ = harness(case)
    original = guardian.call_tool

    async def missing(name, arguments):
        if name == "fixture_approve":
            return {"approved": True}
        return await original(name, arguments)

    guardian.call_tool = missing
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == "TOKEN_MISSING" and not twin.effects


async def test_risk_floor_and_shared_domain_missing_cap_are_blocked():
    for change, code in [("risk_floor", "TRUST_INSUFFICIENT"), ("shared", "CAP_UNAVAILABLE")]:
        case = make_case("S02")
        if change == "risk_floor":
            case["guardian"]["score"] = 85.0  # Reading cutoff passes, R3 does not.
        else:
            case["nodes"][0]["domains"].append("power")
        runtime, twin, _, _ = harness(case)
        result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
        assert result.decisions[0].peer_code == code and not twin.effects


async def test_bad_provider_is_blocked_without_secret():
    case = make_case()
    runtime, twin, _, provider = harness(case)

    async def broken(context):
        raise RuntimeError("PRIVATE_KEY_VALUE")

    provider.generate = broken
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == "AI_UNAVAILABLE"
    assert "PRIVATE_KEY_VALUE" not in str(result) and not twin.effects


async def test_three_low_trust_attempts_are_distinct_ticks():
    case = make_case()
    case["guardian"]["score"] = 50.0
    runtime, twin, guardian, provider = harness(case)
    batch = ReadingsBatch.model_validate(case["batches"][0])
    for tick in range(1, 5):
        if tick > 1:
            batch = next_batch(case, twin, provider, tick)
        result = await runtime.evaluate_tick(batch)
        replay = await runtime.evaluate_tick(batch)
        assert replay == result
    assert result.decisions[0].peer_code == "TRUST_RETRIES_EXHAUSTED"
    assert sum(row["name"] == "fixture_score" for row in guardian.calls) == 3
    assert not twin.effects and not provider.calls


async def test_invalid_new_run_does_not_erase_receipts():
    case = make_case()
    runtime, twin, _, _ = harness(case)
    batch = ReadingsBatch.model_validate(case["batches"][0])
    result = await runtime.evaluate_tick(batch)
    altered = batch.model_copy(deep=True)
    altered.run_id = "invented-run"
    altered.readings[0].run_id = "invented-run"
    refused = await runtime.evaluate_tick(altered)
    assert refused.decisions[0].peer_code == "CLOCK_MISMATCH"
    assert runtime.run_id == batch.run_id
    assert await runtime.evaluate_tick(batch) == result and len(twin.effects) == 1


async def test_fake_twin_rejects_changed_command_for_used_idempotency_key():
    case = make_case()
    runtime, twin, _, _ = harness(case)
    await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    original = copy.deepcopy(
        next(row["arguments"] for row in twin.calls if row["name"] == "actuate")
    )
    original["params"]["plan"] = "normal"
    with pytest.raises(BrainError) as error:
        await twin.call_tool("actuate", original)
    assert error.value.code == "IDEMPOTENCY_CONFLICT" and len(twin.effects) == 1


def test_redaction_handles_nested_secrets_and_bearer_tokens(tmp_path):
    journal = Journal(tmp_path / "trace.jsonl")
    journal.remember_secret("PRIVATE_KEY_VALUE")
    journal.append(
        {
            "token": "opaque",
            "nested": {"api_key": "raw"},
            "reason": "PRIVATE_KEY_VALUE Bearer xyz.abc.def",
        }
    )
    result = json.loads((tmp_path / "trace.jsonl").read_text())
    assert "opaque" not in str(result) and "raw" not in str(result)
    assert "PRIVATE_KEY_VALUE" not in str(result) and "xyz.abc.def" not in str(result)


async def test_scenario_cannot_mutate_the_manifest_used_for_final_validation():
    case = make_case()
    case["ai_plan"]["proposals"][0]["params"]["plan"] = "invented"
    runtime, twin, _, provider = harness(case)

    async def mutated_context(context, plan_provider):
        context.actions[0].params[0]["choices"].append("invented")
        return await plan_provider.generate(context)

    runtime.scenarios[0].draft_plan = mutated_context
    result = await runtime.evaluate_tick(ReadingsBatch.model_validate(case["batches"][0]))
    assert result.decisions[0].peer_code == "INVALID_PARAMS" and not twin.effects

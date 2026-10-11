"""S02 workflow proof through the real shared core. Fixture peers, no network or key."""

import json
from pathlib import Path

import pytest
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.contracts import ReadingsBatch
from civis_brain.integration.runtime import build_runtime

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "mocks" / "cases" / "water"


def load_case(variant):
    return json.loads((CASES / f"{variant}_case.json").read_text(encoding="utf-8"))


def count(calls, name):
    return sum(1 for row in calls if row["name"] == name)


async def run_case(case, tmp_path):
    twin = FixtureTwin(case)
    guardian = FixtureGuardian(case)
    provider = FixturePlanProvider(case)
    runtime = build_runtime(
        twin=twin,
        guardian=guardian,
        provider=provider,
        policies={"S02": case["policy"]},
        features={
            "enabled_scenario_ids": ["S02"],
            "guardian_score_tool": "fixture_score",
            "guardian_token_tool": "fixture_approve",
            "preview_tool": "fixture_preview",
            "commit_tool": "fixture_commit",
            "ai_max_calls_per_run": 10,
        },
        artifact_dir=tmp_path,
    )
    results = []
    for raw in case["batches"]:
        batch = ReadingsBatch.model_validate(raw)
        twin.advance(batch)
        results.append(await runtime.evaluate_tick(batch))
    return results, twin, guardian, provider


async def test_base_case_commits_exactly_one_valve_change(tmp_path):
    case = load_case("base")
    expected = case["expected"]
    results, twin, guardian, provider = await run_case(case, tmp_path)
    decisions = results[-1].decisions
    assert len(decisions) == 1
    assert decisions[0].status == expected["decision_status"]
    assert decisions[0].source_reading_ids == expected["source_reading_ids"]
    assert len(provider.calls) == expected["provider_calls"]
    assert count(guardian.calls, "fixture_approve") == 1
    assert count(twin.calls, "actuate") == expected["actuate_calls"]
    assert len(twin.effects) == expected["effects"]
    assert twin.effects[0] == {
        "action": expected["action"],
        "targets": expected["targets"],
        "params": expected["params"],
    }
    trace = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert "eyJ" not in trace  # no approval token text in the audit trace


async def test_refusal_case_blocks_before_actuation(tmp_path):
    case = load_case("refusal")
    expected = case["expected"]
    results, twin, guardian, provider = await run_case(case, tmp_path)
    decisions = results[-1].decisions
    assert len(decisions) == 1
    assert decisions[0].status == expected["decision_status"]
    assert expected["reason_contains"] in decisions[0].model_dump_json().lower()
    assert len(provider.calls) == expected["provider_calls"]
    assert count(twin.calls, "actuate") == expected["actuate_calls"]
    assert len(twin.effects) == expected["effects"]


async def test_missing_preview_blocks(tmp_path):
    case = load_case("base")
    case["preview"]["available"] = False
    results, twin, guardian, provider = await run_case(case, tmp_path)
    decisions = results[-1].decisions
    assert len(decisions) == 1 and decisions[0].status == "blocked"
    assert count(twin.calls, "actuate") == 0
    assert not twin.effects


async def test_missing_exact_approval_blocks(tmp_path):
    case = load_case("base")
    case["guardian"]["approve"] = False
    results, twin, guardian, provider = await run_case(case, tmp_path)
    decisions = results[-1].decisions
    assert len(decisions) == 1 and decisions[0].status == "blocked"
    assert count(twin.calls, "actuate") == 0
    assert not twin.effects


async def test_one_high_tick_is_not_enough(tmp_path):
    case = load_case("base")
    case["batches"] = case["batches"][:1]
    results, twin, guardian, provider = await run_case(case, tmp_path)
    assert provider.calls == []
    assert count(twin.calls, "actuate") == 0
    assert not twin.effects


async def test_normal_water_does_nothing(tmp_path):
    case = load_case("base")
    for raw in case["batches"]:
        for reading in raw["readings"]:
            reading["value"] = 50.0
    results, twin, guardian, provider = await run_case(case, tmp_path)
    assert provider.calls == []
    assert count(twin.calls, "actuate") == 0
    assert not twin.effects


@pytest.mark.parametrize(
    "change",
    [
        {"source_reading_ids": ["fake-1"]},
        {"targets": ["valve-99"]},
        {"params": {"position_pct": 90}},
    ],
)
async def test_unsupported_ai_proposal_never_reaches_twin(change, tmp_path):
    case = load_case("base")
    case["ai_plan"]["proposals"][0].update(change)
    results, twin, guardian, provider = await run_case(case, tmp_path)
    committed = case["expected"]["decision_status"]
    assert all(row.status != committed for row in results[-1].decisions)
    assert count(guardian.calls, "fixture_approve") == 0
    assert count(twin.calls, "actuate") == 0
    assert not twin.effects

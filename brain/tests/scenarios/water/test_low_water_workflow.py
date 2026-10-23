"""S07 workflow proof through the shared core. Fixture peers, no network or key."""

import json
from pathlib import Path

import pytest
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.contracts import ReadingsBatch
from civis_brain.integration.runtime import build_runtime
from civis_brain.scenarios.registry import IMPLEMENTED_SCENARIOS

pytestmark = pytest.mark.skipif(
    "S07" not in IMPLEMENTED_SCENARIOS, reason="S07 not registered yet (Elyes owns registry)"
)
CASES = Path(__file__).resolve().parents[3] / "mocks" / "cases" / "water"


def load_case(name):
    return json.loads((CASES / f"{name}_case.json").read_text(encoding="utf-8"))


def count(calls, name):
    return sum(1 for row in calls if row["name"] == name)


async def run_case(case, tmp_path):
    twin, guardian, provider = FixtureTwin(case), FixtureGuardian(case), FixturePlanProvider(case)
    runtime = build_runtime(
        twin=twin, guardian=guardian, provider=provider,
        policies={"S07": case["policy"]},
        features={
            "enabled_scenario_ids": ["S07"],
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


async def test_low_base_commits_exactly_one_valve_change(tmp_path):
    case = load_case("low_base")
    exp = case["expected"]
    results, twin, guardian, provider = await run_case(case, tmp_path)
    decisions = results[-1].decisions
    assert len(decisions) == 1 and decisions[0].status == exp["decision_status"]
    assert decisions[0].source_reading_ids == exp["source_reading_ids"]
    assert len(provider.calls) == exp["provider_calls"]
    assert count(guardian.calls, "fixture_approve") == 1
    assert count(twin.calls, "actuate") == exp["actuate_calls"]
    assert twin.effects == [{"action": exp["action"], "targets": exp["targets"],
                             "params": exp["params"]}]


async def test_low_refusal_unsafe_preview_blocks(tmp_path):
    # Reuse the S02 refusal fixture's unsafe-preview shape and expectations.
    refusal = load_case("refusal")
    case = load_case("low_base")
    case["preview"] = refusal["preview"]
    exp = refusal["expected"]
    results, twin, guardian, provider = await run_case(case, tmp_path)
    decisions = results[-1].decisions
    assert len(decisions) == 1 and decisions[0].status == exp["decision_status"]
    assert exp["reason_contains"] in decisions[0].model_dump_json().lower()
    assert count(twin.calls, "actuate") == exp["actuate_calls"] and not twin.effects


async def test_missing_topology_means_no_valve_change(tmp_path):
    case = load_case("low_base")
    case["policy"]["safe_valve_choices"] = []
    results, twin, guardian, provider = await run_case(case, tmp_path)
    assert provider.calls == [] and count(twin.calls, "actuate") == 0 and not twin.effects


async def test_missing_preview_blocks(tmp_path):
    case = load_case("low_base")
    case["preview"]["available"] = False
    results, twin, guardian, provider = await run_case(case, tmp_path)
    assert results[-1].decisions[0].status == "blocked"
    assert count(twin.calls, "actuate") == 0 and not twin.effects


async def test_guardian_denial_blocks(tmp_path):
    case = load_case("low_base")
    case["guardian"]["approve"] = False
    results, twin, guardian, provider = await run_case(case, tmp_path)
    assert results[-1].decisions[0].status == "blocked"
    assert count(twin.calls, "actuate") == 0 and not twin.effects


async def test_normal_water_does_nothing(tmp_path):
    case = load_case("low_base")
    for raw in case["batches"]:
        raw["readings"][0]["value"] = 60.0
    results, twin, guardian, provider = await run_case(case, tmp_path)
    assert provider.calls == [] and count(twin.calls, "actuate") == 0


@pytest.mark.parametrize(
    "change",
    [
        {"source_reading_ids": ["fake-1"]},
        {"targets": ["valve-99"]},
        {"params": {"position": 30}},  # S02's value must not pass in S07
    ],
)
async def test_unsupported_ai_proposal_never_reaches_twin(change, tmp_path):
    case = load_case("low_base")
    case["ai_plan"]["proposals"][0].update(change)
    results, twin, guardian, provider = await run_case(case, tmp_path)
    assert all(r.status != "committed" for r in results[-1].decisions)
    assert count(guardian.calls, "fixture_approve") == 0 and not twin.effects
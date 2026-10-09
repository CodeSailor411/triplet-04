import json
from pathlib import Path

import pytest
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.contracts import Decision, ReadingsBatch
from civis_brain.integration.runtime import build_runtime
from tests.scenarios.emergency.helpers import load_case

BRAIN_DIRECTORY = Path(__file__).resolve().parents[3]
POLICY_DIRECTORY = BRAIN_DIRECTORY / "config" / "scenarios"
POLICY_FILES = {
    "S01": "traffic.json",
    "S02": "water.json",
    "S03": "power.json",
    "S04": "air_quality.json",
    "S05": "emergency.json",
}
FEATURES = {
    "enabled_scenario_ids": ["S05"],
    "guardian_score_tool": "fixture_score",
    "guardian_token_tool": "fixture_approve",
    "preview_tool": None,
    "commit_tool": None,
}


def _all_policies() -> dict[str, dict]:
    return {
        scenario_id: json.loads(
            (POLICY_DIRECTORY / filename).read_text(encoding="utf-8")
        )
        for scenario_id, filename in POLICY_FILES.items()
    }


def _count_tool_calls(peer, tool_name: str) -> int:
    return sum(call["name"] == tool_name for call in peer.calls)


def _count_dispatch_requests(twin: FixtureTwin) -> int:
    return sum(
        call["arguments"].get("action") == "dispatch"
        for call in twin.calls
    )


@pytest.mark.parametrize(
    ("case_filename", "case_id"),
    [
        ("base_case.json", "base-dispatch"),
        ("refusal_case.json", "exact-approval-refusal"),
    ],
    ids=lambda value: value if value.endswith(".json") else None,
)
@pytest.mark.asyncio
async def test_s05_base_and_refusal_workflows_match_decision_and_peer_effects(
    case_filename, case_id, tmp_path
):
    case = load_case(case_filename)
    twin = FixtureTwin(case)
    guardian = FixtureGuardian(case)
    provider = FixturePlanProvider(case)
    runtime = build_runtime(
        twin=twin,
        guardian=guardian,
        provider=provider,
        policies=_all_policies(),
        features=FEATURES,
        artifact_dir=tmp_path / case_id,
    )

    batch = ReadingsBatch.model_validate(case["batches"][0])
    result = await runtime.evaluate_tick(batch)

    assert result.run_id == batch.run_id
    assert result.tick == batch.tick
    assert len(result.decisions) == 1
    assert result.decisions == [Decision.model_validate(case["expected"]["decision"])]
    assert result.decisions[0].source_reading_ids == case["expected"]["decision"][
        "source_reading_ids"
    ]

    expected_counts = case["expected"]["call_counts"]
    assert _count_tool_calls(guardian, "fixture_score") == expected_counts[
        "guardian.fixture_score"
    ]
    assert _count_tool_calls(guardian, "fixture_approve") == expected_counts[
        "guardian.fixture_approve"
    ]
    assert len(provider.calls) == expected_counts["provider.generate"]
    assert _count_dispatch_requests(twin) == expected_counts["twin.actuation_request"]
    assert len(twin.effects) == case["expected"]["actuator_effect_count"]
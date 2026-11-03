import json
from pathlib import Path

import pytest
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.contracts import ReadingsBatch
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
    twin.advance(batch)
    result = await runtime.evaluate_tick(batch)

    assert result.run_id == batch.run_id
    assert result.tick == batch.tick
    assert len(result.decisions) == 1
    expected = case["expected"]
    decision = result.decisions[0]
    assert decision.decision_id
    assert decision.status == expected["final_statuses"][0]
    assert decision.peer_code == expected["peer_code"]
    for field in ("action", "targets", "params", "source_reading_ids"):
        assert getattr(decision, field) == expected[field]
    assert runtime.explain_decision(decision.decision_id)["found"]
    assert _count_tool_calls(guardian, "fixture_score") == 1
    assert _count_tool_calls(guardian, "fixture_approve") == 1
    assert len(provider.calls) == expected["provider_calls"]
    assert _count_dispatch_requests(twin) == expected["actuate_calls"]
    assert len(twin.effects) == expected["effects"]
    if twin.effects:
        assert twin.effects == [{field: expected[field] for field in ("action", "targets", "params")}]
    assert "eyJ" not in (tmp_path / case_id / "trace.jsonl").read_text(encoding="utf-8")

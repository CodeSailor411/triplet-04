"""The real shared runtime enforces the explicit virtual Water command scope."""

import copy
import json

import pytest

from .test_member_integration import ROOT, case_for, evaluate, harness


def scoped_case():
    case = case_for("water")
    override = json.loads((ROOT / "config/integration/twin-mock-3.json").read_text())["S02"]
    case["policy"].update(override)
    case["nodes"] = [{
        "node_id": "WAT-01", "domains": ["water"], "role": "standard",
        "actuators": ["set_valve_position"], "neighbours": [],
        "sensors": [{"name": "water_level", "unit": "cm"}],
    }]
    case["actions"][0]["target_nodes"] = ["WAT-01"]
    for batch in case["batches"]:
        for row in batch["readings"]:
            row["node_id"] = "WAT-01"
    case["ai_plan"]["proposals"][0].update(targets=["WAT-01"], params={"position": 40})
    return case


def set_discovered_seed(twin, seed):
    original = twin.call_tool

    async def discover(name, arguments):
        result = await original(name, arguments)
        return {**result, "seed": seed} if name == "list_nodes" else result

    twin.call_tool = discover


@pytest.mark.parametrize(("seed", "mock_profile", "code"), [
    (7, True, "TOPOLOGY_MISMATCH"),
    (None, True, "TOPOLOGY_MISMATCH"),
    (42, False, "MOCK_POLICY_REQUIRED"),
])
async def test_runtime_rejects_scoped_policy_before_ai_or_authorization(seed, mock_profile, code, tmp_path):
    case = scoped_case()
    runtime, twin, guardian, provider = harness(case, tmp_path)
    runtime.features["mock_integration_profile"] = mock_profile
    set_discovered_seed(twin, seed)
    results = await evaluate(case, runtime, twin)
    assert all(result.decisions[0].peer_code == code for result in results)
    assert not provider.calls
    assert not guardian.calls
    assert not twin.effects
    assert not any(call["name"] == "actuate" for call in twin.calls)


async def test_valid_scoped_policy_commits_only_the_exact_virtual_command(tmp_path):
    case = scoped_case()
    runtime, twin, _, provider = harness(case, tmp_path)
    runtime.features["mock_integration_profile"] = True
    set_discovered_seed(twin, 42)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].status == "committed"
    assert len(provider.calls) == 1
    assert len(twin.effects) == 1
    assert twin.effects[0]["targets"] == ["WAT-01"]
    assert twin.effects[0]["params"] == {"position": 40.0}


async def test_current_manifest_change_blocks_before_ai(tmp_path):
    case = scoped_case()
    case["actions"][0]["params"][0]["max_value"] = 1
    runtime, twin, guardian, provider = harness(case, tmp_path)
    runtime.features["mock_integration_profile"] = True
    set_discovered_seed(twin, 42)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "INVALID_PARAMS"
    assert not provider.calls and not guardian.calls and not twin.effects


async def test_water_scope_failure_does_not_block_other_scenarios(tmp_path):
    case = scoped_case()
    air = case_for("air_quality")
    case["nodes"].extend(air["nodes"])
    for index, batch in enumerate(case["batches"]):
        reading = copy.deepcopy(air["batches"][index]["readings"][0])
        reading.update(run_id=batch["run_id"], tick=batch["tick"], timestamp=batch["time"])
        batch["readings"].append(reading)
        batch["count"] = len(batch["readings"])
    runtime, twin, _, provider = harness(case, tmp_path)
    runtime.enabled.add("S04")
    runtime.policies["S04"] = air["policy"]
    runtime.features["mock_integration_profile"] = True
    set_discovered_seed(twin, 7)
    result = (await evaluate(case, runtime, twin))[-1]
    assert any(row.status == "blocked" and row.peer_code == "TOPOLOGY_MISMATCH"
               for row in result.decisions)
    assert any(row.status == "alert" and row.source_reading_ids
               and all(source.startswith("AQ-01-") for source in row.source_reading_ids)
               for row in result.decisions)
    assert not provider.calls and not twin.effects

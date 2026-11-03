"""Regression and combined-runtime checks from the independent member review."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin, decode_claims

from civis_brain.contracts import Plan, ReadingsBatch
from civis_brain.debug_runs import DebugRunRequest, run_debug_case
from civis_brain.integration.runtime import build_runtime
from civis_brain.planning.gemini import GeminiPlanProvider
from civis_brain.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def case_for(domain, variant="base"):
    return json.loads((ROOT / f"mocks/cases/{domain}/{variant}_case.json").read_text(encoding="utf-8"))


def harness(case, tmp_path):
    twin, guardian, provider = FixtureTwin(case), FixtureGuardian(case), FixturePlanProvider(case)
    runtime = build_runtime(
        twin=twin, guardian=guardian, provider=provider,
        policies={case["scenario_id"]: case["policy"]},
        features={"enabled_scenario_ids": [case["scenario_id"]],
                  "guardian_score_tool": "fixture_score", "guardian_token_tool": "fixture_approve",
                  "preview_tool": "fixture_preview", "commit_tool": "fixture_commit",
                  "ai_max_calls_per_run": 10},
        artifact_dir=tmp_path,
    )
    return runtime, twin, guardian, provider


async def evaluate(case, runtime, twin):
    results = []
    for raw in case["batches"]:
        batch = ReadingsBatch.model_validate(raw)
        twin.advance(batch)
        results.append(await runtime.evaluate_tick(batch))
    return results


@pytest.mark.parametrize("domain,index,change", [
    ("water", 0, {"channel": "flow"}),
    ("water", 0, {"unit": "m"}),
    ("water", 0, {"value": None}),
    ("emergency", 0, {"unit": "calls"}),
    ("emergency", 0, {"channel": "fire"}),
    ("emergency", 1, {"channel": None}),
    ("emergency", 1, {"channel": "police"}),
    ("emergency", 1, {"value": 1.5}),
    ("emergency", 1, {"value": -1}),
    ("emergency", 1, {"value": None}),
    ("emergency", 1, {"value": 0}),
    ("emergency", 1, {"unit": "vehicles"}),
])
async def test_wrong_units_channels_or_missing_evidence_never_actuate(domain, index, change, tmp_path):
    case = case_for(domain)
    for batch in case["batches"]:
        batch["readings"][index].update(change)
    runtime, twin, _, provider = harness(case, tmp_path)
    await evaluate(case, runtime, twin)
    assert not provider.calls
    assert not twin.effects
    assert not any(row["name"] == "actuate" for row in twin.calls)


@pytest.mark.parametrize("domain", ["traffic", "water", "emergency"])
@pytest.mark.parametrize("change", ["missing_evidence", "bool_param", "duplicate_target", "unknown_param"])
async def test_bad_provider_proposals_do_not_reach_approval(domain, change, tmp_path):
    case = case_for(domain)
    plan = case["ai_plan"]["proposals"][0]
    if change == "missing_evidence":
        plan["source_reading_ids"] = plan["source_reading_ids"][:1]
    elif change == "bool_param":
        plan["params"][{"traffic": "plan", "water": "position", "emergency": "units"}[domain]] = True
    elif change == "duplicate_target":
        plan["targets"] *= 2
    else:
        plan["params"]["unadvertised"] = 1
    runtime, twin, guardian, _ = harness(case, tmp_path)
    await evaluate(case, runtime, twin)
    assert not twin.effects
    assert not any(row["name"] == "fixture_approve" for row in guardian.calls)


@pytest.mark.parametrize("domain", ["traffic", "water", "emergency"])
async def test_shared_carrier_needs_caps_in_both_domains(domain, tmp_path):
    case = case_for(domain)
    carrier = case["ai_plan"]["proposals"][0]["targets"][0]
    next(node for node in case["nodes"] if node["node_id"] == carrier)["domains"].append("power")
    case["caps"]["power"] = 0
    runtime, twin, guardian, _ = harness(case, tmp_path)
    results = await evaluate(case, runtime, twin)
    assert results[-1].decisions[0].peer_code == "CAP_EXCEEDED"
    assert not twin.effects
    assert not any(row["name"] == "fixture_approve" for row in guardian.calls)


@pytest.mark.parametrize("scenario,domain", [("S01", "traffic"), ("S02", "water"), ("S05", "emergency")])
async def test_member_through_real_gemini_adapter_with_recorded_http_result(scenario, domain):
    case = case_for(domain)
    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(case["ai_plan"]), status="completed")

    provider = GeminiPlanProvider("", "gemini-3.5-flash-lite",
        client=SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=create))))
    result = await run_debug_case(Settings(_env_file=None),
        DebugRunRequest(scenario=scenario, provider_mode="gemini"), live_provider=provider)
    assert result["acceptance"]["passed"] is True
    assert result["effects"] == 1
    assert len(requests) == 1
    payload = json.loads(requests[0]["input"])
    assert {r["reading_id"] for r in payload["selected_evidence"]} == set(
        case["expected"]["source_reading_ids"])
    assert len(json.dumps(requests[0]["response_format"]["schema"])) > 100


async def test_second_carrier_and_other_unit_channels_do_not_break_dispatch(tmp_path):
    case = case_for("emergency")
    carrier = copy.deepcopy(case["nodes"][1])
    carrier["node_id"] = "EMG-CARRIER-02"
    case["nodes"].append(carrier)
    case["actions"][0]["target_nodes"].append(carrier["node_id"])
    extra = copy.deepcopy(case["batches"][0]["readings"][1])
    extra.update(node_id=carrier["node_id"], device_id="EMG-CARRIER-02.units_free",
                 reading_id="carrier-02", value=2.0)
    police = copy.deepcopy(extra)
    police.update(channel="police", reading_id="police-02")
    case["batches"][0]["readings"] += [extra, police]
    case["batches"][0]["count"] = 4
    case["ai_plan"]["proposals"][0]["source_reading_ids"].append("carrier-02")
    runtime, twin, _, _ = harness(case, tmp_path)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].status == "committed"
    assert len(twin.effects) == 1
    assert "police-02" not in result.decisions[0].source_reading_ids


@pytest.mark.parametrize("moment", ["before_detection", "during_approval"])
async def test_containment_poll_blocks_selected_evidence(moment, tmp_path):
    case = case_for("emergency")
    held = {"device_id": case["batches"][0]["readings"][0]["device_id"], "state": "quarantined"}
    runtime, twin, guardian, _ = harness(case, tmp_path)
    if moment == "before_detection":
        twin.case["contained_devices"] = [held]
    else:
        original = guardian.call_tool

        async def call(name, arguments):
            result = await original(name, arguments)
            if name == "fixture_approve":
                twin.case["contained_devices"] = [held]
            return result

        guardian.call_tool = call
    await evaluate(case, runtime, twin)
    assert not twin.effects
    assert not any(row["name"] == "actuate" for row in twin.calls)
    assert any(row["name"] == "get_containment_state" for row in twin.calls)


async def test_token_lifetime_is_sixty_simulated_seconds_and_logs_link_action(tmp_path):
    case = case_for("emergency")
    case["batches"][0]["tick_seconds"] = 7.5
    runtime, twin, guardian, _ = harness(case, tmp_path)
    original = guardian.call_tool
    claims = []

    async def call(name, arguments):
        result = await original(name, arguments)
        if name == "fixture_approve":
            claims.append(decode_claims(result["token"]))
        return result

    guardian.call_tool = call
    result = (await evaluate(case, runtime, twin))[-1]
    from civis_brain.inputs.service import utc_time
    assert (utc_time(claims[0]["exp"]) - utc_time(claims[0]["iat"])).total_seconds() == 60
    assert claims[0]["score"] == .95
    assert result.decisions[0].status == "committed"
    rows = [json.loads(line) for line in
            (tmp_path / "run-logs/fixture-s05-base.brain.jsonl").read_text().splitlines()]
    decision = next(row for row in rows if row["event_type"] == "decision")
    action = next(row for row in twin.calls if row["name"] == "actuate")
    assert decision["data"]["idempotency_key"] == action["arguments"]["idempotency_key"]
    assert decision["caused_by"] == case["expected"]["source_reading_ids"]
    assert {"event_id", "timestamp", "wall", "layer", "tick", "run_id"} <= decision.keys()
    assert "eyJ" not in json.dumps(rows)


@pytest.mark.parametrize("override", [
    {"exp": "2026-10-09T09:00:00Z"},
    {"iat": "2026-10-09T09:00:01Z"},
    {"exp": "2026-10-09T09:01:01Z"},
    {"exp": 200},
])
async def test_expired_future_or_wrong_clock_tokens_fail(override, tmp_path):
    case = case_for("emergency")
    case["guardian"]["claim_overrides"] = override
    runtime, twin, _, _ = harness(case, tmp_path)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "TOKEN_BINDING_INVALID"
    assert not twin.effects


async def test_all_five_delivered_modules_share_one_runtime_without_cross_scenario_actions(tmp_path):
    cases = [case_for(domain) for domain in ("water", "emergency", "power", "air_quality", "traffic")]
    joint = copy.deepcopy(cases[0])
    joint["nodes"] = [node for case in cases for node in case["nodes"]]
    joint["actions"] = [action for case in cases for action in case["actions"]]
    joint["caps"] = {key: value for case in cases for key, value in case["caps"].items()}
    joint["batches"] = []
    for tick in (1, 2):
        readings = []
        for case in cases:
            raw = copy.deepcopy(case["batches"][min(tick-1, len(case["batches"])-1)]["readings"])
            for row in raw:
                row.update(run_id="combined-five", tick=tick, timestamp=f"2026-10-11T08:00:0{tick}Z",
                           reading_id=f"{case['scenario_id']}-{tick}-{row['reading_id']}")
            readings += raw
        joint["batches"].append(dict(run_id="combined-five", tick=tick,
            time=f"2026-10-11T08:00:0{tick}Z", tick_seconds=1.0, count=len(readings), readings=readings))

    class ScopedProvider:
        def __init__(self):
            self.contexts = []

        async def generate(self, context):
            self.contexts.append(context)
            action = context.actions[0].action
            source = next(c for c in cases if c["actions"] and c["actions"][0]["action"] == action)
            plan = copy.deepcopy(source["ai_plan"])
            for proposal in plan["proposals"]:
                proposal["source_reading_ids"] = context.incidents[0].source_reading_ids
            return Plan.model_validate(plan)

    twin, guardian, provider = FixtureTwin(joint), FixtureGuardian(joint), ScopedProvider()
    runtime = build_runtime(twin=twin, guardian=guardian, provider=provider,
        policies={case["scenario_id"]: case["policy"] for case in cases},
        features={"guardian_score_tool": "fixture_score", "guardian_token_tool": "fixture_approve",
                  "preview_tool": "fixture_preview", "ai_max_calls_per_run": 10},
        artifact_dir=tmp_path)
    results = await evaluate(joint, runtime, twin)
    assert len(twin.effects) == 3
    assert {effect["action"] for effect in twin.effects} == {"dispatch", "set_valve_position", "set_signal_plan"}
    assert {row["scenario_id"] for row in runtime.journal.events if row["event"] == "decision"} == {
        "S01", "S02", "S03", "S04", "S05"}
    for context in provider.contexts:
        assert len(context.actions) == 1
        assert len({incident.kind for incident in context.incidents}) == 1
    before = len(provider.contexts), len(twin.calls)
    repeated = await runtime.evaluate_tick(ReadingsBatch.model_validate(joint["batches"][-1]))
    assert repeated == results[-1]
    assert (len(provider.contexts), len(twin.calls)) == before
    assert len(twin.effects) == 3


@pytest.mark.parametrize("domain", ["traffic", "water", "emergency"])
async def test_twin_refusal_is_not_repeated_on_later_evidence(domain, tmp_path):
    case = case_for(domain)
    case["twin_outcome"] = {"status": "rejected", "code": "DEVICE_QUARANTINED"}
    runtime, twin, guardian, provider = harness(case, tmp_path)
    first = (await evaluate(case, runtime, twin))[-1]
    raw = copy.deepcopy(case["batches"][-1])
    from datetime import timedelta

    from civis_brain.inputs.service import utc_time
    raw["tick"] += 1
    raw["time"] = (utc_time(raw["time"]) + timedelta(seconds=raw["tick_seconds"])).isoformat().replace("+00:00", "Z")
    for row in raw["readings"]:
        row.update(reading_id=row["reading_id"]+"-next", tick=raw["tick"], timestamp=raw["time"])
    # Refresh only the recorded evidence, not the command; the idempotency key must stay fixed.
    ids = [row["reading_id"] for row in raw["readings"]]
    if domain in {"water", "traffic"}:
        ids.insert(0, case["batches"][-1]["readings"][0]["reading_id"])
    provider.case["ai_plan"]["proposals"][0]["source_reading_ids"] = ids
    twin.advance(raw)
    second = await runtime.evaluate_tick(ReadingsBatch.model_validate(raw))
    assert first.decisions[0].status == second.decisions[0].status == "rejected"
    assert first.decisions[0].peer_code == second.decisions[0].peer_code == "DEVICE_QUARANTINED"
    assert sum(row["name"] == "actuate" for row in twin.calls) == 1
    assert sum(row["name"] == "fixture_approve" for row in guardian.calls) == 1
    assert not twin.effects


async def test_log_disk_failure_does_not_change_committed_outcome(tmp_path, monkeypatch):
    case = case_for("emergency")
    runtime, twin, _, _ = harness(case, tmp_path)

    def full_disk(event):
        raise OSError("synthetic disk full")
    monkeypatch.setattr(runtime.journal, "_write_part", full_disk)
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].status == "committed" and len(twin.effects) == 1
    assert runtime.journal.write_error["code"] == "LOG_WRITE_FAILED"
    assert any(row["event"] == "log_failure" for row in runtime.journal.events)


def test_emergency_history_is_bounded_and_stale_tick_cannot_restart_it():
    from civis_brain.contracts import Node
    from civis_brain.scenarios.emergency.service import EmergencyScenario
    case = case_for("emergency")
    policy = {**case["policy"], "persistence_ticks": 2}
    detector, state = EmergencyScenario(), {}
    nodes = [Node.model_validate(row) for row in case["nodes"]]
    first = ReadingsBatch.model_validate(case["batches"][0])
    for tick in range(1, 40):
        rows = [r.model_copy(update={"tick": tick, "reading_id": f"{r.reading_id}-{tick}"})
                for r in first.readings]
        detector.detect(first.model_copy(update={"tick": tick, "readings": rows}), nodes, policy, state)
    history = state["_s05_events_by_node"]["EMG-INCIDENT-01"]
    assert history["streak"] == 2
    assert len(history["reading_ids"]) == 2
    before = copy.deepcopy(state)
    assert detector.detect(first, nodes, policy, state).incidents == []
    assert state == before


@pytest.mark.parametrize("domain", ["traffic", "water", "emergency"])
@pytest.mark.parametrize("change", ["count", "duplicate_id", "nan", "wrong_run", "wrong_tick"])
async def test_malformed_batches_cannot_execute(domain, change, tmp_path):
    case = case_for(domain)
    raw = case["batches"][-1]
    if change == "count":
        raw["count"] += 1
    elif change == "duplicate_id":
        raw["readings"].append(copy.deepcopy(raw["readings"][0]))
        raw["count"] += 1
    elif change == "nan":
        raw["readings"][0]["value"] = float("nan")
    elif change == "wrong_run":
        raw["readings"][0]["run_id"] = "another-run"
    else:
        raw["readings"][0]["tick"] += 1
    runtime, twin, _, _ = harness(case, tmp_path)
    if change == "nan":
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            await evaluate(case, runtime, twin)
    else:
        result = (await evaluate(case, runtime, twin))[-1]
        assert result.decisions[-1].peer_code == "INPUT_INVALID"
    assert not twin.effects


def test_future_gps_fields_do_not_break_batch_validation():
    from civis_brain.contracts import Node
    from civis_brain.inputs.service import normalize_batch
    case = case_for("emergency")
    for row in case["batches"][0]["readings"]:
        row.update(lat=36.12345, lon=10.12345, extra_future_metadata="test")
    raw = case["batches"][0]
    batch = ReadingsBatch.model_validate(raw)
    normalize_batch(batch, [Node.model_validate(row) for row in case["nodes"]])
    assert batch.readings[0].reading_id == raw["readings"][0]["reading_id"]
    assert batch.readings[0].value == raw["readings"][0]["value"]


async def test_clock_change_during_approval_cannot_execute(tmp_path):
    case = case_for("emergency")
    runtime, twin, guardian, _ = harness(case, tmp_path)
    original = guardian.call_tool

    async def call(name, arguments):
        response = await original(name, arguments)
        if name == "fixture_approve":
            twin.clock["tick"] += 1
        return response
    guardian.call_tool = call
    result = (await evaluate(case, runtime, twin))[-1]
    assert result.decisions[0].peer_code == "CLOCK_MISMATCH"
    assert not twin.effects

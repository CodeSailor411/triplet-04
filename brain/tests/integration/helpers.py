"""Synthetic candidates exercise the real shared core, not member detector acceptance."""

import copy

from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.contracts import DetectionResult, Incident, Observation, ReadingsBatch
from civis_brain.integration.runtime import BrainRuntime


def make_case(sid="S01"):
    domain, sensor, unit, kind, action, risk, params = {
        "S01": (
            "traffic",
            "congestion_index",
            "percent",
            "congestion",
            "set_signal_plan",
            "R1",
            {"plan": "priority"},
        ),
        "S02": (
            "water",
            "water_level",
            "cm",
            "flood",
            "set_valve_position",
            "R3",
            {"position": 0.5},
        ),
        "S05": (
            "emergency",
            "emergency_calls",
            "calls/min",
            "medical",
            "dispatch",
            "R2",
            {"unit_type": "ambulance", "destination": "N1", "units": 1},
        ),
    }[sid]
    row = {
        "run_id": "test-run",
        "reading_id": "r1",
        "tick": 1,
        "timestamp": "2026-10-08T08:00:01.000Z",
        "node_id": "N1",
        "device_id": "d1",
        "sensor": sensor,
        "channel": "medical" if sid == "S05" else None,
        "value": 90.0,
        "unit": unit,
    }
    readings = [row]
    target = "N2" if sid == "S05" else "N1"
    specs = [{"name": "plan", "type": "choice", "choices": ["priority", "normal"]}]
    if sid == "S02":
        specs = [{"name": "position", "type": "number", "min_value": 0.0, "max_value": 1.0}]
    if sid == "S05":
        specs = [
            {"name": "unit_type", "type": "choice", "choices": ["ambulance"]},
            {"name": "destination", "type": "node"},
            {"name": "units", "type": "integer", "min_value": 1, "max_value": 1},
        ]
        readings.append(
            {
                **row,
                "reading_id": "availability-1",
                "node_id": "N2",
                "device_id": "d2",
                "sensor": "units_free",
                "channel": "ambulance",
                "value": 2.0,
                "unit": "units",
            }
        )
    case = {
        "scenario_id": sid,
        "kind": kind,
        "fixture_only": True,
        "nodes": [
            {
                "node_id": "N1",
                "domains": [domain],
                "role": "fixture",
                "actuators": [action] if sid != "S05" else [],
                "neighbours": [],
            }
        ],
        "actions": [
            {
                "action": action,
                "domain": domain,
                "risk": risk,
                "preview_required": sid == "S02",
                "params": specs,
                "target_nodes": [target],
                "action_cap": 2,
            }
        ],
        "batches": [
            {
                "run_id": "test-run",
                "tick": 1,
                "time": row["timestamp"],
                "tick_seconds": 1.0,
                "count": len(readings),
                "readings": readings,
            }
        ],
        "policy": {"fixture_only": True},
        "guardian": {
            "score": 95.0,
            "score_scale": 100.0,
            "thresholds": {"reading": 60.0, "R1": 65.0, "R2": 80.0, "R3": 90.0},
            "approve": True,
            "token_lifetime_ticks": 3,
        },
        "preview": {"available": True, "safe": True, "reason": "Synthetic test"},
        "ai_plan": {
            "proposals": [
                {
                    "action": action,
                    "targets": [target],
                    "params": params,
                    "risk": risk,
                    "preview_required": sid == "S02",
                    "source_reading_ids": [row["reading_id"] for row in readings],
                    "reason": "Synthetic candidate",
                }
            ],
            "alerts": [],
        },
        "twin_outcome": {"status": "committed"},
        "caps": {domain: 2},
    }
    if sid == "S02":
        case["policy"]["safe_valve_choices"] = [
            {"incident_node_id": "N1", "targets": ["N1"], "params": params.copy()}
        ]
    if sid == "S05":
        case["nodes"].append(
            {
                "node_id": "N2",
                "domains": [domain],
                "role": "carrier",
                "actuators": [action],
                "neighbours": [],
            }
        )
    return case


class SyntheticCandidate:
    def __init__(self, case):
        self.case, self.scenario_id = case, case["scenario_id"]

    def detect(self, batch, nodes, policy, state):
        return DetectionResult(
            observations=[
                Observation(reading=row, domains=nodes[0].domains, usable=row.value is not None)
                for row in batch.readings
            ],
            incidents=[
                Incident(
                    incident_id="synthetic-incident",
                    kind=self.case["kind"],
                    run_id=batch.run_id,
                    domains=nodes[0].domains,
                    node_ids=["N1"],
                    source_reading_ids=[row.reading_id for row in batch.readings],
                    facts={"supported_valve_actions": policy.get("safe_valve_choices", [])},
                )
            ],
        )

    async def draft_plan(self, context, provider):
        return await provider.generate(context)


def harness(case, artifact_dir=None):
    twin, guardian, provider = FixtureTwin(case), FixtureGuardian(case), FixturePlanProvider(case)
    runtime = BrainRuntime(
        twin=twin,
        guardian=guardian,
        provider=provider,
        policies={case["scenario_id"]: case["policy"]},
        features={
            "enabled_scenario_ids": [case["scenario_id"]],
            "guardian_score_tool": "fixture_score",
            "guardian_token_tool": "fixture_approve",
            "preview_tool": "fixture_preview",
            "commit_tool": "fixture_commit",
            "peer_timeout_seconds": 0.1,
            "ai_max_calls_per_run": 10,
        },
        scenarios=(SyntheticCandidate(case),),
        artifact_dir=artifact_dir,
    )
    return runtime, twin, guardian, provider


def next_batch(case, twin, provider, tick=2):
    raw = copy.deepcopy(case["batches"][0])
    raw.update(tick=tick, time=f"2026-10-08T08:00:{tick:02d}.000Z")
    for row in raw["readings"]:
        row.update(tick=tick, timestamp=raw["time"], reading_id=row["device_id"] + f"-{tick}")
    provider.case["ai_plan"]["proposals"][0]["source_reading_ids"] = [
        row["reading_id"] for row in raw["readings"]
    ]
    batch = ReadingsBatch.model_validate(raw)
    twin.advance(batch)
    return batch

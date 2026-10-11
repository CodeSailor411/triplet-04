"""Small fake provider and builders for water tests. Fixture-only values."""

from civis_brain.contracts import (
    ActionInfo,
    ActionProposal,
    Incident,
    Node,
    Plan,
    PlanningContext,
    Reading,
    ReadingsBatch,
)

CHOICE = {
    "incident_node_id": "tank-01",
    "targets": ["valve-01"],
    "params": {"position_pct": 30},
}
EVIDENCE_IDS = ["w-run-1-10", "w-run-1-11"]


class FakeProvider:
    """Records calls and returns a recorded Plan. No network, no key."""

    def __init__(self, plan: Plan):
        self.plan = plan
        self.calls = 0

    async def generate(self, context: PlanningContext) -> Plan:
        self.calls += 1
        return self.plan


def make_proposal(**overrides) -> ActionProposal:
    data = {
        "action": "set_valve_position",
        "targets": ["valve-01"],
        "params": {"position_pct": 30},
        "risk": "R3",
        "preview_required": True,
        "source_reading_ids": list(EVIDENCE_IDS),
        "reason": "Mock threshold exceeded on two ticks; supplied safe valve choice.",
    }
    data.update(overrides)
    return ActionProposal(**data)


def make_action_info(**overrides) -> ActionInfo:
    data = {
        "action": "set_valve_position",
        "domain": "water",
        "risk": "R3",
        "preview_required": True,
        "params": [
            {"name": "position_pct", "type": "number", "choices": None,
             "min_value": 0, "max_value": 100, "unit": "percent"}
        ],
        "target_nodes": ["valve-01"],
        "action_cap": 1,
    }
    data.update(overrides)
    return ActionInfo(**data)


def make_incident(choices=None) -> Incident:
    return Incident(
        incident_id="flood:run-1:tank-01",
        kind="flood",
        run_id="run-1",
        domains=["water"],
        node_ids=["tank-01"],
        source_reading_ids=list(EVIDENCE_IDS),
        facts={
            "mock_only": True,
            "supported_valve_actions": [CHOICE] if choices is None else choices,
        },
    )


def make_context(incidents=None, actions=None) -> PlanningContext:
    reading = Reading(
        run_id="run-1", reading_id="w-run-1-11", tick=11,
        timestamp="2026-10-08T10:11:00Z", node_id="tank-01", device_id="lvl-01",
        sensor="water_level", channel=None, value=178.0, unit="cm",
    )
    batch = ReadingsBatch(
        run_id="run-1", tick=11, time=reading.timestamp,
        tick_seconds=60.0, count=1, readings=[reading],
    )
    return PlanningContext(
        batch=batch,
        incidents=[make_incident()] if incidents is None else incidents,
        nodes=[Node(node_id="tank-01", domains=["water"], role="tank")],
        actions=[make_action_info()] if actions is None else actions,
        evidence_readings=[reading],
    )
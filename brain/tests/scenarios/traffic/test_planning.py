
import asyncio

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
from civis_brain.scenarios.traffic.service import TrafficScenario


def make_reading(tick: int) -> Reading:
    return Reading(
        run_id="run-1",
        reading_id=f"reading-{tick}",
        tick=tick,
        timestamp=f"2026-10-09T20:0{tick}:00Z",
        node_id="traffic-1",
        device_id="device-1",
        sensor="congestion_index",
        channel=None,
        value=90.0,
        unit="percent",
    )


def make_context(include_incident: bool = True) -> PlanningContext:
    previous = make_reading(1)
    current = make_reading(2)

    incidents = []
    if include_incident:
        incidents.append(
            Incident(
                incident_id="incident-1",
                kind="congestion",
                run_id="run-1",
                domains=["traffic"],
                node_ids=["traffic-1"],
                source_reading_ids=["reading-1", "reading-2"],
                facts={"sensor": "congestion_index"},
            )
        )

    return PlanningContext(
        batch=ReadingsBatch(
            run_id="run-1",
            tick=2,
            time=current.timestamp,
            tick_seconds=1.0,
            count=1,
            readings=[current],
        ),
        incidents=incidents,
        nodes=[
            Node(
                node_id="traffic-1",
                domains=["traffic"],
                role="sensor",
                actuators=["signal"],
            )
        ],
        actions=[
            ActionInfo(
                action="set_signal_plan",
                domain="traffic",
                risk="R1",
                preview_required=True,
                params=[
                    {
                        "name": "plan_id",
                        "type": "string",
                        "choices": ["plan-a", "plan-b"],
                    }
                ],
                target_nodes=["traffic-1"],
                action_cap=1,
            )
        ],
        evidence_readings=[previous],
    )


class RecordedProvider:
    def __init__(self, plan: Plan):
        self.plan = plan
        self.calls = 0
        self.received_context = None

    async def generate(self, context: PlanningContext) -> Plan:
        self.calls += 1
        self.received_context = context
        return self.plan


def valid_plan() -> Plan:
    return Plan(
        proposals=[
            ActionProposal(
                action="set_signal_plan",
                targets=["traffic-1"],
                params={"plan_id": "plan-a"},
                risk="R1",
                preview_required=True,
                source_reading_ids=["reading-1", "reading-2"],
                reason="Apply an advertised traffic signal plan.",
            )
        ],
        alerts=[],
    )


def test_supported_candidate_calls_provider_once_with_restricted_context():
    provider = RecordedProvider(valid_plan())
    context = make_context()

    result = asyncio.run(
        TrafficScenario().draft_plan(context, provider)
    )

    assert provider.calls == 1
    assert len(result.proposals) == 1
    assert provider.received_context is not None
    assert len(provider.received_context.incidents) == 1
    assert [
        action.action for action in provider.received_context.actions
    ] == ["set_signal_plan"]
    assert provider.received_context.evidence_readings[0].reading_id == "reading-1"


def test_no_incident_does_not_call_provider():
    provider = RecordedProvider(valid_plan())
    context = make_context(include_incident=False)

    result = asyncio.run(
        TrafficScenario().draft_plan(context, provider)
    )

    assert result.proposals == []
    assert provider.calls == 0


def test_unknown_action_parameter_is_rejected():
    bad_plan = Plan(
        proposals=[
            ActionProposal(
                action="set_signal_plan",
                targets=["traffic-1"],
                params={"invented_parameter": "anything"},
                risk="R1",
                preview_required=True,
                source_reading_ids=["reading-1", "reading-2"],
                reason="Apply a signal plan.",
            )
        ],
        alerts=[],
    )
    provider = RecordedProvider(bad_plan)

    result = asyncio.run(
        TrafficScenario().draft_plan(make_context(), provider)
    )

    assert provider.calls == 1
    assert result.proposals == []
    assert "Rejected unsupported proposal." in result.alerts
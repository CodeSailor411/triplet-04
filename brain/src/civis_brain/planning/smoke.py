"""Synthetic context for AI-only smoke; never executes a response."""

from civis_brain.contracts import (
    ActionInfo,
    Incident,
    Node,
    PlanningContext,
    Reading,
    ReadingsBatch,
)


def synthetic_context():
    reading = Reading(
        run_id="synthetic-ai-smoke",
        reading_id="synthetic-r1",
        tick=1,
        timestamp="2026-10-08T08:00:01Z",
        node_id="SYNTHETIC-01",
        device_id="synthetic-device",
        sensor="congestion_index",
        channel=None,
        value=95.0,
        unit="percent",
    )
    batch = ReadingsBatch(
        run_id=reading.run_id,
        tick=1,
        time=reading.timestamp,
        tick_seconds=1.0,
        count=1,
        readings=[reading],
    )
    context = PlanningContext(
        batch=batch,
        evidence_readings=[reading],
        incidents=[
            Incident(
                incident_id="synthetic-candidate",
                kind="congestion",
                run_id=reading.run_id,
                domains=["traffic"],
                node_ids=[reading.node_id],
                source_reading_ids=[reading.reading_id],
                facts={"fixture_only": True},
            )
        ],
        nodes=[
            Node(
                node_id=reading.node_id,
                domains=["traffic"],
                role="fixture",
                actuators=["set_signal_plan"],
            )
        ],
        actions=[
            ActionInfo(
                action="set_signal_plan",
                domain="traffic",
                risk="R1",
                preview_required=False,
                target_nodes=[reading.node_id],
                action_cap=1,
                params=[{"name": "plan", "type": "choice", "choices": ["mock_priority"]}],
            )
        ],
    )
    return context

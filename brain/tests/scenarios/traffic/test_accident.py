from types import SimpleNamespace

import pytest

from civis_brain.contracts import Node, Reading, ReadingsBatch
from civis_brain.scenarios.traffic.accident import RoadAccidentScenario


def make_batch(readings, run_id="run-1", tick=1):
    return ReadingsBatch(run_id=run_id, tick=tick, time="2026-10-24T12:00:00Z", tick_seconds=1.0, count=len(readings), readings=readings)


def make_reading(
    reading_id="report-001",
    sensor="road_accident_report",
    value=1,
    unit="report",
    run_id="run-1",
    tick=1,
    channel=None,
):
    return Reading(
        run_id=run_id,
        reading_id=reading_id,
        tick=tick,
        timestamp="2026-10-24T12:00:00Z",
        node_id="TRAFFIC-01",
        device_id="device-01",
        sensor=sensor,
        channel=channel,
        value=value,
        unit=unit,
    )


def make_nodes():
    return [
        Node(
            node_id="TRAFFIC-01",
            domains=["traffic"],
            role="sensor",
            actuators=[],
            neighbours=[],
            lat=None,
            lon=None,
        )
    ]


def test_explicit_report_creates_road_accident_incident():
    scenario = RoadAccidentScenario()
    batch = make_batch([make_reading()])

    result = scenario.detect(batch, make_nodes(), {}, {})

    assert len(result.incidents) == 1
    incident = result.incidents[0]
    assert incident.kind == "road_accident"
    assert incident.source_reading_ids == ["report-001"]
    assert incident.facts["injury_status"] == "unknown"
    assert incident.facts["dispatch_authorized"] is False


def test_low_speed_alone_does_not_create_accident():
    scenario = RoadAccidentScenario()
    batch = make_batch(
        [make_reading(sensor="avg_speed", value=5.0, unit="km/h")]
    )

    result = scenario.detect(batch, make_nodes(), {}, {})

    assert result.incidents == []


def test_mismatched_run_or_tick_is_rejected():
    scenario = RoadAccidentScenario()
    batch = make_batch(
        [make_reading(run_id="another-run", tick=2)]
    )

    result = scenario.detect(batch, make_nodes(), {}, {})

    assert result.incidents == []
    assert result.observations[0].usable is False



def test_duplicate_report_across_ticks_does_not_create_second_incident():
    scenario = RoadAccidentScenario()
    state = {}
    nodes = make_nodes()

    first = scenario.detect(
        make_batch([make_reading(reading_id="report-001", tick=1)], tick=1),
        nodes,
        {},
        state,
    )
    second = scenario.detect(
        make_batch([make_reading(reading_id="report-001", tick=2)], tick=2),
        nodes,
        {},
        state,
    )

    assert len(first.incidents) == 1
    assert second.incidents == []


def test_unknown_injury_status_does_not_authorize_ambulance():
    scenario = RoadAccidentScenario()
    result = scenario.detect(
        make_batch([make_reading(reading_id="report-unknown-injury")]),
        make_nodes(),
        {},
        {},
    )

    assert len(result.incidents) == 1
    incident = result.incidents[0]
    assert incident.facts["injury_status"] == "unknown"
    assert incident.facts["dispatch_authorized"] is False



@pytest.mark.asyncio
async def test_draft_plan_never_dispatches_without_reviewed_action():
    scenario = RoadAccidentScenario()
    incident = scenario.detect(
        make_batch([make_reading()]),
        make_nodes(),
        {},
        {},
    ).incidents[0]

    context = SimpleNamespace(incidents=[incident])

    class ProviderMustNotBeCalled:
        async def generate(self, context):
            pytest.fail("S06 must not call the provider without a reviewed action")

    plan = await scenario.draft_plan(context, ProviderMustNotBeCalled())

    assert plan.proposals == []
    assert any("no reviewed road-accident dispatch action" in alert for alert in plan.alerts)


@pytest.mark.asyncio
async def test_draft_plan_without_incident_does_not_propose_dispatch():
    scenario = RoadAccidentScenario()
    context = SimpleNamespace(incidents=[])

    class ProviderMustNotBeCalled:
        async def generate(self, context):
            pytest.fail("S06 must not call the provider without an incident")

    plan = await scenario.draft_plan(context, ProviderMustNotBeCalled())

    assert plan.proposals == []
    assert plan.alerts == []

def test_wrong_report_unit_is_rejected():
    scenario = RoadAccidentScenario()
    reading = make_reading(unit="km/h")

    result = scenario.detect(
        make_batch([reading]), make_nodes(), {}, {}
    )

    assert result.incidents == []
    assert result.observations[0].usable is False
    assert result.observations[0].reason == "unsupported_report_unit"


def test_unsupported_report_channel_is_rejected():
    scenario = RoadAccidentScenario()
    reading = make_reading(channel="speed")

    result = scenario.detect(
        make_batch([reading]), make_nodes(), {}, {}
    )

    assert result.incidents == []
    assert result.observations[0].usable is False
    assert result.observations[0].reason == "unsupported_report_channel"

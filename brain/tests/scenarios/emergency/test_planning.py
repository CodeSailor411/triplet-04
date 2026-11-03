import pytest

from civis_brain.contracts import PlanningContext
from civis_brain.scenarios.emergency.service import EmergencyScenario
from tests.scenarios.emergency.helpers import (
    RecordedPlanProvider,
    load_actions,
    load_batches,
    load_case,
    load_nodes,
)


@pytest.fixture
def base_case():
    return load_case("base_case.json")


def _planning_context(case, *, batch=None, actions=None):
    batch = load_batches(case)[0] if batch is None else batch
    nodes = load_nodes(case)
    detection = EmergencyScenario().detect(batch, nodes, case["policy"], {})
    return PlanningContext(
        batch=batch,
        incidents=detection.incidents,
        nodes=nodes,
        actions=load_actions(case) if actions is None else actions,
        evidence_readings=batch.readings,
    )


@pytest.mark.asyncio
async def test_empty_context_returns_empty_plan_without_provider_call(base_case):
    context = _planning_context(base_case).model_copy(update={"incidents": []})
    provider = RecordedPlanProvider(base_case)

    plan = await EmergencyScenario().draft_plan(context, provider)

    assert plan.proposals == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_supported_dispatch_calls_provider_once_and_returns_evidence_bound_plan(base_case):
    context = _planning_context(base_case)
    provider = RecordedPlanProvider(base_case)

    plan = await EmergencyScenario().draft_plan(context, provider)

    assert provider.calls == [context]
    assert len(plan.proposals) == 1
    proposal = plan.proposals[0]
    assert proposal.action == "dispatch"
    assert proposal.targets == ["EMG-CARRIER-01"]
    assert proposal.params == {
        "unit_type": "ambulance",
        "destination": "EMG-INCIDENT-01",
        "units": 1,
    }
    assert proposal.targets[0] != proposal.params["destination"]
    assert proposal.risk == "R2"
    assert proposal.source_reading_ids == ["s05-base-calls-01", "s05-base-units-01"]
    assert proposal.reason == (
        "Dispatch one available ambulance to the reported medical-event location "
        "using supplied evidence."
    )


@pytest.mark.asyncio
async def test_unavailable_ambulance_returns_no_action_without_provider_call(base_case):
    batch = load_batches(base_case)[0]
    readings = [
        reading.model_copy(update={"value": 0.0})
        if reading.sensor == "units_free"
        else reading
        for reading in batch.readings
    ]
    context = _planning_context(base_case, batch=batch.model_copy(update={"readings": readings}))
    provider = RecordedPlanProvider(base_case)

    plan = await EmergencyScenario().draft_plan(context, provider)

    assert len(context.incidents) == 1
    assert plan.proposals == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_unadvertised_carrier_returns_no_action_without_provider_call(base_case):
    action = load_actions(base_case)[0].model_copy(update={"target_nodes": []})
    context = _planning_context(base_case, actions=[action])
    provider = RecordedPlanProvider(base_case)

    plan = await EmergencyScenario().draft_plan(context, provider)

    assert plan.proposals == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_unresolved_incident_evidence_blocks_provider_call(base_case):
    context = _planning_context(base_case)
    incident = context.incidents[0].model_copy(
        update={"source_reading_ids": [*context.incidents[0].source_reading_ids, "missing-reading"]}
    )
    context = context.model_copy(update={"incidents": [incident]})
    provider = RecordedPlanProvider(base_case)

    plan = await EmergencyScenario().draft_plan(context, provider)

    assert plan.proposals == []
    assert provider.calls == []


@pytest.mark.parametrize(
    "proposal_updates",
    [
        pytest.param(
            {
                "params": {
                    "unit_type": "fire_engine",
                    "destination": "EMG-INCIDENT-01",
                    "units": 1,
                }
            },
            id="invalid-unit-type",
        ),
        pytest.param(
            {
                "params": {
                    "unit_type": "ambulance",
                    "destination": "EMG-INCIDENT-01",
                    "units": 2,
                }
            },
            id="invalid-unit-count",
        ),
        pytest.param(
            {"source_reading_ids": ["unknown-reading"]},
            id="unknown-evidence",
        ),
        pytest.param(
            {
                "params": {
                    "unit_type": "ambulance",
                    "destination": "EMG-CARRIER-01",
                    "units": 1,
                }
            },
            id="destination-is-carrier",
        ),
        pytest.param(
            {"action": "release_device"},
            id="containment-action",
        ),
    ],
)
@pytest.mark.asyncio
async def test_rejects_provider_proposals_outside_evidence_and_dispatch_manifest(
    base_case, proposal_updates
):
    context = _planning_context(base_case)
    provider = RecordedPlanProvider(base_case)
    original_proposal = provider.plan.proposals[0]
    provider.plan = provider.plan.model_copy(
        update={"proposals": [original_proposal.model_copy(update=proposal_updates)]}
    )

    plan = await EmergencyScenario().draft_plan(context, provider)

    assert provider.calls == [context]
    assert plan.proposals == []
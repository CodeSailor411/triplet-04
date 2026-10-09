"""Edge-case tests for the S02 constrained response (fake provider, no network)."""

import asyncio

import pytest
from pydantic import ValidationError

from civis_brain.contracts import ActionInfo, ActionProposal, Incident, Plan, PlanningContext
from civis_brain.scenarios.water.planner import plan_response, rejection_reason

CHOICE = {
    "incident_node_id": "tank-01",
    "targets": ["valve-01"],
    "params": {"position_pct": 30},
}


def make_info() -> ActionInfo:
    return ActionInfo.model_validate(
        {
            "action": "set_valve_position",
            "domain": "water",
            "risk": "R3",
            "preview_required": True,
            "params": [
                {
                    "name": "position_pct",
                    "type": "number",
                    "choices": None,
                    "min_value": 0,
                    "max_value": 100,
                    "unit": "percent",
                }
            ],
            "target_nodes": ["valve-01"],
            "action_cap": 1,
        }
    )


def make_incident(choices=None) -> Incident:
    return Incident.model_validate(
        {
            "incident_id": "flood:run-water-1:tank-01",
            "kind": "flood",
            "run_id": "run-water-1",
            "domains": ["water"],
            "node_ids": ["tank-01"],
            "source_reading_ids": ["w-r10", "w-r11"],
            "facts": {"supported_valve_actions": [CHOICE] if choices is None else choices},
        }
    )


def make_proposal(**changes) -> ActionProposal:
    data = {
        "action": "set_valve_position",
        "targets": ["valve-01"],
        "params": {"position_pct": 30},
        "risk": "R3",
        "preview_required": True,
        "source_reading_ids": ["w-r10", "w-r11"],
        "reason": "test",
    }
    data.update(changes)
    return ActionProposal.model_validate(data)


class FakeProvider:
    def __init__(self, proposals):
        self.proposals = proposals
        self.calls = 0

    async def generate(self, context):
        self.calls += 1
        return Plan(proposals=self.proposals, alerts=[])


def make_context(incidents) -> PlanningContext:
    return PlanningContext.model_construct(incidents=incidents, actions=[make_info()])


def run(context, provider):
    return asyncio.run(plan_response(context, provider))


# ---- rejection_reason ----

def test_exact_match_is_allowed():
    assert rejection_reason(make_proposal(), make_incident(), make_info(), [CHOICE]) is None


def test_empty_evidence_cannot_even_be_built():
    # The shared ActionProposal model forbids an empty evidence list.
    with pytest.raises(ValidationError):
        make_proposal(source_reading_ids=[])


def test_fabricated_evidence_is_rejected():
    reason = rejection_reason(
        make_proposal(source_reading_ids=["fake-1"]), make_incident(), make_info(), [CHOICE]
    )
    assert reason == "evidence ids not produced by the detector"


def test_unsupported_valve_target_is_rejected():
    reason = rejection_reason(
        make_proposal(targets=["valve-99"]), make_incident(), make_info(), [CHOICE]
    )
    assert reason == "targets or params are not a supported valve choice"


def test_wrong_param_value_is_rejected():
    reason = rejection_reason(
        make_proposal(params={"position_pct": 90}), make_incident(), make_info(), [CHOICE]
    )
    assert reason == "targets or params are not a supported valve choice"


def test_unknown_action_is_rejected():
    reason = rejection_reason(
        make_proposal(action="open_gate"), make_incident(), make_info(), [CHOICE]
    )
    assert reason == "unknown action open_gate"


# ---- plan_response ----

def test_no_incident_means_empty_plan_and_no_provider_call():
    provider = FakeProvider([make_proposal()])
    plan = run(make_context([]), provider)
    assert plan.proposals == []
    assert provider.calls == 0


def test_no_supported_valve_choice_is_alert_only_and_no_provider_call():
    provider = FakeProvider([make_proposal()])
    plan = run(make_context([make_incident(choices=[])]), provider)
    assert plan.proposals == []
    assert plan.alerts
    assert provider.calls == 0


def test_valid_proposal_is_kept_with_exactly_one_provider_call():
    provider = FakeProvider([make_proposal()])
    plan = run(make_context([make_incident()]), provider)
    assert len(plan.proposals) == 1
    assert plan.proposals[0].targets == ["valve-01"]
    assert provider.calls == 1


def test_bad_proposals_are_dropped_with_an_alert():
    provider = FakeProvider(
        [
            make_proposal(source_reading_ids=["fake-1"]),
            make_proposal(targets=["valve-99"]),
            make_proposal(params={"position_pct": 90}),
        ]
    )
    plan = run(make_context([make_incident()]), provider)
    assert plan.proposals == []
    assert len(plan.alerts) == 3
    assert provider.calls == 1
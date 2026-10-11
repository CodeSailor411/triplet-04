import asyncio
import importlib.util
from pathlib import Path

from civis_brain.contracts import Plan
from civis_brain.scenarios.water.service import WaterScenario

_spec = importlib.util.spec_from_file_location(
    "water_test_helpers", Path(__file__).with_name("helpers.py")
)
helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helpers)


def run(context, plan):
    provider = helpers.FakeProvider(plan)
    result = asyncio.run(WaterScenario().draft_plan(context, provider))
    return result, provider


def plan_of(*proposals):
    return Plan(proposals=list(proposals), alerts=[])


def test_no_incident_gives_empty_plan_without_provider_call():
    result, provider = run(
        helpers.make_context(incidents=[]), plan_of(helpers.make_proposal())
    )
    assert result.proposals == [] and result.alerts == []
    assert provider.calls == 0


def test_supported_incident_calls_provider_once_and_keeps_matching_proposal():
    result, provider = run(helpers.make_context(), plan_of(helpers.make_proposal()))
    assert provider.calls == 1
    assert len(result.proposals) == 1
    assert result.proposals[0].action == "set_valve_position"
    assert result.proposals[0].risk == "R3"
    assert result.proposals[0].preview_required is True


def test_no_supported_valve_choice_is_alert_only_without_provider_call():
    context = helpers.make_context(incidents=[helpers.make_incident(choices=[])])
    result, provider = run(context, plan_of(helpers.make_proposal()))
    assert result.proposals == []
    assert "no supported valve action" in result.alerts[0]
    assert provider.calls == 0


def test_action_missing_from_manifest_is_alert_only():
    result, provider = run(
        helpers.make_context(actions=[]), plan_of(helpers.make_proposal())
    )
    assert result.proposals == []
    assert result.alerts
    assert provider.calls == 0


def test_choice_outside_manifest_targets_is_not_actionable():
    info = helpers.make_action_info(target_nodes=["valve-99"])
    result, provider = run(
        helpers.make_context(actions=[info]), plan_of(helpers.make_proposal())
    )
    assert result.proposals == []
    assert provider.calls == 0


def test_unknown_action_is_dropped():
    proposal = helpers.make_proposal(action="close_gate")
    result, _ = run(helpers.make_context(), plan_of(proposal))
    assert result.proposals == []
    assert "unknown action" in result.alerts[0]


def test_unsupported_target_is_dropped():
    proposal = helpers.make_proposal(targets=["valve-77"])
    result, _ = run(helpers.make_context(), plan_of(proposal))
    assert result.proposals == []
    assert "not a supported valve choice" in result.alerts[0]


def test_changed_param_value_is_dropped():
    proposal = helpers.make_proposal(params={"position_pct": 90})
    result, _ = run(helpers.make_context(), plan_of(proposal))
    assert result.proposals == []


def test_fabricated_evidence_is_dropped():
    proposal = helpers.make_proposal(source_reading_ids=["w-made-up"])
    result, _ = run(helpers.make_context(), plan_of(proposal))
    assert result.proposals == []
    assert "evidence" in result.alerts[0]


def test_wrong_risk_or_preview_flag_is_dropped():
    result, _ = run(
        helpers.make_context(), plan_of(helpers.make_proposal(risk="R1"))
    )
    assert result.proposals == []
    result, _ = run(
        helpers.make_context(),
        plan_of(helpers.make_proposal(preview_required=False)),
    )
    assert result.proposals == []
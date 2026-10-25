"""S07 detector and planner unit tests. No peers, no network."""

import copy
import json
from pathlib import Path

import pytest

from civis_brain.contracts import (
    ActionInfo,
    ActionProposal,
    Incident,
    Node,
    Plan,
    PlanningContext,
    ReadingsBatch,
)
from civis_brain.scenarios.water.detector import detect_high_water
from civis_brain.scenarios.water.low_water import (
    LowWaterScenario,
    detect_low_water,
    pair_error,
    policy_error,
)

CASES = Path(__file__).resolve().parents[3] / "mocks" / "cases" / "water"
CASE = json.loads((CASES / "low_base_case.json").read_text(encoding="utf-8"))
HIGH = json.loads((CASES / "base_case.json").read_text(encoding="utf-8"))["policy"]
POLICY = CASE["policy"]
NODES = [Node.model_validate(n) for n in CASE["nodes"]] + [
    Node(node_id="road-01", domains=["traffic"], role="road")
]


def policy(**over):
    p = copy.deepcopy(POLICY)
    p.update(over)
    return p


def make_batch(tick, value, run="run-low-1", node="reservoir-01", unit="cm", channel=None):
    return ReadingsBatch.model_validate({
        "run_id": run, "tick": tick, "time": f"2026-10-08T10:{tick:02d}:00Z",
        "tick_seconds": 60.0, "count": 1,
        "readings": [{
            "run_id": run, "reading_id": f"r{tick}", "tick": tick,
            "timestamp": f"2026-10-08T10:{tick:02d}:00Z", "node_id": node,
            "device_id": "lvl-02", "sensor": "water_level", "channel": channel,
            "value": value, "unit": unit,
        }],
    })


def feed(values, pol=None, state=None, **kw):
    state = {} if state is None else state
    return [
        detect_low_water(make_batch(t, v, **kw), NODES, pol or POLICY, state)
        for t, v in values
    ]


def fired(results):
    return [bool(r.incidents) for r in results]


def test_below_threshold_needs_persistence():
    results = feed([(10, 20.0), (11, 19.0)])
    assert fired(results) == [False, True]
    inc = results[1].incidents[0]
    assert inc.kind == "low_water" and inc.source_reading_ids == ["r10", "r11"]
    assert inc.facts["datum"] == POLICY["datum"] and inc.facts["unit"] == "cm"


def test_equal_to_threshold_is_not_low():
    assert fired(feed([(10, 30.0), (11, 30.0), (12, 30.0)])) == [False] * 3


def test_above_threshold_is_not_low():
    assert fired(feed([(10, 31.0), (11, 60.0), (12, 150.0)])) == [False] * 3


@pytest.mark.parametrize(
    "kw",
    [
        {"unit": "m"},
        {"channel": "raw"},
        {"node": "road-01"},
        {"node": "reservoir-99"},
        {"node": "valve-02"},  # water node, but not a reviewed supply node
    ],
)
def test_unusable_readings_never_fire(kw):
    results = feed([(10, 5.0), (11, 5.0), (12, 5.0)], **kw)
    assert fired(results) == [False] * 3
    assert not results[-1].observations[0].usable


def test_null_value_is_unusable_not_zero():
    results = feed([(10, None), (11, None), (12, None)])
    assert fired(results) == [False] * 3
    assert results[-1].observations[0].reason == "null value"


def test_duplicate_ticks_do_not_extend_streak():
    assert fired(feed([(10, 20.0), (10, 20.0), (10, 20.0)])) == [False] * 3
    results = feed([(10, 20.0), (11, 20.0), (11, 20.0)])
    assert fired(results) == [False, True, False]


def test_gapped_tick_restarts_streak():
    results = feed([(10, 20.0), (12, 20.0), (13, 20.0)])
    assert fired(results) == [False, False, True]
    assert results[2].incidents[0].source_reading_ids == ["r12", "r13"]


def test_sustained_low_keeps_reporting_latest_evidence():
    results = feed([(10, 20.0), (11, 20.0), (12, 20.0)])
    assert fired(results) == [False, True, True]
    assert results[2].incidents[0].source_reading_ids == ["r11", "r12"]


def test_recovery_rearms():
    results = feed([(10, 20.0), (11, 20.0), (12, 50.0), (13, 20.0), (14, 20.0)])
    assert fired(results) == [False, True, False, False, True]


def test_dead_band_does_not_rearm():
    values = [(10, 20.0), (11, 20.0), (12, 35.0), (13, 20.0), (14, 20.0)]
    assert fired(feed(values)) == [False, True, False, False, False]
    values += [(15, 50.0), (16, 20.0), (17, 20.0)]
    assert fired(feed(values))[-1] is True


def test_new_run_resets_history():
    state = {}
    feed([(10, 20.0)], state=state)
    result = feed([(11, 20.0)], state=state, run="run-low-2")[0]
    assert result.incidents == []


def test_low_and_high_detectors_do_not_cross_trigger():
    assert fired(feed([(10, 150.0), (11, 150.0)])) == [False, False]
    state = {}
    for t in (10, 11, 12):
        res = detect_high_water(make_batch(t, 20.0), NODES, HIGH, state)
        assert res.incidents == []


@pytest.mark.parametrize(
    "over",
    [
        {"threshold_max": float("nan")},
        {"threshold_max": float("inf")},
        {"recovery_level": 30.0},
        {"recovery_level": 10.0},
        {"persistence_ticks": 0},
        {"persistence_ticks": True},
        {"datum": ""},
        {"datum": None},
        {"supply_nodes": []},
        {"unit": ""},
        {"scenario_id": "S02"},
    ],
)
def test_invalid_policy_disables_detection(over):
    pol = policy(**over)
    assert policy_error(pol) is not None
    results = feed([(10, 1.0), (11, 1.0), (12, 1.0)], pol=pol)
    assert fired(results) == [False] * 3
    assert "disabled" in results[0].warnings[0]


def test_shipped_config_is_disabled_until_supply_nodes_confirmed():
    root = Path(__file__).resolve().parents[3]
    shipped = json.loads((root / "config" / "scenarios" / "water_low.json").read_text("utf-8"))
    assert policy_error(shipped) == "no reviewed supply nodes"


def test_pair_validation():
    assert pair_error(HIGH, POLICY) is None
    assert pair_error(HIGH, policy(threshold_max=120.0, recovery_level=130.0))
    assert pair_error(HIGH, policy(threshold_max=90.0, recovery_level=100.0))
    assert pair_error(HIGH, policy(unit="m"))
    assert pair_error({}, POLICY)


def test_unreviewed_valve_choice_is_never_supported():
    copied = {"incident_node_id": "reservoir-01", "targets": ["valve-02"],
              "params": {"position": 30}}  # S02-style: no review fields
    pol = policy(safe_valve_choices=[copied])
    results = feed([(10, 20.0), (11, 20.0)], pol=pol)
    assert results[1].incidents[0].facts["supported_valve_actions"] == []


def test_low_valve_choice_is_not_the_high_choice():
    result = feed([(10, 20.0), (11, 20.0)])[1]
    supported = result.incidents[0].facts["supported_valve_actions"]
    assert supported and all(c not in HIGH["safe_valve_choices"] for c in supported)
    assert all(c["params"] != HIGH["safe_valve_choices"][0]["params"] for c in supported)


# ---- planner ----

class StubProvider:
    def __init__(self, plan):
        self.plan, self.calls = plan, 0

    async def generate(self, context):
        self.calls += 1
        return self.plan


def context(pol=None, incidents=None):
    if incidents is None:
        state = {}
        incidents = []
        for raw in CASE["batches"]:
            incidents = detect_low_water(
                ReadingsBatch.model_validate(raw), NODES, pol or POLICY, state
            ).incidents
    return PlanningContext(
        batch=ReadingsBatch.model_validate(CASE["batches"][-1]),
        incidents=incidents,
        nodes=NODES,
        actions=[ActionInfo.model_validate(a) for a in CASE["actions"]],
    )


def proposal(**change):
    raw = copy.deepcopy(CASE["ai_plan"]["proposals"][0])
    raw.update(change)
    return ActionProposal.model_validate(raw)


async def test_no_reviewed_choice_alerts_without_provider_call():
    ctx = context(policy(safe_valve_choices=[]))
    provider = StubProvider(Plan(proposals=[proposal()]))
    plan = await LowWaterScenario().draft_plan(ctx, provider)
    assert plan.proposals == [] and provider.calls == 0
    assert "Low-water supply candidate" in plan.alerts[0] and "no valve change" in plan.alerts[0]


async def test_reviewed_choice_keeps_exact_proposal():
    provider = StubProvider(Plan(proposals=[proposal()]))
    plan = await LowWaterScenario().draft_plan(context(), provider)
    assert len(plan.proposals) == 1 and provider.calls == 1


@pytest.mark.parametrize(
    "change",
    [
        {"params": {"position": 30}},  # high-water value copied over
        {"targets": ["valve-01"]},
        {"source_reading_ids": ["fake-1"]},
        {"risk": "R2"},
    ],
)
async def test_unsupported_proposal_is_dropped(change):
    provider = StubProvider(Plan(proposals=[proposal(**change)]))
    plan = await LowWaterScenario().draft_plan(context(), provider)
    assert plan.proposals == [] and "Dropped proposal" in plan.alerts[0]


async def test_low_planner_ignores_flood_incidents():
    flood = Incident(incident_id="flood:x", kind="flood", run_id="run-low-1",
                     domains=["water"], node_ids=["reservoir-01"], source_reading_ids=["a"])
    provider = StubProvider(Plan(proposals=[proposal()]))
    plan = await LowWaterScenario().draft_plan(context(incidents=[flood]), provider)
    assert plan.proposals == [] and plan.alerts == [] and provider.calls == 0
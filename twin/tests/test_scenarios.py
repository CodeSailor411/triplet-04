"""Scenario engine: fake reading, stuck sensor, exact replay. The key promise: faults change what is REPORTED, never the truth,
and never a reading that was already sent."""
import asyncio
import math

import pytest

from twin.actions import BadRequest
from twin.containment import ContainmentBook, _reading_id
from twin.generator import generate
from twin.scenarios import ScenarioBook
from twin.settings import load_config
from twin.sim import Simulation

WAT = "WAT-01.water_level"


def world(tick=100):
    cfg = load_config()
    topo, _ = generate(cfg)
    sim = Simulation(topo, cfg)
    sim.tick = tick
    cont = ContainmentBook(topo, cfg, sim)
    sc = ScenarioBook(sim)
    sim.overlay, sim.faults = cont, sc
    return sim, cont, sc


def run(sc, name, params=None):
    return asyncio.run(sc.run(name, params))


def dev(sim, device_id):
    return next(d for d in sim.devices if d.device_id == device_id)


def rep(sim, device_id, tick, ch=None):
    return sim.reported(dev(sim, device_id), ch, tick)


# ------------------------------------------------------------------ list
def test_list_names_every_scenario_and_control():
    _, _, sc = world()
    r = run(sc, "list")
    assert r.status == "listed"
    assert {s.name for s in r.scenarios} == {"fake_reading", "stuck_sensor", "replay_exact", "list", "stop", "reset"}


# ------------------------------------------------------------------ fake reading
def test_fake_reading_with_no_params_is_the_t5_case():
    sim, _, sc = world(100)
    r = run(sc, "fake_reading")
    f = r.faults[0]
    assert r.status == "started" and f.device_id == WAT and f.value == 180.0 and f.start_tick == 102 and f.end_tick is None
    clean_before = rep(sim, WAT, 101)
    assert 20 < clean_before.value < 70                                            # a normal water level, about 40 cm
    assert rep(sim, WAT, 102).value == 180.0 and rep(sim, WAT, 500).value == 180.0
    d = dev(sim, WAT)
    assert 20 < sim.model.true_value(d, None, 102) < 70                           # the TRUTH did not move
    assert rep(sim, WAT, 102).reading_id == f"rd0000102-{WAT}"                    # same id, tick and unit, only the value is fake


def test_fake_reading_can_end_and_can_be_a_custom_value():
    sim, _, sc = world(100)
    run(sc, "fake_reading", {"device_id": "AIR-01.pm25", "value": 999, "delay_ticks": 3, "duration_ticks": 4})
    assert [rep(sim, "AIR-01.pm25", t).value for t in (102, 103, 106, 107)][0] != 999
    assert [rep(sim, "AIR-01.pm25", t).value for t in (103, 104, 105, 106)] == [999.0] * 4
    assert rep(sim, "AIR-01.pm25", 107).value != 999


def test_only_the_faked_device_changes():
    sim, _, sc = world(100)
    before = sim.readings_at(110).model_dump()
    run(sc, "fake_reading")
    after = sim.readings_at(110).model_dump()
    changed = [(a["device_id"]) for a, b in zip(after["readings"], before["readings"]) if a != b]
    assert changed == [WAT] and after["count"] == before["count"]


def test_a_fault_never_changes_readings_that_were_already_sent():
    sim, _, sc = world(100)
    old = [sim.readings_at(t).model_dump() for t in range(0, 102)]               # everything up to the start tick - 1
    run(sc, "fake_reading")
    run(sc, "stuck_sensor")
    assert [sim.readings_at(t).model_dump() for t in range(0, 102)] == old


def test_same_seed_same_faults_same_run():
    a, _, sa = world(100)
    b, _, sb = world(100)
    for sc in (sa, sb):
        run(sc, "fake_reading"); run(sc, "stuck_sensor"); run(sc, "replay_exact")
    assert [a.readings_at(t).model_dump() for t in range(95, 140)] == [b.readings_at(t).model_dump() for t in range(95, 140)]


def test_fault_on_one_channel_leaves_the_other_channels_alone():
    sim, _, sc = world(100)
    run(sc, "fake_reading", {"device_id": "EMG-01.emergency_calls", "channel": "fire", "value": 40})
    assert rep(sim, "EMG-01.emergency_calls", 105, "fire").value == 40.0
    assert rep(sim, "EMG-01.emergency_calls", 105, "medical").value != 40.0
    d = dev(sim, "EMG-01.emergency_calls")
    assert rep(sim, "EMG-01.emergency_calls", 105, "medical").value == sim.model.observed_value(d, "medical", 105)


def test_a_fault_without_channel_hits_every_channel():
    sim, _, sc = world(100)
    run(sc, "fake_reading", {"device_id": "EMG-01.emergency_calls", "value": 7})
    assert {rep(sim, "EMG-01.emergency_calls", 105, c).value for c in ("accident", "fire", "flood", "medical")} == {7.0}


# ------------------------------------------------------------------ stuck
def test_stuck_sensor_repeats_the_last_reported_value():
    sim, _, sc = world(100)
    f = run(sc, "stuck_sensor").faults[0]
    d = dev(sim, f.device_id)
    frozen = sim.model.observed_value(d, None, f.start_tick - 1)
    assert [rep(sim, f.device_id, t).value for t in range(f.start_tick, f.start_tick + 20)] == [frozen] * 20
    healthy = {sim.model.observed_value(d, None, t) for t in range(f.start_tick, f.start_tick + 20)}
    assert len(healthy) > 3                                                       # a healthy sensor would have kept moving


# ------------------------------------------------------------------ replay
def test_replay_exact_re_sends_the_old_reading_untouched():
    sim, _, sc = world(100)
    f = run(sc, "replay_exact", {"lag_ticks": 30}).faults[0]
    for t in (f.start_tick, f.start_tick + 7):
        got = rep(sim, f.device_id, t)
        old = sim.reported(dev(sim, f.device_id), None, t - 30)
        assert got.model_dump() == old.model_dump()                               # same reading_id, same old tick and time
        assert got.tick == t - 30 and got.reading_id == f"rd{t - 30:07d}-{f.device_id}"
    assert sim.readings_at(f.start_tick).count == 109                             # the feed still has a reading for the device


def test_replay_needs_enough_history():
    _, _, sc = world(0)
    with pytest.raises(BadRequest) as e:
        run(sc, "replay_exact")
    assert e.value.code == "START_TOO_EARLY"
    assert run(world(100)[2], "replay_exact").status == "started"


# ------------------------------------------------------------------ checks on the request
@pytest.mark.parametrize("name, params, code", [
    ("nope", None, "UNKNOWN_SCENARIO"),
    ("fake_reading", {"colour": "red"}, "UNKNOWN_PARAM"),
    ("fake_reading", {"lag_ticks": 3}, "UNKNOWN_PARAM"),                          # belongs to replay only
    ("fake_reading", {"device_id": "NOPE-01.x"}, "UNKNOWN_DEVICE"),
    ("fake_reading", {"device_id": 5}, "UNKNOWN_DEVICE"),
    ("fake_reading", {"channel": "fire"}, "UNKNOWN_CHANNEL"),                     # water_level has no channels
    ("fake_reading", {"device_id": "EMG-01.emergency_calls", "channel": "tsunami"}, "UNKNOWN_CHANNEL"),
    ("fake_reading", {"delay_ticks": 0}, "INVALID_PARAM"),
    ("fake_reading", {"delay_ticks": True}, "INVALID_PARAM"),
    ("fake_reading", {"delay_ticks": 1.5}, "INVALID_PARAM"),
    ("fake_reading", {"duration_ticks": 0}, "INVALID_PARAM"),
    ("fake_reading", {"value": "180"}, "INVALID_PARAM"),
    ("fake_reading", {"value": math.nan}, "INVALID_PARAM"),
    ("fake_reading", {"value": math.inf}, "INVALID_PARAM"),
    ("fake_reading", {"value": 1e12}, "INVALID_PARAM"),
    ("replay_exact", {"lag_ticks": 0}, "INVALID_PARAM"),
    ("replay_exact", {"lag_ticks": 601}, "INVALID_PARAM"),
    ("list", {"x": 1}, "UNKNOWN_PARAM"),
    ("stop", {}, "UNKNOWN_SCENARIO_ID"),
    ("stop", {"scenario_id": "sc-9999"}, "UNKNOWN_SCENARIO_ID"),
    ("stop", {"scenario_id": ["sc-0001"]}, "UNKNOWN_SCENARIO_ID"),
    ("fake_reading", "not an object", "INVALID_PARAMS"),
])
def test_bad_requests_are_errors_with_a_code_and_start_nothing(name, params, code):
    _, _, sc = world(100)
    with pytest.raises(BadRequest) as e:
        run(sc, name, params)
    assert e.value.code == code
    assert sc.faults == [] and sc.history == []


# ------------------------------------------------------------------ overlap and stop
def test_overlapping_faults_on_one_device_are_refused_but_other_times_and_devices_are_fine():
    sim, _, sc = world(100)
    first = run(sc, "fake_reading", {"duration_ticks": 10})                         # 102..111
    with pytest.raises(BadRequest) as e:
        run(sc, "stuck_sensor", {"device_id": WAT})
    assert e.value.code == "FAULT_ALREADY_ACTIVE" and first.scenario_id in e.value.message
    assert run(sc, "stuck_sensor", {"device_id": "WAT-02.water_level"}).status == "started"   # another device
    assert run(sc, "stuck_sensor", {"device_id": WAT, "delay_ticks": 20}).status == "started"  # later, no overlap
    with pytest.raises(BadRequest):                                                # the open-ended one at 120 overlaps another start
        run(sc, "fake_reading", {"device_id": WAT, "delay_ticks": 30})


def test_channel_overlap_rules():
    _, _, sc = world(100)
    run(sc, "fake_reading", {"device_id": "EMG-01.emergency_calls", "channel": "fire"})
    assert run(sc, "fake_reading", {"device_id": "EMG-01.emergency_calls", "channel": "flood"}).status == "started"
    with pytest.raises(BadRequest):                                                # "all channels" clashes with the fire one
        run(sc, "fake_reading", {"device_id": "EMG-01.emergency_calls"})


def test_stop_ends_the_fault_after_the_current_tick_and_frees_the_device():
    sim, _, sc = world(100)
    sid = run(sc, "fake_reading", {"delay_ticks": 1}).scenario_id                   # starts at 101
    sim.tick = 110
    r = run(sc, "stop", {"scenario_id": sid})
    assert r.status == "stopped" and r.faults[0].end_tick == 111
    assert rep(sim, WAT, 110).value == 180.0 and rep(sim, WAT, 111).value != 180.0
    assert run(sc, "fake_reading", {"delay_ticks": 5}).status == "started"          # free again


def test_stopping_before_the_start_means_it_never_happens():
    sim, _, sc = world(100)
    sid = run(sc, "fake_reading", {"delay_ticks": 50}).scenario_id
    run(sc, "stop", {"scenario_id": sid})
    assert all(rep(sim, WAT, t).value != 180.0 for t in range(100, 200))


def test_history_records_start_and_stop_for_the_log_writer():
    _, _, sc = world(100)
    sid = run(sc, "fake_reading").scenario_id
    run(sc, "stop", {"scenario_id": sid})
    assert [(h["event"], h["scenario_id"]) for h in sc.history] == [("scenario_started", sid), ("scenario_stopped", sid)]


def test_reset_starts_a_new_run_and_forgets_everything():
    sim, cont, sc = world(100)
    run(sc, "fake_reading")
    cont.contain("isolate_sensor", ["AIR-01.pm25"])
    old_run = sim.run_id
    r = run(sc, "reset")
    assert r.status == "reset" and r.run_id != old_run and sim.tick == 0 and r.tick == 0
    assert sc.faults == [] and sc.history == [] and cont.state().devices == []
    sim.tick = 50
    assert rep(sim, WAT, 60).value != 180.0
    assert run(sc, "fake_reading").scenario_id == "sc-0001"                         # counters start over


# ------------------------------------------------------------------ next to containment
def test_an_isolated_device_stays_off_the_feed_even_if_faulted():
    sim, cont, sc = world(100)
    run(sc, "fake_reading")
    cont.contain("isolate_sensor", [WAT])
    assert WAT not in {r.device_id for r in sim.readings_at(105).readings}


def test_rollback_never_restores_a_faked_value():
    sim, cont, sc = world(100)
    run(sc, "fake_reading", {"delay_ticks": 2})                                     # fake from 102
    sim.tick = 110
    c = cont.rollback([_reading_id(110, dev(sim, WAT), None)]).corrections[0]
    assert c.restored_from == _reading_id(101, dev(sim, WAT), None)                # the last tick before the fault
    assert c.value == sim.model.observed_value(dev(sim, WAT), None, 101) and c.value != 180.0


def test_rollback_also_skips_stuck_and_replayed_ticks():
    sim, cont, sc = world(200)
    run(sc, "stuck_sensor", {"device_id": "WAT-02.water_level"})
    run(sc, "replay_exact", {"device_id": "WAT-03.water_level", "lag_ticks": 10})
    sim.tick = 210
    for dev_id in ("WAT-02.water_level", "WAT-03.water_level"):
        c = cont.rollback([_reading_id(210, dev(sim, dev_id), None)]).corrections[0]
        assert c.restored_from == _reading_id(201, dev(sim, dev_id), None)


def test_the_quarantine_lane_shows_what_the_sensor_reports_including_the_fake():
    sim, cont, sc = world(100)
    run(sc, "fake_reading", {"delay_ticks": 1})
    cont.contain("quarantine_device", [WAT])
    sim.tick = 105
    assert [r.value for r in cont.lane().held_readings] == [180.0]


# ------------------------------------------------------------------ through the real Twin (MCP)
async def test_scenario_key_can_list_start_and_stop_over_mcp(mcp_client):
    async with mcp_client("scenario") as c:
        listed = (await c.call_tool("run_scenario", {"name": "list"})).structured_content
        started = (await c.call_tool("run_scenario", {"name": "fake_reading", "params": {"device_id": "PWR-01.load_kw", "value": 5000}})).structured_content
        bad = await c.call_tool("run_scenario", {"name": "fake_reading", "params": {"device_id": "PWR-01.load_kw", "valu": 1}})
        stopped = (await c.call_tool("run_scenario", {"name": "stop", "params": {"scenario_id": started["scenario_id"]}})).structured_content
    assert {s["name"] for s in listed["scenarios"]} >= {"fake_reading", "stuck_sensor", "replay_exact"}
    assert started["status"] == "started" and started["faults"][0]["value"] == 5000.0
    assert bad.is_error and "UNKNOWN_PARAM" in bad.content[0].text
    assert stopped["status"] == "stopped"


async def test_other_layers_do_not_learn_about_a_running_scenario_from_their_own_tools(mcp_client):
    async with mcp_client("scenario") as c:
        s = (await c.call_tool("run_scenario", {"name": "fake_reading", "params": {"device_id": "PWR-02.load_kw", "value": 4321}})).structured_content
    try:
        for who in ("city_brain", "guardian"):
            async with mcp_client(who) as c:
                answers = [(await c.call_tool(t, a)).structured_content for t, a in
                           (("get_capabilities", {}), ("get_clock", {}), ("get_containment_state", {}))]
                blob = str(answers)
            assert "fake_reading" not in blob and "scenario_id" not in blob and "sc-0" not in blob
    finally:
        async with mcp_client("scenario") as c:
            await c.call_tool("run_scenario", {"name": "stop", "params": {"scenario_id": s["scenario_id"]}})

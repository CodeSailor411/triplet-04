"""The real incident (scenario `real_jam`, 2 Nov): a REAL traffic jam that moves the true value.

What must hold:
  * nothing changes before the jam starts, and a calm run (no jam) is exactly what it was before this feature
  * it builds up smoothly (no jump a fake reading would also show), holds, fades and ends by itself
  * the centre node reaches the Brain's S01 rule (congestion index of at least 80 on two ticks in a row), its traffic
    neighbours rise a little (a lone fake spike has no neighbours that move), everything else stays as it was
  * it is a pure function of (seed, device, tick, the incident record): same input, same run
  * a fake reading can run on top of it ("a real incident and an attack at the same time")
  * the readings it moves are written to the run log, and the true values only to the private file
"""
import asyncio
import json

import pytest

from test_runlog import build, lines
from test_scenarios import dev, rep, run, world
from twin.actions import BadRequest
from twin.scenarios import JAM_TARGETS

CENTRE = "SH-05"
CI = f"{CENTRE}.congestion_index"
TRAFFIC_NEIGHBOURS = ["SH-06", "TRF-02", "TRF-06", "TRF-08"]       # linked to SH-05 and carrying traffic sensors (seed 42)
AIR_NEIGHBOURS = ["AIR-02", "AIR-03"]                               # linked to SH-05, not traffic: must stay calm
FAR = "TRF-01"                                                      # a traffic node that is not linked to SH-05


def true_of(sim, device_id, tick):
    return sim.model.true_value(dev(sim, device_id), None, tick)


def obs(sim, device_id, tick):
    return sim.model.observed_value(dev(sim, device_id), None, tick)


def jam(sc, **params):
    return run(sc, "real_jam", params or None)


def calm_and_jam(**params):
    """Two worlds of the same city at the same tick: one calm, one with a jam started in the same way."""
    calm, _, _ = world(100)
    sim, _, sc = world(100)
    r = jam(sc, **params)
    return calm, sim, sc, r.incidents[0]


# ------------------------------------------------------------------ what it is
def test_the_list_names_real_jam_and_its_params():
    _, _, sc = world()
    listed = {s.name: s for s in run(sc, "list").scenarios}
    assert "real_jam" in listed
    assert {"node_id", "delay_ticks", "ramp_ticks", "hold_ticks", "fade_ticks", "spread"} == set(listed["real_jam"].params)


def test_no_params_gives_the_documented_defaults():
    _, sim, sc, inc = calm_and_jam()
    assert inc.node_id == CENTRE and inc.start_tick == 102 and inc.spread == 0.35
    assert (inc.ramp_ticks, inc.hold_ticks, inc.fade_ticks) == (10, 40, 10) and inc.end_tick == 102 + 60
    assert inc.affected_nodes == [CENTRE, *TRAFFIC_NEIGHBOURS]


# ------------------------------------------------------------------ before, and the calm city
def test_nothing_changes_before_the_start_tick_and_a_calm_run_is_untouched():
    calm, sim, sc, inc = calm_and_jam()
    for t in range(0, inc.start_tick):
        assert [r.value for r in sim.readings_at(t).readings] == [r.value for r in calm.readings_at(t).readings]
    calm_only, _, _ = world(100)
    assert calm_only.model.incident_source is not None            # the hook exists even without a jam...
    assert [r.value for r in calm_only.readings_at(150).readings] == [r.value for r in world(100)[0].readings_at(150).readings]
    sim2, _, sc2 = world(100)
    assert sc2.incident_effect(CI, None, 150) is None              # ...and says "no incident" for every device


def test_readings_already_sent_never_change():
    calm, sim, sc, inc = calm_and_jam(delay_ticks=1)
    assert inc.start_tick == 101
    for t in range(0, 101):                                        # up to and including the current tick
        assert [r.value for r in sim.readings_at(t).readings] == [r.value for r in calm.readings_at(t).readings]


# ------------------------------------------------------------------ the shape
def test_the_centre_builds_up_smoothly_holds_at_the_target_then_fades_and_ends():
    calm, sim, sc, inc = calm_and_jam()
    s, ramp, hold, fade = inc.start_tick, inc.ramp_ticks, inc.hold_ticks, inc.fade_ticks
    calm_true = [true_of(calm, CI, t) for t in range(s - 1, inc.end_tick + 3)]
    true = [true_of(sim, CI, t) for t in range(s - 1, inc.end_tick + 3)]
    assert true[0] == calm_true[0]                                  # the tick before the start
    up = true[1:ramp + 1]
    assert all(b > a for a, b in zip(up, up[1:])) and up[0] > calm_true[1]          # rising every tick, from the first
    for t in range(s + ramp, s + ramp + hold):                      # holding: exactly the target
        assert true_of(sim, CI, t) == pytest.approx(JAM_TARGETS["congestion_index"])
    fading = [true_of(sim, CI, t) for t in range(s + ramp + hold, inc.end_tick)]
    assert all(b < a for a, b in zip(fading, fading[1:])) and fading[0] < JAM_TARGETS["congestion_index"]
    for t in range(inc.end_tick, inc.end_tick + 3):                 # over by itself: exactly the calm value again
        assert true_of(sim, CI, t) == true_of(calm, CI, t)


def test_no_single_step_is_bigger_than_the_ramp_needs():
    """A fake reading jumps; a real jam must not (Guardian's rate-of-change check would call it fake)."""
    calm, sim, sc, inc = calm_and_jam()
    biggest = max(abs(true_of(sim, CI, t + 1) - true_of(sim, CI, t)) for t in range(inc.start_tick - 1, inc.end_tick + 1))
    calm_move = max(abs(true_of(calm, CI, t + 1) - true_of(calm, CI, t)) for t in range(inc.start_tick - 1, inc.end_tick + 1))
    assert biggest <= (JAM_TARGETS["congestion_index"] - 20) / inc.ramp_ticks + calm_move + 0.5
    assert biggest < 10


def test_the_brain_s01_rule_sees_it_at_the_centre_and_not_at_the_neighbours():
    """S01: congestion index of at least 80 on two ticks in a row, on the OBSERVED value (with noise and bias)."""
    calm, sim, sc, inc = calm_and_jam()
    hold_ticks = range(inc.start_tick + inc.ramp_ticks, inc.start_tick + inc.ramp_ticks + inc.hold_ticks)
    assert all(obs(sim, CI, t) >= 80 for t in hold_ticks)
    assert all(obs(calm, CI, t) < 80 for t in range(0, 400))        # a calm city never trips it
    for n in TRAFFIC_NEIGHBOURS:
        seen = [obs(sim, f"{n}.congestion_index", t) for t in hold_ticks]
        assert max(seen) < 80                                       # the Brain would not fire here
        assert min(seen) > max(obs(calm, f"{n}.congestion_index", t) for t in hold_ticks) - 8     # but it clearly rose


def test_the_other_two_sensors_follow_the_same_jam():
    calm, sim, sc, inc = calm_and_jam()
    t = inc.start_tick + inc.ramp_ticks + 5
    assert true_of(sim, f"{CENTRE}.vehicle_count", t) == pytest.approx(JAM_TARGETS["vehicle_count"])
    assert true_of(sim, f"{CENTRE}.avg_speed", t) == pytest.approx(JAM_TARGETS["avg_speed"])
    assert true_of(sim, f"{CENTRE}.vehicle_count", t) > true_of(calm, f"{CENTRE}.vehicle_count", t)
    assert true_of(sim, f"{CENTRE}.avg_speed", t) < true_of(calm, f"{CENTRE}.avg_speed", t)


# ------------------------------------------------------------------ who it touches
def test_a_neighbour_gets_the_spread_share_and_nothing_else_moves():
    calm, sim, sc, inc = calm_and_jam()
    t = inc.start_tick + inc.ramp_ticks + 5
    for n in TRAFFIC_NEIGHBOURS:
        before = true_of(calm, f"{n}.congestion_index", t)
        assert true_of(sim, f"{n}.congestion_index", t) == pytest.approx(before + 0.35 * (90.0 - before))
    untouched = [d for d in sim.devices if d.node_id not in inc.affected_nodes or d.sensor not in JAM_TARGETS]
    assert untouched                                                 # air sensors on the centre node, the other domains, ...
    for t in range(inc.start_tick, inc.end_tick):
        for d in untouched:
            for ch in (d.channels or (None,)):
                assert sim.model.true_value(d, ch, t) == calm.model.true_value(dev(calm, d.device_id), ch, t), d.device_id


def test_air_neighbours_and_the_centre_nodes_own_air_sensors_stay_calm():
    calm, sim, sc, inc = calm_and_jam()
    for t in (inc.start_tick + 15, inc.start_tick + 30):
        for n in AIR_NEIGHBOURS:
            assert true_of(sim, f"{n}.pm25", t) == true_of(calm, f"{n}.pm25", t)
        assert true_of(sim, f"{CENTRE}.pm25", t) == true_of(calm, f"{CENTRE}.pm25", t)
    assert not set(AIR_NEIGHBOURS) & set(inc.affected_nodes)


def test_spread_zero_keeps_the_jam_on_one_node():
    calm, sim, sc, inc = calm_and_jam(spread=0)
    assert inc.affected_nodes == [CENTRE]
    t = inc.start_tick + 15
    assert all(true_of(sim, f"{n}.congestion_index", t) == true_of(calm, f"{n}.congestion_index", t) for n in TRAFFIC_NEIGHBOURS)


def test_a_traffic_node_far_away_does_not_move():
    calm, sim, sc, inc = calm_and_jam()
    assert FAR not in inc.affected_nodes
    assert all(true_of(sim, f"{FAR}.congestion_index", t) == true_of(calm, f"{FAR}.congestion_index", t)
               for t in range(inc.start_tick, inc.end_tick))


def test_a_jam_can_be_started_somewhere_else():
    calm, sim, sc, inc = calm_and_jam(node_id=FAR)
    assert inc.node_id == FAR and inc.affected_nodes[0] == FAR and CENTRE not in inc.affected_nodes
    assert true_of(sim, f"{FAR}.congestion_index", inc.start_tick + 20) == pytest.approx(90.0)


# ------------------------------------------------------------------ same seed, same run
def test_same_seed_and_same_jam_give_the_same_run():
    _, a, sa, _ = calm_and_jam()
    _, b, sb, _ = calm_and_jam()
    for t in (0, 101, 110, 130, 170, 400):
        assert [r.value for r in a.readings_at(t).readings] == [r.value for r in b.readings_at(t).readings]


# ------------------------------------------------------------------ stop, reset, overlap, bad input
def test_stop_ends_the_jam_at_once_and_leaves_earlier_ticks_alone():
    calm, sim, sc, inc = calm_and_jam()
    sim.tick = 120
    kept = [true_of(sim, CI, t) for t in range(100, 121)]            # tick 120 is the current one: 121 is still to come
    res = run(sc, "stop", {"scenario_id": sc.incidents[0].scenario_id})
    assert res.status == "stopped" and res.incidents[0].end_tick == 121
    assert [true_of(sim, CI, t) for t in range(100, 121)] == kept     # nothing sent so far changed
    assert all(true_of(sim, CI, t) == true_of(calm, CI, t) for t in range(121, 200))      # gone from the next tick on


def test_stopping_before_it_started_cancels_it():
    calm, sim, sc, inc = calm_and_jam(delay_ticks=50)
    run(sc, "stop", {"scenario_id": sc.incidents[0].scenario_id})
    assert all(true_of(sim, CI, t) == true_of(calm, CI, t) for t in range(100, 250))


def test_reset_forgets_the_jam():
    calm, sim, sc, inc = calm_and_jam()
    run(sc, "reset")
    assert sc.incidents == [] and sc.incident_effect(CI, None, 130) is None
    sim.tick = 100
    assert true_of(sim, CI, 130) == true_of(calm, CI, 130)


def test_two_jams_on_the_same_nodes_at_the_same_time_are_refused_but_a_far_one_is_fine():
    sim, cont, sc = world(100)
    first = jam(sc)
    with pytest.raises(BadRequest) as e:
        jam(sc, node_id="TRF-02")                                    # TRF-02 is inside the first jam's reach
    assert e.value.code == "INCIDENT_ALREADY_ACTIVE" and first.scenario_id in e.value.message
    assert jam(sc, node_id=FAR).status == "started"                   # nothing shared: allowed, "a real incident" can have company
    jam(sc, node_id="TRF-02", delay_ticks=500)                        # after the first one is over: allowed


@pytest.mark.parametrize("params,code", [
    ({"node_id": "WAT-01"}, "UNKNOWN_NODE"), ({"node_id": "NOPE"}, "UNKNOWN_NODE"), ({"node_id": 5}, "UNKNOWN_NODE"),
    ({"spread": 1.5}, "INVALID_PARAM"), ({"spread": -0.1}, "INVALID_PARAM"), ({"spread": True}, "INVALID_PARAM"),
    ({"spread": float("nan")}, "INVALID_PARAM"), ({"ramp_ticks": 0}, "INVALID_PARAM"), ({"fade_ticks": 0}, "INVALID_PARAM"),
    ({"hold_ticks": -1}, "INVALID_PARAM"), ({"delay_ticks": 0}, "INVALID_PARAM"), ({"ramp_ticks": 2.5}, "INVALID_PARAM"),
    ({"ramp_ticks": True}, "INVALID_PARAM"), ({"duration_ticks": 5}, "UNKNOWN_PARAM"), ({"device_id": CI}, "UNKNOWN_PARAM"),
])
def test_bad_input_is_refused_with_a_clear_code_and_starts_nothing(params, code):
    sim, cont, sc = world(100)
    with pytest.raises(BadRequest) as e:
        jam(sc, **params)
    assert e.value.code == code and e.value.message
    assert sc.incidents == []


def test_hold_zero_is_allowed_and_peaks_for_no_longer_than_the_ramp_end():
    calm, sim, sc, inc = calm_and_jam(hold_ticks=0, ramp_ticks=3, fade_ticks=2)
    assert inc.end_tick == inc.start_tick + 5
    assert true_of(sim, CI, inc.start_tick + 2) == pytest.approx(90.0)
    assert true_of(sim, CI, inc.end_tick) == true_of(calm, CI, inc.end_tick)


# ------------------------------------------------------------------ real incident AND an attack
def test_a_fake_reading_can_run_on_top_of_a_real_jam():
    """The spec's 'a real incident and an attack at the same time'."""
    sim, cont, sc = world(100)
    inc = jam(sc).incidents[0]
    run(sc, "fake_reading", {"device_id": f"{FAR}.congestion_index", "value": 95, "delay_ticks": 2})       # a lie somewhere else
    run(sc, "fake_reading", {"device_id": f"{TRAFFIC_NEIGHBOURS[0]}.congestion_index", "value": 5, "delay_ticks": 2})
    t = inc.start_tick + inc.ramp_ticks + 3
    assert rep(sim, f"{FAR}.congestion_index", t).value == 95            # the lie is reported...
    assert true_of(sim, f"{FAR}.congestion_index", t) < 60                # ...though the city there is calm
    assert rep(sim, f"{TRAFFIC_NEIGHBOURS[0]}.congestion_index", t).value == 5      # a lie that hides a real rise
    assert true_of(sim, f"{TRAFFIC_NEIGHBOURS[0]}.congestion_index", t) > 45
    assert rep(sim, CI, t).value >= 80                                    # and the real jam still reports itself


def test_a_sensor_that_sticks_in_the_middle_of_a_jam_repeats_what_it_last_said():
    sim, cont, sc = world(100)
    inc = jam(sc).incidents[0]
    sim.tick = inc.start_tick + 4
    f = run(sc, "stuck_sensor", {"device_id": CI, "delay_ticks": 1}).faults[0]
    stuck = obs(sim, CI, f.start_tick - 1)
    assert all(rep(sim, CI, t).value == stuck for t in range(f.start_tick, f.start_tick + 20))
    assert stuck < 80                                                    # it froze while the jam was still building


def test_an_isolated_sensor_stays_off_the_feed_even_in_a_jam():
    sim, cont, sc = world(100)
    inc = jam(sc).incidents[0]
    cont.contain("isolate_sensor", [CI], "test")
    t = inc.start_tick + 20
    ids = {r.device_id for r in sim.readings_at(t).readings}
    assert CI not in ids and f"{CENTRE}.vehicle_count" in ids


# ------------------------------------------------------------------ the run log
def jam_rows(tmp_path):
    sim, _, cont, sc, rl, _ = build(tmp_path)
    inc = jam(sc).incidents[0]
    for t in range(inc.start_tick - 2, inc.end_tick + 2):
        sim.tick = t
        rl.log_tick(t)
    started = next(e for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "scenario" and e["data"].get("phase") == "started")
    return sim, rl, inc, started


def test_the_readings_a_jam_moves_are_logged_and_linked_to_its_start(tmp_path):
    sim, rl, inc, started = jam_rows(tmp_path)
    ev = lines(rl.part_path(sim.run_id))
    readings = [e for e in ev if e["event_type"] == "reading"]
    per_tick = len(inc.affected_nodes) * len(JAM_TARGETS)
    assert len(readings) == per_tick * (inc.end_tick - inc.start_tick)
    assert {e["data"]["sensor"] for e in readings} == set(JAM_TARGETS)
    assert {e["data"]["node_id"] for e in readings} == set(inc.affected_nodes)
    assert all(e["caused_by"] == [started["event_id"]] for e in readings)
    assert all(inc.start_tick <= e["tick"] < inc.end_tick for e in readings)          # none before it began or after it ended
    assert started["data"]["name"] == "real_jam" and started["data"]["faults"] == [] and started["data"]["incidents"][0]["node_id"] == CENTRE


def test_a_logged_reading_is_what_the_feed_showed(tmp_path):
    sim, rl, inc, _ = jam_rows(tmp_path)
    for e in [x for x in lines(rl.part_path(sim.run_id)) if x["event_type"] == "reading"][:40]:
        feed = next(r for r in sim.readings_at(e["tick"]).readings if r.reading_id == e["data"]["reading_id"])
        assert feed.value == e["data"]["value"]                          # a verdict can point at this reading_id and find it


def test_true_values_go_only_to_the_private_file(tmp_path):
    sim, rl, inc, _ = jam_rows(tmp_path)
    shared = rl.part_path(sim.run_id).read_text()
    assert "true_value" not in shared
    private = lines(rl.private_path(sim.run_id))
    assert private and all(p["fault_kind"] == "real_jam" and p["fault_id"] == inc.incident_id for p in private)
    centre = [p for p in private if p["device_id"] == CI and p["tick"] == inc.start_tick + inc.ramp_ticks + 1][0]
    assert centre["true_value"] == pytest.approx(90.0) and centre["reported_value"] != centre["true_value"]    # noise and bias on top
    rl.export()
    assert "true_value" not in rl.merged_path(sim.run_id).read_text()


def test_the_log_stays_quiet_when_nothing_is_going_on(tmp_path):
    sim, _, cont, sc, rl, _ = build(tmp_path)
    for t in range(0, 30):
        rl.log_tick(t)
    assert not rl.part_path(sim.run_id).exists()                     # not even a run file: nothing happened


def test_an_isolated_device_is_not_logged_as_seen(tmp_path):
    sim, _, cont, sc, rl, _ = build(tmp_path)
    inc = jam(sc).incidents[0]
    cont.contain("isolate_sensor", [CI], "test")
    t = inc.start_tick + 12
    sim.tick = t
    rl.log_tick(t)
    logged = {e["data"]["device_id"] for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "reading"}
    assert CI not in logged and f"{CENTRE}.avg_speed" in logged


# ------------------------------------------------------------------ over MCP (hidden behind the scenario key)
@pytest.mark.asyncio
async def test_scenario_key_can_start_and_stop_a_real_jam_over_mcp(mcp_client):
    async with mcp_client("scenario") as c:
        started = (await c.call_tool("run_scenario", {"name": "real_jam", "params": {"node_id": FAR}})).structured_content
        assert started["status"] == "started" and started["incidents"][0]["node_id"] == FAR and started["faults"] == []
        bad = await c.call_tool("run_scenario", {"name": "real_jam", "params": {"node_id": "WAT-01"}})
        stopped = (await c.call_tool("run_scenario", {"name": "stop", "params": {"scenario_id": started["scenario_id"]}})).structured_content
    assert bad.is_error and "UNKNOWN_NODE" in bad.content[0].text
    assert stopped["status"] == "stopped" and stopped["incidents"][0]["incident_id"] == started["incidents"][0]["incident_id"]


@pytest.mark.asyncio
async def test_other_layers_cannot_start_a_real_jam(mcp_client):
    for who in ("city_brain", "guardian"):
        async with mcp_client(who) as c:
            r = await c.call_tool("run_scenario", {"name": "real_jam"})
            tools = {t.name for t in (await c.list_tools()).tools}
        assert r.is_error and "run_scenario" not in str(r.structured_content or "")
        same = await _error_text_for_unknown_tool(mcp_client, who)
        assert r.content[0].text == same                                 # same answer as for a tool that does not exist


async def _error_text_for_unknown_tool(mcp_client, who):
    async with mcp_client(who) as c:
        return (await c.call_tool("no_such_tool", {"name": "real_jam"})).content[0].text.replace("no_such_tool", "run_scenario")

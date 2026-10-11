"""Containment: isolate, quarantine, rollback, release, caps. Unit tests on the book, then through the real Twin."""
import asyncio
import itertools

import pytest

from twin.actions import ActionBook, BadRequest
from twin.auth import Identity
from twin.containment import ContainmentBook, _reading_id
from twin.generator import generate
from twin.settings import load_config
from twin.sim import Simulation
from twin.tokens import make_token

_jti = itertools.count(1)


def world(tick=100):
    cfg = load_config()
    topo, _ = generate(cfg)
    sim = Simulation(topo, cfg)
    sim.tick = tick
    book, cont = ActionBook(topo, cfg, sim), None
    cont = ContainmentBook(topo, cfg, sim)
    sim.overlay, book.containment = cont, cont
    return sim, book, cont, topo


def devices_of(topo, domain):
    """device ids grouped by node, for devices whose sensor belongs to this domain (device domain, not node domain)"""
    cfg = load_config()
    out: dict[str, list[str]] = {}
    sim = Simulation(topo, cfg)
    for d in sim.devices:
        if d.domain == domain:
            out.setdefault(d.node_id, []).append(d.device_id)
    return out


def ids_on_feed(sim, tick=None):
    return {r.device_id for r in sim.readings_at(sim.tick if tick is None else tick).readings}


# ------------------------------------------------------------------ isolate and quarantine
def test_isolate_cuts_the_feed_from_now_on_but_not_the_past():
    sim, _, cont, _ = world(100)
    dev = "WAT-01.water_level"
    assert dev in ids_on_feed(sim)
    r = cont.contain("isolate_sensor", [dev], "looks stuck")
    assert r.status == "applied" and r.changed == [dev] and r.unchanged == []
    assert dev not in ids_on_feed(sim, 100) and dev not in ids_on_feed(sim, 150)
    assert dev in ids_on_feed(sim, 99)                       # ticks before the cut stay as they were
    assert sim.readings_at(100).count == 108                 # exactly this one reading is gone


def test_isolating_twice_is_harmless():
    sim, _, cont, _ = world()
    cont.contain("isolate_sensor", ["WAT-01.water_level"])
    again = cont.contain("isolate_sensor", ["WAT-01.water_level"])
    assert again.status == "applied" and again.changed == [] and again.unchanged == ["WAT-01.water_level"]
    assert len(cont.state().devices) == 1


@pytest.mark.parametrize("bad, code", [
    ([], "INVALID_DEVICE_IDS"),
    (["WAT-01.water_level", "WAT-01.water_level"], "INVALID_DEVICE_IDS"),
    (["NOPE-01.thing"], "UNKNOWN_DEVICE"),
    ("WAT-01.water_level", "INVALID_DEVICE_IDS"),
])
def test_bad_device_ids_are_errors_with_a_code(bad, code):
    _, _, cont, _ = world()
    with pytest.raises(BadRequest) as e:
        cont.contain("isolate_sensor", bad)
    assert e.value.code == code


def test_reason_is_checked():
    _, _, cont, _ = world()
    with pytest.raises(BadRequest) as e:
        cont.contain("isolate_sensor", ["WAT-01.water_level"], "x" * 201)
    assert e.value.code == "INVALID_REASON"


def test_isolation_cap_counts_nodes_not_devices_and_refuses_the_whole_request():
    sim, _, cont, topo = world()
    traffic = devices_of(topo, "traffic")                    # 11 nodes, two sensors each, cap 5 nodes
    nodes = sorted(traffic)
    five = [d for n in nodes[:5] for d in traffic[n]]        # 5 nodes, 10 devices: fine
    assert cont.contain("isolate_sensor", five).status == "applied"
    over = cont.contain("isolate_sensor", traffic[nodes[5]])
    assert over.status == "rejected" and over.code == "CAP_EXCEEDED"
    assert {k: over.details[k] for k in ("pool", "domain", "cap", "in_use", "requested", "remaining")} == \
           {"pool": "isolation", "domain": "traffic", "cap": 5, "in_use": 5, "requested": 1, "remaining": 0}
    assert len(cont.state().devices) == 10                   # nothing from the refused request got in


def test_one_request_over_the_cap_changes_nothing():
    _, _, cont, topo = world()
    traffic = devices_of(topo, "traffic")
    six = [traffic[n][0] for n in sorted(traffic)[:6]]
    r = cont.contain("isolate_sensor", six)
    assert r.status == "rejected" and r.details["requested"] == 6 and r.details["remaining"] == 5
    assert cont.state().devices == []


def test_power_exception_all_power_sensors_can_go_and_shared_nodes_do_not_eat_other_pools():
    sim, _, cont, topo = world()
    pumps = [n.node_id for n in topo.nodes if {"water", "power"} <= set(n.domains)]
    assert pumps                                              # the city really has pump stations in both domains
    power = devices_of(topo, "power")
    assert len(power) == 9
    every = [d for devs in power.values() for d in devs]
    assert cont.contain("isolate_sensor", every).status == "applied"
    use = {p.domain: p.isolation_in_use for p in cont.state().pools}
    assert use["power"] == 9
    assert use["water"] == 0 and use["emergency"] == 0       # the pump stations' water sensors still report
    on_feed = {(r.node_id, r.sensor) for r in sim.readings_at(100).readings}
    for n in pumps:
        assert (n, "water_level") in on_feed and (n, "load_kw") not in on_feed      # water sensor still reports, power cut


def test_quarantine_and_isolate_share_one_pool_and_switching_costs_no_new_slot():
    _, _, cont, topo = world()
    traffic = devices_of(topo, "traffic")
    nodes = sorted(traffic)
    cont.contain("isolate_sensor", [traffic[n][0] for n in nodes[:4]])
    cont.contain("quarantine_device", [traffic[nodes[4]][0]])                 # 5th slot, by quarantine
    assert cont.contain("isolate_sensor", [traffic[nodes[5]][0]]).code == "CAP_EXCEEDED"
    switch = cont.contain("quarantine_device", [traffic[nodes[0]][0]])        # isolated -> quarantined, same node
    assert switch.status == "applied" and switch.changed == [traffic[nodes[0]][0]]
    # second sensor of an already counted node needs no slot either
    assert cont.contain("isolate_sensor", [traffic[nodes[0]][1]]).status == "applied"


def test_release_frees_the_slot_and_data_flows_again_from_that_tick():
    sim, _, cont, topo = world(100)
    traffic = devices_of(topo, "traffic")
    nodes = sorted(traffic)
    five = [traffic[n][0] for n in nodes[:5]]
    cont.contain("isolate_sensor", five)
    sim.tick = 120
    rel = cont.release([five[0]])
    assert rel.released == [five[0]] and rel.not_contained == []
    assert five[0] in ids_on_feed(sim, 120) and five[0] in ids_on_feed(sim, 130)
    assert five[0] not in ids_on_feed(sim, 110)             # the gap while it was cut stays a gap
    assert cont.contain("isolate_sensor", [traffic[nodes[5]][0]]).status == "applied"      # the slot is free again
    assert cont.release(["WAT-01.water_level"]).not_contained == ["WAT-01.water_level"]


# ------------------------------------------------------------------ quarantine holds commands
def valve_token(sim, params, targets=("WAT-01",)):
    return make_token({"iss": "guardian", "aud": "twin", "jti": f"cq-{next(_jti)}", "run_id": sim.run_id,
                       "iat": sim.clock.iso_of(sim.tick), "exp": sim.clock.iso_of(sim.tick + 60),
                       "action": "set_valve_position", "targets": list(targets), "params": params, "score": 0.9})


def test_quarantine_holds_commands_without_spending_the_token_and_isolation_does_not():
    sim, book, cont, _ = world()
    params, tok = {"position": 30}, None
    tok = valve_token(sim, params)
    cont.contain("isolate_sensor", ["WAT-01.water_level"])                     # isolation alone does not block commands
    ok = book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-01"], params, tok, "k-iso")
    assert ok.status == "committed"

    tok2 = valve_token(sim, params)
    cont.contain("quarantine_device", ["WAT-01.water_level"])
    held = book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-01"], params, tok2, "k-q")
    assert held.status == "rejected" and held.code == "DEVICE_QUARANTINED" and held.details == {"nodes": ["WAT-01"]}
    lane = cont.lane()
    assert [(h.action, h.targets, h.caller) for h in lane.held_commands] == [("set_valve_position", ["WAT-01"], "city_brain")]
    assert [r.device_id for r in lane.held_readings] == ["WAT-01.water_level"]

    cont.release(["WAT-01.water_level"])
    again = book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-01"], params, tok2, "k-q2")
    assert again.status == "committed"                                         # the same token still works: it was not spent


def test_a_bad_token_is_still_a_token_error_not_a_quarantine_answer():
    sim, book, cont, _ = world()
    cont.contain("quarantine_device", ["WAT-01.water_level"])
    r = book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-01"], {"position": 30}, "garbage", "k-bad")
    assert r.status == "rejected" and r.code != "DEVICE_QUARANTINED"          # the token is checked first
    assert cont.lane().held_commands == []


def test_the_lane_remembers_only_the_last_few_commands():
    sim, book, cont, _ = world()
    cont.cfg.containment.held_commands_kept = 3
    cont.contain("quarantine_device", ["WAT-01.water_level"])
    for i in range(5):
        book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-01"], {"position": i}, valve_token(sim, {"position": i}), f"k{i}")
    assert [h.params["position"] for h in cont.lane().held_commands] == [2, 3, 4]


# ------------------------------------------------------------------ rollback
def test_rollback_restores_the_last_reported_value_and_marks_it_corrected():
    sim, _, cont, _ = world(100)
    d = next(x for x in sim.devices if x.device_id == "WAT-01.water_level")
    bad = _reading_id(100, d, None)
    r = cont.rollback([bad])
    assert r.status == "applied" and len(r.corrections) == 1
    c = r.corrections[0]
    assert c.corrected is True and c.corrects == bad and c.restored_from == _reading_id(99, d, None)
    assert c.value == sim.model.observed_value(d, None, 99)                    # the reported value of tick 99
    assert set(c.model_dump()) == {"corrected", "corrects", "restored_from", "run_id", "tick", "timestamp", "node_id",
                                   "device_id", "sensor", "channel", "value", "unit"}      # no field that could carry the truth


def test_rollback_skips_ticks_that_are_already_known_bad_and_ticks_nobody_saw():
    sim, _, cont, _ = world(100)
    d = next(x for x in sim.devices if x.device_id == "WAT-01.water_level")
    cont.rollback([_reading_id(99, d, None)])                                   # 99 is now known bad
    second = cont.rollback([_reading_id(100, d, None)]).corrections[0]
    assert second.restored_from == _reading_id(98, d, None)                    # skips 99
    cont.contain("isolate_sensor", ["WAT-02.water_level"])
    sim.tick = 110
    d2 = next(x for x in sim.devices if x.device_id == "WAT-02.water_level")
    cont.release([d2.device_id])
    sim.tick = 111
    assert cont.rollback([_reading_id(111, d2, None)]).corrections[0].restored_from == _reading_id(110, d2, None)


def test_rollback_twice_returns_the_first_answer_and_uses_no_new_slot():
    sim, _, cont, _ = world()
    d = next(x for x in sim.devices if x.device_id == "WAT-01.water_level")
    rid = _reading_id(100, d, None)
    first = cont.rollback([rid]).corrections[0]
    again = cont.rollback([rid])
    assert again.already_corrected == [rid] and again.corrections == [first]
    assert {p.domain: p.rollback_in_use for p in cont.state().pools}["water"] == 1


def test_rollback_with_a_channel_reading():
    sim, _, cont, _ = world()
    d = next(x for x in sim.devices if x.sensor == "emergency_calls")
    rid = _reading_id(100, d, "fire")
    c = cont.rollback([rid]).corrections[0]
    assert c.channel == "fire" and c.corrects == rid and c.restored_from == _reading_id(99, d, "fire")


@pytest.mark.parametrize("rid, code", [
    ("garbage", "UNKNOWN_READING"),
    ("rd0000100-NOPE.thing", "UNKNOWN_READING"),
    ("rd0000101-WAT-01.water_level", "UNKNOWN_READING"),                       # in the future
    ("rd0000100-WAT-01.water_level-fire", "UNKNOWN_READING"),                  # this sensor has no channels
])
def test_bad_reading_ids_are_errors(rid, code):
    _, _, cont, _ = world(100)
    with pytest.raises(BadRequest) as e:
        cont.rollback([rid])
    assert e.value.code == code


def test_cannot_roll_back_a_reading_that_never_reached_the_feed():
    sim, _, cont, _ = world(100)
    cont.contain("isolate_sensor", ["WAT-01.water_level"])
    with pytest.raises(BadRequest) as e:
        cont.rollback(["rd0000100-WAT-01.water_level"])
    assert e.value.code == "READING_NOT_PUBLISHED"


def test_no_trusted_value_is_a_refusal_and_changes_nothing():
    sim, _, cont, _ = world(0)
    r = cont.rollback(["rd0000000-WAT-01.water_level"])
    assert r.status == "rejected" and r.code == "NO_TRUSTED_VALUE"
    assert cont.state().corrections == [] and all(p.rollback_in_use == 0 for p in cont.state().pools)


def test_rollback_has_its_own_pool_with_the_same_sizes():
    sim, _, cont, topo = world(100)
    traffic = devices_of(topo, "traffic")
    by_id = {d.device_id: d for d in sim.devices}
    nodes = sorted(traffic)
    cont.contain("isolate_sensor", [traffic[n][0] for n in nodes[:5]])         # isolation pool is full ...
    ids = [_reading_id(100, by_id[traffic[n][0]], None) for n in nodes[5:10]]  # ... rollback still has 5 free
    # those 5 nodes are not isolated, so their readings are on the feed
    assert cont.rollback(ids).status == "applied"
    over = cont.rollback([_reading_id(100, by_id[traffic[nodes[10]][0]], None)])
    assert over.status == "rejected" and over.code == "CAP_EXCEEDED"
    assert over.details["pool"] == "rollback" and over.details["cap"] == 5 and over.details["in_use"] == 5
    assert len(cont.state().corrections) == 5


def test_release_clears_rollback_marks_and_frees_the_slot():
    sim, _, cont, _ = world()
    d = next(x for x in sim.devices if x.device_id == "WAT-01.water_level")
    cont.rollback([_reading_id(100, d, None)])
    assert cont.release([d.device_id]).released == [d.device_id]
    assert cont.state().corrections == [] and {p.domain: p.rollback_in_use for p in cont.state().pools}["water"] == 0


# ------------------------------------------------------------------ misc
def test_new_run_wipes_containment():
    sim, _, cont, _ = world()
    cont.contain("isolate_sensor", ["WAT-01.water_level"])
    asyncio.run(sim.reset())
    assert cont.state().devices == []
    assert "WAT-01.water_level" in ids_on_feed(sim, 0)


def test_reading_id_format_matches_the_simulation():
    sim, _, _, _ = world()
    by_id = {d.device_id: d for d in sim.devices}
    for r in sim.readings_at(7).readings:
        assert r.reading_id == _reading_id(7, by_id[r.device_id], r.channel)


def test_containment_state_lists_every_domain_pool():
    _, _, cont, _ = world()
    pools = {p.domain: (p.isolation_cap, p.rollback_cap) for p in cont.state().pools}
    assert pools == {"traffic": (5, 5), "water": (4, 4), "power": (9, 9), "air_quality": (4, 4), "emergency": (3, 3)}


# ------------------------------------------------------------------ through the real Twin (MCP)
GUARDIAN_ONLY = [("isolate_sensor", {"device_ids": ["WAT-01.water_level"]}),
                 ("quarantine_device", {"device_ids": ["WAT-01.water_level"]}),
                 ("rollback_reading", {"reading_ids": ["rd0000000-WAT-01.water_level"]}),
                 ("release_device", {"device_ids": ["WAT-01.water_level"]}),
                 ("get_quarantine_lane", {})]


@pytest.mark.parametrize("tool, args", GUARDIAN_ONLY)
async def test_only_guardian_may_contain(mcp_client, tool, args):
    for who, word in (("city_brain", "FORBIDDEN"), ("scenario", "FORBIDDEN"), (None, "UNAUTHENTICATED")):
        async with mcp_client(who) as c:
            r = await c.call_tool(tool, args)
        assert r.is_error and word in r.content[0].text


async def test_brain_and_guardian_can_read_the_state_but_scenario_cannot(mcp_client):
    for who in ("city_brain", "guardian"):
        async with mcp_client(who) as c:
            data = (await c.call_tool("get_containment_state", {})).structured_content
        assert data["devices"] == [] and len(data["pools"]) == 5
    async with mcp_client("scenario") as c:
        assert (await c.call_tool("get_containment_state", {})).is_error


async def test_isolate_through_mcp_changes_what_the_brain_sees_and_release_undoes_it(mcp_client):
    dev = "AIR-03.pm25"
    try:
        async with mcp_client("city_brain") as brain, mcp_client("guardian") as guardian:
            before = (await brain.call_tool("get_readings", {})).structured_content["count"]
            r = (await guardian.call_tool("isolate_sensor", {"device_ids": [dev], "reason": "stuck"})).structured_content
            assert r["status"] == "applied" and r["changed"] == [dev]
            after = (await brain.call_tool("get_readings", {})).structured_content
            assert after["count"] == before - 1 and dev not in {x["device_id"] for x in after["readings"]}
            state = (await brain.call_tool("get_containment_state", {})).structured_content
            assert [(d["device_id"], d["state"], d["reason"]) for d in state["devices"]] == [(dev, "isolated", "stuck")]
    finally:
        async with mcp_client("guardian") as guardian:
            rel = (await guardian.call_tool("release_device", {"device_ids": [dev]})).structured_content
    assert rel["released"] == [dev]
    async with mcp_client("city_brain") as brain:
        assert (await brain.call_tool("get_readings", {})).structured_content["count"] == before


async def test_cap_exceeded_over_mcp_has_the_agreed_fields_and_is_not_a_failed_call(mcp_client):
    ids = [f"TRF-{i:02d}.vehicle_count" for i in range(1, 7)]
    async with mcp_client("guardian") as g:
        r = await g.call_tool("isolate_sensor", {"device_ids": ids})
        state = (await g.call_tool("get_containment_state", {})).structured_content
    assert not r.is_error
    d = r.structured_content
    assert d["status"] == "rejected" and d["code"] == "CAP_EXCEEDED"
    assert {k: d["details"][k] for k in ("domain", "cap", "in_use", "requested", "remaining")} == \
           {"domain": "traffic", "cap": 5, "in_use": 0, "requested": 6, "remaining": 5}
    assert state["devices"] == []


async def test_unknown_device_over_mcp_is_a_failed_call_with_a_code(mcp_client):
    async with mcp_client("guardian") as g:
        r = await g.call_tool("isolate_sensor", {"device_ids": ["NOPE-01.thing"]})
    assert r.is_error and "UNKNOWN_DEVICE" in r.content[0].text


async def test_rollback_over_mcp_and_no_truth_in_any_containment_answer(mcp_client):
    dev = "AIR-04.pm25"
    rid = "rd0000000-AIR-04.pm25"
    async with mcp_client("guardian") as g:
        first = (await g.call_tool("rollback_reading", {"reading_ids": [rid]})).structured_content
        assert first["status"] == "rejected" and first["code"] == "NO_TRUSTED_VALUE"      # the standing clock is at tick 0
        answers = [(await g.call_tool(t, a)).structured_content for t, a in
                   (("get_containment_state", {}), ("get_quarantine_lane", {}))]
        blob = str(answers).lower()
    for forbidden in ("true_value", "truth", "bias", "noise", "wobble", "ground_truth"):
        assert forbidden not in blob

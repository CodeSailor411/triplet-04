"""The dashboard: reading logs, drawing, and the page itself (in NiceGUI's simulated browser, no real browser needed)."""
import asyncio
import json
import re
import os
import xml.etree.ElementTree as ET

import pytest
from nicegui import ui
from nicegui.testing import user_simulation

from twin.dashboard.events import (LogFollower, build_state, node_status, resolve_causes, short_label, summarize, trust_from_score)
from twin.dashboard.page import Hub, build_page
from twin.dashboard.basemap import street_graph
from twin.dashboard.sample import write_sample
from twin.dashboard.svg import MIN_GAP, Scene, chain_of, city_scene, display_positions, document, tick_clock, timeline_scene
from twin.generator import fingerprint, generate
from twin.settings import DashboardCfg, load_config

CUT = {"trusted": 0.8, "degraded": 0.5}


@pytest.fixture(scope="module")
def city():
    cfg = load_config()
    topo, layout = generate(cfg)
    return cfg, topo, layout


def ev(layer="twin", n=1, tick=1, t="reading", data=None, caused_by=None, run="run-42-001", wall=None, ts="2026-10-05T08:00:01.000Z"):
    return {"run_id": run, "event_id": f"{layer}-{n:06d}", "timestamp": ts, "tick": tick, "wall": wall or f"2026-10-07T10:00:{tick:02d}.000Z",
            "layer": layer, "event_type": t, "caused_by": caused_by or [], "data": data if data is not None else {}}


def write_lines(path, events, newline=True):
    path.write_text("\n".join(json.dumps(e) for e in events) + ("\n" if newline else ""))


def state_of(topo, events, run="run-42-001"):
    return build_state(sorted(events, key=lambda e: (e["tick"], e["event_id"])), topo, CUT, run)


# ====================================================================== reading the logs
def test_follower_reads_new_lines_as_they_arrive(tmp_path):
    f = tmp_path / "a.jsonl"
    write_lines(f, [ev(n=1), ev(n=2)])
    lf = LogFollower([str(tmp_path)])
    assert lf.poll() is True and len(lf.runs()["run-42-001"]) == 2 and lf.version == 1
    assert lf.poll() is False and lf.version == 1                       # nothing new: nothing changes
    with open(f, "a") as h:
        h.write(json.dumps(ev(n=3)) + "\n")
    assert lf.poll() is True and len(lf.runs()["run-42-001"]) == 3 and lf.version == 2


def test_a_half_written_line_waits_until_it_is_whole(tmp_path):
    f = tmp_path / "a.jsonl"
    whole = json.dumps(ev(n=2))
    f.write_text(json.dumps(ev(n=1)) + "\n" + whole[:30])
    lf = LogFollower([str(f)])
    lf.poll()
    assert len(lf._events) == 1 and lf.bad_lines == 0                   # the broken tail is not counted as junk
    with open(f, "a") as h:
        h.write(whole[30:] + "\n")
    lf.poll()
    assert len(lf._events) == 2 and lf.bad_lines == 0


def test_a_complete_last_line_without_newline_is_still_read(tmp_path):
    f = tmp_path / "a.jsonl"
    write_lines(f, [ev(n=1), ev(n=2)], newline=False)
    lf = LogFollower([str(f)])
    lf.poll()
    assert len(lf._events) == 2
    lf.poll()
    assert len(lf._events) == 2                                         # and it is not read twice


def test_the_same_event_in_a_part_file_and_a_merged_file_is_shown_once(tmp_path):
    write_lines(tmp_path / "run-42-001.twin.jsonl", [ev(n=1), ev(n=2)])
    write_lines(tmp_path / "run-42-001.jsonl", [ev(n=1), ev(n=2), ev("guardian", 1, 2, "verdict")])
    lf = LogFollower([str(tmp_path)])
    lf.poll()
    assert len(lf.runs()["run-42-001"]) == 3


def test_a_replaced_file_is_read_again_without_duplicates(tmp_path):
    f = tmp_path / "run.jsonl"
    write_lines(f, [ev(n=1)])
    lf = LogFollower([str(f)])
    lf.poll()
    new = tmp_path / "new.tmp"
    write_lines(new, [ev(n=1), ev(n=2), ev(n=3)])
    os.replace(new, f)                                                   # exactly how the merge writes its file
    assert lf.poll() is True and len(lf._events) == 3


def test_rewriting_a_file_with_the_same_events_is_not_a_change(tmp_path):
    """The merge rewrites its file on every export. If nothing new is in it, the page must not redraw for nothing."""
    f = tmp_path / "run.jsonl"
    write_lines(f, [ev(n=1), ev(n=2)])
    lf = LogFollower([str(f)])
    lf.poll()
    version = lf.version
    new = tmp_path / "new.tmp"
    write_lines(new, [ev(n=1), ev(n=2)])
    os.replace(new, f)
    assert lf.poll() is False and lf.version == version and len(lf._events) == 2


def test_junk_is_skipped_and_counted(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(json.dumps(ev(n=1)) + "\nnot json\n[1,2]\n{\"run_id\": \"x\"}\n" + json.dumps({**ev(n=2), "tick": "five"}) + "\n\n")
    lf = LogFollower([str(f)])
    lf.poll()
    assert len(lf._events) == 1 and lf.bad_lines == 4


def test_the_private_truth_file_is_never_read(tmp_path):
    write_lines(tmp_path / "run-42-001.twin.jsonl", [ev(n=1)])
    private = tmp_path / "run-42-001.twin-private.jsonl"
    write_lines(private, [ev(n=9, data={"true_value": 37.0})])
    for sources in ([str(tmp_path)], [str(tmp_path), str(private)]):      # in a folder, and named directly
        lf = LogFollower(sources)
        lf.poll()
        assert [e["event_id"] for e in lf.runs()["run-42-001"]] == ["twin-000001"]
        assert "private" not in " ".join(p.name for p in lf.files())


def test_missing_folders_are_ignored_and_runs_are_separated(tmp_path):
    write_lines(tmp_path / "a.jsonl", [ev(n=1, run="run-A", wall="2026-10-07T10:00:01.000Z"), ev(n=2, run="run-B", wall="2026-10-07T11:00:00.000Z")])
    lf = LogFollower([str(tmp_path / "nope"), str(tmp_path)])
    lf.poll()
    assert set(lf.runs()) == {"run-A", "run-B"} and lf.latest_run() == "run-B"
    assert LogFollower([]).latest_run() is None


# ====================================================================== what the events mean
def test_trust_from_score_uses_the_cutoffs():
    assert [trust_from_score(s, CUT) for s in (1.0, 0.8, 0.79, 0.5, 0.49, 0.0)] == ["trusted", "trusted", "degraded", "degraded", "untrusted", "untrusted"]


def test_state_follows_verdicts_containment_and_release(city):
    _, topo, _ = city
    evs = [ev("guardian", 1, 1, "verdict", {"device_id": "WAT-02.water_level", "score": 0.9}),
           ev("guardian", 2, 2, "verdict", {"device_id": "WAT-01.water_level", "score": 0.2}),
           ev("twin", 3, 3, "containment", {"tool": "isolate_sensor", "status": "applied", "changed": ["WAT-01.water_level"]}),
           ev("twin", 4, 4, "containment", {"tool": "quarantine_device", "status": "applied", "changed": ["WAT-02.water_level"]}),
           ev("twin", 5, 5, "containment", {"tool": "isolate_sensor", "status": "rejected", "code": "CAP_EXCEEDED", "changed": ["AIR-01.pm25"]}),
           ev("twin", 6, 6, "containment", {"tool": "rollback_reading", "status": "applied", "corrections": [{"device_id": "AIR-02.pm25"}]})]
    st = state_of(topo, evs)
    d = st.devices
    assert (d["WAT-02.water_level"].trust, d["WAT-02.water_level"].cut) == ("trusted", "quarantined")
    assert (d["WAT-01.water_level"].trust, d["WAT-01.water_level"].cut, d["WAT-01.water_level"].score) == ("untrusted", "isolated", 0.2)
    assert d["AIR-01.pm25"].cut is None and d["AIR-02.pm25"].corrections == 1       # a refused call changes nothing
    st2 = state_of(topo, evs + [ev("twin", 7, 7, "containment", {"tool": "release_device", "status": "applied", "changed": ["WAT-01.water_level"]})])
    assert st2.devices["WAT-01.water_level"].cut is None and st2.devices["WAT-01.water_level"].trust == "untrusted"
    assert st.tick == 6


def test_odd_data_never_crashes_the_state_or_the_labels(city):
    _, topo, _ = city
    weird = [ev("guardian", 1, 1, "verdict", {"device_id": "NOPE", "score": 0.1}), ev("guardian", 2, 1, "verdict", {"device_id": "WAT-01.water_level", "score": True}),
             ev("guardian", 3, 1, "verdict", {"device_id": "WAT-01.water_level", "score": "high"}), ev("twin", 4, 1, "containment", "text"),
             ev("twin", 5, 1, "containment", {"tool": "isolate_sensor", "status": "applied", "changed": "WAT-01.water_level"}),
             ev("twin", 6, 1, "scenario", {"phase": "started", "faults": ["x", {"nostart": 1}]}), ev("twin", 7, 1, "scenario", None),
             ev("brain", 8, 1, "decision", [1, 2]), ev("brain", 9, 1, "escalation", {}), ev("brain", 10, 1, "something_new", {"a": 1}),
             ev("twin", 11, 1, "reading", {"value": "x" * 5000}), ev("twin", 12, 1, "action", {"targets": 5})]
    st = state_of(topo, weird)
    assert st.devices["WAT-01.water_level"].trust == "unknown"
    for e in weird:
        assert isinstance(summarize(e), str) and isinstance(short_label(e), str)


def test_attacks_run_between_start_and_end_and_stop_when_stopped(city):
    _, topo, _ = city
    fault = {"fault_id": "f-1", "device_id": "WAT-01.water_level", "kind": "fake_reading", "start_tick": 10, "end_tick": None, "value": 180.0}
    start = ev("twin", 1, 3, "scenario", {"phase": "started", "scenario_id": "sc-1", "name": "fake_reading", "faults": [fault]})
    assert state_of(topo, [start, ev("twin", 2, 9)]).attacks() == []                 # not yet
    running = state_of(topo, [start, ev("twin", 2, 12)])
    assert [a["device_id"] for a in running.attacks()] == ["WAT-01.water_level"]
    stop = ev("twin", 3, 15, "scenario", {"phase": "stopped", "scenario_id": "sc-1", "faults": [{**fault, "end_tick": 16}]})
    assert state_of(topo, [start, ev("twin", 2, 12), stop]).attacks() == []
    assert node_status(next(n for n in topo.nodes if n.node_id == "WAT-01"), running)["attack"] is True


def test_causes_come_from_ids_reading_ids_tokens_and_keys_and_nothing_is_guessed():
    evs = [ev("twin", 1, 1, "scenario", {"phase": "started"}),
           ev("twin", 2, 2, "reading", {"reading_id": "rd0000002-X"}, caused_by=["twin-000001"]),
           ev("guardian", 1, 2, "verdict", {"device_id": "X", "score": 0.1}, caused_by=["rd0000002-X"]),                 # a reading_id
           ev("guardian", 2, 3, "verdict", {"token_id": "t-1"}, caused_by=["guardian-000001"]),
           ev("brain", 1, 3, "decision", {"idempotency_key": "k-1"}, caused_by=["guardian-000002"]),
           ev("twin", 3, 4, "action", {"token_id": "t-1", "idempotency_key": "k-1", "status": "committed"}),              # joined
           ev("twin", 4, 5, "action", {"token_id": "t-unknown", "idempotency_key": None, "status": "rejected"}),         # no one claims it
           ev("twin", 5, 5, "containment", {}, caused_by=["ghost-000001", "twin-000005"])]                                # unknown + itself
    c = resolve_causes(evs)
    assert c["twin-000002"] == ["twin-000001"] and c["guardian-000001"] == ["twin-000002"]
    assert c["twin-000003"] == ["guardian-000002", "brain-000001"]
    assert "twin-000004" not in c and "twin-000005" not in c


# ====================================================================== drawing
def parse(scene: Scene) -> ET.Element:
    return ET.fromstring(document(scene.content, scene.width, scene.height))      # raises if the SVG is not well formed


def test_city_map_is_valid_and_has_every_node(city):
    cfg, topo, layout = city
    st = state_of(topo, [ev()])
    sc = city_scene(topo, layout, st)
    root = parse(sc)
    nodes = [g for g in root.iter("{http://www.w3.org/2000/svg}g") if g.get("data-node")]
    assert len(nodes) == 38 == len(sc.hits) and {g.get("data-node") for g in nodes} == {n.node_id for n in topo.nodes}
    assert sc.content.count("<polygon points=\"46,24 35,43.05 13,43.05 2,24 13,4.95 35,4.95\" fill=\"#04060B\"") == 38      # one spec hexagon per node, filled with the map colour
    assert sc.content.count("<path d=\"M") >= 2 * (len(topo.nodes) - 1)                                                    # at least pale + dark line for each of the 37 roads that link 38 nodes


def test_neighbour_links_only_on_request_but_always_for_the_selected_node(city):
    _, topo, layout = city
    st = state_of(topo, [ev()])
    links = lambda svg: svg.count('stroke-width="2" opacity="0.32"')               # noqa: E731
    off = city_scene(topo, layout, st)
    assert links(off.content) == 0
    on = city_scene(topo, layout, st, show_edges=True)
    assert links(on.content) == len(topo.edges)
    sel = next(n for n in topo.nodes if n.neighbours)
    mine = sum(1 for a, b in topo.edges if sel.node_id in (a, b))
    s = city_scene(topo, layout, st, selected=sel.node_id)
    assert s.content.count('stroke-width="4" opacity="0.9"') == mine and 'fill-opacity="0.08"' in s.content


def test_nodes_never_draw_on_top_of_each_other_and_the_city_data_is_untouched(city):
    _, topo, _ = city
    before = [(n.node_id, n.x, n.y) for n in topo.nodes]
    pos = display_positions(topo)
    ids = list(pos)
    closest = min(((pos[a][0] - pos[b][0]) ** 2 + (pos[a][1] - pos[b][1]) ** 2) ** 0.5 for i, a in enumerate(ids) for b in ids[i + 1:])
    assert closest >= MIN_GAP - 1
    assert [(n.node_id, n.x, n.y) for n in topo.nodes] == before
    far = max(((pos[n.node_id][0] - n.x) ** 2 + (pos[n.node_id][1] - n.y) ** 2) ** 0.5 for n in topo.nodes)
    assert far < 30                                                                 # only a small nudge, never a different place


def test_node_pictures_show_trust_cut_off_and_attack(city):
    _, topo, layout = city
    fault = {"fault_id": "f-1", "device_id": "WAT-02.water_level", "kind": "fake_reading", "start_tick": 1, "end_tick": None}
    evs = [ev("guardian", 1, 1, "verdict", {"device_id": "AIR-01.pm25", "score": 0.9}), ev("guardian", 2, 1, "verdict", {"device_id": "AIR-02.pm25", "score": 0.1}),
           ev("twin", 3, 2, "containment", {"tool": "isolate_sensor", "status": "applied", "changed": ["AIR-03.pm25"]}),
           ev("twin", 4, 2, "containment", {"tool": "quarantine_device", "status": "applied", "changed": ["AIR-04.pm25"]}),
           ev("twin", 5, 2, "scenario", {"phase": "started", "scenario_id": "sc-1", "name": "fake_reading", "faults": [fault]})]
    sc = city_scene(topo, layout, state_of(topo, evs))
    assert sc.content.count('<line x1="14" y1="14" x2="34" y2="34"') == 1           # AIR-02 untrusted: the X
    assert sc.content.count('<rect x="14" y="25" width="20" height="13"') == 2      # AIR-03 isolated and AIR-04 quarantined: the padlock
    assert sc.content.count(">Q</text>") == 1                                      # only the quarantined one has the Q badge
    assert "ATTACK" in sc.content and "<animate" in sc.content                      # the attack: title, pulsing ring and triangle
    quiet = city_scene(topo, layout, state_of(topo, evs), show_attacks=False).content
    assert "ATTACK" not in quiet and "<animate" not in quiet


def test_text_from_logs_can_never_break_out_of_the_svg(city):
    _, topo, layout = city
    evil = '</text><script>alert(1)</script><image href="x" onerror="alert(2)"/>&"\''
    evs = [ev("twin", 1, 1, "containment", {"tool": evil, "status": "applied", "changed": ["AIR-01.pm25"]}),
           ev("brain", 1, 2, "decision", {"incident": evil, "chosen_action": evil}),
           ev("brain", 2, 2, "escalation", {"reason": evil}), ev("twin", 2, 2, "scenario", {"phase": evil, "name": evil, "faults": []}),
           ev("brain", 3, 3, "partner_failure", {"partner": evil, "failure": evil}),
           ev("twin", 3, 3, "reading", {"device_id": evil, "value": evil, "unit": evil})]
    st = state_of(topo, evs)
    for sc in (timeline_scene(st, window_ticks=0), timeline_scene(st, selected="brain-000001", window_ticks=0), city_scene(topo, layout, st)):
        parse(sc)                                                                    # still well formed
        assert "<script" not in sc.content and "<image" not in sc.content and "onerror=\"" not in sc.content


def test_timeline_has_four_lanes_ticks_and_one_glyph_per_event():
    evs = [ev("twin", 1, 10, "reading", {"reading_id": "r1", "value": 180, "unit": "cm"}), ev("guardian", 1, 11, "verdict", {"device_id": "X", "score": 0.1, "reading_id": "r1"}, caused_by=["r1"]),
           ev("brain", 1, 12, "decision", {"incident": "i"}, caused_by=["guardian-000001"]), ev("twin", 2, 13, "action", {"action": "set_valve_position", "status": "committed", "token_id": "t"}),
           ev("twin", 3, 14, "containment", {"tool": "isolate_sensor", "status": "applied", "changed": ["X"]}), ev("brain", 2, 15, "escalation", {"reason": "r"})]
    st = build_state(evs, generate(load_config())[0], CUT, "run-42-001")
    sc = timeline_scene(st, window_ticks=0)
    parse(sc)
    assert len(sc.hits) == 6
    assert all(f">{t}<" in sc.content for t in ("Reading", "Verdict", "Decision", "Action"))
    assert sc.content.count('marker-end="url(#tl-arrow)"') == sum(len(v) for v in st.causes.values()) == 2


def test_timeline_window_cuts_old_events_and_follows_the_end():
    evs = [ev("twin", i, i, "reading", {"reading_id": f"r{i}", "value": i, "unit": "cm"}) for i in range(1, 41)]
    st = build_state(evs, generate(load_config())[0], CUT, "run-42-001")
    assert len(timeline_scene(st, window_ticks=10).hits) == 11 and len(timeline_scene(st, window_ticks=0).hits) == 40
    assert {h[0] for h in timeline_scene(st, window_ticks=5, end_tick=20).hits} == {f"twin-{i:06d}" for i in range(15, 21)}


def test_many_loose_events_on_one_tick_become_one_numbered_glyph_but_linked_ones_stay_single():
    loose = [ev("guardian", i, 5, "verdict", {"device_id": f"D{i}", "score": 0.9}) for i in range(1, 9)]
    linked = ev("guardian", 9, 5, "verdict", {"device_id": "WAT-01.water_level", "score": 0.1}, caused_by=["r1"])
    reading = ev("twin", 1, 4, "reading", {"reading_id": "r1", "value": 1, "unit": "cm"})
    st = build_state(sorted(loose + [linked, reading], key=lambda e: (e["tick"], e["event_id"])), generate(load_config())[0], CUT, "run-42-001")
    sc = timeline_scene(st, window_ticks=0)
    assert "8</text><title>8 events on tick 5" in sc.content                        # the cluster says how many
    assert any(h[0] == "guardian-000009" for h in sc.hits) and sum(1 for h in sc.hits if h[0].startswith("guardian-")) == 2    # linked + one cluster


def test_selecting_an_event_highlights_its_whole_chain_and_dims_the_rest():
    evs = [ev("twin", 1, 1, "reading", {"reading_id": "r1"}), ev("guardian", 1, 2, "verdict", {"device_id": "X"}, caused_by=["r1"]),
           ev("brain", 1, 3, "decision", {}, caused_by=["guardian-000001"]), ev("twin", 2, 4, "reading", {"reading_id": "r2"})]
    st = build_state(evs, generate(load_config())[0], CUT, "run-42-001")
    assert chain_of(st, "guardian-000001") == {"twin-000001", "guardian-000001", "brain-000001"}
    assert chain_of(st, "brain-000001") == chain_of(st, "twin-000001") and chain_of(st, None) == set() and chain_of(st, "nope") == set()
    assert timeline_scene(st, selected="guardian-000001", window_ticks=0).content.count('opacity="0.22"') == 1      # only the loner is dimmed
    assert timeline_scene(st, window_ticks=0).content.count('opacity="0.22"') == 0


def test_timeline_says_when_a_layer_has_not_written_anything_and_copes_with_an_empty_run():
    st = build_state([ev()], generate(load_config())[0], CUT, "run-42-001")
    c = timeline_scene(st, window_ticks=0).content
    assert "waiting for Guardian events" in c and "waiting for Brain events" in c
    empty = build_state([], generate(load_config())[0], CUT, "none")
    parse(timeline_scene(empty))


def test_simulated_clock_is_fitted_on_the_events():
    evs = [ev(tick=0, ts="2026-10-05T08:00:00.000Z"), ev(n=2, tick=10, ts="2026-10-05T08:00:10.000Z")]
    clock = tick_clock(evs)
    assert clock(5) == "08:00:05" and clock(20) == "08:00:20" and tick_clock([ev()])(3) == ""


def test_scene_picks_the_nearest_thing_within_reach():
    sc = Scene("", 100, 100, [("a", 10, 10), ("b", 50, 50)])
    assert sc.nearest(12, 11, 20) == "a" and sc.nearest(49, 60, 20) == "b" and sc.nearest(90, 90, 20) is None


# ====================================================================== the real sample story
@pytest.fixture(scope="module")
def sample_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("sample")
    write_sample(d)
    return d


def test_sample_story_has_all_four_lanes_real_twin_events_and_marked_partner_events(sample_dir, city):
    _, topo, layout = city
    lf = LogFollower([str(sample_dir)])
    lf.poll()
    events = lf.runs()["run-42-001"]
    kinds = {(e["layer"], e["event_type"]) for e in events}
    assert {("twin", "reading"), ("guardian", "verdict"), ("brain", "decision"), ("twin", "action"), ("twin", "containment"), ("brain", "escalation")} <= kinds
    assert all(e["data"].get("sample") is True for e in events if e["layer"] in ("guardian", "brain"))      # invented, and says so
    assert not any(e["data"].get("sample") for e in events if e["layer"] == "twin" and e["event_type"] != "scenario")
    st = build_state(events, topo, CUT, "run-42-001")
    assert [a["status"] for a in (e["data"] for e in events if e["event_type"] == "action")] == ["committed", "rejected"]
    committed = next(e for e in events if e["event_type"] == "action" and e["data"]["status"] == "committed")
    assert {st.by_id[c]["layer"] for c in st.causes[committed["event_id"]]} == {"guardian", "brain"}               # the chain really links up
    isolate = next(e for e in events if e["event_type"] == "containment")
    assert [st.by_id[c]["event_type"] for c in st.causes[isolate["event_id"]]] == ["verdict"]
    assert not any("true_value" in json.dumps(e) for e in events)                                                  # no truth in the shared log


# ====================================================================== the page
def make_hub(city, sources, **kw):
    cfg, topo, layout = city
    return Hub(DashboardCfg(refresh_seconds=0.2, **kw), topo, layout, sources=[str(s) for s in sources], fingerprint=fingerprint(topo))


def fire(element, type_, args):
    """Do what the browser would do: send an event to the listener of this type."""
    hits = [lst for lst in element._event_listeners.values() if lst.type == type_]
    assert hits, f"no {type_} listener on {element}"
    for lst in hits:
        element._handle_event({"listener_id": lst.id, "args": args})


async def test_page_shows_the_sample_story(city, sample_dir):
    hub = make_hub(city, [sample_dir])
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        for text in ("Triplet 04", "SAMPLE DATA", "run-42-001", "Needs a person", "A person must check the valve", "fake_reading on WAT-01.water_level",
                     "Partner failures", "no verdict for AIR-02", "All events", "Timeline"):
            await user.should_see(text)


async def test_page_with_no_logs_says_what_it_is_waiting_for(city, tmp_path):
    hub = make_hub(city, [tmp_path / "nothing-here"])
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        await user.should_see("Waiting for a run")
        await user.should_see("python -m twin.dashboard --sample")
        await user.should_not_see("All events")


async def test_clicking_the_map_selects_the_nearest_node_and_clicking_again_clears_it(city, sample_dir):
    _, topo, _ = city
    hub = make_hub(city, [sample_dir])
    x, y = display_positions(topo)["WAT-01"]
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        img = next(e for e in user.find(ui.interactive_image).elements if tuple(e._props["size"])[0] == 1920)     # the map (the other image is the timeline)
        click = {"mouse_event_type": "click", "image_x": x + 8, "image_y": y - 5, "button": 0, "buttons": 0,
                 "altKey": False, "ctrlKey": False, "metaKey": False, "shiftKey": False}
        fire(img, "mouse", click)
        await user.should_see("WAT-01 ·")
        await user.should_see("WAT-01.water_level")
        await user.should_see("isolated")
        fire(img, "mouse", click)
        await user.should_not_see("WAT-01 ·")
        fire(img, "mouse", {**click, "image_x": 5, "image_y": 5})                  # a click on empty map selects nothing
        await user.should_not_see("WAT-01 ·")


async def test_clicking_a_table_row_shows_the_event_and_where_it_came_from(city, sample_dir):
    hub = make_hub(city, [sample_dir])
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        table = next(iter(user.find(ui.table).elements))
        action = next(e for e in hub.follower.runs()["run-42-001"] if e["event_type"] == "action" and e["data"]["status"] == "committed")
        fire(table, "rowClick", [{}, {"id": action["event_id"]}, 0])
        await user.should_see("twin · action")
        await user.should_see("Came from: guardian verdict, brain decision")


def stat_value(user, key: str) -> str:
    """The number shown in one of the stat blocks of the top bar (they are marked `stat-<key>`)."""
    return next(iter(user.find(marker=f"stat-{key}").elements)).text


async def test_page_follows_a_log_that_is_still_growing(city, tmp_path):
    f = tmp_path / "run-42-001.twin.jsonl"
    write_lines(f, [ev("twin", 1, 1, "scenario", {"phase": "run_started"})])
    hub = make_hub(city, [tmp_path])
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        assert stat_value(user, "events") == "1"
        with open(f, "a") as h:
            h.write(json.dumps(ev("brain", 1, 2, "escalation", {"reason": "Please check the pump"})) + "\n")
        await asyncio.sleep(0.8)                                                    # the page looks again every 0.2 s
        await user.should_see("Please check the pump")
        assert stat_value(user, "events") == "2"


async def test_a_log_from_another_city_gets_a_warning(city, tmp_path):
    write_lines(tmp_path / "a.jsonl", [ev("twin", 1, 1, "scenario", {"phase": "run_started", "city_fingerprint": "deadbeef0000"})])
    hub = make_hub(city, [tmp_path])
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        await user.should_see("another city")


async def test_evil_text_from_a_log_is_shown_as_plain_text_everywhere(city, tmp_path):
    evil = '<img src=x onerror=alert(1)>'
    write_lines(tmp_path / "a.jsonl", [ev("brain", 1, 1, "escalation", {"reason": evil}), ev("brain", 2, 1, "decision", {"incident": evil})])
    hub = make_hub(city, [tmp_path])
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        await user.should_see(evil)                                                  # visible as text, not run as HTML
        html = (await user.http_client.get("/")).text
        assert "<img src=x" not in html and "&lt;img src=x" in html                  # only ever present as escaped text
        for img in user.find(ui.interactive_image).elements:
            assert "<img" not in img._props.get("content", "")


async def test_the_page_needs_no_internet(city, sample_dir):
    hub = make_hub(city, [sample_dir])
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        html = (await user.http_client.get("/")).text
        import re
        external = [u for u in re.findall(r'(?:src|href)="(https?://[^"]+)"', html)]
        assert external == [], external                                                # no CDN, no web fonts: it works with the Wi-Fi off


def test_the_launcher_builds_the_sample_and_starts_the_app(monkeypatch, tmp_path):
    from twin.dashboard import __main__ as launcher
    started = {}
    monkeypatch.setattr(launcher.ui, "run", lambda root, **kw: started.update(root=root, **kw))
    monkeypatch.setattr(launcher.tempfile, "mkdtemp", lambda prefix="": str(tmp_path))
    launcher.main(["--sample", "--port", "8123"])
    assert started["port"] == 8123 and started["reload"] is False and started["host"] == "127.0.0.1"
    assert (tmp_path / "run-42-001.twin.jsonl").exists() and (tmp_path / "run-42-001.guardian.jsonl").exists()


# ====================================================================== the look (node style spec, dark theme, made-up map)
from twin.dashboard.basemap import basemap                       # noqa: E402
from twin.dashboard.nodes import HEX, SIDES, glyph, side_colors  # noqa: E402
from twin.dashboard.page import legend_svg                       # noqa: E402
from twin.dashboard.style import DOMAIN_COLORS, SHARED_CORE, SWITCHED_OFF, TEXT  # noqa: E402

SPEC_HEX = "46,24 35,43.05 13,43.05 2,24 13,4.95 35,4.95"


def svg_ok(fragment: str) -> ET.Element:
    return ET.fromstring(f'<svg xmlns="http://www.w3.org/2000/svg">{fragment}</svg>')


def test_the_hexagon_is_exactly_the_one_in_the_node_style_spec():
    assert " ".join(f"{x:g},{y:g}" for x, y in HEX) == SPEC_HEX
    assert SIDES[0] == ((13, 4.95), (35, 4.95)) and SIDES[3] == ((35, 43.05), (13, 43.05))        # side 0 = top, side 3 = bottom
    g = glyph(100, 100, 44, ["water"], "trusted")
    svg_ok(g)
    assert f'<polygon points="{SPEC_HEX}" fill="none" stroke="{DOMAIN_COLORS["water"]}" stroke-width="3"' in g
    assert '<circle cx="24" cy="24" r="4"' in g


def test_the_four_trust_states_look_different_in_the_right_way():
    tr, de, un, iso = (glyph(0, 0, 44, ["water"], st) for st in ("trusted", "degraded", "untrusted", "isolated"))
    assert len({tr, de, un, iso}) == 4
    assert de.count("<line") == 4 and 'x1="13" y1="4.95" x2="35" y2="4.95"' not in de and 'x1="35" y1="43.05" x2="13" y2="43.05"' not in de   # top and bottom missing
    assert '<circle cx="24" cy="24" r="4"' in de                                                        # degraded keeps the dot
    assert 'x1="14" y1="14" x2="34" y2="34"' in un and 'x1="34" y1="14" x2="14" y2="34"' in un and '<circle cx="24" cy="24" r="4"' not in un
    assert 'd="M18 27 V18 A6 6 0 0 1 30 18 V27"' in iso and '<rect x="14" y="25" width="20" height="13"' in iso     # closed padlock, legs enter the body
    assert iso.count('stroke-width="2"/>') == 4 and '<circle cx="24" cy="24" r="4"' not in iso          # four corner brackets, no core dot


def test_shared_nodes_hand_out_their_sides_in_the_spec_order():
    a, b, c = (DOMAIN_COLORS[d] for d in ("traffic", "water", "power"))
    assert side_colors(["traffic"]) == [a] * 6
    assert side_colors(["water", "traffic"]) == [a, a, a, b, b, b]                       # traffic comes before water in the fixed order
    assert side_colors(["power", "water", "traffic"]) == [a, a, b, b, c, c]
    assert side_colors(["traffic", "water"], active={"water"}) == [b] * 6              # a switched-off domain is ignored, never left dark
    assert side_colors(["traffic"], active={"water"}) is None
    shared = glyph(0, 0, 44, ["traffic", "water"], "trusted")
    assert SHARED_CORE in shared and shared.count("<line") == 6 and f'<polygon points="{SPEC_HEX}" fill="none"' not in shared


def test_a_switched_off_layer_is_grey_but_an_isolated_node_keeps_its_lock():
    off = glyph(0, 0, 44, ["water"], "trusted", active={"power"})
    assert SWITCHED_OFF in off and DOMAIN_COLORS["water"] not in off and "fill-opacity" not in off     # grey, no halo
    iso = glyph(0, 0, 44, ["water"], "isolated", active={"power"})
    assert iso.count(f'stroke="{TEXT}"') >= 5                                                       # the lock and brackets stay bright


def test_the_map_is_quiet_names_only_where_something_is_going_on(city):
    _, topo, layout = city
    calm = city_scene(topo, layout, state_of(topo, [ev()])).content
    assert "stroke-width=\"7\" stroke-linejoin=\"round\"" not in calm                          # no node-name labels at all
    bad = [ev("guardian", 1, 1, "verdict", {"device_id": "AIR-02.pm25", "score": 0.1})]
    loud = city_scene(topo, layout, state_of(topo, bad)).content
    assert loud.count(">AIR-02</text>") == 2 and loud.count("stroke-width=\"7\" stroke-linejoin=\"round\"") == 1     # one label (a dark outline text plus the bright one)


def test_hiding_a_layer_greys_its_nodes_only(city):
    _, topo, layout = city
    st = state_of(topo, [ev()])
    all_on = city_scene(topo, layout, st)
    water_off = city_scene(topo, layout, st, hidden={"water"})
    assert SWITCHED_OFF not in all_on.content and SWITCHED_OFF in water_off.content
    water_only = sum(1 for n in topo.nodes if n.domains == ["water"])
    assert water_off.content.count(f'stroke="{SWITCHED_OFF}" stroke-width="3"') == water_only


def test_the_map_is_one_connected_black_and_white_city(city):
    _, topo, layout = city
    pts = [display_positions(topo)[n.node_id] for n in topo.nodes]
    a = basemap(pts, 1920, 1080)
    assert a == basemap(pts, 1920, 1080)                                                             # no randomness: same positions, same picture
    assert svg_ok(a) is not None
    main, side = street_graph(pts)
    parent = list(range(len(pts)))

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x
    for i, j in main + side:
        parent[find(i)] = find(j)
    assert len({find(i) for i in range(len(pts))}) == 1                                              # every node is linked to every other: ONE city, not districts
    assert len(main) == len(pts) - 1                                                                 # the main roads are exactly the shortest way to link everything
    assert not set(main) & set(side)
    assert a.count("<path") >= 1 + 2 * (len(main) + len(side))                                       # outline + pale line + dark line for every road
    assert not any(z.name.upper() in a or z.name in a for z in layout.zones)                         # no district names on the map
    assert "<text" not in a and "<ellipse" not in a                                                  # no labels, no park blobs
    colours = set(re.findall(r'(?:fill|stroke)="(#[0-9A-Fa-f]{6})"', a))
    assert colours <= {"#04060B", "#E6ECF5"}                                                         # the map has only the dark and the white, nothing else


def test_every_node_sits_on_a_road_end_and_roads_do_not_cross_in_the_middle_of_nowhere(city):
    _, topo, _ = city
    pts = [display_positions(topo)[n.node_id] for n in topo.nodes]
    main, side = street_graph(pts)
    used = {i for e in main + side for i in e}
    assert used == set(range(len(pts)))                                                              # every node has at least one road


def test_street_graph_on_a_tiny_example():
    pts = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0), (100.0, 100.0)]
    main, side = street_graph(pts)
    assert len(main) == 3 and set(main) <= {(0, 1), (1, 2), (1, 3), (0, 3), (2, 3)}
    assert (0, 2) not in main + side                                                                 # node 1 sits on the line between 0 and 2, so no street skips it


def test_the_legend_is_drawn_with_the_real_node_pictures():
    root = ET.fromstring(legend_svg())
    text = ET.tostring(root, encoding="unicode")
    for word in ("Trusted", "Degraded", "Untrusted", "Isolated", "Shared node", "No verdict yet"):
        assert word in text
    assert text.count("polygon") >= 6                                                                # one hexagon per legend entry


async def test_page_has_layer_buttons_step_chips_and_still_no_browser_needed(city, sample_dir):
    hub = make_hub(city, [sample_dir])
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        for text in ("Layers", "Water", "Traffic", "Reading ·", "Verdict ·", "Decision ·", "Action ·", "Click a node for details"):
            await user.should_see(text)

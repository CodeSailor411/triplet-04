"""The 1 Nov dashboard rework: sessions, system events, real time, labels, legend, top bar and font."""
import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import timezone
from pathlib import Path

import pytest
from nicegui.testing import user_simulation

from twin.dashboard import style
from twin.dashboard.events import (build_state, display_type, format_wall, is_system, short_label, split_sessions, summarize)
from twin.dashboard.page import CSS, Hub, LEGEND_FONT, build_page, legend_svg
from twin.dashboard.svg import timeline_scene
from twin.generator import fingerprint, generate
from twin.settings import DashboardCfg, load_config

CUT = {"trusted": 0.8, "degraded": 0.5}


@pytest.fixture(scope="module")
def city():
    cfg = load_config()
    topo, layout = generate(cfg)
    return cfg, topo, layout


_n = 0


def ev(layer, tick, t, data=None, caused_by=None, wall_sec=None, wall=True, run="run-42-001"):
    """An event. `wall_sec` = seconds after 10:00:00 on the real clock (default: same as the tick)."""
    global _n
    _n += 1
    w = tick if wall_sec is None else wall_sec
    e = {"run_id": run, "event_id": f"{layer}-{_n:06d}", "timestamp": f"2026-10-05T08:{tick // 60:02d}:{tick % 60:02d}.000Z", "tick": tick,
         "layer": layer, "event_type": t, "caused_by": caused_by or [], "data": data or {}}
    if wall:
        e["wall"] = f"2026-11-01T10:{w // 60:02d}:{w % 60:02d}.123Z"
    return e


def start(tick=0, wall_sec=0, seed=42):
    return [ev("twin", tick, "scenario", {"phase": "run_started", "seed": seed, "nodes": 38}, wall_sec=wall_sec),
            ev("twin", tick, "scenario", {"phase": "twin_started"}, wall_sec=wall_sec)]


# ---------------------------------------------------------------- sessions (N1)
def test_a_start_event_pair_is_one_session_not_two():
    assert len(split_sessions(start())) == 1


def test_a_restart_with_the_same_run_id_makes_a_second_session():
    first = start(0, 0) + [ev("twin", 5, "reading", {"reading_id": "a"}, wall_sec=5)]
    second = start(0, 100) + [ev("twin", 3, "reading", {"reading_id": "b"}, wall_sec=103)]
    parts = split_sessions(first + second)
    assert [len(p) for p in parts] == [3, 3]
    assert {e["data"].get("reading_id") for e in parts[1]} == {None, "b"}          # the newest session holds only the new events


def test_a_clock_that_falls_back_starts_a_new_session_even_without_start_events():
    a = [ev("twin", t, "reading", {"reading_id": f"a{t}"}, wall_sec=t) for t in (10, 20, 30)]
    b = [ev("twin", t, "reading", {"reading_id": f"b{t}"}, wall_sec=100 + t) for t in (2, 4)]
    assert [len(p) for p in split_sessions(a + b)] == [3, 2]


def test_a_partner_that_lags_a_few_ticks_does_not_split_the_session():
    evs = start() + [ev("twin", 20, "reading", wall_sec=20), ev("guardian", 17, "verdict", {"device_id": "X", "score": 0.1}, wall_sec=21)]
    assert len(split_sessions(evs)) == 1


def test_events_with_no_real_clock_join_the_newest_session_that_began_before_their_tick():
    old = start(0, 0) + [ev("twin", 8, "reading", wall_sec=8)]
    new = start(0, 100) + [ev("twin", 3, "reading", wall_sec=103)]
    loose = ev("guardian", 2, "verdict", {"device_id": "X", "score": 0.2}, wall=False)
    parts = split_sessions(old + new + [loose])
    assert loose in parts[1] and loose not in parts[0]


def test_no_events_gives_one_empty_session():
    assert split_sessions([]) == [[]]


def test_the_hub_shows_only_the_newest_session_until_you_ask_for_all(city, tmp_path):
    cfg, topo, layout = city
    old = start(0, 0) + [ev("twin", 7, "reading", {"reading_id": "old", "value": 1, "unit": "cm"}, wall_sec=7)]
    new = start(0, 100) + [ev("twin", 2, "reading", {"reading_id": "new", "value": 2, "unit": "cm"}, wall_sec=102)]
    (tmp_path / "run-42-001.twin.jsonl").write_text("\n".join(json.dumps(e) for e in old + new) + "\n")
    hub = Hub(DashboardCfg(refresh_seconds=0.2), topo, layout, sources=[str(tmp_path)], fingerprint=fingerprint(topo))
    hub.poll()
    now, every = hub.state("run-42-001"), hub.state("run-42-001", all_sessions=True)
    assert now.sessions == every.sessions == 2
    assert now.tick == 2 and every.tick == 7
    assert len(now.events) == 3 and len(every.events) == 6


# ---------------------------------------------------------------- real time (R3)
def test_real_time_is_shown_to_the_millisecond_and_missing_when_the_log_has_none():
    e = ev("twin", 1, "reading")
    assert format_wall(e, timezone.utc) == "10:00:01.123"
    assert format_wall(ev("twin", 1, "reading", wall=False)) == ""
    assert format_wall({**e, "wall": "not a time"}) == ""


def test_real_time_puts_events_of_one_tick_in_order_and_is_in_the_hover_text(city):
    evs = [ev("twin", 10, "reading", {"reading_id": "r"}, wall_sec=30), ev("guardian", 10, "verdict", {"device_id": "A.x", "score": 0.1}, wall_sec=31)]
    sc = timeline_scene(build_state(evs, city[1], CUT, "run-42-001"), window_ticks=0)
    assert f"real time {format_wall(evs[0])}" in sc.content and f"real time {format_wall(evs[1])}" in sc.content


# ---------------------------------------------------------------- system events (N7) and wording (N4)
def test_lifecycle_events_are_called_system_but_keep_their_log_type():
    s, other = start()[0], ev("twin", 1, "scenario", {"phase": "started", "name": "fake_reading", "scenario_id": "s1"})
    assert is_system(s) and display_type(s) == "system" and s["event_type"] == "scenario"
    assert not is_system(other) and display_type(other) == "scenario"
    assert summarize(s) == "Run started (seed 42, 38 nodes)" and summarize(start()[1]) == "Twin started"


def test_system_events_stay_off_the_timeline_unless_asked(city):
    evs = start() + [ev("twin", 1, "scenario", {"phase": "started", "name": "fake_reading", "scenario_id": "s1"}),
                     ev("twin", 4, "scenario", {"phase": "run_ended"}, wall_sec=4)]
    st = build_state(evs, city[1], CUT, "run-42-001")
    quiet, loud = timeline_scene(st, window_ticks=0), timeline_scene(st, window_ticks=0, show_system=True)
    assert len(quiet.hits) == 1 and len(loud.hits) == 4                         # only the real scenario start, then all of them


def test_a_token_verdict_has_real_words_not_none():
    ok = ev("guardian", 1, "verdict", {"device_id": None, "score": 0.9, "token_id": "t", "approved_action": "set_signal_plan"})
    no = ev("guardian", 1, "verdict", {"device_id": None, "score": 0.15, "refused": True})
    assert summarize(ok) == "token approved for set_signal_plan, score 0.9" and short_label(ok) == "token ok 0.9"
    assert summarize(no) == "token refused, score 0.15" and short_label(no) == "token refused 0.15"
    assert "None" not in summarize(ok) + summarize(no) + short_label(ok) + short_label(no)


def test_a_decision_does_not_say_the_action_twice():
    same = ev("brain", 1, "decision", {"incident": "set_signal_plan on TRF-01", "chosen_action": "set_signal_plan"})
    diff = ev("brain", 1, "decision", {"incident": "traffic jam at SH-05", "chosen_action": "set_signal_plan"})
    assert summarize(same) == "set_signal_plan on TRF-01" and summarize(diff) == "traffic jam at SH-05 -> set_signal_plan"


# ---------------------------------------------------------------- the timeline picture (N3)
def _text_sizes(sc):
    root = ET.fromstring(f"<svg xmlns='http://www.w3.org/2000/svg'>{sc.content}</svg>")
    return [t for t in root.iter("{http://www.w3.org/2000/svg}text") if t.get("font-size") == "17"]


def _chain(city):
    r = ev("twin", 5, "reading", {"reading_id": "r1", "value": 95, "unit": "percent"})
    v = ev("guardian", 5, "verdict", {"device_id": "TRF-01.vehicle_count", "score": 0.1, "reading_id": "r1"}, caused_by=[r["event_id"]])
    d = ev("brain", 6, "decision", {"incident": "jam", "chosen_action": "set_signal_plan"}, caused_by=[v["event_id"]])
    return build_state([r, v, d], city[1], CUT, "run-42-001"), (r, v, d)


def test_event_labels_are_off_by_default_on_with_the_switch_and_on_for_a_selected_chain(city):
    st, (r, v, d) = _chain(city)
    assert _text_sizes(timeline_scene(st, window_ticks=0)) == []
    words = lambda sc: {"".join(t.itertext()) for t in _text_sizes(sc)}                              # noqa: E731  (each label is drawn twice: outline + fill)
    assert len(words(timeline_scene(st, window_ticks=0, labels=True))) == 3
    assert len(words(timeline_scene(st, window_ticks=0, selected=v["event_id"]))) == 3                 # the chain gets its text without the switch


def test_nothing_in_the_plot_leaves_the_clip_rectangle_or_sits_on_the_lane_titles(city):
    st, _ = _chain(city)
    for sel in (None, "x"):
        sc = timeline_scene(st, window_ticks=0, labels=True)
        assert 'clip-path="url(#tl-clip)"' in sc.content and 'clipPath id="tl-clip"' in sc.content
        assert all(x >= 200 + 17 and x <= sc.width - 17 for _, x, _ in sc.hits), sc.hits


def test_labels_that_would_overlap_are_left_out_not_drawn_on_top_of_each_other(city):
    evs = [ev("twin", t, "reading", {"reading_id": f"r{t}", "value": 95, "unit": "percent"}) for t in range(1, 40)]
    st = build_state(evs, city[1], CUT, "run-42-001")
    sc = timeline_scene(st, window_ticks=0, labels=True)
    boxes = sorted((float(t.get("x")), t.get("text-anchor"), len("".join(t.itertext()))) for t in _text_sizes(sc) if t.get("stroke") is None)
    assert 0 < len(boxes) < 39                                                   # some got a label, not all
    assert len(sc.hits) == 39                                                    # every event is still clickable


# ---------------------------------------------------------------- legend (N6) and font
def test_the_legend_is_big_enough_and_narrow_enough_for_a_1366_screen():
    root = ET.fromstring(legend_svg())
    vb = [float(v) for v in root.attrib["viewBox"].split()]
    assert LEGEND_FONT >= 16 and vb[2] <= 700                                    # drawn at its natural size on a 1366 screen (map column is about 870 px)
    ys = {round(float(t.get("y"))) for t in root.iter("{http://www.w3.org/2000/svg}text")}
    assert len(ys) == 2                                                          # two rows


def test_the_font_is_inter_its_files_ship_with_the_dashboard_and_nothing_mentions_lato():
    folder = Path(style.__file__).parent / "fonts"
    assert style.FONT_NAME == "Inter" and style.FONT.startswith("Inter")
    for f in style.FONT_FILES.values():
        assert (folder / f).stat().st_size > 10_000
    assert "OFL" in (folder / "OFL.txt").read_text() or "Open Font License" in (folder / "OFL.txt").read_text()
    assert not list(folder.glob("lato*")) and "Lato" not in CSS and "Lato" not in style.FONT
    assert all(f"/tw-fonts/{f}" in CSS for f in style.FONT_FILES.values())


# ---------------------------------------------------------------- the page
def hub_for(city, folder):
    cfg, topo, layout = city
    return Hub(DashboardCfg(refresh_seconds=0.2, live_feed=False), topo, layout, sources=[str(folder)], fingerprint=fingerprint(topo))


def put(folder, events):
    (folder / "run-42-001.twin.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


def text_of(user, marker):
    return next(iter(user.find(marker=marker).elements)).text


async def test_the_top_bar_names_the_run_has_one_clock_and_one_status_chip(city, tmp_path):
    put(tmp_path, start() + [ev("twin", 9, "reading", {"reading_id": "r", "value": 1, "unit": "cm"}, wall_sec=9)])
    async with user_simulation(root=lambda: build_page(hub_for(city, tmp_path))) as user:
        await user.open("/")
        assert text_of(user, "run-title") == "Run 42-001 · seed 42"
        assert text_of(user, "clock-time") == "08:00:09" and text_of(user, "clock-tick") == "tick 9 · from log"
        assert text_of(user, "feed-status") == "Log only · no live feed"
        await user.should_not_see("Sim time")                                    # the second clock is gone
        await user.should_not_see("IDLE")


async def test_after_a_restart_only_the_new_session_is_shown_and_the_switch_brings_the_old_one_back(city, tmp_path):
    old = start(0, 0) + [ev("brain", 7, "escalation", {"reason": "OLD SESSION NOTE"}, wall_sec=7)]
    new = start(0, 100) + [ev("brain", 2, "escalation", {"reason": "NEW SESSION NOTE"}, wall_sec=102)]
    put(tmp_path, old + new)
    async with user_simulation(root=lambda: build_page(hub_for(city, tmp_path))) as user:
        await user.open("/")
        await user.should_see("NEW SESSION NOTE")
        await user.should_not_see("OLD SESSION NOTE")
        await user.should_see("1 earlier session hidden")
        sw = next(e for e in user.find(kind=__import__("nicegui").ui.switch).elements if e.text == "Show earlier sessions")
        sw.set_value(True)
        await asyncio.sleep(0.5)
        await user.should_see("OLD SESSION NOTE")


async def test_the_table_has_a_real_time_column_and_calls_lifecycle_events_system(city, tmp_path):
    put(tmp_path, start() + [ev("twin", 3, "reading", {"reading_id": "r", "value": 1, "unit": "cm"}, wall_sec=3)])
    async with user_simulation(root=lambda: build_page(hub_for(city, tmp_path))) as user:
        await user.open("/")
        table = next(iter(user.find(kind=__import__("nicegui").ui.table).elements))
        assert [c["label"] for c in table.columns][:2] == ["Sim time", "Real time"]
        assert {r["type"] for r in table.rows} == {"system", "reading"}
        assert all(r["real"] for r in table.rows)
        await user.should_not_see("run_started")


# ---------------------------------------------------------------- 2 Nov top bar
def test_the_top_bar_has_no_tiny_capital_caption_and_no_run_caption():
    """2 Nov screenshot: the counts used a 10 px, wide-spaced, all-capitals caption. They are now chips: bold number, name in normal case."""
    assert "tw-cap" not in CSS and "uppercase" not in CSS and "letter-spacing:.16em" not in CSS
    stat = CSS[CSS.index(".tw-stat-name"):].split("}}")[0]
    assert "font-size:13px" in stat
    import inspect
    from twin.dashboard import page
    src = inspect.getsource(page)
    assert "Switch run" not in src                                               # the run picker stands alone


def test_the_legend_wrapper_takes_the_full_card_width():
    """The legend sits in a card that shrinks its children to their content; the wrapper must be w-full so the pixel width can apply."""
    import inspect
    from twin.dashboard import page
    assert 'ui.html(legend_svg(), sanitize=False).classes("w-full px-2")' in inspect.getsource(page)


# ---------------------------------------------------------------- 2 Nov: run strip and map edge light
from twin.dashboard.svg import CHAR_W, city_scene                                  # noqa: E402


def _strip_texts(sc):
    """(left, right) box of every 18 px text of the run strip, per row (y)."""
    root = ET.fromstring(f"<svg xmlns='http://www.w3.org/2000/svg'>{sc.content}</svg>")
    rows = {}
    for t in root.iter("{http://www.w3.org/2000/svg}text"):
        if t.get("font-size") != "18" or t.get("text-anchor") not in ("start", "end"):
            continue
        w, x = len("".join(t.itertext())) * CHAR_W * 18 / 17, float(t.get("x"))
        rows.setdefault(t.get("y"), []).append((x, x + w) if t.get("text-anchor") == "start" else (x - w, x))
    return rows


def test_ten_system_markers_on_one_tick_become_one_dashed_line_with_one_label(city):
    evs = []
    for _ in range(5):
        evs += start(0, 0)
    evs += [ev("twin", 20, "scenario", {"phase": "run_ended"}, wall_sec=20)]
    sc = timeline_scene(build_state(evs, city[1], CUT, "run-42-001"), window_ticks=0, show_system=True)
    assert sc.content.count(">run started x5, twin started x5</text>") == 1                 # one visible label (the hover text holds it too)
    assert sc.content.count("stroke-dasharray=\"3 8\"") == 2                      # one dashed line for the tick-0 pile, one for run ended
    assert len(sc.hits) == 11                                                    # every event is still clickable


def test_system_events_sit_exactly_on_their_tick_not_in_side_by_side_slots(city):
    evs = start(0, 0) + [ev("twin", 0, "reading", {"reading_id": "r", "value": 1, "unit": "percent"}),
                         ev("twin", 10, "scenario", {"phase": "run_ended"}, wall_sec=10)]
    st = build_state(evs, city[1], CUT, "run-42-001")
    hits = {i: x for i, x, _ in timeline_scene(st, window_ticks=0, show_system=True).hits}
    xs = sorted({round(x) for x in hits.values()})
    assert len(xs) == 2                                                          # tick 0 and tick 10, nothing spread out between


def test_run_strip_texts_never_overlap_each_other(city):
    evs = start(0, 0) * 4 + [ev("twin", t, "scenario", {"phase": "started", "name": f"fake_reading_{t}", "scenario_id": f"s{t}"}) for t in range(1, 30)]
    evs += [ev("twin", 31, "scenario", {"phase": "run_ended"}, wall_sec=31)]
    sc = timeline_scene(build_state(evs, city[1], CUT, "run-42-001"), window_ticks=0, show_system=True)
    for boxes in _strip_texts(sc).values():
        boxes.sort()
        assert all(a[1] <= b[0] for a, b in zip(boxes, boxes[1:])), boxes

"""The dashboard's live values (dashboard/live.py) and the parts of the page that show them.

Two kinds of test: the reader against a REAL running Twin (right key, wrong key, Twin stops), and the reader fed by hand
(bad events, a new run, quiet, channels). The page parts are checked in NiceGUI's simulated browser, as in test_dashboard.py.
"""
import asyncio
import json
import time

import pytest
from conftest import KEYS, run_twin
from nicegui import ui
from nicegui.testing import user_simulation
from test_dashboard import ev, fire, make_hub, write_lines

from twin.dashboard import live as live_module
from twin.dashboard.live import LiveFeed, find_key
from twin.dashboard.page import build_page
from twin.dashboard.svg import display_positions
from twin.generator import generate
from twin.settings import Secrets, Settings, load_config


@pytest.fixture(scope="module")
def city():
    cfg = load_config()
    topo, layout = generate(cfg)
    return cfg, topo, layout


@pytest.fixture
def fast(config):
    """A fresh Twin whose clock runs fast (a tick every 50 ms)."""
    cfg = config.model_copy(deep=True)
    cfg.clock.autorun, cfg.clock.speed = True, 20.0
    with run_twin(Settings(config=cfg, secrets=Secrets(**KEYS))) as (url, _app):
        yield url


async def wait_for(condition, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.02)
    return False


async def start(feed):
    task = asyncio.create_task(feed.run())
    return task


async def stop(task):
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def readings_event(feed, tick, readings, run="run-42-001"):
    feed._handle("readings", json.dumps({"run_id": run, "tick": tick, "time": f"2026-10-05T08:00:{tick:02d}.000Z", "readings": readings}))


def one(device="WAT-01.water_level", node="WAT-01", sensor="water_level", value=77.5, unit="cm", tick=1, channel=None):
    return {"device_id": device, "node_id": node, "sensor": sensor, "value": value, "unit": unit, "tick": tick, "channel": channel}


# ---------------------------------------------------------------- against a real Twin
async def test_it_receives_every_sensors_newest_value_from_a_real_twin(fast):
    feed = LiveFeed(fast, KEYS["city_brain"])
    task = await start(feed)
    try:
        assert await wait_for(lambda: feed.version >= 3)
        text, live = feed.status()
        assert live is True and text == f"LIVE · tick {feed.tick}"
        assert feed.count == 120 and len(feed.latest) == 120                      # one value per sensor, 120 readings per tick
        row = feed.latest["WAT-01.water_level"]
        assert row["node_id"] == "WAT-01" and row["unit"] == "cm" and isinstance(row["value"], float)
        assert [r["device_id"] for r in feed.node_values("WAT-01")] == ["WAT-01.flow_rate", "WAT-01.water_level"]   # this node has two sensors, sorted
        newest = feed.tick
        assert await wait_for(lambda: feed.tick > newest)                         # and it keeps moving
    finally:
        await stop(task)


async def test_a_wrong_key_is_said_plainly_and_retried_slowly_not_hammered(fast, monkeypatch):
    monkeypatch.setattr(live_module, "REFUSED_RETRY_SECONDS", 30.0)
    feed = LiveFeed(fast, "not-the-right-key-1")
    task = await start(feed)
    try:
        assert await wait_for(lambda: feed.error is not None)
        text, live = feed.status()
        assert live is False and "refused the dashboard's key" in text and "401" in text
        assert feed.latest == {} and feed.version == 0
        assert not task.done()                                                     # it keeps living, it does not crash
    finally:
        await stop(task)


async def test_a_refused_key_is_not_retried_again_and_again(fast, monkeypatch):
    monkeypatch.setattr(live_module, "RETRY_SECONDS", 0.05)                        # a normal failure would retry this fast ...
    monkeypatch.setattr(live_module, "REFUSED_RETRY_SECONDS", 30.0)                # ... but a refused key must wait this long
    attempts = []
    original = LiveFeed._stream

    async def counting(self):
        attempts.append(1)
        return await original(self)

    monkeypatch.setattr(LiveFeed, "_stream", counting)
    feed = LiveFeed(fast, "not-the-right-key-1")
    task = await start(feed)
    await asyncio.sleep(1.0)
    await stop(task)
    assert len(attempts) == 1


async def test_a_twin_that_stops_makes_the_status_feed_lost(config):
    cfg = config.model_copy(deep=True)
    cfg.clock.autorun, cfg.clock.speed = True, 20.0
    feed = None
    with run_twin(Settings(config=cfg, secrets=Secrets(**KEYS))) as (url, _app):
        feed = LiveFeed(url, KEYS["city_brain"])
        task = await start(feed)
        assert await wait_for(lambda: feed.version >= 2)
    # the Twin is gone now
    assert await wait_for(lambda: feed.status()[1] is False, 10)
    text, _ = feed.status()
    assert text.startswith("feed lost") or text.startswith("feed quiet")
    await stop(task)


async def test_nothing_listening_at_the_address_is_feed_lost_not_a_crash():
    feed = LiveFeed("http://127.0.0.1:9", "some-key-1234")
    task = await start(feed)
    try:
        assert await wait_for(lambda: feed.error is not None)
        assert feed.status()[0].startswith("feed lost:") and feed.status()[1] is False
        assert not task.done()
    finally:
        await stop(task)


async def test_it_comes_back_by_itself_when_the_twin_comes_back(config, monkeypatch):
    monkeypatch.setattr(live_module, "RETRY_SECONDS", 0.2)
    cfg = config.model_copy(deep=True)
    cfg.clock.autorun, cfg.clock.speed = True, 20.0
    feed = LiveFeed("http://127.0.0.1:1", KEYS["city_brain"])            # wrong place first
    task = await start(feed)
    try:
        assert await wait_for(lambda: feed.error is not None)
        with run_twin(Settings(config=cfg, secrets=Secrets(**KEYS))) as (url, _app):
            feed.url = url + "/events"                                      # the Twin appears at a new address
            assert await wait_for(lambda: feed.version >= 2)
            assert feed.status()[1] is True and feed.error is None
    finally:
        await stop(task)


# ---------------------------------------------------------------- fed by hand
def test_no_key_means_the_feed_is_off_and_says_why():
    feed = LiveFeed("http://x", None)
    text, live = feed.status()
    assert feed.enabled is False and live is False and text.startswith("feed off: no key")


async def test_a_feed_with_no_key_does_not_even_try_to_connect():
    feed = LiveFeed("http://127.0.0.1:9", None)
    await asyncio.wait_for(feed.run(), 1)                                    # returns at once instead of looping forever


def test_a_new_run_forgets_the_old_values():
    feed = LiveFeed("http://x", "k-12345678")
    readings_event(feed, 5, [one(value=10.0)], run="run-42-001")
    readings_event(feed, 1, [one(device="AIR-01.pm25", node="AIR-01", sensor="pm25", value=20.0, unit="ug/m3")], run="run-42-002")
    assert list(feed.latest) == ["AIR-01.pm25"] and feed.run_id == "run-42-002" and feed.tick == 1


def test_a_newer_value_replaces_the_older_one_for_the_same_sensor():
    feed = LiveFeed("http://x", "k-12345678")
    readings_event(feed, 1, [one(value=10.0, tick=1)])
    readings_event(feed, 2, [one(value=11.0, tick=2)])
    assert feed.latest["WAT-01.water_level"]["value"] == 11.0 and feed.latest["WAT-01.water_level"]["tick"] == 2 and feed.version == 2


def test_a_bad_event_is_skipped_and_the_feed_carries_on():
    feed = LiveFeed("http://x", "k-12345678")
    readings_event(feed, 1, [one()])
    feed._handle("readings", "{not json")
    feed._handle("readings", "[1, 2, 3]")                                    # valid JSON, wrong shape
    feed._handle("readings", json.dumps({"run_id": "run-42-001", "tick": 2, "readings": [{"device_id": "x"}, "text", 5, one(device="AIR-01.pm25", node="AIR-01")]}))
    assert sorted(feed.latest) == ["AIR-01.pm25", "WAT-01.water_level"]       # the old value stays, the good new one is added
    assert feed.count == 1 and feed.tick == 2                                # of the 4 entries only the good one counted


def test_a_channel_sensor_keeps_one_value_per_channel():
    feed = LiveFeed("http://x", "k-12345678")
    readings_event(feed, 1, [one(device="EMS-01.calls", node="EMS-01", sensor="calls", value=3.0, unit="calls/min", channel="fire"),
                             one(device="EMS-01.calls", node="EMS-01", sensor="calls", value=1.0, unit="calls/min", channel="medical")])
    assert sorted(feed.latest) == ["EMS-01.calls/fire", "EMS-01.calls/medical"]
    assert [r["channel"] for r in feed.node_values("EMS-01")] == ["fire", "medical"]


def test_no_value_is_kept_as_no_value():
    feed = LiveFeed("http://x", "k-12345678")
    readings_event(feed, 1, [one(value=None)])
    assert feed.latest["WAT-01.water_level"]["value"] is None


def test_the_status_goes_quiet_when_no_reading_arrives_for_a_while():
    feed = LiveFeed("http://x", "k-12345678")
    readings_event(feed, 7, [one()])
    assert feed.status() == ("LIVE · tick 7", True)
    feed.last_event = time.monotonic() - (live_module.QUIET_AFTER_SECONDS + 1)
    assert feed.status() == ("feed quiet (last tick 7)", False)


def test_the_key_comes_from_the_command_line_then_the_environment_then_the_env_file(monkeypatch, tmp_path):
    monkeypatch.setattr(live_module, "TWIN_ROOT", tmp_path)
    monkeypatch.delenv("TWIN_KEY_CITY_BRAIN", raising=False)
    assert find_key() is None
    (tmp_path / ".env").write_text("# note\nTWIN_KEY_CITY_BRAIN='from-file-123'\n", encoding="utf-8")
    assert find_key() == "from-file-123"
    monkeypatch.setenv("TWIN_KEY_CITY_BRAIN", "from-env-1234")
    assert find_key() == "from-env-1234"
    assert find_key("from-cli-1234") == "from-cli-1234"


# ---------------------------------------------------------------- the page
def run_dir(tmp_path, stand_in=False):
    data = {"stand_in": True} if stand_in else {}
    write_lines(tmp_path / "run-42-001.twin.jsonl", [ev(n=1, t="scenario", data={"phase": "twin_started"}),
                                                     ev(layer="guardian", n=1, tick=2, t="verdict", data={"device_id": "WAT-01.water_level", "score": 0.9, **data})])
    return tmp_path


def feed_with(readings, tick=7):
    feed = LiveFeed("http://x", "k-12345678")
    feed._handle("hello", json.dumps({"run_id": "run-42-001"}))
    readings_event(feed, tick, readings)
    return feed


async def test_the_header_chip_and_the_values_card_show_the_live_feed(city, tmp_path):
    hub = make_hub(city, [run_dir(tmp_path)])
    hub.live = feed_with([one(), one(device="AIR-01.pm25", node="AIR-01", sensor="pm25", value=20.0, unit="ug/m3")])
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        await user.should_see("LIVE · tick 7")
        await user.should_see("Live values")
        await user.should_see("2 readings per tick")
        await user.should_see("Click a node to see its values")


async def test_clicking_a_node_shows_its_own_live_values_with_units(city, tmp_path):
    _, topo, _ = city
    hub = make_hub(city, [run_dir(tmp_path)])
    hub.live = feed_with([one(value=77.5, unit="cm"), one(device="AIR-01.pm25", node="AIR-01", sensor="pm25", value=21.25, unit="ug/m3")])
    x, y = display_positions(topo)["WAT-01"]
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        img = next(e for e in user.find(ui.interactive_image).elements if tuple(e._props["size"])[0] == 1920)
        fire(img, "mouse", {"mouse_event_type": "click", "image_x": x + 8, "image_y": y - 5, "button": 0, "buttons": 0,
                            "altKey": False, "ctrlKey": False, "metaKey": False, "shiftKey": False})
        await user.should_see("77.5 cm")
        await user.should_not_see("21.25 ug/m3")                                  # another node's value is not shown


async def test_the_picked_nodes_value_follows_the_feed_tick_by_tick(city, tmp_path):
    _, topo, _ = city
    hub = make_hub(city, [run_dir(tmp_path)])
    hub.live = feed_with([one(value=77.5, unit="cm")], tick=7)
    x, y = display_positions(topo)["WAT-01"]
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        img = next(e for e in user.find(ui.interactive_image).elements if tuple(e._props["size"])[0] == 1920)
        fire(img, "mouse", {"mouse_event_type": "click", "image_x": x + 8, "image_y": y - 5, "button": 0, "buttons": 0,
                            "altKey": False, "ctrlKey": False, "metaKey": False, "shiftKey": False})
        await user.should_see("77.5 cm")
        readings_event(hub.live, 8, [one(value=81.5, unit="cm", tick=8)])
        await asyncio.sleep(1.2)                                                   # the page looks at the feed twice a second
        await user.should_see("81.5 cm")                                           # the card redrew, no log changed
        await user.should_not_see("77.5 cm")


async def test_a_new_tick_changes_the_chip_without_any_log_change(city, tmp_path):
    hub = make_hub(city, [run_dir(tmp_path)])
    hub.live = feed_with([one()], tick=7)
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        await user.should_see("LIVE · tick 7")
        readings_event(hub.live, 8, [one(value=80.0, tick=8)])
        await user.should_see("LIVE · tick 8")


async def test_a_lost_feed_says_why_on_the_page(city, tmp_path):
    hub = make_hub(city, [run_dir(tmp_path)])
    hub.live = LiveFeed("http://x", None)                                          # no key
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        await user.should_see("feed off: no key")


async def test_without_a_feed_there_is_no_values_card_and_no_chip(city, tmp_path):
    hub = make_hub(city, [run_dir(tmp_path)])                                      # live is None, like --no-feed
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        await user.should_see("All events")
        await user.should_not_see("Live values")
        await user.should_not_see("LIVE · tick")
        await user.should_not_see("feed off")


async def test_the_stand_in_badge_shows_only_when_an_event_is_marked(city, tmp_path):
    marked = tmp_path / "marked"
    plain = tmp_path / "plain"
    marked.mkdir(), plain.mkdir()
    async with user_simulation(root=lambda: build_page(make_hub(city, [run_dir(marked, stand_in=True)]))) as user:
        await user.open("/")
        await user.should_see("STAND-IN LAYERS")
    async with user_simulation(root=lambda: build_page(make_hub(city, [run_dir(plain)]))) as user:
        await user.open("/")
        await user.should_see("All events")
        await user.should_not_see("STAND-IN LAYERS")


async def test_a_value_with_markup_in_it_is_shown_as_text(city, tmp_path):
    hub = make_hub(city, [run_dir(tmp_path)])
    evil = "<script>alert(1)</script>"
    hub.live = feed_with([one(unit=evil)])
    _, topo, _ = city
    x, y = display_positions(topo)["WAT-01"]
    async with user_simulation(root=lambda: build_page(hub)) as user:
        await user.open("/")
        img = next(e for e in user.find(ui.interactive_image).elements if tuple(e._props["size"])[0] == 1920)
        fire(img, "mouse", {"mouse_event_type": "click", "image_x": x + 8, "image_y": y - 5, "button": 0, "buttons": 0,
                            "altKey": False, "ctrlKey": False, "metaKey": False, "shiftKey": False})
        await user.should_see(evil)

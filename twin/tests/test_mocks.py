"""The Twin team's stand-ins (mocks/mock_brain.py, mocks/mock_guardian.py), tested against a REAL Twin (R1).

Each test that changes the Twin gets its own fresh Twin, so tests cannot affect each other. The proof that a stand-in
did NOT act (refused, silent, blocked) is that the next real action gets the very first action number, ac-00001.
"""
import asyncio
import base64
import contextlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import KEYS, run_twin
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

from twin.settings import Secrets, Settings

MOCKS = Path(__file__).resolve().parents[1] / "mocks"
sys.path.insert(0, str(MOCKS))

import mock_common                                          # noqa: E402
from mock_brain import MockBrain                            # noqa: E402
from mock_common import MockError, TwinClient               # noqa: E402
from mock_guardian import MockGuardian                      # noqa: E402

SIGNAL = ("set_signal_plan", ["TRF-01"], {"plan": "normal"})
VALVE = ("set_valve_position", ["WAT-03"], {"position": 25})


@pytest.fixture
def fresh(settings):
    """A new Twin whose clock stands still at tick 0."""
    with run_twin(settings) as (url, _app):
        yield url


@pytest.fixture
def fast(config):
    """A new Twin whose clock runs fast (a tick every 50 ms), for the scripted incident."""
    cfg = config.model_copy(deep=True)
    cfg.clock.autorun, cfg.clock.speed = True, 20.0
    with run_twin(Settings(config=cfg, secrets=Secrets(**KEYS))) as (url, _app):
        yield url


@pytest.fixture
def signed(config):
    """A new Twin that checks Ed25519 signatures. Yields (url, private key as base64, a different private key)."""
    def make():
        key = Ed25519PrivateKey.generate()
        return key, base64.b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()

    good, good_private = make()
    _, other_private = make()
    cfg = config.model_copy(deep=True)
    cfg.tokens.mode = "signed"
    cfg.tokens.guardian_public_key = base64.b64encode(good.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    with run_twin(Settings(config=cfg, secrets=Secrets(**KEYS))) as (url, _app):
        yield url, good_private, other_private


@contextlib.asynccontextmanager
async def stand_ins(url, mode="approve", timeout=3.0, private_key=None, slow_seconds=2.0, scenario=False):
    async with TwinClient(url, KEYS["city_brain"]) as brain_twin, TwinClient(url, KEYS["guardian"]) as guardian_twin:
        guardian = MockGuardian(guardian_twin, mode=mode, private_key=private_key, slow_seconds=slow_seconds)
        brain = MockBrain(brain_twin, guardian, timeout)
        if scenario:
            async with TwinClient(url, KEYS["scenario"]) as scenario_twin:
                yield brain, guardian, scenario_twin
        else:
            yield brain, guardian, None


async def next_action_id(brain) -> str:
    """Make one real action and say which action number it got. ac-00001 means nothing was committed before."""
    done = await brain.act(*SIGNAL)
    assert done["outcome"] == "committed", done
    return done["twin_answers"][0]["action_id"]


# ---------------------------------------------------------------- the path works
async def test_approved_action_is_committed_by_the_twin(fresh):
    async with stand_ins(fresh) as (brain, _g, _s):
        done = await brain.act(*SIGNAL)
    answer = done["twin_answers"][0]
    assert done["outcome"] == "committed" and done["token_format"] == "unsigned"
    assert answer["action"] == "set_signal_plan" and answer["targets"] == ["TRF-01"] and answer["replayed"] is False
    assert answer["action_id"] == "ac-00001" and answer["token_id"] == done["token_id"]


async def test_an_action_that_needs_a_preview_is_previewed_first(fresh):
    """The Twin refuses a valve action without a fresh preview, so a commit proves the preview step ran."""
    async with stand_ins(fresh) as (brain, _g, _s):
        done = await brain.act(*VALVE)
    assert done["outcome"] == "committed"


async def test_a_blocked_preview_means_nothing_is_sent(fresh):
    too_many = ["WAT-01", "WAT-03", "SH-03"]                     # the water action cap is 2 nodes per request
    async with stand_ins(fresh) as (brain, _g, _s):
        blocked = await brain.act("set_valve_position", too_many, {"position": 5})
        assert blocked == {"outcome": "not_sent", "reason": "PREVIEW_BLOCKED", "blocked_by": ["CAP_EXCEEDED"]}
        assert await next_action_id(brain) == "ac-00001"


# ---------------------------------------------------------------- Guardian says no, is slow, or is silent
async def test_guardian_refuses_so_the_brain_sends_nothing(fresh):
    async with stand_ins(fresh, mode="refuse") as (brain, _g, _s):
        refused = await brain.act(*SIGNAL)
    assert refused["outcome"] == "not_sent" and refused["reason"] == "GUARDIAN_REFUSED"
    assert refused["refusal_code"] == "MOCK_REFUSED"
    async with stand_ins(fresh) as (brain, _g, _s):                # same Twin, now an approving Guardian
        assert await next_action_id(brain) == "ac-00001"          # the refused request never reached the Twin


async def test_silent_guardian_ends_in_a_timeout_not_a_hang(fresh):
    async with stand_ins(fresh, mode="silent", timeout=0.3) as (brain, _g, _s):
        started = time.monotonic()
        result = await brain.act(*SIGNAL)
        took = time.monotonic() - started
    assert result["reason"] == "GUARDIAN_TIMEOUT" and result["outcome"] == "not_sent"
    assert took < 2.0
    async with stand_ins(fresh) as (brain, _g, _s):
        assert await next_action_id(brain) == "ac-00001"


async def test_slow_guardian_is_waited_for_within_the_timeout_and_cut_off_beyond_it(fresh):
    async with stand_ins(fresh, mode="slow", slow_seconds=0.3, timeout=3.0) as (brain, _g, _s):
        assert (await brain.act(*SIGNAL))["outcome"] == "committed"
    async with stand_ins(fresh, mode="slow", slow_seconds=5.0, timeout=0.3) as (brain, _g, _s):
        assert (await brain.act(*SIGNAL))["reason"] == "GUARDIAN_TIMEOUT"


# ---------------------------------------------------------------- exactly once
async def test_the_same_request_sent_three_times_acts_once(fresh):
    async with stand_ins(fresh) as (brain, _g, _s):
        done = await brain.act(*SIGNAL, idempotency_key="same-key", sends=3)
        answers = done["twin_answers"]
        assert [a["replayed"] for a in answers] == [False, True, True]
        assert {a["action_id"] for a in answers} == {"ac-00001"}
        assert await next_action_id(brain) == "ac-00002"          # only ONE action was ever committed before this


# ---------------------------------------------------------------- signed tokens (Guardian's g1 format)
async def test_a_signed_twin_accepts_the_mock_guardians_g1_token(signed):
    url, private, _other = signed
    async with stand_ins(url, private_key=private) as (brain, _g, _s):
        done = await brain.act(*SIGNAL)
    assert done["outcome"] == "committed" and done["token_format"] == "g1"


async def test_a_signed_twin_refuses_a_token_signed_with_the_wrong_key(signed):
    url, _private, other = signed
    async with stand_ins(url, private_key=other) as (brain, _g, _s):
        done = await brain.act(*SIGNAL)
    assert done["outcome"] == "rejected" and done["twin_answers"][0]["code"] == "TOKEN_INVALID"


async def test_a_signed_twin_without_a_private_key_gives_a_clear_message(signed, monkeypatch):
    monkeypatch.delenv("MOCK_GUARDIAN_PRIVATE_KEY", raising=False)
    url, _private, _other = signed
    async with stand_ins(url) as (brain, _g, _s):
        with pytest.raises(MockError, match="private"):
            await brain.act(*SIGNAL)


# ---------------------------------------------------------------- Guardian's containment calls
async def test_the_mock_guardian_can_isolate_and_release_a_sensor(fresh):
    device = "WAT-01.water_level"
    async with stand_ins(fresh) as (brain, guardian, _s):
        assert (await guardian.isolate([device], "stuck sensor"))["status"] == "applied"
        state = await brain.twin.call("get_containment_state")      # the Brain may read it
        assert [(d["device_id"], d["state"], d["reason"]) for d in state["devices"]] == [(device, "isolated", "stuck sensor")]
        assert (await guardian.release([device]))["released"] == [device]
        assert (await brain.twin.call("get_containment_state"))["devices"] == []


# ---------------------------------------------------------------- the scripted jam
async def test_a_calm_city_is_not_an_incident(fast):
    async with stand_ins(fast) as (brain, _g, _s):
        result = await brain.incident(wait_seconds=1.5, poll_seconds=0.02)
        assert result["outcome"] == "no_incident" and result["jam"] is False and result["ticks_seen"] > 5
        assert await next_action_id(brain) == "ac-00001"          # a calm day: the Brain did not overreact


async def test_a_fake_jam_makes_one_signal_change_and_is_cleaned_up_afterwards(fast):
    async with stand_ins(fast, scenario=True) as (brain, _g, scenario):
        first = await brain.incident(wait_seconds=20, poll_seconds=0.02, scenario=scenario)
        answer = first["twin_answers"][0]
        assert first["outcome"] == "committed" and answer["action"] == "set_signal_plan"
        assert answer["params"] == {"plan": "favor_main_road"} and len(answer["targets"]) == 1
        ticks = [e["tick"] for e in first["evidence"]]
        assert ticks[1] == ticks[0] + 1 and all(e["value"] >= 80 for e in first["evidence"])
        assert first["trigger"].startswith("fake reading")
        # The fake was stopped, so starting another one on the same sensor is allowed (otherwise: FAULT_ALREADY_ACTIVE).
        second = await brain.incident(wait_seconds=20, poll_seconds=0.02, scenario=scenario)
        assert second["outcome"] == "committed" and second["twin_answers"][0]["action_id"] != answer["action_id"]


async def test_a_fake_jam_with_a_refusing_guardian_changes_nothing(fast):
    async with stand_ins(fast, mode="refuse", scenario=True) as (brain, _g, scenario):
        result = await brain.incident(wait_seconds=20, poll_seconds=0.02, scenario=scenario)
        assert result["outcome"] == "not_sent" and result["reason"] == "GUARDIAN_REFUSED"
    async with stand_ins(fast) as (brain, _g, _s):
        assert await next_action_id(brain) == "ac-00001"


# ---------------------------------------------------------------- the jam counting, with no Twin at all
class ScriptedTwin:
    """Answers get_readings with a fixed list of (tick, value), one per call, and repeats the last one forever."""
    def __init__(self, script):
        self.script, self.i = list(script), 0

    async def call(self, tool, args=None):
        tick, value = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return {"tick": tick, "readings": [{"value": value}]}


async def watch(script, ticks=2, wait=0.3):
    return await MockBrain(ScriptedTwin(script), None).watch_for_jam("TRF-01", 80.0, ticks, wait, poll_seconds=0)


async def test_two_hot_ticks_in_a_row_are_a_jam():
    result = await watch([(1, 10), (2, 90), (3, 91)])
    assert result["jam"] is True and [e["tick"] for e in result["evidence"]] == [2, 3]


async def test_a_calm_tick_in_between_resets_the_count():
    assert (await watch([(1, 90), (2, 10), (3, 90)]))["jam"] is False


async def test_a_missed_tick_in_between_resets_the_count():
    assert (await watch([(1, 90), (3, 90)]))["jam"] is False          # tick 2 was never seen: not "in a row"
    assert (await watch([(1, 90), (3, 90), (4, 90)]))["jam"] is True  # but 3 and 4 are


async def test_no_value_is_not_a_hot_tick():
    assert (await watch([(1, None), (2, None), (3, 90)]))["jam"] is False


async def test_the_threshold_itself_counts():
    assert (await watch([(1, 80.0), (2, 80.0)]))["jam"] is True
    assert (await watch([(1, 79.9), (2, 79.9)]))["jam"] is False


async def test_the_same_tick_polled_twice_counts_once():
    assert (await watch([(1, 90), (1, 90), (1, 90)]))["jam"] is False


# ---------------------------------------------------------------- address and keys come from settings
def test_the_twin_address_comes_from_the_command_line_then_the_environment_then_config(monkeypatch):
    monkeypatch.delenv("TWIN_URL", raising=False)
    assert mock_common.twin_url("http://example:1/") == "http://example:1"
    monkeypatch.setenv("TWIN_URL", "http://from-env:2")
    assert mock_common.twin_url() == "http://from-env:2"
    monkeypatch.delenv("TWIN_URL")
    assert mock_common.twin_url() == "http://127.0.0.1:8000"          # `server` in config/twin.yaml


def test_keys_come_from_the_command_line_then_the_environment_then_the_env_file_and_never_from_nowhere(monkeypatch, tmp_path):
    monkeypatch.setattr(mock_common, "TWIN_ROOT", tmp_path)
    monkeypatch.delenv("TWIN_KEY_GUARDIAN", raising=False)
    with pytest.raises(MockError, match="TWIN_KEY_GUARDIAN"):
        mock_common.key_for("guardian")
    (tmp_path / ".env").write_text("# a comment\nTWIN_KEY_GUARDIAN=from-the-file\n", encoding="utf-8")
    assert mock_common.key_for("guardian") == "from-the-file"
    monkeypatch.setenv("TWIN_KEY_GUARDIAN", "from-env")
    assert mock_common.key_for("guardian") == "from-env"
    assert mock_common.key_for("guardian", "from-cli") == "from-cli"


async def test_an_unreachable_twin_gives_a_clear_message():
    with pytest.raises(MockError, match="Is it running"):
        async with TwinClient("http://127.0.0.1:9", "some-key-123"):
            pass


# ---------------------------------------------------------------- the command lines, as a person would run them
def run_cli(script, url, *args):
    env = {**os.environ, "TWIN_KEY_CITY_BRAIN": KEYS["city_brain"], "TWIN_KEY_GUARDIAN": KEYS["guardian"],
           "TWIN_KEY_SCENARIO": KEYS["scenario"]}
    command, rest = args[0], list(args[1:])             # the options go AFTER the command name
    return subprocess.run([sys.executable, str(MOCKS / script), command, "--url", url, *rest],
                          capture_output=True, text=True, env=env, timeout=60)


def test_command_line_mock_brain_acts_and_resends(fresh):
    done = run_cli("mock_brain.py", fresh, "act", "--action", "set_signal_plan", "--targets", "TRF-01",
                   "--params", '{"plan":"normal"}', "--idempotency-key", "cli-1", "--sends", "2")
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["outcome"] == "committed" and [a["replayed"] for a in out["twin_answers"]] == [False, True]


def test_command_line_options_work_after_the_command_name(fresh):
    done = run_cli("mock_brain.py", fresh, "act", "--guardian-mode", "refuse", "--action", "set_signal_plan",
                   "--targets", "TRF-01", "--params", '{"plan":"normal"}')
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["reason"] == "GUARDIAN_REFUSED"


def test_command_line_mock_guardian_makes_a_token_and_isolates(fresh):
    token = run_cli("mock_guardian.py", fresh, "token", "--action", "set_signal_plan", "--targets", "TRF-01",
                    "--params", '{"plan":"normal"}', "--idempotency-key", "cli-2")
    assert token.returncode == 0, token.stderr
    assert json.loads(token.stdout)["decision"] == "approved"
    isolate = run_cli("mock_guardian.py", fresh, "isolate", "--devices", "WAT-01.water_level", "--reason", "cli test")
    assert isolate.returncode == 0, isolate.stderr
    assert json.loads(isolate.stdout)["changed"] == ["WAT-01.water_level"]


def test_command_line_failure_is_a_message_and_exit_code_1_not_a_stack_trace():
    done = run_cli("mock_brain.py", "http://127.0.0.1:9", "act", "--action", "set_signal_plan", "--targets", "TRF-01")
    assert done.returncode == 1 and done.stderr.startswith("ERROR:") and "Traceback" not in done.stderr


# ================================================================== the stand-ins' run logs (27 Oct)
from mock_common import PartLog                                    # noqa: E402
from twin.dashboard.events import LogFollower, build_state, resolve_causes  # noqa: E402
from twin.generator import generate                                # noqa: E402
from twin.settings import load_config                              # noqa: E402


@pytest.fixture
def logged(config, tmp_path):
    """A fast Twin that writes its own run log into tmp_path/parts, so the chain can be read back like the dashboard does."""
    cfg = config.model_copy(deep=True)
    cfg.clock.autorun, cfg.clock.speed = True, 20.0
    cfg.logging.enabled = True
    cfg.logging.parts_dir, cfg.logging.merged_dir = str(tmp_path / "parts"), str(tmp_path / "merged")
    with run_twin(Settings(config=cfg, secrets=Secrets(**KEYS))) as (url, _app):
        yield url, tmp_path / "parts", tmp_path / "merged"


@contextlib.asynccontextmanager
async def logging_stand_ins(url, parts, mode="approve", timeout=3.0):
    async with TwinClient(url, KEYS["city_brain"]) as bt, TwinClient(url, KEYS["guardian"]) as gt, \
            TwinClient(url, KEYS["scenario"]) as scenario:
        guardian = MockGuardian(gt, mode=mode, log=PartLog("guardian", parts))
        yield MockBrain(bt, guardian, timeout, log=PartLog("brain", parts)), guardian, scenario


def read_run(parts):
    follower = LogFollower([str(parts)])
    follower.poll()
    runs = follower.runs()
    run_id = next(iter(runs))
    topo, _ = generate(load_config())
    return build_state(runs[run_id], topo, {"trusted": 0.8, "degraded": 0.5}, run_id)


def kinds(state):
    return [(e["layer"], e["event_type"]) for e in state.events if e["event_type"] != "scenario"]


def cause_chain(state, event):
    """Every event that led to `event`, found the way the dashboard draws its arrows."""
    seen, todo = [], [event["event_id"]]
    while todo:
        for c in state.causes.get(todo.pop(), []):
            if c not in seen:
                seen.append(c)
                todo.append(c)
    return [state.by_id[c] for c in seen]


async def test_the_whole_chain_reading_verdict_decision_action_is_in_the_logs(logged):
    url, parts, merged = logged
    async with logging_stand_ins(url, parts) as (brain, _g, scenario):
        result = await brain.incident(wait_seconds=20, poll_seconds=0.02, scenario=scenario)
    assert result["outcome"] == "committed"
    st = read_run(parts)
    action = next(e for e in st.events if e["event_type"] == "action")
    chain = {(e["layer"], e["event_type"]) for e in cause_chain(st, action)}
    assert {("guardian", "verdict"), ("brain", "decision"), ("twin", "reading")} <= chain       # reading -> verdict -> decision -> action
    verdict = next(e for e in st.events if e["event_type"] == "verdict")
    decision = next(e for e in st.events if e["event_type"] == "decision")
    assert st.causes[decision["event_id"]] == [verdict["event_id"]]
    assert verdict["data"]["token_id"] == action["data"]["token_id"]                          # how the Twin's action is joined to Guardian
    assert decision["data"]["idempotency_key"] == action["data"]["idempotency_key"]           # ... and to the Brain
    assert decision["data"]["incident"].startswith("traffic jam at ")


async def test_every_stand_in_event_is_marked_and_has_the_agreed_fields(logged):
    url, parts, _m = logged
    async with logging_stand_ins(url, parts) as (brain, _g, scenario):
        await brain.incident(wait_seconds=20, poll_seconds=0.02, scenario=scenario)
    st = read_run(parts)
    mine = [e for e in st.events if e["layer"] in ("guardian", "brain")]
    assert mine and all(e["data"]["stand_in"] is True for e in mine)
    assert not any(e["data"].get("stand_in") for e in st.events if e["layer"] == "twin")
    assert all(set(e) == {"run_id", "event_id", "timestamp", "tick", "wall", "layer", "event_type", "caused_by", "data"} for e in mine)
    assert all(e["event_id"].startswith(e["layer"] + "-") for e in mine)


async def test_the_twins_merge_after_the_scenario_stops_keeps_the_stand_in_events(logged):
    url, parts, merged = logged
    async with logging_stand_ins(url, parts) as (brain, _g, scenario):
        await brain.incident(wait_seconds=20, poll_seconds=0.02, scenario=scenario)   # stopping the fake makes the Twin merge
    text = next(merged.glob("*.jsonl")).read_text()
    layers = {json.loads(x)["layer"] for x in text.splitlines()}
    assert layers == {"twin", "guardian", "brain"} and "true_value" not in text


async def test_a_refusing_guardian_shows_as_a_low_verdict_a_decision_to_do_nothing_and_a_person_to_check(logged):
    url, parts, _m = logged
    async with logging_stand_ins(url, parts, mode="refuse") as (brain, _g, scenario):
        result = await brain.incident(wait_seconds=20, poll_seconds=0.02, scenario=scenario)
    assert result["reason"] == "GUARDIAN_REFUSED"
    st = read_run(parts)
    assert ("twin", "action") not in kinds(st)                                   # nothing was sent to the Twin
    verdict = next(e for e in st.events if e["event_type"] == "verdict")
    assert verdict["data"]["score"] == 0.15 and verdict["data"]["refused"] is True
    decision = next(e for e in st.events if e["event_type"] == "decision")
    assert decision["data"]["chosen_action"] is None and st.causes[decision["event_id"]] == [verdict["event_id"]]
    assert len(st.escalations) == 1 and "A person must check" in st.escalations[0]["data"]["reason"]
    device = verdict["data"]["device_id"]
    assert st.devices[device].trust == "untrusted"                               # the map shows the sensor as untrusted


async def test_a_silent_guardian_shows_as_a_partner_failure_and_a_person_to_check(logged):
    url, parts, _m = logged
    async with logging_stand_ins(url, parts, mode="silent", timeout=0.3) as (brain, _g, scenario):
        result = await brain.incident(wait_seconds=20, poll_seconds=0.02, scenario=scenario)
    assert result["reason"] == "GUARDIAN_TIMEOUT"
    st = read_run(parts)
    assert ("guardian", "verdict") not in kinds(st)                              # silent means silent: no verdict at all
    assert len(st.failures) == 1 and st.failures[0]["data"]["partner"] == "guardian"
    decision = next(e for e in st.events if e["event_type"] == "decision")
    assert decision["data"]["chosen_action"] is None and st.causes[decision["event_id"]] == [st.failures[0]["event_id"]]
    assert len(st.escalations) == 1


async def test_a_blocked_preview_is_logged_as_a_decision_to_do_nothing(logged):
    url, parts, _m = logged
    async with logging_stand_ins(url, parts) as (brain, _g, _s):
        result = await brain.act("set_valve_position", ["WAT-01", "WAT-03", "SH-03"], {"position": 5})
    assert result["reason"] == "PREVIEW_BLOCKED"
    st = read_run(parts)
    decision = next(e for e in st.events if e["event_type"] == "decision")
    assert decision["data"]["chosen_action"] is None and "CAP_EXCEEDED" in decision["data"]["reason"]
    assert len(st.escalations) == 1


async def test_isolating_with_a_log_writes_a_verdict_and_the_containment_event_points_at_it(logged):
    url, parts, _m = logged
    async with logging_stand_ins(url, parts) as (_b, guardian, _s):
        await guardian.isolate(["WAT-01.water_level"], "stuck sensor")
    st = read_run(parts)
    verdict = next(e for e in st.events if e["event_type"] == "verdict")
    containment = next(e for e in st.events if e["event_type"] == "containment")
    assert st.causes[containment["event_id"]] == [verdict["event_id"]]
    assert st.devices["WAT-01.water_level"].cut == "isolated" and st.devices["WAT-01.water_level"].trust == "untrusted"


async def test_without_a_log_nothing_is_written(fresh, tmp_path):
    async with stand_ins(fresh) as (brain, _g, _s):
        await brain.act(*SIGNAL)
    assert not list(tmp_path.glob("**/*.jsonl"))


def test_part_log_numbers_continue_after_a_restart_and_the_format_is_the_shared_one(tmp_path):
    stamp = {"run_id": "run-42-001", "tick": 7, "time": "2026-10-05T08:00:07.000Z"}
    first = PartLog("brain", tmp_path).write(stamp, "decision", {"chosen_action": None})
    second = PartLog("brain", tmp_path).write(stamp, "decision", {"chosen_action": None}, caused_by=[first])     # a new object = a restart
    assert (first, second) == ("brain-000001", "brain-000002")
    lines_ = [json.loads(x) for x in (tmp_path / "run-42-001.brain.jsonl").read_text().splitlines()]
    assert lines_[1]["caused_by"] == [first] and lines_[1]["tick"] == 7 and lines_[1]["layer"] == "brain"
    with pytest.raises(MockError):
        PartLog("twin", tmp_path)                                                   # the Twin writes its own file, not through this


def test_command_line_writes_logs_by_default_and_not_with_no_log(fresh, tmp_path):
    base = ["act", "--action", "set_signal_plan", "--targets", "TRF-01", "--params", '{"plan":"normal"}']
    off = run_cli("mock_brain.py", fresh, *base, "--no-log", "--log-dir", str(tmp_path / "off"))
    assert off.returncode == 0 and not (tmp_path / "off").exists()
    on = run_cli("mock_brain.py", fresh, *base, "--log-dir", str(tmp_path / "on"))
    assert on.returncode == 0, on.stderr
    assert sorted(p.name for p in (tmp_path / "on").glob("*.jsonl")) == ["run-42-001.brain.jsonl", "run-42-001.guardian.jsonl"]

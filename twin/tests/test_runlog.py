"""The run log: what the Twin writes, what it must never write, and the merge."""
import asyncio
import json

import pytest

from test_containment import world as cworld                    # noqa: F401  (shared helper style)
from twin.actions import ActionBook
from twin.auth import Identity
from twin.containment import ContainmentBook, _reading_id
from twin.generator import generate
from twin.logmerge import main as merge_main
from twin.runlog import RunLog, merge_parts, read_part
from twin.scenarios import ScenarioBook
from twin.settings import load_config
from twin.sim import Simulation
from twin.tokens import make_token

WAT = "WAT-01.water_level"


def build(tmp_path, tick=100, enabled=True):
    cfg = load_config()
    cfg.logging.enabled = enabled
    cfg.logging.parts_dir, cfg.logging.merged_dir = str(tmp_path / "parts"), str(tmp_path / "logs")
    topo, _ = generate(cfg)
    sim = Simulation(topo, cfg)
    sim.tick = tick
    book, cont, sc = ActionBook(topo, cfg, sim), ContainmentBook(topo, cfg, sim), ScenarioBook(sim)
    sim.overlay, sim.faults, book.containment = cont, sc, cont
    rl = RunLog(cfg.logging, sim, sc, {"seed": 42})
    book.recorder = cont.recorder = sc.recorder = rl
    return sim, book, cont, sc, rl, cfg


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def run(sc, name, params=None):
    return asyncio.run(sc.run(name, params))


def token(sim, action="set_valve_position", targets=("WAT-01",), params=None, jti="t-1"):
    return make_token({"iss": "guardian", "aud": "twin", "jti": jti, "run_id": sim.run_id, "iat": sim.clock.iso_of(sim.tick),
                       "exp": sim.clock.iso_of(sim.tick + 60), "action": action, "targets": list(targets),
                       "params": params or {"position": 30}, "score": 0.9})


# ------------------------------------------------------------------ the part file
def test_first_event_opens_the_run_and_every_line_has_the_agreed_fields(tmp_path):
    sim, _, cont, sc, rl, _ = build(tmp_path)
    cont.contain("isolate_sensor", ["AIR-01.pm25"], "stuck")
    ev = lines(rl.part_path(sim.run_id))
    assert [(e["event_type"], e["data"].get("phase")) for e in ev] == [("scenario", "run_started"), ("containment", None)]
    for e in ev:
        assert set(e) == {"run_id", "event_id", "timestamp", "tick", "wall", "layer", "event_type", "caused_by", "data"}
        assert e["run_id"] == "run-42-001" and e["layer"] == "twin" and e["tick"] == 100 and e["timestamp"].endswith("Z")
    assert [e["event_id"] for e in ev] == ["twin-000001", "twin-000002"]
    assert ev[0]["data"]["seed"] == 42
    assert ev[1]["data"] == {"tool": "isolate_sensor", "status": "applied", "changed": ["AIR-01.pm25"], "unchanged": [], "reason": "stuck"}


def test_disabled_log_writes_nothing_and_breaks_nothing(tmp_path):
    sim, _, cont, sc, rl, _ = build(tmp_path, enabled=False)
    cont.contain("isolate_sensor", ["AIR-01.pm25"])
    run(sc, "fake_reading")
    assert rl.record("x", {}) is None and not (tmp_path / "parts").exists()


def test_a_disk_problem_never_stops_the_twin(tmp_path):
    sim, _, cont, sc, rl, cfg = build(tmp_path)
    (tmp_path / "parts").write_text("I am a file, not a folder")                  # makes every write fail
    assert cont.contain("isolate_sensor", ["AIR-01.pm25"]).status == "applied"
    assert run(sc, "fake_reading").status == "started"


def test_a_restart_continues_the_numbering_instead_of_repeating_ids(tmp_path):
    sim, _, cont, _, rl, cfg = build(tmp_path)
    cont.contain("isolate_sensor", ["AIR-01.pm25"])
    sim2, _, cont2, _, rl2, _ = build(tmp_path)                                    # same run id again, like a restart
    cont2.contain("isolate_sensor", ["AIR-02.pm25"])
    ids = [e["event_id"] for e in lines(rl.part_path("run-42-001"))]
    assert ids == [f"twin-{i:06d}" for i in range(1, 5)] and len(set(ids)) == 4


# ------------------------------------------------------------------ scenario events
def test_scenario_start_and_stop_are_linked(tmp_path):
    sim, _, _, sc, rl, _ = build(tmp_path)
    sid = run(sc, "fake_reading").scenario_id
    run(sc, "stop", {"scenario_id": sid})
    ev = lines(rl.part_path(sim.run_id))
    start, stop = ev[1], ev[2]
    assert start["data"]["phase"] == "started" and start["data"]["faults"][0]["value"] == 180.0
    assert stop["data"]["phase"] == "stopped" and stop["caused_by"] == [start["event_id"]]
    assert rl.merged_path(sim.run_id).exists()                                     # stop leaves the merged file


def test_reset_closes_the_old_run_and_opens_a_new_one(tmp_path):
    sim, _, _, sc, rl, _ = build(tmp_path)
    run(sc, "fake_reading")
    old = sim.run_id
    run(sc, "reset")
    run(sc, "fake_reading", {"delay_ticks": 3})
    new = sim.run_id
    assert old != new
    old_ev = lines(rl.merged_path(old))
    assert old_ev[-1]["data"]["phase"] == "run_ended" and {e["run_id"] for e in old_ev} == {old}
    new_ev = lines(rl.part_path(new))
    assert [e["data"].get("phase") for e in new_ev] == ["run_started", "started"] and {e["run_id"] for e in new_ev} == {new}


# ------------------------------------------------------------------ faulted readings and the truth
def test_faulted_readings_are_logged_and_the_truth_stays_private(tmp_path):
    sim, _, _, sc, rl, _ = build(tmp_path, tick=100)
    started = run(sc, "fake_reading")                                              # fake from tick 102
    for t in range(100, 106):
        rl.log_tick(t)
    shared = [e for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "reading"]
    assert [e["tick"] for e in shared] == [102, 103, 104, 105]
    assert all(e["data"]["value"] == 180.0 and e["data"]["device_id"] == WAT for e in shared)
    scenario_event = lines(rl.part_path(sim.run_id))[1]["event_id"]
    assert all(e["caused_by"] == [scenario_event] for e in shared)
    private = lines(rl.private_path(sim.run_id))
    assert len(private) == 4 and all(p["reported_value"] == 180.0 and 20 < p["true_value"] < 70 for p in private)
    assert {p["event_id"] for p in private} == {e["event_id"] for e in shared}      # each private line points at its shared one
    # THE promise: no true value anywhere in what gets shared
    text = rl.part_path(sim.run_id).read_text() + rl.merged_path(sim.run_id).read_text() if rl.merged_path(sim.run_id).exists() \
        else rl.part_path(sim.run_id).read_text()
    assert "true_value" not in text and str(private[0]["true_value"]) not in text


def test_logging_a_tick_twice_is_the_followers_job_not_a_bug(tmp_path):
    sim, _, _, sc, rl, _ = build(tmp_path, tick=100)
    run(sc, "fake_reading")
    rl.log_tick(103)
    rl.log_tick(103)
    assert len([e for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "reading"]) == 2    # the follower never repeats a tick


def test_channel_fault_logs_only_that_channel_and_replay_keeps_the_old_reading_id(tmp_path):
    sim, _, _, sc, rl, _ = build(tmp_path, tick=100)
    run(sc, "fake_reading", {"device_id": "EMG-01.emergency_calls", "channel": "fire", "value": 40})
    run(sc, "replay_exact", {"device_id": "WAT-03.water_level", "lag_ticks": 10})
    rl.log_tick(105)
    got = {e["data"]["device_id"]: e["data"] for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "reading"}
    assert got["EMG-01.emergency_calls"]["channel"] == "fire" and len(got) == 2
    assert got["WAT-03.water_level"]["reading_id"] == "rd0000095-WAT-03.water_level" and got["WAT-03.water_level"]["reading_tick"] == 95


def test_an_isolated_faulted_device_is_not_logged_as_a_reading(tmp_path):
    sim, _, cont, sc, rl, _ = build(tmp_path, tick=100)
    run(sc, "fake_reading")
    cont.contain("isolate_sensor", [WAT])
    rl.log_tick(105)
    assert [e for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "reading"] == []


def test_the_follower_logs_every_tick_that_passes(tmp_path):
    async def go():
        sim, _, _, sc, rl, _ = build(tmp_path, tick=100)
        run_fault = await sc.run("fake_reading", {"delay_ticks": 1})
        task = asyncio.create_task(rl.follow_clock())
        await asyncio.sleep(0.05)
        for _ in range(3):
            await sim.advance(1)
            await asyncio.sleep(0.05)
        task.cancel()
        return [e["tick"] for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "reading"]
    ticks = asyncio.run(go())
    assert ticks == sorted(set(ticks)) and set(ticks) >= {101, 102, 103}


# ------------------------------------------------------------------ actions and containment
def test_actions_are_logged_with_the_token_id_but_never_the_token(tmp_path):
    sim, book, _, _, rl, _ = build(tmp_path)
    tok = token(sim)
    ok = book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-01"], {"position": 30}, tok, "k1")
    book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-01"], {"position": 30}, tok, "k1")       # repeat: not a new event
    bad = book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-01"], {"position": 30}, "garbage", "k2")
    acts = [e for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "action"]
    assert len(acts) == 2
    assert acts[0]["data"] == {"caller": "city_brain", "action": "set_valve_position", "targets": ["WAT-01"], "params": {"position": 30},
                               "idempotency_key": "k1", "status": "committed", "action_id": ok.action_id, "code": None, "token_id": "t-1"}
    assert acts[1]["data"]["status"] == "rejected" and acts[1]["data"]["code"] == bad.code and acts[1]["data"]["token_id"] is None
    assert tok not in rl.part_path(sim.run_id).read_text()


def test_refused_actions_after_the_token_still_carry_its_id(tmp_path):
    sim, book, cont, _, rl, _ = build(tmp_path)
    cont.contain("quarantine_device", [WAT])
    r = book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-01"], {"position": 30}, token(sim, jti="t-q"), "kq")
    assert r.code == "DEVICE_QUARANTINED" and r.token_id == "t-q"
    last = [e for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "action"][-1]
    assert last["data"]["code"] == "DEVICE_QUARANTINED" and last["data"]["token_id"] == "t-q"


def test_containment_events_cover_applied_refused_rollback_and_release(tmp_path):
    sim, _, cont, _, rl, _ = build(tmp_path)
    traffic = [f"TRF-{i:02d}.vehicle_count" for i in range(1, 7)]
    cont.contain("isolate_sensor", traffic)                                         # 6 nodes, cap 5: refused
    cont.rollback([_reading_id(100, next(d for d in sim.devices if d.device_id == WAT), None)])
    cont.release([WAT])
    c = [e["data"] for e in lines(rl.part_path(sim.run_id)) if e["event_type"] == "containment"]
    assert c[0]["status"] == "rejected" and c[0]["code"] == "CAP_EXCEEDED" and c[0]["details"]["cap"] == 5
    assert c[1]["tool"] == "rollback_reading" and c[1]["corrections"][0]["restored_from"] == f"rd0000099-{WAT}"
    assert c[2]["tool"] == "release_device" and c[2]["changed"] == [WAT]


# ------------------------------------------------------------------ merge
def write_part(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def ev(layer, n, tick, wall, t="verdict", run="run-42-001"):
    return {"run_id": run, "event_id": f"{layer}-{n:06d}", "timestamp": "2026-10-05T08:00:00.000Z", "tick": tick, "wall": wall,
            "layer": layer, "event_type": t, "caused_by": [], "data": {}}


def test_merge_orders_by_tick_then_real_clock_then_layer(tmp_path):
    a, b, out = tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "out" / "run.jsonl"
    write_part(a, [ev("twin", 1, 5, "2026-10-07T10:00:00.100Z", "reading"), ev("twin", 2, 6, "2026-10-07T10:00:01.000Z", "action")])
    write_part(b, [ev("guardian", 1, 5, "2026-10-07T10:00:00.300Z"), ev("brain", 1, 5, "2026-10-07T10:00:00.300Z", "decision"),
                   ev("guardian", 2, 4, "2026-10-07T10:00:09.000Z"), ev("brain", 2, 5, "2026-10-07T10:00:00.050Z", "decision")])
    merge_parts([a, b], out)
    # tick 4 first. Inside tick 5 the real clock wins over the layer name (brain-000002 happened first), a tie goes by layer.
    assert [e["event_id"] for e in lines(out)] == ["guardian-000002", "brain-000002", "twin-000001", "guardian-000001", "brain-000001",
                                                    "twin-000002"]


def test_merge_survives_a_half_written_last_line_and_junk(tmp_path):
    a, out = tmp_path / "a.jsonl", tmp_path / "run.jsonl"
    write_part(a, [ev("twin", 1, 1, "w1")])
    with open(a, "a") as f:
        f.write('{"run_id": "run-42-001", "event_id": "twin-00000')                     # the Twin died in the middle of a line
        f.write('\n\nnot json at all\n[1,2,3]\n')
    got, bad = read_part(a)
    assert len(got) == 1 and bad == 3
    merge_parts([a], out)
    assert len(lines(out)) == 1


def test_merge_refuses_two_different_runs_and_never_leaves_a_half_file(tmp_path):
    a, b, out = tmp_path / "a.jsonl", tmp_path / "b.jsonl", tmp_path / "run.jsonl"
    write_part(a, [ev("twin", 1, 1, "w")])
    write_part(b, [ev("guardian", 1, 1, "w", run="run-42-002")])
    with pytest.raises(ValueError):
        merge_parts([a, b], out)
    assert not out.exists() and not list(tmp_path.glob("*.tmp"))


def test_merge_can_run_again_and_gives_the_same_file(tmp_path):
    sim, _, cont, _, rl, _ = build(tmp_path)
    cont.contain("isolate_sensor", ["AIR-01.pm25"])
    first = rl.export().read_text()
    assert rl.export().read_text() == first


def test_command_line_merge_with_a_partner_part(tmp_path, capsys, monkeypatch):
    sim, _, cont, _, rl, cfg = build(tmp_path)
    cont.contain("isolate_sensor", ["AIR-01.pm25"])
    partner = tmp_path / "guardian.jsonl"
    write_part(partner, [ev("guardian", 1, 100, "2999-01-01T00:00:00.000Z")])
    monkeypatch.setattr("twin.logmerge.load_config", lambda: cfg)
    assert merge_main(["run-42-001", "--parts", str(partner)]) == 0
    assert "3 events from 2 part file(s)" in capsys.readouterr().out
    assert {e["layer"] for e in lines(tmp_path / "logs" / "run-42-001.jsonl")} == {"twin", "guardian"}
    assert merge_main(["run-42-999"]) == 1 and "No Twin part file" in capsys.readouterr().err


def test_the_example_config_and_gitignore_keep_the_part_files_out_of_the_repo():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    assert "run-logs/" in (root / ".gitignore").read_text().splitlines()
    cfg = load_config().logging
    assert cfg.enabled and cfg.parts_dir == "run-logs" and cfg.merged_dir == "../logs"

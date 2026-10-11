"""A made-up run to look at the dashboard (and to test it) before the partners' logs exist.

The Twin's events are REAL: this runs the real scenario engine, containment tools and `actuate` and lets the real run log write
them. The Guardian and Brain events are INVENTED stand-ins and every one carries `"sample": true` in its data, so nobody can
mistake them for the partners' real events. The story is the challenge's T5 case: a fake water level, Guardian's low score,
isolation, a refused command, an approved command, and an escalation to a person.

    python -m twin.dashboard --sample
"""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .. import runlog
from ..actions import ActionBook, BadRequest
from ..auth import Identity
from ..containment import ContainmentBook
from ..generator import generate
from ..runlog import RunLog
from ..scenarios import ScenarioBook
from ..settings import load_config
from ..sim import Simulation
from ..tokens import make_token

SAMPLE_RUN = "run-42-001"


def _run(coro):
    """Run a coroutine from normal code, also when an event loop is already running (for example inside the dashboard tests)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, coro).result()


def write_sample(out_dir: Path) -> str:
    """Write the sample part files into out_dir and return the run id."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{SAMPLE_RUN}.*"):
        old.unlink()
    cfg = load_config()
    cfg.logging.enabled = True
    cfg.logging.parts_dir, cfg.logging.merged_dir = str(out_dir), str(out_dir / "merged")
    topo, _ = generate(cfg)
    sim = Simulation(topo, cfg)
    book, cont, sc = ActionBook(topo, cfg, sim), ContainmentBook(topo, cfg, sim), ScenarioBook(sim)
    sim.overlay, sim.faults, book.containment = cont, sc, cont
    rl = RunLog(cfg.logging, sim, sc, {"seed": cfg.seed, "sample": True})
    book.recorder = cont.recorder = sc.recorder = rl

    clock = {"n": 0}
    base = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)

    def fake_wall() -> str:                                   # one steady clock for all layers, so the merge order is right
        clock["n"] += 1
        return (base + timedelta(milliseconds=40 * clock["n"])).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    real_wall, runlog._wall = runlog._wall, fake_wall
    counters = {"guardian": 0, "brain": 0}

    def partner(layer: str, etype: str, data: dict[str, Any], caused_by: list[str] | None = None) -> str:
        counters[layer] += 1
        eid = f"{layer}-{counters[layer]:06d}"
        line = {"run_id": sim.run_id, "event_id": eid, "timestamp": sim.clock.iso_of(sim.tick), "tick": sim.tick, "wall": fake_wall(),
                "layer": layer, "event_type": etype, "caused_by": caused_by or [], "data": {**data, "sample": True}}
        with open(out_dir / f"{sim.run_id}.{layer}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line, separators=(",", ":")) + "\n")
        return eid

    def token(jti: str, action: str, targets: list[str], params: dict[str, Any]) -> str:
        return make_token({"iss": "guardian", "aud": "twin", "jti": jti, "run_id": sim.run_id, "iat": sim.clock.iso_of(sim.tick),
                           "exp": sim.clock.iso_of(sim.tick + 120), "action": action, "targets": targets, "params": params, "score": 0.93})

    try:
        sim.tick = 0
        rl.record("scenario", {"phase": "twin_started"})
        for t in range(1, 9):
            sim.tick = t
            rl.log_tick(t)
        sim.tick = 8
        _run(sc.run("fake_reading", {"device_id": "WAT-01.water_level", "value": 180, "delay_ticks": 2}))   # fake from tick 10
        trusted = ["WAT-02.water_level", "WAT-03.water_level", "WAT-04.water_level", "TRF-01.vehicle_count", "TRF-02.vehicle_count",
                   "AIR-01.pm25", "PWR-01.load_kw", "PWR-02.load_kw"]
        reading_event: dict[int, str] = {}
        verdicts: dict[str, str] = {}
        for t in range(9, 31):
            sim.tick = t
            rl.log_tick(t)
            if t == 10:
                for d in trusted:
                    partner("guardian", "verdict", {"device_id": d, "score": 0.9})
            if t == 11:
                verdicts["low"] = partner("guardian", "verdict", {"device_id": "WAT-01.water_level", "score": 0.15,
                                                                  "reading_id": f"rd{10:07d}-WAT-01.water_level"},
                                          [f"rd{10:07d}-WAT-01.water_level"])
            if t == 12:
                cont.contain("isolate_sensor", ["WAT-01.water_level"], "score 0.15, far from its neighbours", [verdicts["low"]])
                partner("guardian", "verdict", {"device_id": "WAT-02.water_level", "score": 0.62})                      # one device a bit shaky
            if t == 14:
                partner("brain", "decision", {"incident": "flood risk near the port", "chosen_action": None,
                                              "reason": "WAT-01 is untrusted and isolated, no action without a trusted reading"},
                        [verdicts["low"]])
            if t == 16:                                                                                              # an approved command
                g = partner("guardian", "verdict", {"device_id": "WAT-03.water_level", "score": 0.93, "token_id": "t-sample-1",
                                                    "approved_action": "set_valve_position"})
                partner("brain", "decision", {"incident": "flood risk near the port", "chosen_action": "set_valve_position",
                                              "idempotency_key": "sample-k1"}, [g])
                book.actuate(Identity.CITY_BRAIN, "set_valve_position", ["WAT-03"], {"position": 40},
                             token("t-sample-1", "set_valve_position", ["WAT-03"], {"position": 40}), "sample-k1")
            if t == 20:                                                                                              # a refused command
                partner("brain", "decision", {"incident": "traffic jam on the ring", "chosen_action": "set_signal_plan",
                                              "idempotency_key": "sample-k2"})
                try:
                    book.actuate(Identity.CITY_BRAIN, "set_signal_plan", ["TRF-01"], {"plan": "favor_main_road"},
                                 token("t-sample-2", "set_valve_position", ["WAT-03"], {"position": 40}), "sample-k2")   # token is for another action
                except BadRequest:
                    pass
            if t == 24:
                partner("brain", "partner_failure", {"partner": "guardian", "failure": "no verdict for AIR-02 within 5 ticks",
                                                     "handled": "retry 2 of 3, used neighbour AIR-04"})
            if t == 26:
                d = partner("brain", "decision", {"incident": "flood risk near the port", "chosen_action": None,
                                                  "reason": "still no trusted sensor at the port"}, [verdicts["low"]])
                partner("brain", "escalation", {"reason": "No trusted water sensor at the port. A person must check the valve.",
                                                "incident": "flood risk near the port"}, [d])
        sim.tick = 30
        stop = _run(sc.run("stop", {"scenario_id": "sc-0001"}))
        rl.end_run()
    finally:
        runlog._wall = real_wall
    return sim.run_id

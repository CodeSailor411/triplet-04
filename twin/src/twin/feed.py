"""The live feed (SSE): which events a connected reader gets, and when.

Kept apart from app.py so the logic can be tested without a network: the tests drive this generator by hand,
one event at a time, and move the clock between events (that is exactly what a slow reader looks like to the server).
"""
import json
from collections.abc import AsyncIterator

from .sim import Simulation
from .util import now_iso

MAX_BACKLOG = 100       # a slow feed reader may fall this many ticks behind before it skips ahead


async def feed_events(sim: Simulation, *, seed: int, who: str, heartbeat_seconds: float,
                      max_events: int | None = None) -> AsyncIterator[dict]:
    """Yield SSE events: `hello` once, then one `readings` event per tick, plus `heartbeat` when nothing moved.
    A reader that starts now begins at the current tick. A reader more than MAX_BACKLOG ticks behind skips ahead,
    and the first event after the jump says how many ticks it skipped (`skipped_ticks`)."""
    sent = 0
    run_number, last = sim.run_number, sim.tick       # everything up to and including `last` counts as seen.
    # Fixed BEFORE `hello` goes out, so "you start at the tick named in hello" stays true even if the clock moves
    # before the reader takes the event.
    yield {"event": "hello", "data": json.dumps({"service": "twin", "seed": seed, "you_are": who,
                                                 "run_id": sim.run_id, "tick": last, "time": now_iso()})}
    sent += 1
    while max_events is None or sent < max_events:
        if not await sim.wait_for_change(run_number, last, heartbeat_seconds):
            yield {"event": "heartbeat", "data": json.dumps({"time": now_iso()})}
            sent += 1
            continue
        if sim.run_number != run_number:               # a new run started: begin at its current tick
            run_number, last = sim.run_number, sim.tick - 1
        first, skipped = last + 1, 0
        if sim.tick - last > MAX_BACKLOG:
            first, skipped = sim.tick, sim.tick - last - 1
        for tick in range(first, sim.tick + 1):
            batch = sim.readings_at(tick)
            payload = batch.model_dump()
            if skipped:
                payload["skipped_ticks"] = skipped
                skipped = 0
            yield {"event": "readings", "id": f"{batch.run_id}:{tick}", "data": json.dumps(payload)}
            sent += 1
            last = tick        # the last tick the reader was really given. NOT sim.tick: while we waited for a slow
            #                    reader the clock kept moving, and copying it here made those ticks vanish silently.
            if max_events is not None and sent >= max_events:
                return

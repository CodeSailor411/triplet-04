"""The live feed's catch-up rules, tested by driving the generator by hand (no network, no timing luck).

Holding the generator between two `anext` calls is the same as a reader that is not reading: the server is stuck
at a `yield` while the clock keeps moving. That is the situation the 17 Oct feed check found a bug in."""
import pytest

from twin.feed import MAX_BACKLOG, feed_events
from twin.generator import generate
from twin.settings import load_config
from twin.sim import Simulation


@pytest.fixture
def sim():
    cfg = load_config()
    cfg.clock.autorun = False
    return Simulation(generate(cfg)[0], cfg)


def _batches(events):
    return [(e["event"], __import__("json").loads(e["data"])) for e in events]


async def _take(gen, n):
    return [await anext(gen) for _ in range(n)]


async def test_clock_moves_while_reader_is_stuck_mid_batch_and_the_gap_is_reported(sim):
    """Reader is at tick 1 of a 5-tick batch, then the clock jumps 400 ticks. The reader must be TOLD it lost ticks."""
    await sim.advance(5)
    gen = feed_events(sim, seed=42, who="city_brain", heartbeat_seconds=0.05)
    await anext(gen)                                   # hello (reader starts at tick 5, seen)
    await sim.advance(5)                               # now ticks 6..10 are waiting
    first = await anext(gen)                           # tick 6 is sent, the generator is now stuck inside the batch
    assert _batches([first])[0][1]["tick"] == 6
    await sim.advance(400)                             # clock runs away while the reader is not reading
    rest = _batches(await _take(gen, 5))               # ticks 7..10 finish the old batch, then the next event
    assert [d["tick"] for _, d in rest[:4]] == [7, 8, 9, 10]
    name, jump = rest[4]
    assert name == "readings" and jump["tick"] == sim.tick == 410
    assert jump["skipped_ticks"] == 410 - 10 - 1       # ticks 11..409 were not sent, and the event says so


async def test_small_lag_is_delivered_in_full_with_no_skip(sim):
    """A reader that is behind by less than MAX_BACKLOG gets every tick in order and no skipped_ticks field."""
    gen = feed_events(sim, seed=42, who="city_brain", heartbeat_seconds=0.05)
    await anext(gen)
    await sim.advance(MAX_BACKLOG)                     # exactly at the limit: still delivered in full
    got = _batches(await _take(gen, MAX_BACKLOG))
    assert [d["tick"] for _, d in got] == list(range(1, MAX_BACKLOG + 1))
    assert all("skipped_ticks" not in d for _, d in got)


async def test_reader_that_never_reads_for_a_long_time_skips_ahead_with_a_count(sim):
    """No batch in progress: the reader is behind by more than the limit when it comes back."""
    gen = feed_events(sim, seed=42, who="city_brain", heartbeat_seconds=0.05)
    await anext(gen)
    await sim.advance(MAX_BACKLOG + 50)
    ev = _batches(await _take(gen, 1))[0][1]
    assert ev["tick"] == sim.tick and ev["skipped_ticks"] == MAX_BACKLOG + 49


async def test_quiet_clock_sends_heartbeats_and_nothing_else(sim):
    gen = feed_events(sim, seed=42, who="guardian", heartbeat_seconds=0.02)
    names = [e["event"] for e in await _take(gen, 3)]
    assert names == ["hello", "heartbeat", "heartbeat"]

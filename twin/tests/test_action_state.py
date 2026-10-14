"""Action state (14 Oct): used token IDs and idempotency answers, memory and Redis.

The Redis tests need a Redis server. They run only when TWIN_TEST_REDIS_URL is set, for example
  TWIN_TEST_REDIS_URL=redis://127.0.0.1:6379/15 python -m pytest tests/test_action_state.py
Without it they are skipped (and say so), so a plain `pytest` works on any machine.
Database 15 is used so a test never touches database 0. The tests delete only their own keys (prefix twin:run-).
"""
import os
import uuid
from datetime import datetime, timezone

import pytest

from test_actions import BRAIN, GRID, VALVE, claims
from twin.actions import ActionBook
from twin.generator import generate
from twin.settings import StorageCfg, load_config
from twin.sim import Simulation
from twin.storage import MemoryActionState, StateUnavailable, open_action_state
from twin.tokens import make_token

REDIS_URL = os.environ.get("TWIN_TEST_REDIS_URL")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="set TWIN_TEST_REDIS_URL to run the Redis tests")
NOW = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


def world(state, seed_suffix=None):
    cfg = load_config()
    topo, _ = generate(cfg)
    sim = Simulation(topo, cfg)
    return sim, ActionBook(topo, cfg, sim, state)


def valve(sim, book, jti, key, position=40, caller=BRAIN):
    token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": position}, jti=jti))
    return book.actuate(caller, VALVE, ["WAT-01"], {"position": position}, token, key)


class DownState(MemoryActionState):
    """A store that fails on purpose. `fail` says which call breaks."""
    def __init__(self, fail: str):
        super().__init__()
        self.fail = fail

    def _maybe(self, what):
        if self.fail == what:
            raise StateUnavailable("pretend Redis is down")

    def get_answer(self, *a):
        self._maybe("get_answer")
        return super().get_answer(*a)

    def jti_used(self, *a):
        self._maybe("jti_used")
        return super().jti_used(*a)

    def commit(self, *a):
        self._maybe("commit")
        return super().commit(*a)

    def next_action_number(self, *a):
        self._maybe("next_action_number")
        return super().next_action_number(*a)


# ------------------------------------------------------------------ memory backend and the choice of backend
def test_default_config_is_memory():
    cfg = load_config()
    assert cfg.storage.state == "memory"
    assert open_action_state(cfg.storage).name == "memory"


def test_redis_without_an_address_stops_the_start_with_a_clear_message(tmp_path):
    with pytest.raises(SystemExit, match="TWIN_REDIS_URL"):
        open_action_state(StorageCfg(state="redis"), environ={}, env_file=tmp_path / "no.env")


def test_memory_commit_spends_the_token_once():
    s = MemoryActionState()
    assert s.commit("run-1", "tk", NOW, "city_brain", "k", "fp", "{}") is True
    assert s.commit("run-1", "tk", NOW, "city_brain", "k2", "fp", "{}") is False
    assert s.get_answer("run-1", "city_brain", "k") == ("fp", "{}")
    assert s.get_answer("run-1", "city_brain", "k2") is None            # the refused commit stored nothing


# ------------------------------------------------------------------ fail safe (runs without any Redis)
@pytest.mark.parametrize("broken", ["get_answer", "jti_used", "next_action_number", "commit"])
def test_when_the_store_is_down_nothing_is_carried_out(broken):
    sim, book = world(DownState(broken))
    r = valve(sim, book, "tk-a", "k-a")
    assert r.status == "rejected" and r.code == "STATE_UNAVAILABLE"
    assert book.state == {} and book.seq == 0                            # no actuator moved, no action id used
    assert r.details["store"] == "memory"


def test_a_failed_commit_can_be_retried_with_the_same_token_and_key():
    store = DownState("commit")
    sim, book = world(store)
    assert valve(sim, book, "tk-a", "k-a").code == "STATE_UNAVAILABLE"
    store.fail = ""                                                      # Redis is back
    again = valve(sim, book, "tk-a", "k-a")
    assert again.status == "committed" and book.state[("WAT-01", VALVE)] == {"position": 40.0}


def test_input_errors_are_still_input_errors_when_the_store_is_down():
    from twin.actions import BadRequest
    sim, book = world(DownState("get_answer"))
    with pytest.raises(BadRequest):
        book.actuate(BRAIN, "no_such_action", ["WAT-01"], {}, "x", "k")


# ------------------------------------------------------------------ real Redis
@pytest.fixture
def redis_state():
    from twin.storage.actionstate import RedisActionState
    state = RedisActionState(REDIS_URL, timeout_seconds=0.5, ttl_seconds=600)
    yield state
    for k in state._r.scan_iter("twin:run-*"):
        state._r.delete(k)
    state.close()


@needs_redis
def test_redis_commit_is_all_or_nothing_and_spends_the_token_once(redis_state):
    run = f"run-t-{uuid.uuid4().hex[:6]}"
    assert redis_state.commit(run, "tk", NOW, "city_brain", "k", "fp", "{}") is True
    assert redis_state.commit(run, "tk", NOW, "city_brain", "k2", "fp", "{}") is False
    assert redis_state.jti_used(run, "tk", NOW) is True
    assert redis_state.get_answer(run, "city_brain", "k") == ("fp", "{}")
    assert redis_state.get_answer(run, "city_brain", "k2") is None       # refused commit left no answer behind
    assert redis_state.jti_used("run-other", "tk", NOW) is False         # another run is another namespace


@needs_redis
def test_redis_keys_expire(redis_state):
    run = f"run-t-{uuid.uuid4().hex[:6]}"
    redis_state.commit(run, "tk", NOW, "city_brain", "k", "fp", "{}")
    ttl = redis_state._r.ttl(f"twin:{run}:jti:tk")
    assert 0 < ttl <= 600


@needs_redis
def test_a_restart_does_not_allow_a_token_replay(redis_state):
    """The point of the whole feature. Same run id before and after the restart (our known run-id reuse)."""
    sim, book = world(redis_state)
    jti = f"tk-{uuid.uuid4().hex[:6]}"
    token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}, jti=jti))
    assert book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "first").status == "committed"

    sim2, book2 = world(redis_state)                                    # "restart": a brand new Twin, same run id
    assert sim2.run_id == sim.run_id
    replay = book2.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "a-new-key")
    assert replay.status == "rejected" and replay.code == "TOKEN_REUSED"
    assert book2.state == {}


@needs_redis
def test_memory_alone_would_have_allowed_that_replay():
    """Proof that the test above tests something: with the memory store the replay after a restart WORKS."""
    sim, book = world(MemoryActionState())
    token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}, jti="tk-mem"))
    assert book.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "first").status == "committed"
    sim2, book2 = world(MemoryActionState())
    assert book2.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "a-new-key").status == "committed"


@needs_redis
def test_a_restart_still_gives_the_first_answer_to_a_repeated_key(redis_state):
    sim, book = world(redis_state)
    key = f"key-{uuid.uuid4().hex[:6]}"
    first = valve(sim, book, f"tk-{uuid.uuid4().hex[:6]}", key)
    sim2, book2 = world(redis_state)
    again = valve(sim2, book2, f"tk-{uuid.uuid4().hex[:6]}", key)      # a fresh token, same key, same request
    assert again.replayed and again.action_id == first.action_id and again.status == "committed"
    assert book2.state == {}                                           # replayed answer: no second action
    changed = valve(sim2, book2, f"tk-{uuid.uuid4().hex[:6]}", key, position=60)
    assert changed.code == "IDEMPOTENCY_CONFLICT"


@needs_redis
def test_action_numbers_keep_counting_after_a_restart(redis_state):
    """Found by the live crash test: after a restart the first new action got ac-00001 again, the same ID as an
    old stored answer."""
    sim, book = world(redis_state)
    first = valve(sim, book, f"tk-{uuid.uuid4().hex[:6]}", f"key-{uuid.uuid4().hex[:6]}")
    sim2, book2 = world(redis_state)                                    # restart
    second = valve(sim2, book2, f"tk-{uuid.uuid4().hex[:6]}", f"key-{uuid.uuid4().hex[:6]}", position=55)
    n1, n2 = int(first.action_id[3:]), int(second.action_id[3:])
    assert n2 == n1 + 1


@needs_redis
def test_two_twins_racing_for_one_token_only_one_wins(redis_state):
    """Two processes sharing one Redis: the Lua step lets exactly one commit."""
    sim, book_a = world(redis_state)
    _, book_b = world(redis_state)
    token = make_token(claims(sim, VALVE, ["WAT-01"], {"position": 40}, jti=f"tk-{uuid.uuid4().hex[:6]}"))
    a = book_a.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "ka")
    b = book_b.actuate(BRAIN, VALVE, ["WAT-01"], {"position": 40}, token, "kb")
    assert sorted([a.status, b.status]) == ["committed", "rejected"]
    assert b.code == "TOKEN_REUSED"


@needs_redis
def test_redis_server_stops_in_the_middle_then_returns(redis_state):
    """Break the connection on purpose: refused with STATE_UNAVAILABLE, then fine again after it is back."""
    sim, book = world(redis_state)
    good = redis_state._r
    redis_state._r = type(good)(host="127.0.0.1", port=1, socket_timeout=0.2, socket_connect_timeout=0.2)   # nothing listens on port 1
    r = valve(sim, book, f"tk-{uuid.uuid4().hex[:6]}", "down-1")
    assert r.code == "STATE_UNAVAILABLE" and book.state == {}
    redis_state._r = good
    assert valve(sim, book, f"tk-{uuid.uuid4().hex[:6]}", "down-2").status == "committed"


@needs_redis
def test_health_status_reports_redis(redis_state):
    assert redis_state.status() == {"backend": "redis", "ok": True}
    good = redis_state._r
    redis_state._r = type(good)(host="127.0.0.1", port=1, socket_timeout=0.2, socket_connect_timeout=0.2)
    st = redis_state.status()
    assert st["ok"] is False and st["backend"] == "redis"
    redis_state._r = good


@needs_redis
def test_unreadable_answer_in_redis_fails_closed(redis_state):
    sim, book = world(redis_state)
    redis_state._r.set(f"twin:{sim.run_id}:key:city_brain:broken", "not json", ex=60)
    r = valve(sim, book, f"tk-{uuid.uuid4().hex[:6]}", "broken")
    assert r.code == "STATE_UNAVAILABLE"
    redis_state._r.delete(f"twin:{sim.run_id}:key:city_brain:broken")

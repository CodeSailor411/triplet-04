"""Action state: the two things `actuate` must never forget (Redis option A, chosen 14 Oct).

  1. USED TOKEN IDS (jti). A token works once. If the Twin restarts and forgets which tokens were used, an old
     token can be replayed. That is the real security hole this closes.
  2. IDEMPOTENCY ANSWERS. The first answer to a key, so a repeated command gets the same answer and does not act twice.

What is NOT here (that would be option B): the commanded actuator state and the containment state. Those stay in
the Twin's memory and are lost on a restart. See README, "Action state".

Two backends, same methods (a Protocol = a list of methods any backend must have):
  * `memory` (default): plain dicts. Nothing to install. Lost on restart, exactly like before 14 Oct.
  * `redis`: survives a Twin restart.

FAIL SAFE: if the store cannot be reached, it raises StateUnavailable. `actuate` then refuses the request with the
code STATE_UNAVAILABLE. It never lets a token through just because it could not check whether it was used.
"""
import json
from datetime import datetime
from typing import Protocol


class StateUnavailable(Exception):
    """The store could not be reached or gave an answer we cannot read. The caller must refuse, not guess."""


class ActionState(Protocol):
    name: str

    def get_answer(self, run_id: str, caller: str, key: str) -> tuple[str, str] | None:
        """The first answer stored for this idempotency key: (fingerprint, result as JSON text), or None."""

    def jti_used(self, run_id: str, jti: str, now: datetime) -> bool:
        """True if this token ID was already spent in this run."""

    def next_action_number(self, run_id: str) -> int:
        """The next action number of this run (1, 2, 3 ...). It must keep counting after a restart, otherwise a new
        action would get an ID that an old stored answer already has. A number can be skipped (a failed commit);
        it is never given out twice."""

    def commit(self, run_id: str, jti: str, expires_at: datetime, caller: str, key: str,
               fingerprint: str, result_json: str) -> bool:
        """Spend the token AND store the answer, together or not at all. False: the token was already spent."""

    def reset(self) -> None:
        """A new run starts. The memory backend wipes itself; Redis does nothing (every key carries its run id)."""

    def status(self) -> dict: ...

    def close(self) -> None: ...


class MemoryActionState:
    name = "memory"

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._answers: dict[tuple[str, str, str], tuple[str, str]] = {}
        self._used: dict[tuple[str, str], datetime] = {}           # (run, jti) -> expiry in simulated time
        self._numbers: dict[str, int] = {}                         # run -> last action number given out

    def get_answer(self, run_id, caller, key):
        return self._answers.get((run_id, caller, key))

    def jti_used(self, run_id, jti, now):
        for old in [k for k, exp in self._used.items() if exp <= now]:     # forget tokens that could not work anyway
            del self._used[old]
        return (run_id, jti) in self._used

    def next_action_number(self, run_id):
        self._numbers[run_id] = self._numbers.get(run_id, 0) + 1
        return self._numbers[run_id]

    def commit(self, run_id, jti, expires_at, caller, key, fingerprint, result_json):
        if (run_id, jti) in self._used:
            return False
        self._used[(run_id, jti)] = expires_at
        self._answers[(run_id, caller, key)] = (fingerprint, result_json)
        return True

    def status(self) -> dict:
        return {"backend": "memory", "ok": True}

    def close(self) -> None:
        pass


# A Lua script is a few lines that run INSIDE Redis in one step, so nothing else can run in between.
# KEYS[1] = the used-token key, KEYS[2] = the answer key, ARGV[1] = seconds to keep both, ARGV[2] = the answer.
# SET ... NX means "only set it if it does not exist yet". If the token key already exists, we change nothing.
_COMMIT_LUA = """
if redis.call('SET', KEYS[1], '1', 'NX', 'EX', ARGV[1]) then
  redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[1])
  return 1
end
return 0
"""


class RedisActionState:
    name = "redis"

    def __init__(self, url: str, timeout_seconds: float, ttl_seconds: int, client=None) -> None:
        import redis                                      # imported here so a memory-only Twin never needs it
        self._redis = redis
        self._r = client or redis.Redis.from_url(url, socket_timeout=timeout_seconds,
                                                 socket_connect_timeout=timeout_seconds, decode_responses=True)
        self._ttl = ttl_seconds
        self._commit = self._r.register_script(_COMMIT_LUA)

    @staticmethod
    def _jti_key(run_id: str, jti: str) -> str:
        return f"twin:{run_id}:jti:{jti}"

    @staticmethod
    def _answer_key(run_id: str, caller: str, key: str) -> str:
        return f"twin:{run_id}:key:{caller}:{key}"

    def get_answer(self, run_id, caller, key):
        try:
            raw = self._r.get(self._answer_key(run_id, caller, key))
        except self._redis.RedisError as e:
            raise StateUnavailable(f"Redis: {e}") from None
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return data["fp"], data["result"]
        except (ValueError, KeyError, TypeError):
            raise StateUnavailable("Redis holds an answer the Twin cannot read.") from None   # fail closed

    def jti_used(self, run_id, jti, now):
        try:
            return bool(self._r.exists(self._jti_key(run_id, jti)))
        except self._redis.RedisError as e:
            raise StateUnavailable(f"Redis: {e}") from None

    def next_action_number(self, run_id):
        # INCR adds 1 to a counter in Redis and returns the new value, in one step (two Twins cannot get the same number).
        try:
            key = f"twin:{run_id}:seq"
            n = int(self._r.incr(key))
            self._r.expire(key, self._ttl)
            return n
        except self._redis.RedisError as e:
            raise StateUnavailable(f"Redis: {e}") from None

    def commit(self, run_id, jti, expires_at, caller, key, fingerprint, result_json):
        answer = json.dumps({"fp": fingerprint, "result": result_json}, separators=(",", ":"))
        try:
            done = self._commit(keys=[self._jti_key(run_id, jti), self._answer_key(run_id, caller, key)],
                                args=[self._ttl, answer])
        except self._redis.RedisError as e:
            raise StateUnavailable(f"Redis: {e}") from None
        return bool(done)

    def reset(self) -> None:
        pass

    def status(self) -> dict:
        try:
            self._r.ping()
            return {"backend": "redis", "ok": True}
        except self._redis.RedisError as e:
            return {"backend": "redis", "ok": False, "error": str(e)[:120]}

    def close(self) -> None:
        try:
            self._r.close()
        except self._redis.RedisError:
            pass

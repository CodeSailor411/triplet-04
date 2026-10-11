"""Actuators: `actuate`, the token gate, idempotency and blast-radius caps.

Order of checks in `actuate` (the order matters, it is on purpose):
  1. Is the request well formed? (known action, real target nodes that carry this actuator, valid params)
     Wrong input is an ERROR (the tool call fails with a code and a clear message).
  2. Same idempotency key as before? Same request: return the first result. Changed request: rejected.
  3. The token: present, signed (if required), this run, not expired, never used, same action/targets/params as
     the request, score high enough. Any failure is a REJECTION (a normal result with status "rejected" and a code).
  3b. Quarantine: a target node with a quarantined device holds the command (it is not carried out).
  4. Preview rule (flag exists, enforced from 15 Oct).
  5. Caps: how many nodes of each domain this one request touches.
  6. Commit: the actuator now holds the commanded value, the token is spent.
The token is spent only when the action commits, so a request refused for caps can be tried again with the same token.
Nothing here changes what the sensors report yet: actuator effects come later (15 Oct).
"""
import json
import math
import threading
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from .auth import Identity
from .caps import compute_caps
from .models import Topology
from .settings import ActuatorCfg, ParamCfg, TwinConfig
from .sim import Simulation
from .tokens import TokenError, read_token
from .util import format_rfc3339


class BadRequest(Exception):
    """The request itself is wrong. Becomes a failed tool call: 'CODE: message'."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class ParamInfo(BaseModel):
    name: str
    type: str
    choices: list[str] = []
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None


class ActionInfo(BaseModel):
    action: str
    domain: str
    risk: str | None                # R1, R2, R3 or null (no tier)
    preview_required: bool
    params: list[ParamInfo]
    target_nodes: list[str]         # nodes that carry this actuator: the only valid values for `targets`
    action_cap: int | None          # most nodes of one domain a single request may touch


class ActionList(BaseModel):
    token_mode: Literal["unsigned", "signed"]
    preview_enforced: bool
    actions: list[ActionInfo]


class ActuateResult(BaseModel):
    status: Literal["committed", "rejected"]      # "pending" arrives with the two-step switch (8 Oct, off by default)
    run_id: str
    tick: int
    time: str
    action: str
    targets: list[str]
    params: dict[str, Any]
    action_id: str | None = None                  # only when committed
    token_id: str | None = None                   # the token's id (never the token itself), once the token was read
    code: str | None = None                       # only when rejected
    message: str | None = None
    details: dict[str, Any] | None = None
    replayed: bool = False                        # true: this is the stored first answer to a repeated idempotency key


def _clean_param(name: str, spec: ParamCfg, value: Any, node_ids: set[str]) -> Any:
    def bad(why: str):
        raise BadRequest("INVALID_PARAMS", f"Parameter '{name}': {why}")
    if spec.type == "choice":
        if not isinstance(value, str) or value not in spec.choices:
            bad(f"must be one of {spec.choices}, got {value!r}")
        return value
    if spec.type == "node":
        if not isinstance(value, str) or value not in node_ids:
            bad(f"must be an existing node id (see list_nodes), got {value!r}")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        bad(f"must be a number, got {value!r}")
    if spec.type == "integer":
        if not isinstance(value, int):
            bad(f"must be a whole number, got {value!r}")
    else:
        value = float(value)
    if spec.min_value is not None and value < spec.min_value:
        bad(f"must be at least {spec.min_value:g}, got {value!r}")
    if spec.max_value is not None and value > spec.max_value:
        bad(f"must be at most {spec.max_value:g}, got {value!r}")
    return value


class ActionBook:
    def __init__(self, topology: Topology, config: TwinConfig, sim: Simulation):
        self.cfg, self.sim = config, sim
        self.nodes = {n.node_id: n for n in topology.nodes}
        self.caps = compute_caps(config.generator, config.caps)
        self._lock = threading.Lock()
        self.containment = None            # set by the app: used to hold commands for quarantined nodes
        self.recorder = None               # set by the app: the run log
        self._run = sim.run_number
        self._reset_state()

    def _reset_state(self) -> None:
        self.seq = 0
        self.committed: dict[str, ActuateResult] = {}                      # action_id -> result
        self.state: dict[tuple[str, str], dict[str, Any]] = {}             # (node_id, action) -> commanded params
        self._by_key: dict[tuple[Identity, str], tuple[str, ActuateResult]] = {}
        self._used_jti: dict[str, datetime] = {}                           # jti -> expiry

    # ------------------------------------------------------------------ list
    def list_actions(self) -> ActionList:
        out = []
        for name, a in self.cfg.actuators.items():
            params = [ParamInfo(name=n, type=p.type, choices=p.choices, min_value=p.min_value,
                                max_value=p.max_value, unit=p.unit) for n, p in a.params.items()]
            out.append(ActionInfo(action=name, domain=a.domain, risk=a.risk, preview_required=a.preview_required,
                                  params=params, target_nodes=self._carriers(name),
                                  action_cap=self.caps[a.domain]["action_cap"]))
        return ActionList(token_mode=self.cfg.tokens.mode, preview_enforced=self.cfg.actions.preview_enforced,
                          actions=out)

    def _carriers(self, action: str) -> list[str]:
        return sorted(n for n, node in self.nodes.items() if action in node.actuators)

    # ------------------------------------------------------------------ actuate
    def actuate(self, caller: Identity, action: str, targets: list[str], params: dict[str, Any] | None,
                token: str | None, idempotency_key: str) -> ActuateResult:
        result = self._actuate(caller, action, targets, params, token, idempotency_key)
        if self.recorder is not None and not result.replayed:           # a repeated key is not a new event
            self.recorder.record("action", {"caller": caller.value, "action": result.action, "targets": result.targets,
                                            "params": result.params, "idempotency_key": idempotency_key,
                                            "status": result.status, "action_id": result.action_id, "code": result.code,
                                            "token_id": result.token_id})
        return result

    def _actuate(self, caller: Identity, action: str, targets: list[str], params: dict[str, Any] | None,
                 token: str | None, idempotency_key: str) -> ActuateResult:
        with self._lock:
            if self._run != self.sim.run_number:                            # a new run wipes all action state
                self._run = self.sim.run_number
                self._reset_state()
            act = self.cfg.actuators.get(action)
            if act is None:
                raise BadRequest("UNKNOWN_ACTION", f"'{action}' is not an action. Known: "
                                                   f"{', '.join(self.cfg.actuators)}. See list_actions.")
            targets = self._check_targets(action, targets)
            cleaned = self._check_params(act, params)
            if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
                raise BadRequest("INVALID_IDEMPOTENCY_KEY", "idempotency_key must be a string of 1 to 128 characters.")

            fingerprint = json.dumps({"action": action, "targets": targets, "params": cleaned},
                                     sort_keys=True, separators=(",", ":"))
            seen = self._by_key.get((caller, idempotency_key))
            if seen:
                if seen[0] == fingerprint:
                    return seen[1].model_copy(update={"replayed": True})
                return self._reject("IDEMPOTENCY_CONFLICT", action, targets, cleaned,
                                    "This idempotency_key was already used for a different request. Reuse a key only "
                                    "for a retry of the same unchanged request.",
                                    {"first_action_id": seen[1].action_id})

            now = self.sim.clock.time_of(self.sim.tick)
            try:
                claims = read_token(token or "", self.cfg.tokens)
            except TokenError as e:
                return self._reject(e.code, action, targets, cleaned, e.message)
            for code, failed, why in (
                ("TOKEN_WRONG_RUN", claims.run_id != self.sim.run_id, "Token is for another run."),
                ("TOKEN_EXPIRED", claims.expires_at() <= now, "Token has expired (simulated clock, see get_clock)."),
                ("TOKEN_REUSED", self._jti_used(claims.jti, now), "Token was already used."),
                ("TOKEN_MISMATCH", (claims.action, sorted(claims.targets), claims.params) != (action, targets, cleaned),
                 "Token was issued for a different action, targets or params than this request."),
            ):
                if failed:
                    return self._reject(code, action, targets, cleaned, why, token_id=claims.jti)
            floor = self.cfg.tokens.min_score.get(act.risk) if act.risk else None
            if floor is not None and claims.score < floor:
                return self._reject("TOKEN_SCORE_TOO_LOW", action, targets, cleaned,
                                    f"Score is too low for a {act.risk} action.", {"risk": act.risk}, token_id=claims.jti)

            held = self.containment.quarantined_nodes(targets) if self.containment else []
            if held:
                self.containment.hold_command(caller, action, targets, cleaned)
                return self._reject("DEVICE_QUARANTINED", action, targets, cleaned,
                                    "A target node has a quarantined device. The command is held in the quarantine "
                                    "lane and was not carried out. Guardian can release the device.", {"nodes": held},
                                    token_id=claims.jti)
            if act.preview_required and self.cfg.actions.preview_enforced:
                return self._reject("PREVIEW_REQUIRED", action, targets, cleaned,
                                    f"'{action}' must be previewed before it is committed.", token_id=claims.jti)
            violations = self._cap_violations(targets)
            if violations:
                return self._reject("CAP_EXCEEDED", action, targets, cleaned,
                                    "This request touches more nodes than the blast-radius cap allows. "
                                    "The whole request was refused.", {**violations[0], "violations": violations},
                                    token_id=claims.jti)

            self.seq += 1
            result = ActuateResult(status="committed", run_id=self.sim.run_id, tick=self.sim.tick,
                                   time=format_rfc3339(now), action=action, targets=targets, params=cleaned,
                                   action_id=f"ac-{self.seq:05d}", token_id=claims.jti)
            for t in targets:
                self.state[(t, action)] = cleaned
            self.committed[result.action_id] = result
            self._by_key[(caller, idempotency_key)] = (fingerprint, result)
            self._used_jti[claims.jti] = claims.expires_at()
            return result

    # ------------------------------------------------------------------ pieces
    def _check_targets(self, action: str, targets: list[str]) -> list[str]:
        if not targets:
            raise BadRequest("INVALID_TARGETS", "targets must list at least one node id.")
        if len(set(targets)) != len(targets):
            raise BadRequest("INVALID_TARGETS", "targets contains the same node twice.")
        carriers = self._carriers(action)
        for t in targets:
            if t not in self.nodes:
                raise BadRequest("UNKNOWN_NODE", f"'{t}' is not a node. Call list_nodes for the node ids.")
            if t not in carriers:
                raise BadRequest("INVALID_TARGETS", f"'{t}' has no '{action}' actuator. Nodes that do: {', '.join(carriers)}.")
        return sorted(targets)

    def _check_params(self, act: ActuatorCfg, params: dict[str, Any] | None) -> dict[str, Any]:
        params = params or {}
        unknown = sorted(set(params) - set(act.params))
        if unknown:                       # strict on purpose: a silently ignored typo on an actuator command is worse than an error
            raise BadRequest("INVALID_PARAMS", f"Unknown parameter(s) {unknown}. Allowed: {sorted(act.params)}.")
        node_ids = set(self.nodes)
        out = {}
        for name, spec in act.params.items():
            if name not in params:
                raise BadRequest("INVALID_PARAMS", f"Missing parameter '{name}'.")
            out[name] = _clean_param(name, spec, params[name], node_ids)
        return out

    def _jti_used(self, jti: str, now: datetime) -> bool:
        for old in [j for j, exp in self._used_jti.items() if exp <= now]:   # forget tokens that could not work anyway
            del self._used_jti[old]
        return jti in self._used_jti

    def _cap_violations(self, targets: list[str]) -> list[dict[str, Any]]:
        """A shared node counts in every domain it belongs to; one broken cap refuses the whole request."""
        counts: dict[str, int] = {}
        for t in targets:
            for d in self.nodes[t].domains:
                counts[d] = counts.get(d, 0) + 1
        out = []
        for domain in self.caps:                                     # config order, so the "first" violation is stable
            cap = self.caps[domain]["action_cap"]
            n = counts.get(domain, 0)
            if cap is not None and n > cap:
                # The action cap is per request, so nothing is "in use" from earlier requests.
                out.append({"pool": "action", "domain": domain, "cap": cap, "in_use": 0, "requested": n,
                            "remaining": cap})
        return out

    def _reject(self, code: str, action: str, targets: list[str], params: dict[str, Any], message: str,
                details: dict[str, Any] | None = None, token_id: str | None = None) -> ActuateResult:
        tick = self.sim.tick
        return ActuateResult(status="rejected", run_id=self.sim.run_id, tick=tick, time=self.sim.clock.iso_of(tick),
                             action=action, targets=targets, params=params, code=code, message=message, details=details,
                             token_id=token_id)

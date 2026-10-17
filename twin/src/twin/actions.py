"""Actuators: `actuate`, the token gate, idempotency and blast-radius caps.

Order of checks in `actuate` (the order matters, it is on purpose):
  1. Is the request well formed? (known action, real target nodes that carry this actuator, valid params)
     Wrong input is an ERROR (the tool call fails with a code and a clear message).
  2. Same idempotency key as before? Same request: return the first result. Changed request: rejected.
  3. The token: present, signed (if required), this run, not expired, never used, same action/targets/params as
     the request, score high enough. Any failure is a REJECTION (a normal result with status "rejected" and a code).
  3b. Quarantine: a target node with a quarantined device holds the command (it is not carried out).
  4. Preview rule: an action with preview_required needs a fresh `preview_action` from the same caller for exactly
     this request (action, targets, params), if actions.preview_enforced is true. A preview is used up by the commit.
  5. Caps: how many nodes of each domain this one request touches.
  6. Commit: the actuator now holds the commanded value, the token is spent.
The token is spent only when the action commits, so a request refused for caps can be tried again with the same token.
`preview_action` is the dry-run: it runs the checks that do not need a token and reports what the action WOULD do.
It changes nothing (no token, no idempotency key, no actuator, no action number). It only remembers that the
preview happened, in memory, so a Twin restart forgets it. That fails safe: the Brain just previews again.
Nothing here changes what the sensors report yet: actuator effects come later.
"""
import json
import math
import threading
from typing import Any, Literal

from pydantic import BaseModel

from .auth import Identity
from .caps import compute_caps
from .models import Topology
from .settings import ActuatorCfg, ParamCfg, TwinConfig
from .sim import Simulation
from .storage.actionstate import ActionState, MemoryActionState, StateUnavailable
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


class IsolationCap(BaseModel):
    """Guardian's containment limit for one domain. The Brain cannot isolate anything itself, but it needs the number
    to plan around it (for example, not to ask for a data source that Guardian can no longer cut off)."""
    domain: str
    nodes: int                      # how many nodes the domain has
    isolation_cap: int              # most nodes of this domain that may be isolated or quarantined at once (one shared pool)


class ActionList(BaseModel):
    token_mode: Literal["unsigned", "signed"]
    preview_enforced: bool
    actions: list[ActionInfo]
    isolation_caps: list[IsolationCap]   # same numbers as the pools of get_containment_state, without the usage (D8, 16 Oct)


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


class PreviewChange(BaseModel):
    node_id: str
    domains: list[str]
    current: dict[str, Any] | None   # what this actuator was last commanded to in this run (null: never commanded)
    new: dict[str, Any]              # what it would hold after the action
    held: bool                       # true: the node is quarantined, so the command would be held, not carried out


class PreviewResult(BaseModel):
    run_id: str
    tick: int
    time: str
    action: str
    targets: list[str]
    params: dict[str, Any]
    risk: str | None
    token_needed: bool = True        # a preview is never a permission: the real action still needs Guardian's token
    min_score: float | None          # lowest token score the Twin accepts for this risk level (null: not set yet)
    changes: list[PreviewChange]
    would_pass_checks: bool          # the checks that do not need a token (caps, quarantine) would all pass
    blocked_by: list[str]            # codes of the checks that would refuse it: CAP_EXCEEDED, DEVICE_QUARANTINED
    details: dict[str, Any] | None = None
    valid_until_tick: int            # commit by this tick, or preview again
    valid_until: str
    message: str


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


def _fingerprint(action: str, targets: list[str], params: dict[str, Any]) -> str:
    """One string that identifies a request: same action, targets and params give the same string."""
    return json.dumps({"action": action, "targets": targets, "params": params}, sort_keys=True, separators=(",", ":"))


class ActionBook:
    def __init__(self, topology: Topology, config: TwinConfig, sim: Simulation, state: ActionState | None = None):
        self.cfg, self.sim = config, sim
        self.store: ActionState = state or MemoryActionState()      # used token IDs and idempotency answers
        self.nodes = {n.node_id: n for n in topology.nodes}
        self.caps = compute_caps(config.generator, config.caps)
        self._lock = threading.Lock()
        self.containment = None            # set by the app: used to hold commands for quarantined nodes
        self.recorder = None               # set by the app: the run log
        self._run = sim.run_number
        self._reset_state()

    def _reset_state(self) -> None:
        self.seq = 0
        self.previews: dict[tuple[str, str], int] = {}                     # (caller, request) -> tick of the preview
        self.committed: dict[str, ActuateResult] = {}                      # action_id -> result
        self.state: dict[tuple[str, str], dict[str, Any]] = {}             # (node_id, action) -> commanded params
        self.store.reset()                                                 # memory backend: wipe. Redis: nothing (keys carry the run id)

    # ------------------------------------------------------------------ list
    def list_actions(self) -> ActionList:
        out = []
        for name, a in self.cfg.actuators.items():
            params = [ParamInfo(name=n, type=p.type, choices=p.choices, min_value=p.min_value,
                                max_value=p.max_value, unit=p.unit) for n, p in a.params.items()]
            out.append(ActionInfo(action=name, domain=a.domain, risk=a.risk, preview_required=a.preview_required,
                                  params=params, target_nodes=self._carriers(name),
                                  action_cap=self.caps[a.domain]["action_cap"]))
        iso = [IsolationCap(domain=d, nodes=c["nodes"], isolation_cap=c["isolation_cap"]) for d, c in self.caps.items()]
        return ActionList(token_mode=self.cfg.tokens.mode, preview_enforced=self.cfg.actions.preview_enforced,
                          actions=out, isolation_caps=iso)

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
            self._sync_run()
            act, targets, cleaned = self._check_request(action, targets, params)
            if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
                raise BadRequest("INVALID_IDEMPOTENCY_KEY", "idempotency_key must be a string of 1 to 128 characters.")

            fingerprint = _fingerprint(action, targets, cleaned)
            run_id = self.sim.run_id
            try:
                seen = self.store.get_answer(run_id, caller.value, idempotency_key)
            except StateUnavailable as e:
                return self._store_down(action, targets, cleaned, e)
            if seen:
                first = ActuateResult.model_validate_json(seen[1])
                if seen[0] == fingerprint:
                    return first.model_copy(update={"replayed": True})
                return self._reject("IDEMPOTENCY_CONFLICT", action, targets, cleaned,
                                    "This idempotency_key was already used for a different request. Reuse a key only "
                                    "for a retry of the same unchanged request.",
                                    {"first_action_id": first.action_id})

            now = self.sim.clock.time_of(self.sim.tick)
            try:
                claims = read_token(token or "", self.cfg.tokens)
            except TokenError as e:
                return self._reject(e.code, action, targets, cleaned, e.message)
            try:
                already_used = self.store.jti_used(run_id, claims.jti, now)
            except StateUnavailable as e:
                return self._store_down(action, targets, cleaned, e, token_id=claims.jti)
            for code, failed, why in (
                ("TOKEN_WRONG_RUN", claims.run_id != self.sim.run_id, "Token is for another run."),
                ("TOKEN_EXPIRED", claims.expires_at() <= now, "Token has expired (simulated clock, see get_clock)."),
                ("TOKEN_REUSED", already_used, "Token was already used."),
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
            if act.preview_required and self.cfg.actions.preview_enforced and not self._preview_is_fresh(
                    caller, fingerprint):
                return self._reject("PREVIEW_REQUIRED", action, targets, cleaned,
                                    f"'{action}' must be previewed (preview_action, same action, targets and params) "
                                    f"before it is committed. A preview lasts "
                                    f"{self.cfg.actions.preview_valid_ticks} ticks and is used up by one commit.",
                                    {"preview_valid_ticks": self.cfg.actions.preview_valid_ticks}, token_id=claims.jti)
            violations = self._cap_violations(targets)
            if violations:
                return self._reject("CAP_EXCEEDED", action, targets, cleaned,
                                    "This request touches more nodes than the blast-radius cap allows. "
                                    "The whole request was refused.", {**violations[0], "violations": violations},
                                    token_id=claims.jti)

            try:
                number = self.store.next_action_number(run_id)          # keeps counting after a restart (Redis)
            except StateUnavailable as e:
                return self._store_down(action, targets, cleaned, e, token_id=claims.jti)
            result = ActuateResult(status="committed", run_id=run_id, tick=self.sim.tick,
                                   time=format_rfc3339(now), action=action, targets=targets, params=cleaned,
                                   action_id=f"ac-{number:05d}", token_id=claims.jti)
            # The token is spent and the answer stored in ONE step. Only if that worked does the actuator change.
            # If the store fails here, nothing changed and the same request can be tried again.
            try:
                spent = self.store.commit(run_id, claims.jti, claims.expires_at(), caller.value, idempotency_key,
                                          fingerprint, result.model_dump_json())
            except StateUnavailable as e:
                return self._store_down(action, targets, cleaned, e, token_id=claims.jti)
            if not spent:                         # someone spent this token between our check and now
                return self._reject("TOKEN_REUSED", action, targets, cleaned, "Token was already used.",
                                    token_id=claims.jti)
            self.seq = number
            self.previews.pop((caller.value, fingerprint), None)           # one preview, one commit
            for t in targets:
                self.state[(t, action)] = cleaned
            self.committed[result.action_id] = result
            return result

    # ------------------------------------------------------------------ preview (dry-run)
    def preview(self, caller: Identity, action: str, targets: list[str], params: dict[str, Any] | None) -> PreviewResult:
        """Dry-run of `actuate`. Same input checks, then reports what would happen. Changes nothing."""
        with self._lock:
            self._sync_run()
            act, targets, cleaned = self._check_request(action, targets, params)
            if not act.preview_required:
                raise BadRequest("PREVIEW_NOT_AVAILABLE",
                                 f"'{action}' has no preview: only actions with preview_required (see list_actions) do.")
            held = self.containment.quarantined_nodes(targets) if self.containment else []
            violations = self._cap_violations(targets)
            blocked = (["DEVICE_QUARANTINED"] if held else []) + (["CAP_EXCEEDED"] if violations else [])
            details: dict[str, Any] = {}
            if held:
                details["quarantined_nodes"] = held
            if violations:
                details["cap_violations"] = violations
            changes = [PreviewChange(node_id=t, domains=list(self.nodes[t].domains),
                                     current=self.state.get((t, action)), new=cleaned, held=t in held)
                       for t in targets]
            tick = self.sim.tick
            until = tick + self.cfg.actions.preview_valid_ticks
            self.previews[(caller.value, _fingerprint(action, targets, cleaned))] = tick
            return PreviewResult(
                run_id=self.sim.run_id, tick=tick, time=self.sim.clock.iso_of(tick), action=action, targets=targets,
                params=cleaned, risk=act.risk, min_score=self.cfg.tokens.min_score.get(act.risk) if act.risk else None,
                changes=changes, would_pass_checks=not blocked, blocked_by=blocked, details=details or None,
                valid_until_tick=until, valid_until=self.sim.clock.iso_of(until),
                message=("Dry-run only, nothing was changed. " + (
                    "These checks would refuse it: " + ", ".join(blocked) + "." if blocked else
                    "The caps and quarantine checks would pass. The real action still needs Guardian's token.")))

    def _preview_is_fresh(self, caller: Identity, fingerprint: str) -> bool:
        seen = self.previews.get((caller.value, fingerprint))
        return seen is not None and self.sim.tick - seen <= self.cfg.actions.preview_valid_ticks

    # ------------------------------------------------------------------ pieces
    def _sync_run(self) -> None:
        if self._run != self.sim.run_number:                                # a new run wipes all action state
            self._run = self.sim.run_number
            self._reset_state()

    def _check_request(self, action: str, targets: list[str], params: dict[str, Any] | None):
        """The input checks that actuate and preview share. Wrong input raises BadRequest."""
        act = self.cfg.actuators.get(action)
        if act is None:
            raise BadRequest("UNKNOWN_ACTION", f"'{action}' is not an action. Known: "
                                               f"{', '.join(self.cfg.actuators)}. See list_actions.")
        return act, self._check_targets(action, targets), self._check_params(act, params)

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

    def _store_down(self, action: str, targets: list[str], params: dict[str, Any], why: Exception,
                    token_id: str | None = None) -> ActuateResult:
        """Fail safe: if we cannot check or record token use, no action is carried out."""
        return self._reject("STATE_UNAVAILABLE", action, targets, params,
                            "The Twin cannot check or record token use right now, so it refuses all actions until "
                            "that works again. Nothing was changed. Try again later with the same request.",
                            {"store": self.store.name, "reason": str(why)[:120]}, token_id=token_id)

    def _reject(self, code: str, action: str, targets: list[str], params: dict[str, Any], message: str,
                details: dict[str, Any] | None = None, token_id: str | None = None) -> ActuateResult:
        tick = self.sim.tick
        return ActuateResult(status="rejected", run_id=self.sim.run_id, tick=tick, time=self.sim.clock.iso_of(tick),
                             action=action, targets=targets, params=params, code=code, message=message, details=details,
                             token_id=token_id)

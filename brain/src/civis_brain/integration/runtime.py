"""Shared, fail-closed orchestration; scenario detectors never call peers themselves."""

import asyncio
import base64
import copy
import hashlib
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from civis_brain.context_graph import ContextGraph
from civis_brain.contracts import (
    ActionInfo,
    ContainmentNotice,
    Decision,
    DecisionBatch,
    Node,
    PlanningContext,
    ReadingsBatch,
)
from civis_brain.errors import BrainError
from civis_brain.inputs.service import normalize_batch, utc_time
from civis_brain.integration.journal import Journal
from civis_brain.integration.recovery import recover
from civis_brain.planning.service import check_caps, validate_plan
from civis_brain.ports import PlanProvider, ToolPeer
from civis_brain.scenarios.registry import SCENARIOS

RELEVANCE = {
    "S01": ("traffic", {"congestion_index", "vehicle_count", "avg_speed"}),
    "S02": ("water", {"water_level"}),
    "S03": ("power", {"load_kw", "voltage_v"}),
    "S04": ("air_quality", {"pm25"}),
    "S05": ("emergency", {"emergency_calls"}),
    "S06": ("traffic", {"road_accident_report"}),
    "S07": ("water", {"water_level"}),
    "S08": ("emergency", {"emergency_calls"}),
}
ACTION_BY_SCENARIO = {
    "S01": "set_signal_plan",
    "S02": "set_valve_position",
    "S03": None,
    "S04": None,
    "S05": "dispatch",
    "S06": "dispatch",
    "S07": "set_valve_position",
    "S08": "dispatch",
}
PROTOCOL = "2026-07-28"


def fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class BudgetProvider:
    def __init__(self, runtime):
        self.runtime = runtime

    async def generate(self, context):
        runtime = self.runtime
        if runtime.ai_calls >= runtime.features.get("ai_max_calls_per_run", 3):
            raise BrainError("AI_BUDGET_EXCEEDED", "Configured AI call budget exhausted")
        runtime.ai_calls += 1
        try:
            return await asyncio.wait_for(
                runtime.provider.generate(context), runtime.features.get("ai_timeout_seconds", 15)
            )
        except TimeoutError:
            raise BrainError("AI_TIMEOUT", "Plan generation timed out") from None
        except BrainError:
            raise
        except Exception:
            raise BrainError("AI_UNAVAILABLE", "Plan provider failed") from None


class BrainRuntime:
    def __init__(
        self,
        *,
        twin,
        guardian,
        provider,
        policies,
        features,
        artifact_dir=None,
        scenarios=SCENARIOS,
    ):
        self.twin, self.guardian, self.provider = twin, guardian, provider
        self.policies, self.features = policies, features
        self.scenarios = tuple(scenarios)
        enabled = features.get("enabled_scenario_ids", [sid for sid, p in policies.items() if p.get("enabled", True)])
        if not isinstance(enabled, list) or not set(enabled).issubset(RELEVANCE):
            raise ValueError("enabled_scenario_ids must contain known scenario IDs")
        self.enabled = set(enabled)
        if {"S02", "S07"}.issubset(self.enabled) and policies.get("S07", {}).get("supply_nodes"):
            from civis_brain.scenarios.water.low_water import pair_error
            problem = pair_error(policies["S02"], policies["S07"])
            if problem:
                raise ValueError("Invalid paired Water policies: " + problem)
        self.lock = asyncio.Lock()
        self.journal = Journal(
            artifact_dir / "trace.jsonl" if artifact_dir else None,
            run_log_dir=Path(features["run_log_dir"]) if features.get("run_log_dir")
            else artifact_dir / "run-logs" if artifact_dir else None,
        )
        self.run_id = None
        self.feed_generation = 0
        self.latest_feed = None
        self.feed_connected = None
        self._reset()

    def _reset(self):
        self.states = {scenario.scenario_id: {} for scenario in self.scenarios}
        self.ledger = {}
        self.invalid_ids = set()
        self.blocked_devices = set()
        self.polled_devices = set()
        self.containment_events = set()
        self.generation = 0
        self.last_tick = -1
        self.cached_ticks = {}
        self.active = {}
        self.graph_context = {}
        self.decisions = {}
        self.intents = {}
        self.trust_attempts = {}
        self.ai_calls = 0
        self.episodes = {}
        self.episode_receipts = {}
        self.pending_started = {}
        self.sent_requests = {}
        self.reconciliation_attempts = set()
        self.dispatch_allocations = {}
        self.observed_feed_generation = self.feed_generation

    def observe_feed(self, batch=None, *, discontinuity=False, connected=True):
        """Called by the independent receiver, including while Gemini is awaiting I/O."""
        self.feed_connected = connected
        if discontinuity or not connected or (
            batch and self.run_id and batch.run_id != self.run_id
        ):
            self.graph_context = {}
            self.feed_generation += 1
            self.generation += 1
        if batch is not None:
            self.latest_feed = batch

    def _validate_clock(self, batch, clock, *, execution=False):
        tick = clock.get("tick")
        if (clock.get("run_id") != batch.run_id or type(tick) is not int
                or tick < batch.tick or clock.get("tick_seconds") != batch.tick_seconds):
            raise BrainError("CLOCK_MISMATCH", "Twin clock has a different run, rate or older tick")
        age = (utc_time(clock["time"]) - utc_time(batch.time)).total_seconds()
        expected = (tick - batch.tick) * batch.tick_seconds
        if abs(age - expected) > 0.001:
            raise BrainError("CLOCK_MISMATCH", "Simulated time and tick difference disagree")
        limit = self.features.get("max_evidence_age_seconds", 10)
        if age < 0 or age > limit:
            raise BrainError("EVIDENCE_STALE", "Evidence exceeded the configured simulated-time age")
        if execution and self.feed_connected is False:
            raise BrainError("FEED_DISCONNECTED", "Feed disconnected while planning")
        return SimpleNamespace(**clock)

    def _operation_key(self, batch, sid, proposal):
        intent = dict(action=proposal.action, targets=proposal.targets, params=proposal.params)
        sources = set(proposal.source_reading_ids)
        episodes = sorted(incident.incident_id for owner, incident in self.active.values()
                          if owner == sid and sources.intersection(incident.source_reading_ids))
        key = "brain-" + fingerprint({"run_id": batch.run_id, "scenario": sid,
                                      "episodes": episodes or [batch.tick], **intent})
        return key

    async def _call(self, peer, name, arguments):
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
        if not name:
            raise BrainError("TOOL_UNAVAILABLE", "Required peer tool has no confirmed mapping")
        try:
            result = await asyncio.wait_for(
                peer.call_tool(name, arguments), self.features.get("peer_timeout_seconds", 5)
            )
            if not isinstance(result, dict):
                raise BrainError("PEER_SCHEMA_INVALID", "Peer response must be an object")
            return result
        except BrainError:
            raise
        except TimeoutError:
            raise BrainError("PEER_TIMEOUT", "Peer request timed out") from None
        except Exception:
            raise BrainError(
                "PEER_UNAVAILABLE", "Peer call failed; no success was assumed"
            ) from None

    def _decision(
        self, batch, scenario, status, reason, evidence=(), proposal=None, code=None, details=None
    ):
        content = dict(
            run_id=batch.run_id,
            tick=batch.tick,
            status=status,
            reason=reason,
            source_reading_ids=list(evidence),
            peer_code=code,
            peer_details=details or {},
        )
        if proposal is not None:
            content.update(action=proposal.action, targets=proposal.targets, params=proposal.params)
        content["decision_id"] = (
            "dec-"
            + fingerprint({**content, "scenario": scenario, "sequence": len(self.decisions)})[:24]
        )
        decision = Decision.model_validate(self.journal.redact(content))
        self.decisions[decision.decision_id] = decision
        if len(self.decisions) > 1000:
            self.decisions.pop(next(iter(self.decisions)))
        intent = (dict(action=proposal.action, targets=proposal.targets, params=proposal.params)
                  if proposal is not None else None)
        key = (self._operation_key(batch, scenario, proposal)
               if intent is not None else None)
        self.journal.set_clock(batch)
        self.journal.append({"event": "decision", "scenario_id": scenario,
                             **decision.model_dump(), "idempotency_key": key})
        return decision

    async def _discovery(self, batch):
        capabilities = await self._call(self.twin, "get_capabilities", {})
        if capabilities.get("protocol_version") != PROTOCOL:
            raise BrainError("PROTOCOL_MISMATCH", "Twin must negotiate the required MCP protocol")
        clock = await self._call(self.twin, "get_clock", {})
        self._validate_clock(batch, clock)
        nodes_response = await self._call(self.twin, "list_nodes", {})
        actions_response = await self._call(self.twin, "list_actions", {})
        nodes = [Node.model_validate(row) for row in nodes_response["nodes"]]
        actions = [ActionInfo.model_validate(row) for row in actions_response["actions"]]
        normalize_batch(batch, nodes)
        return nodes, actions, capabilities

    async def _sync_containment(self, batch, capabilities):
        if "get_containment_state" not in capabilities.get("tools_you_can_call", []):
            if not getattr(self.twin, "is_fixture", False):
                raise BrainError("CONTAINMENT_UNAVAILABLE", "Twin must advertise containment discovery")
            return
        state = await self._call(self.twin, "get_containment_state", {})
        self._validate_clock(batch, {**state, "tick_seconds": batch.tick_seconds})
        devices, corrections = state.get("devices"), state.get("corrections")
        if not isinstance(devices, list) or not isinstance(corrections, list):
            raise BrainError("PEER_SCHEMA_INVALID", "Malformed containment snapshot")
        current = set()
        for row in devices:
            if (not isinstance(row, dict) or row.get("state") not in {"isolated", "quarantined"}
                    or not isinstance(row.get("device_id"), str) or not row["device_id"]):
                raise BrainError("PEER_SCHEMA_INVALID", "Malformed contained device")
            current.add(row["device_id"])
        corrected = set()
        for row in corrections:
            if (not isinstance(row, dict) or not isinstance(row.get("corrects"), str)
                    or not row["corrects"]):
                raise BrainError("PEER_SCHEMA_INVALID", "Malformed corrected reading")
            corrected.add(row["corrects"])
        for status, changed in (
            ("quarantined", current - self.polled_devices),
            ("released", self.polled_devices - current),
        ):
            if changed:
                self.notify_containment(ContainmentNotice(
                    event_id="poll-" + fingerprint({"run": batch.run_id, "tick": batch.tick,
                                                    "state": status, "devices": sorted(changed),
                                                    "generation": self.generation}),
                    run_id=batch.run_id, state=status, device_ids=sorted(changed),
                ))
        if corrected - self.invalid_ids:
            self.notify_containment(ContainmentNotice(
                event_id="corrections-" + fingerprint({"run": batch.run_id,
                                                       "ids": sorted(corrected)}),
                run_id=batch.run_id, state="corrected", device_ids=[],
                reading_ids=sorted(corrected),
            ))
        self.polled_devices = current

    def _eligible(self, source_ids):
        rules = {
            "congestion_index": ({"percent", "%"}, {None}),
            "water_level": ({"cm"}, {None}), "load_kw": ({"kW"}, {None}),
            "voltage_v": ({"V"}, {None}), "pm25": ({"ug/m3"}, {None}),
            "emergency_calls": ({"calls/min"}, {"medical", "fire", "accident"}),
            "units_free": ({"units"}, {"ambulance", "fire", "police"}),
        }
        # Proposed report conventions are usable only in explicit offline fixtures.
        if getattr(self.twin, "is_fixture", False):
            rules["road_accident_report"] = ({"report"}, {None})
            fire = self.policies.get("S08", {})
            if fire.get("fixture_only") and fire.get("report_sensor"):
                rules[fire["report_sensor"]] = ({fire.get("report_unit")}, {fire.get("report_channel")})
                rules["units_free"][1].add(fire.get("availability_channel"))
        for source in source_ids:
            row = self.ledger.get(source)
            if (row is None or source in self.invalid_ids or row.device_id in self.blocked_devices
                    or row.value is None or row.sensor not in rules):
                return False
            units, channels = rules[row.sensor]
            if row.unit not in units or row.channel not in channels:
                return False
        return True

    @staticmethod
    def _incident_cleared(row, policy, sid):
        if (row.value is None or row.sensor != policy.get("sensor")
                or (policy.get("unit") is not None and row.unit != policy["unit"])
                or row.channel != policy.get("channel")):
            return False
        if sid == "S07":
            return row.value >= policy.get("recovery_level", float("inf"))
        return row.value < policy.get("threshold_min", float("-inf"))

    def _parse_scores(self, response, scale):
        rows = response.get("scores")
        if not isinstance(rows, list):
            raise BrainError("PEER_SCHEMA_INVALID", "Guardian did not return per-reading scores")
        scores = {}
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("reading_id"), str)
                    or not row["reading_id"]):
                raise BrainError("PEER_SCHEMA_INVALID", "Guardian verdict needs a reading ID and score")
            score = row.get("score")
            if (row["reading_id"] in scores or isinstance(score, bool)
                    or not isinstance(score, (int, float)) or not math.isfinite(score)
                    or not 0 <= score <= scale):
                raise BrainError("PEER_SCHEMA_INVALID", "Guardian returned malformed numeric evidence")
            scores[row["reading_id"]] = score
        return scores

    async def _trusted(self, batch, incidents, nodes=()):
        if not (
            getattr(self.guardian, "is_fixture", False)
            or self.features.get("guardian_contract_confirmed") is True
        ):
            raise BrainError(
                "GUARDIAN_CONTRACT_UNCONFIRMED", "Confirm Guardian schemas, scale and cut-offs"
            )
        ids = sorted({source for incident in incidents for source in incident.source_reading_ids})
        if not self._eligible(ids):
            raise BrainError(
                "EVIDENCE_INVALID", "Missing, null or contained evidence cannot be used"
            )
        capability = await self._call(self.guardian, "get_capabilities", {})
        if capability.get("protocol_version") != PROTOCOL:
            raise BrainError("PROTOCOL_MISMATCH", "Guardian must support the required MCP protocol")
        scale = capability.get("score_scale")
        thresholds = capability.get("thresholds")
        if (
            not isinstance(scale, (int, float))
            or isinstance(scale, bool)
            or not math.isfinite(scale)
            or scale <= 0
            or not isinstance(thresholds, dict)
        ):
            raise BrainError(
                "TRUST_POLICY_UNAVAILABLE", "No declared numeric trust scale and cut-offs"
            )
        # Risk cut-offs are required only for an actual proposal, later.
        cutoff = thresholds.get("reading")
        if (
            isinstance(cutoff, bool)
            or not isinstance(cutoff, (int, float))
            or not math.isfinite(cutoff)
            or not 0 <= cutoff <= scale
        ):
            raise BrainError("TRUST_POLICY_UNAVAILABLE", "Reading trust cut-off is not configured")
        # Detector incident IDs can change every tick; retain limits per kind/location.
        attempts_keys = {
            (incident.kind, tuple(sorted(incident.node_ids))) for incident in incidents
        }
        attempt = max((self.trust_attempts.get(key, 0) for key in attempts_keys), default=0)
        if attempt >= 3:
            raise BrainError(
                "TRUST_RETRIES_EXHAUSTED", "Three distinct-tick evidence attempts failed"
            )
        response = await self._call(
            self.guardian,
            self.features.get("guardian_score_tool"),
            {
                "run_id": batch.run_id,
                "tick": batch.tick,
                "readings": [self.ledger[source].model_dump() for source in ids],
            },
        )
        scores = self._parse_scores(response, scale)
        if set(scores) != set(ids) or any(score < cutoff for score in scores.values()):
            for key in attempts_keys:
                self.trust_attempts[key] = self.trust_attempts.get(key, 0) + 1
            self.journal.append(
                {
                    "event": "trust_refusal",
                    "run_id": batch.run_id,
                    "tick": batch.tick,
                    "attempt": attempt + 1,
                    "source_reading_ids": ids,
                }
            )
            if self.features.get("evidence_recovery_enabled"):
                # A failed three-step recovery exhausts this incident's budget. Do
                # not start a new ten-second recovery on every arriving tick.
                for key in attempts_keys:
                    self.trust_attempts[key] = 3
                response, recovery_ids = await recover(self, batch, ids, nodes)
                recovered = self._parse_scores(response, scale)
                if (set(recovered) != recovery_ids
                        or any(score < cutoff for score in recovered.values())):
                    raise BrainError("TRUST_INSUFFICIENT", "Fresh Guardian verdict still refuses evidence")
                scores = {source: recovered[source] for source in ids}
            else:
                raise BrainError("TRUST_INSUFFICIENT", "Evidence has missing or insufficient trust")
        for key in attempts_keys:
            self.trust_attempts.pop(key, None)
        return [self.ledger[source] for source in ids], scores, thresholds, scale

    def _token_binding(self, token, intent, clock, floor, scale, *, idempotency_key=None, reading_ids=None, risk=None):
        if not isinstance(token, str) or not token:
            raise BrainError("TOKEN_MISSING", "Guardian supplied no exact-action approval token")
        self.journal.remember_secret(token)
        # JWS claims are checked here; signature verification and consumption belong to Twin.
        try:
            parts = token.split(".")
            if len(token) > 4096 or len(parts) != 3:
                raise ValueError
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
            if parts[0] == "g1":
                now = utc_time(clock.time).timestamp()
                valid = (
                    bool(parts[2]) and type(claims.get("v")) is int and claims["v"] == 1
                    and isinstance(claims.get("kid"), str) and bool(claims["kid"])
                    and claims.get("iss") == "guardian" and claims.get("aud") == "twin"
                    and claims.get("run_id") == clock.run_id
                    and type(claims.get("iat")) in (int, float)
                    and type(claims.get("exp")) in (int, float)
                    and math.isfinite(claims["iat"]) and math.isfinite(claims["exp"])
                    and claims["iat"] <= now < claims["exp"]
                    and 0 < claims["exp"] - claims["iat"] <= 60
                    and isinstance(claims.get("token_id"), str) and bool(claims["token_id"])
                    and all(claims.get(f) == intent[f] for f in ("action", "targets", "params"))
                    and isinstance(claims.get("params"), dict)
                    and not any(isinstance(v, bool) for v in claims["params"].values())
                    and type(claims.get("trust_score")) in (int, float)
                    and math.isfinite(claims["trust_score"])
                    and floor / scale <= claims["trust_score"] <= 1
                    and idempotency_key is not None and claims.get("idempotency_key") == idempotency_key
                    and isinstance(claims.get("reading_ids"), list)
                    and reading_ids is not None and len(set(claims["reading_ids"])) == len(claims["reading_ids"])
                    and set(claims["reading_ids"]) == set(reading_ids)
                    and risk is not None and claims.get("risk_level") == risk
                )
                if not valid:
                    raise BrainError("TOKEN_BINDING_INVALID", "g1 approval does not bind this command and clock")
                return token
            valid = (
                claims["iss"] == "guardian"
                and claims["aud"] == "twin"
                and claims["run_id"] == clock.run_id
                and utc_time(claims["iat"]) <= utc_time(clock.time) < utc_time(claims["exp"])
                and 0 < (utc_time(claims["exp"]) - utc_time(claims["iat"])).total_seconds() <= 60
                and isinstance(claims["jti"], str)
                and bool(claims["jti"])
                and all(claims[field] == intent[field] for field in ("action", "targets", "params"))
                and isinstance(claims["params"], dict)
                and not any(isinstance(value, bool) for value in claims["params"].values())
                and type(claims["score"]) in (int, float)
                and math.isfinite(claims["score"])
                and floor / scale <= claims["score"] <= 1
                and claims.get("score_scale") in (None, "0..1")
            )
        except (ValueError, TypeError, KeyError):
            valid = False
        if not valid:
            raise BrainError(
                "TOKEN_BINDING_INVALID", "Approval does not bind this exact command and clock"
            )
        return token

    async def evaluate_tick(self, batch: ReadingsBatch) -> DecisionBatch:
        async with self.lock:
            self.journal.set_clock(batch)
            signature = fingerprint(batch.model_dump())
            if batch.run_id == self.run_id and batch.tick in self.cached_ticks:
                previous, result = self.cached_ticks[batch.tick]
                if signature == previous:
                    return result.model_copy(deep=True)
                return DecisionBatch(
                    run_id=batch.run_id,
                    tick=batch.tick,
                    decisions=[
                        self._decision(
                            batch,
                            "core",
                            "blocked",
                            "Changed batch for an already evaluated tick",
                            code="INPUT_CONFLICT",
                        )
                    ],
                )
            if batch.run_id == self.run_id and batch.tick < self.last_tick:
                return DecisionBatch(
                    run_id=batch.run_id,
                    tick=batch.tick,
                    decisions=[
                        self._decision(
                            batch,
                            "core",
                            "blocked",
                            "Ticks must advance within a run",
                            code="STALE_TICK",
                        )
                    ],
                )
            try:
                nodes, actions, capabilities = await self._discovery(batch)
                if batch.run_id != self.run_id:
                    self.run_id = batch.run_id
                    self._reset()
                if (self.observed_feed_generation != self.feed_generation
                        or (self.last_tick >= 0 and batch.tick > self.last_tick + 1)):
                    # Missing ticks cannot establish persistence. Keep operation receipts
                    # and episode identity so reconnects cannot duplicate an action.
                    self.states = {scenario.scenario_id: {} for scenario in self.scenarios}
                    self.trust_attempts.clear()
                    self.invalid_ids.update(self.ledger)
                    self.generation += 1
                    self.observed_feed_generation = self.feed_generation
                    self.journal.append({"event": "feed_gap", "run_id": batch.run_id,
                                         "tick": batch.tick, "previous_tick": self.last_tick})
                await self._sync_containment(batch, capabilities)
                for reading in batch.readings:
                    prior = self.ledger.get(reading.reading_id)
                    if prior and prior != reading:
                        raise BrainError(
                            "READING_ID_CONFLICT", "A reading ID was reused with different data"
                        )
                self.ledger.update(
                    {
                        reading.reading_id: reading.model_copy(deep=True)
                        for reading in batch.readings
                    }
                )
                while len(self.ledger) > 2000:
                    self.ledger.pop(next(iter(self.ledger)))
                decisions = await self._evaluate_scenarios(batch, nodes, actions, capabilities)
            except BrainError as error:
                decisions = [
                    self._decision(
                        batch,
                        "core",
                        "blocked",
                        error.message,
                        code=error.code,
                        details=error.details,
                    )
                ]
            except (ValueError, KeyError, TypeError, ValidationError):
                decisions = [
                    self._decision(
                        batch,
                        "core",
                        "blocked",
                        "Malformed batch or peer discovery",
                        code="INPUT_INVALID",
                    )
                ]
            result = DecisionBatch(run_id=batch.run_id, tick=batch.tick, decisions=decisions)
            if batch.run_id != self.run_id:
                return result
            self.last_tick = batch.tick
            self.cached_ticks[batch.tick] = (signature, result.model_copy(deep=True))
            while len(self.cached_ticks) > 100:
                self.cached_ticks.pop(next(iter(self.cached_ticks)))
            return result

    async def _evaluate_scenarios(self, batch, nodes, actions, capabilities):
        results = []
        node_map = {node.node_id: node for node in nodes}
        available_batch = batch.model_copy(
            update={
                "readings": [
                    row
                    for row in batch.readings
                    if row.device_id not in self.blocked_devices
                    and row.reading_id not in self.invalid_ids
                ]
            }
        )
        available_batch = available_batch.model_copy(
            update={"count": len(available_batch.readings)}
        )
        for scenario in self.scenarios:
            sid = scenario.scenario_id
            domain, sensors = RELEVANCE[sid]
            if sid == "S08":
                sensors = {self.policies.get(sid, {}).get("report_sensor", "emergency_calls")}
            if sid in {"S06", "S08"} and not getattr(self.twin, "is_fixture", False) and not self.policies.get(sid, {}).get("report_contract_confirmed"):
                continue
            relevant = [
                row
                for row in available_batch.readings
                if row.sensor in sensors and domain in node_map[row.node_id].domains
            ]
            if sid not in self.enabled or not relevant:
                continue
            incidents = []
            try:
                policy = self.policies.get(sid, {})
                if policy.get("fixture_only") is True and not getattr(
                    self.twin, "is_fixture", False
                ) and not self.features.get("mock_integration_profile", False):
                    raise BrainError(
                        "POLICY_NOT_APPROVED",
                        "Illustrative thresholds cannot authorize live actions",
                    )
                detected = scenario.detect(
                    available_batch.model_copy(deep=True),
                    [node.model_copy(deep=True) for node in nodes],
                    copy.deepcopy(policy),
                    self.states[sid],
                )
                incidents = detected.incidents
                touched = {row.node_id for row in relevant}
                current_episode_keys = {(sid, item.kind, tuple(sorted(item.node_ids)))
                                        for item in incidents}
                # Only usable observations can close an episode. Silence/null/gaps
                # are not evidence that the incident ended.
                clear_nodes = {row.reading.node_id for row in detected.observations
                               if row.usable and self._incident_cleared(row.reading, policy, sid)}
                for episode_key in list(self.episodes):
                    if (episode_key[0] == sid and episode_key not in current_episode_keys
                            and set(episode_key[2]).issubset(clear_nodes)):
                        self.episode_receipts.pop(self.episodes.pop(episode_key), None)
                        self.trust_attempts.pop((episode_key[1], episode_key[2]), None)
                for incident in incidents:
                    episode_key = (sid, incident.kind, tuple(sorted(incident.node_ids)))
                    stable_id = self.episodes.setdefault(
                        episode_key, f"{incident.incident_id}:onset:{batch.tick}")
                    incident.incident_id = stable_id
                for key, (owner, incident) in list(self.active.items()):
                    if owner == sid and set(incident.node_ids) & touched:
                        self.active.pop(key)
                for incident in incidents:
                    self.active[incident.incident_id] = (sid, incident)
                # A confirmed operation resolves this episode. Continuous input
                # must not spend another Gemini call on the same completed action.
                if self.features.get("one_response_per_episode"):
                    settled = {self.episode_receipts[i.incident_id].decision_id:
                               self.episode_receipts[i.incident_id] for i in incidents
                               if i.incident_id in self.episode_receipts}
                    results.extend(row.model_copy(deep=True) for row in settled.values())
                    incidents = [i for i in incidents if i.incident_id not in self.episode_receipts]
                evidence_ids = [row.reading_id for row in relevant]
                for warning in detected.warnings:
                    results.append(
                        self._decision(
                            batch, sid, "alert", warning, evidence_ids, code="EVIDENCE_WARNING"
                        )
                    )
                if not incidents:
                    continue
                generation = self.generation
                evidence, scores, thresholds, scale = await self._trusted(batch, incidents, nodes)
                graph = ContextGraph(nodes)
                self.graph_context = graph.explain(
                    run_id=batch.run_id, tick=batch.tick, evidence=evidence,
                    focus_ids=[key for incident in incidents for key in incident.node_ids],
                    invalid_ids=self.invalid_ids, blocked_devices=self.blocked_devices,
                )
                self.journal.append({"event": "graph_context", "scenario_id": sid, **self.graph_context})
                allowed = [row for row in actions if row.action == ACTION_BY_SCENARIO[sid]]
                context = PlanningContext(
                    batch=available_batch,
                    incidents=incidents,
                    nodes=nodes,
                    actions=allowed,
                    evidence_readings=evidence,
                    graph_context=copy.deepcopy(self.graph_context),
                )
                plan = await scenario.draft_plan(
                    context.model_copy(deep=True), BudgetProvider(self)
                )
                plan = validate_plan(context, plan)
                if self.generation != generation or not self._eligible(
                    [row.reading_id for row in evidence]
                ):
                    raise BrainError(
                        "EVIDENCE_INVALIDATED", "Containment changed the selected evidence"
                    )
                for alert in plan.alerts:
                    results.append(
                        self._decision(
                            batch, sid, "alert", alert, [row.reading_id for row in evidence]
                        )
                    )
                for proposal in plan.proposals:
                    try:
                        results.append(
                            await self._execute(
                                batch,
                                sid,
                                proposal,
                                policy,
                                nodes,
                                actions,
                                capabilities,
                                scores,
                                thresholds,
                                scale,
                                generation,
                            )
                        )
                    except BrainError as error:
                        results.append(
                            self._decision(
                                batch,
                                sid,
                                "blocked",
                                error.message,
                                proposal.source_reading_ids,
                                proposal,
                                error.code,
                                error.details,
                            )
                        )
                if not plan.proposals and not plan.alerts:
                    results.append(
                        self._decision(
                            batch,
                            sid,
                            "blocked",
                            "Incident has no supported response",
                            [row.reading_id for row in evidence],
                            code="RESPONSE_UNAVAILABLE",
                        )
                    )
            except NotImplementedError:
                results.append(
                    self._decision(
                        batch,
                        sid,
                        "blocked",
                        "Assigned scenario implementation has not been delivered",
                        [row.reading_id for row in relevant],
                        code="SCENARIO_NOT_IMPLEMENTED",
                    )
                )
            except BrainError as error:
                results.append(
                    self._decision(
                        batch,
                        sid,
                        "blocked",
                        error.message,
                        [
                            source
                            for incident in incidents
                            for source in incident.source_reading_ids
                        ],
                        code=error.code,
                        details=error.details,
                    )
                )
            except (ValueError, KeyError, TypeError, ValidationError):
                results.append(
                    self._decision(
                        batch,
                        sid,
                        "blocked",
                        "Scenario policy or response is malformed",
                        [row.reading_id for row in relevant],
                        code="SCENARIO_INVALID",
                    )
                )
        return results

    async def _check_execution_state(self, batch, capabilities, generation, proposal, sid):
        clock = await self._call(self.twin, "get_clock", {})
        current = self._validate_clock(batch, clock, execution=True)
        await self._sync_containment(batch, capabilities)
        if self.generation != generation or not self._eligible(proposal.source_reading_ids):
            raise BrainError("EVIDENCE_INVALIDATED", "Containment invalidated the queued command")
        if proposal.action == "dispatch":
            key = self._operation_key(batch, sid, proposal)
            for carrier in proposal.targets:
                readings = [self.ledger[source] for source in proposal.source_reading_ids
                            if self.ledger[source].node_id == carrier
                            and self.ledger[source].sensor == "units_free"
                            and self.ledger[source].channel == proposal.params.get("unit_type")]
                used = sum(qty for other, (node, unit, qty, sent_tick) in self.dispatch_allocations.items()
                           if other != key and node == carrier and unit == proposal.params["unit_type"]
                           and (self.intents.get(other, {}).get("status") != "committed"
                                or not readings or min(r.tick for r in readings) <= sent_tick))
                if not readings or min(r.value for r in readings) - used < proposal.params["units"]:
                    raise BrainError("RESOURCE_RESERVED", "Unit is already allocated to another action")
        latest = self.latest_feed
        if latest is not None and latest.run_id != batch.run_id:
            raise BrainError("CLOCK_MISMATCH", "Twin reset while planning")
        if latest is not None and latest.tick > batch.tick:
            # Newer observations can withdraw a plan, never grant permission for it.
            fresh = {(r.device_id, r.sensor, r.channel): r for r in latest.readings}
            for source in proposal.source_reading_ids:
                old = self.ledger[source]
                row = fresh.get((old.device_id, old.sensor, old.channel))
                if row is None or row.value is None or row.unit != old.unit:
                    raise BrainError("EVIDENCE_CHANGED", "Latest feed no longer supports the plan evidence")
                if row.sensor == "units_free" and row.value < proposal.params.get("units", 1):
                    raise BrainError("EVIDENCE_CHANGED", "Latest feed has insufficient matching-unit availability")
                policy = self.policies.get(sid, {})
                withdrawn = self._incident_cleared(row, policy, sid)
                if sid == "S07" and row.sensor == policy.get("sensor"):
                    withdrawn = row.value >= policy.get("threshold_max", float("-inf"))
                if withdrawn:
                    raise BrainError("EVIDENCE_CHANGED", "Latest feed no longer shows this incident")
        return current

    async def _execute(
        self,
        batch,
        sid,
        proposal,
        policy,
        nodes,
        actions,
        capabilities,
        scores,
        thresholds,
        scale,
        generation,
    ):
        tools = capabilities.get("tools_you_can_call", [])
        if "actuate" not in tools:
            raise BrainError("TOOL_UNAVAILABLE", "Twin does not advertise actuation")
        caps = capabilities.get("action_caps", {})
        # Single-domain manifest caps are usable; shared domains still need their own limit.
        caps = dict(caps)
        for row in actions:
            caps.setdefault(row.domain, row.action_cap)
        check_caps(proposal, nodes, caps)
        if proposal.action == "set_valve_position":
            if not any(
                (sid != "S07" or (choice.get("supply_preserving") is True
                                  and bool(choice.get("reviewed_topology_ref"))))
                and sorted(choice.get("targets", [])) == proposal.targets
                and choice.get("params") == proposal.params
                and any(
                    self.ledger[source].node_id == choice.get("incident_node_id")
                    for source in proposal.source_reading_ids
                )
                for choice in policy.get("safe_valve_choices", [])
            ):
                raise BrainError(
                    "TOPOLOGY_UNAVAILABLE", "Configured topology does not support the valve request"
                )
        cutoff = thresholds.get(proposal.risk)
        if (
            isinstance(cutoff, bool)
            or not isinstance(cutoff, (int, float))
            or not math.isfinite(cutoff)
            or not 0 <= cutoff <= scale
        ):
            raise BrainError("TRUST_POLICY_UNAVAILABLE", "Risk cut-off is not configured")
        if any(scores[source] < cutoff for source in proposal.source_reading_ids):
            raise BrainError(
                "TRUST_INSUFFICIENT", "Evidence does not meet the actuator's risk cut-off"
            )
        intent = dict(action=proposal.action, targets=proposal.targets, params=proposal.params)
        key = self._operation_key(batch, sid, proposal)
        receipt = self.intents.get(key)
        if receipt and receipt["status"] in {"committed", "rejected"}:
            return self._decision(
                batch,
                sid,
                receipt["status"],
                "Existing exact-command receipt reused",
                proposal.source_reading_ids,
                proposal,
                receipt.get("code"),
                receipt.get("details"),
            )
        if receipt and receipt["status"] == "pending":
            return await self._confirm(batch, sid, proposal, key, capabilities, generation)
        if receipt and receipt["status"] == "uncertain":
            request = self.sent_requests.get(key)
            if request and key not in self.reconciliation_attempts:
                current = await self._check_execution_state(batch, capabilities, generation, proposal, sid)
                self._token_binding(request["token"], intent, current, cutoff, scale,
                                    idempotency_key=key, reading_ids=proposal.source_reading_ids, risk=proposal.risk)
                self.reconciliation_attempts.add(key)
                try:
                    response = await self._call(self.twin, "actuate", request)
                except BrainError:
                    return self._decision(batch, sid, "pending", "Reconciliation failed; original outcome remains unknown",
                                          proposal.source_reading_ids, proposal, code="OUTCOME_UNCERTAIN")
                result = self._save_receipt(batch, sid, proposal, key, response)
                if self.intents[key]["status"] == "pending":
                    return await self._confirm(batch, sid, proposal, key, capabilities, generation)
                return result
            return self._decision(batch, sid, "pending", "Uncertain send needs reconciliation; no new token or send",
                                  proposal.source_reading_ids, proposal, code="OUTCOME_UNCERTAIN")
        for previous_key, previous in self.intents.items():
            request = self.sent_requests.get(previous_key, {})
            if (previous.get("status") in {"pending", "uncertain"}
                    and request.get("action") == proposal.action
                    and set(request.get("targets", [])) & set(proposal.targets)):
                raise BrainError("OUTCOME_UNCERTAIN", "An earlier operation on this actuator is unresolved")
        await self._sync_containment(batch, capabilities)
        if self.generation != generation or not self._eligible(proposal.source_reading_ids):
            raise BrainError("EVIDENCE_INVALIDATED", "Containment invalidated the queued command")
        preview = None
        if proposal.preview_required:
            preview_tool = self.features.get("preview_tool")
            if not preview_tool or preview_tool not in tools:
                raise BrainError("PREVIEW_UNAVAILABLE", "Required preview is not advertised")
            preview = await self._call(self.twin, preview_tool, intent)
            if preview_tool == "preview_action":
                if (preview.get("run_id") != batch.run_id
                        or any(preview.get(field) != intent[field] for field in intent)):
                    raise BrainError("PREVIEW_INVALID", "Preview does not bind the exact request")
                passed = preview.get("would_pass_checks") is True and preview.get("blocked_by") == []
            else:
                passed = preview.get("safe") is True
            if not passed:
                raise BrainError(
                    "PREVIEW_UNSAFE", "Required preview did not confirm a safe command"
                )
        authorization_clock = await self._check_execution_state(batch, capabilities, generation, proposal, sid)
        approval = await self._call(
            self.guardian,
            self.features.get("guardian_token_tool"),
            {
                "run_id": batch.run_id,
                "tick": authorization_clock.tick,
                **intent,
                "time": authorization_clock.time,
                "risk": proposal.risk,
                "source_reading_ids": proposal.source_reading_ids,
                **({"idempotency_key": key} if self.features.get("guardian_exact_idempotency") else {}),
            },
        )
        if approval.get("approved") is not True:
            raise BrainError(
                "GUARDIAN_DENIED",
                "Guardian refused the exact command",
                {
                    "guardian_code": approval.get("code"),
                },
            )
        current = await self._check_execution_state(batch, capabilities, generation, proposal, sid)
        token = self._token_binding(approval.get("token"), intent, current, cutoff, scale,
                                    idempotency_key=key, reading_ids=proposal.source_reading_ids, risk=proposal.risk)
        if preview is not None and self.features.get("preview_tool") == "preview_action":
            until = preview.get("valid_until_tick")
            if type(until) is not int or current.tick > until:
                raise BrainError("PREVIEW_EXPIRED", "Preview expired before execution")
        self.journal.set_clock(current)
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=" * (-len(token.split(".")[1]) % 4)))
        self.journal.append({"event": "guardian_approval", "run_id": batch.run_id,
                             "tick": current.tick, "token_id": claims.get("jti", claims.get("token_id")),
                             "source_reading_ids": proposal.source_reading_ids,
                             "idempotency_key": key})
        self.journal.append(
            {
                "event": "actuate_requested",
                "run_id": batch.run_id,
                "tick": batch.tick,
                "scenario_id": sid,
                "idempotency_key": key,
                **intent,
            }
        )
        try:
            self.pending_started.setdefault(key, time.monotonic())
            if proposal.action == "dispatch":
                self.dispatch_allocations[key] = (proposal.targets[0], proposal.params["unit_type"], proposal.params["units"], current.tick)
            self.sent_requests[key] = {**intent, "token": token, "idempotency_key": key}
            self.intents[key] = {"status": "uncertain"}
            response = await self._call(
                self.twin,
                "actuate",
                self.sent_requests[key],
            )
        except BrainError as error:
            if error.code in {"PEER_TIMEOUT", "PEER_UNAVAILABLE"}:
                self.intents[key] = {"status": "uncertain"}
                return self._decision(
                    batch,
                    sid,
                    "pending",
                    "Send outcome is uncertain; preserve the original idempotency key",
                    proposal.source_reading_ids,
                    proposal,
                    code=error.code,
                )
            self.dispatch_allocations.pop(key, None)
            self.intents[key] = {"status": "rejected", "code": error.code, "details": error.details}
            return self._decision(
                batch,
                sid,
                "rejected",
                error.message,
                proposal.source_reading_ids,
                proposal,
                error.code,
                error.details,
            )
        result = self._save_receipt(batch, sid, proposal, key, response)
        if self.intents[key]["status"] == "pending":
            return await self._confirm(batch, sid, proposal, key, capabilities, generation)
        return result

    async def _confirm(self, batch, sid, proposal, key, capabilities, generation):
        tool = self.features.get("commit_tool")
        if not tool or tool not in capabilities.get("tools_you_can_call", []):
            return self._decision(batch, sid, "pending", "Twin confirmation is not advertised",
                                  proposal.source_reading_ids, proposal, code="CONFIRMATION_UNAVAILABLE")
        deadline = self.pending_started.setdefault(key, time.monotonic()) + 10
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                async with asyncio.timeout(remaining):
                    current = await self._check_execution_state(batch, capabilities, generation, proposal, sid)
                    request = self.sent_requests.get(key)
                    if request:
                        self._token_binding(request["token"],
                                            {field: request[field] for field in ("action", "targets", "params")},
                                            current, 0, 1, idempotency_key=key,
                                            reading_ids=proposal.source_reading_ids, risk=proposal.risk)
                    response = await asyncio.wait_for(
                        self._call(self.twin, tool, {"idempotency_key": key}), min(3, remaining))
                return self._save_receipt(batch, sid, proposal, key, response)
            except (TimeoutError, BrainError) as error:
                if isinstance(error, BrainError) and error.code not in {"PEER_TIMEOUT", "PEER_UNAVAILABLE"}:
                    raise
                if attempt == 0 and deadline - time.monotonic() > 1:
                    await asyncio.sleep(1)
        return self._decision(batch, sid, "pending", "Confirmation outcome uncertain; retain original key",
                              proposal.source_reading_ids, proposal, code="CONFIRMATION_TIMEOUT")

    def _save_receipt(self, batch, sid, proposal, key, response):
        expected = {"run_id": batch.run_id, "action": proposal.action,
                    "targets": proposal.targets, "params": proposal.params}
        if any(field in response and response[field] != value for field, value in expected.items()):
            self.intents[key] = {"status": "uncertain"}
            return self._decision(batch, sid, "pending", "Peer receipt refers to a different operation",
                                  proposal.source_reading_ids, proposal, code="RECEIPT_MISMATCH")
        status = response.get("status")
        if status not in {"committed", "pending", "rejected"}:
            self.intents[key] = {"status": "uncertain"}
            return self._decision(
                batch,
                sid,
                "pending",
                "Twin returned no recognized confirmation",
                proposal.source_reading_ids,
                proposal,
                code="PEER_SCHEMA_INVALID",
            )
        self.intents[key] = response
        if status in {"committed", "rejected"}:
            self.sent_requests.pop(key, None)
            self.pending_started.pop(key, None)
        decision = self._decision(
            batch,
            sid,
            status,
            {
                "committed": "Twin confirmed the command",
                "pending": "Twin accepted the command; confirmation is pending",
                "rejected": "Twin rejected the complete command",
            }[status],
            proposal.source_reading_ids,
            proposal,
            response.get("code"),
            response.get("details"),
        )
        if status == "rejected":
            self.dispatch_allocations.pop(key, None)
        if status == "committed":
            for owner, incident in self.active.values():
                if (owner == sid and incident.source_reading_ids
                        and set(incident.source_reading_ids).issubset(proposal.source_reading_ids)):
                    self.episode_receipts[incident.incident_id] = decision
        return decision

    def notify_containment(self, notice: ContainmentNotice):
        if notice.run_id != self.run_id:
            return {"accepted": False, "code": "RUN_MISMATCH"}
        if notice.event_id in self.containment_events:
            return {"accepted": True, "duplicate": True}
        self.containment_events.add(notice.event_id)
        self.graph_context = {}
        self.generation += 1
        devices = set(notice.device_ids)
        affected = set(notice.reading_ids) | {
            source for source, row in self.ledger.items() if row.device_id in devices
        }
        self.invalid_ids.update(affected)
        if notice.state == "released":
            self.blocked_devices.difference_update(devices)
        elif notice.state in {"isolated", "quarantined"}:
            self.blocked_devices.update(devices)
        # Release never resurrects old evidence. Corrected evidence must arrive with new IDs.
        for state in self.states.values():
            state.clear()
        for key, (_, incident) in list(self.active.items()):
            if set(incident.source_reading_ids) & affected:
                self.active.pop(key)
        self.journal.append(
            {
                "event": "containment_notice",
                **notice.model_dump(),
                "invalidated_reading_ids": sorted(affected),
            }
        )
        return {"accepted": True, "invalidated": len(affected), "committed_effects_unchanged": True}

    def get_active_incidents(self, run_id):
        return {
            "run_id": run_id,
            "incidents": [
                incident.model_dump()
                for _, incident in self.active.values()
                if incident.run_id == run_id
            ],
        }

    def explain_decision(self, decision_id):
        decision = self.decisions.get(decision_id)
        return {
            "found": decision is not None,
            "decision": decision.model_dump() if decision else None,
        }

    async def close(self):
        closer = getattr(self.provider, "aclose", None)
        if closer:
            await closer()


def build_runtime(
    *,
    twin: ToolPeer,
    guardian: ToolPeer,
    provider: PlanProvider,
    policies: dict[str, dict],
    features: dict,
    artifact_dir: Path | None = None,
) -> BrainRuntime:
    return BrainRuntime(
        twin=twin,
        guardian=guardian,
        provider=provider,
        policies=policies,
        features=features,
        artifact_dir=artifact_dir,
    )

"""Shared, fail-closed orchestration; scenario detectors never call peers themselves."""

import asyncio
import base64
import copy
import hashlib
import json
import math
from pathlib import Path

from pydantic import ValidationError

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
from civis_brain.inputs.service import normalize_batch
from civis_brain.integration.journal import Journal
from civis_brain.planning.service import check_caps, validate_plan
from civis_brain.ports import PlanProvider, ToolPeer
from civis_brain.scenarios.registry import SCENARIOS

RELEVANCE = {
    "S01": ("traffic", {"congestion_index"}),
    "S02": ("water", {"water_level"}),
    "S03": ("power", {"load_kw", "voltage_v"}),
    "S04": ("air_quality", {"pm25"}),
    "S05": ("emergency", {"emergency_calls"}),
}
ACTION_BY_SCENARIO = {
    "S01": "set_signal_plan",
    "S02": "set_valve_position",
    "S03": None,
    "S04": None,
    "S05": "dispatch",
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
        enabled = features.get("enabled_scenario_ids", list(RELEVANCE))
        if not isinstance(enabled, list) or not set(enabled).issubset(RELEVANCE):
            raise ValueError("enabled_scenario_ids must contain known scenario IDs")
        self.enabled = set(enabled)
        self.lock = asyncio.Lock()
        self.journal = Journal(artifact_dir / "trace.jsonl" if artifact_dir else None)
        self.run_id = None
        self._reset()

    def _reset(self):
        self.states = {scenario.scenario_id: {} for scenario in self.scenarios}
        self.ledger = {}
        self.invalid_ids = set()
        self.blocked_devices = set()
        self.containment_events = set()
        self.generation = 0
        self.last_tick = -1
        self.cached_ticks = {}
        self.active = {}
        self.decisions = {}
        self.intents = {}
        self.trust_attempts = {}
        self.ai_calls = 0

    async def _call(self, peer, name, arguments):
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
        self.journal.append({"event": "decision", "scenario_id": scenario, **decision.model_dump()})
        return decision

    async def _discovery(self, batch):
        capabilities = await self._call(self.twin, "get_capabilities", {})
        if capabilities.get("protocol_version") != PROTOCOL:
            raise BrainError("PROTOCOL_MISMATCH", "Twin must negotiate the required MCP protocol")
        clock = await self._call(self.twin, "get_clock", {})
        if any(
            clock.get(field) != getattr(batch, field)
            for field in ("run_id", "tick", "time", "tick_seconds")
        ):
            raise BrainError("CLOCK_MISMATCH", "Batch does not match Twin's current run and clock")
        nodes_response = await self._call(self.twin, "list_nodes", {})
        actions_response = await self._call(self.twin, "list_actions", {})
        nodes = [Node.model_validate(row) for row in nodes_response["nodes"]]
        actions = [ActionInfo.model_validate(row) for row in actions_response["actions"]]
        normalize_batch(batch, nodes)
        return nodes, actions, capabilities

    def _eligible(self, source_ids):
        return all(
            source in self.ledger
            and source not in self.invalid_ids
            and self.ledger[source].device_id not in self.blocked_devices
            and self.ledger[source].value is not None
            and self.ledger[source].unit
            == {
                "congestion_index": "percent",
                "water_level": "cm",
                "load_kw": "kW",
                "voltage_v": "V",
                "pm25": "ug/m3",
                "emergency_calls": "calls/min",
                "units_free": "units",
            }.get(self.ledger[source].sensor)
            and self.ledger[source].channel
            == {
                "emergency_calls": "medical",
                "units_free": "ambulance",
            }.get(self.ledger[source].sensor)
            for source in source_ids
        )

    async def _trusted(self, batch, incidents):
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
        attempts_key = tuple(sorted(incident.incident_id for incident in incidents))
        attempt = self.trust_attempts.get(attempts_key, 0)
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
        rows = response.get("scores")
        if not isinstance(rows, list):
            raise BrainError("PEER_SCHEMA_INVALID", "Guardian did not return per-reading scores")
        scores = {}
        for row in rows:
            score = row.get("score")
            if (
                row.get("reading_id") in scores
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                or not 0 <= score <= scale
            ):
                raise BrainError(
                    "PEER_SCHEMA_INVALID", "Guardian returned malformed numeric evidence"
                )
            scores[row.get("reading_id")] = score
        if set(scores) != set(ids) or any(score < cutoff for score in scores.values()):
            self.trust_attempts[attempts_key] = attempt + 1
            self.journal.append(
                {
                    "event": "trust_refusal",
                    "run_id": batch.run_id,
                    "tick": batch.tick,
                    "attempt": attempt + 1,
                    "source_reading_ids": ids,
                }
            )
            raise BrainError("TRUST_INSUFFICIENT", "Evidence has missing or insufficient trust")
        self.trust_attempts.pop(attempts_key, None)
        return [self.ledger[source] for source in ids], scores, thresholds, scale

    def _token_binding(self, token, intent, clock, floor, scale):
        if not isinstance(token, str) or not token:
            raise BrainError("TOKEN_MISSING", "Guardian supplied no exact-action approval token")
        self.journal.remember_secret(token)
        # JWS claims are checked here; signature verification and consumption belong to Twin.
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
            valid = (
                claims["iss"] == "guardian"
                and claims["aud"] == "twin"
                and claims["run_id"] == clock.run_id
                and type(claims["iat"]) is int
                and type(claims["exp"]) is int
                and claims["iat"] <= clock.tick < claims["exp"]
                and isinstance(claims["jti"], str)
                and bool(claims["jti"])
                and all(claims[field] == intent[field] for field in ("action", "targets", "params"))
                and type(claims["score"]) in (int, float)
                and math.isfinite(claims["score"])
                and floor <= claims["score"] <= scale
                and claims.get("score_scale") == scale
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
                ):
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
                for key, (owner, incident) in list(self.active.items()):
                    if owner == sid and set(incident.node_ids) & touched:
                        self.active.pop(key)
                for incident in incidents:
                    self.active[incident.incident_id] = (sid, incident)
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
                evidence, scores, thresholds, scale = await self._trusted(batch, incidents)
                allowed = [row for row in actions if row.action == ACTION_BY_SCENARIO[sid]]
                context = PlanningContext(
                    batch=available_batch,
                    incidents=incidents,
                    nodes=nodes,
                    actions=allowed,
                    evidence_readings=evidence,
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
                sorted(choice.get("targets", [])) == proposal.targets
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
        key = "brain-" + fingerprint({"run_id": batch.run_id, "scenario": sid, **intent})
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
            commit_tool = self.features.get("commit_tool")
            if not commit_tool or commit_tool not in tools:
                return self._decision(
                    batch,
                    sid,
                    "pending",
                    "Twin confirmation is not advertised",
                    proposal.source_reading_ids,
                    proposal,
                    code="CONFIRMATION_UNAVAILABLE",
                )
            response = await self._call(self.twin, commit_tool, {"idempotency_key": key})
            return self._save_receipt(batch, sid, proposal, key, response)
        if proposal.preview_required:
            preview_tool = self.features.get("preview_tool")
            if not preview_tool or preview_tool not in tools:
                raise BrainError("PREVIEW_UNAVAILABLE", "Required preview is not advertised")
            preview = await self._call(
                self.twin,
                preview_tool,
                {
                    "run_id": batch.run_id,
                    "tick": batch.tick,
                    **intent,
                },
            )
            if preview.get("safe") is not True:
                raise BrainError(
                    "PREVIEW_UNSAFE", "Required preview did not confirm a safe command"
                )
        approval = await self._call(
            self.guardian,
            self.features.get("guardian_token_tool"),
            {
                "run_id": batch.run_id,
                "tick": batch.tick,
                **intent,
                "risk": proposal.risk,
                "source_reading_ids": proposal.source_reading_ids,
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
        token = self._token_binding(approval.get("token"), intent, batch, cutoff, scale)
        clock = await self._call(self.twin, "get_clock", {})
        if any(clock.get(field) != getattr(batch, field) for field in ("run_id", "tick", "time")):
            raise BrainError(
                "CLOCK_CHANGED", "Twin advanced before execution; re-evaluate fresh evidence"
            )
        if self.generation != generation or not self._eligible(proposal.source_reading_ids):
            raise BrainError("EVIDENCE_INVALIDATED", "Containment invalidated the queued command")
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
            response = await self._call(
                self.twin,
                "actuate",
                {
                    **intent,
                    "token": token,
                    "idempotency_key": key,
                },
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
        return self._save_receipt(batch, sid, proposal, key, response)

    def _save_receipt(self, batch, sid, proposal, key, response):
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
        return self._decision(
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

    def notify_containment(self, notice: ContainmentNotice):
        if notice.run_id != self.run_id:
            return {"accepted": False, "code": "RUN_MISMATCH"}
        if notice.event_id in self.containment_events:
            return {"accepted": True, "duplicate": True}
        self.containment_events.add(notice.event_id)
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

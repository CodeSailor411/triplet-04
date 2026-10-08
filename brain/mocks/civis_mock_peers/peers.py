"""Network-free peers. Unsigned fixture approvals are test data, not authentication."""

import base64
import copy
import json
from typing import Any

from civis_brain.contracts import ActionInfo, ActionProposal, Node, Plan, PlanningContext
from civis_brain.errors import BrainError
from civis_brain.integration.journal import Journal
from civis_brain.planning.service import check_caps, validate_command

PROTOCOL = "2026-07-28"


def encode_claims(claims: dict) -> str:
    def encode(value):
        return (
            base64.urlsafe_b64encode(json.dumps(value, sort_keys=True).encode())
            .decode()
            .rstrip("=")
        )

    return encode({"alg": "none", "typ": "JWT"}) + "." + encode(claims) + "."


def decode_claims(token: str) -> dict:
    try:
        header, payload, signature = token.split(".")
        metadata = json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))
        if metadata != {"alg": "none", "typ": "JWT"} or signature:
            raise ValueError
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not isinstance(claims, dict):
            raise ValueError
        return claims
    except (ValueError, TypeError, KeyError):
        raise BrainError("TOKEN_INVALID", "Invalid fixture approval") from None


class FixtureTwin:
    is_fixture = True

    def __init__(self, case: dict):
        if case.get("fixture_only") is not True:
            raise ValueError("Fixture peers require fixture_only=true")
        self.case = copy.deepcopy(case)
        self.calls: list[dict] = []
        self.effects: list[dict] = []
        self.clock = copy.deepcopy(case["batches"][0])
        self.receipts: dict[str, tuple[dict, dict]] = {}
        self.used_tokens: set[str] = set()
        self.journal = Journal(None)

    def advance(self, batch):
        self.clock = batch.model_dump() if hasattr(batch, "model_dump") else copy.deepcopy(batch)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"name": name, "arguments": self.journal.redact(arguments)})
        if name == "get_capabilities":
            tools = ["get_capabilities", "get_clock", "list_nodes", "list_actions", "actuate"]
            if self.case.get("preview", {}).get("available") is True:
                tools.append("fixture_preview")
            if self.case.get("twin_outcome", {}).get("commit_available") is True:
                tools.append("fixture_commit")
            return {
                "protocol_version": PROTOCOL,
                "tools_you_can_call": tools,
                "action_caps": self.case.get("caps", {}),
            }
        if name == "get_clock":
            return {key: self.clock[key] for key in ("run_id", "tick", "time", "tick_seconds")}
        if name == "list_nodes":
            return {"nodes": self.case["nodes"]}
        if name == "list_actions":
            return {"actions": self.case["actions"]}
        if name == "fixture_preview" and self.case.get("preview", {}).get("available") is True:
            return copy.deepcopy(self.case["preview"])
        if name == "actuate":
            return self._actuate(arguments)
        if (
            name == "fixture_commit"
            and self.case.get("twin_outcome", {}).get("commit_available") is True
        ):
            key = arguments["idempotency_key"]
            if key not in self.receipts:
                raise BrainError("UNKNOWN_REQUEST", "Unknown pending fixture command")
            intent, result = self.receipts[key]
            if result["status"] == "pending":
                self.effects.append(copy.deepcopy(intent))
                result = {"status": "committed", "code": "FIXTURE_COMMITTED"}
                self.receipts[key] = (intent, result)
            return copy.deepcopy(result)
        raise BrainError("TOOL_UNAVAILABLE", "Fixture Twin does not advertise this tool")

    def _actuate(self, arguments: dict) -> dict:
        intent = {key: arguments[key] for key in ("action", "targets", "params")}
        key = arguments["idempotency_key"]
        if key in self.receipts:
            previous, result = self.receipts[key]
            if previous != intent:
                raise BrainError(
                    "IDEMPOTENCY_CONFLICT", "Fixture key already binds a different command"
                )
            return copy.deepcopy(result)
        claims = decode_claims(arguments["token"])
        self.journal.remember_secret(arguments["token"])
        if claims.get("iss") != "guardian" or claims.get("aud") != "twin":
            raise BrainError("TOKEN_INVALID", "Fixture approval has the wrong issuer or audience")
        if claims.get("run_id") != self.clock["run_id"]:
            raise BrainError("TOKEN_RUN_MISMATCH", "Fixture approval belongs to another run")
        if not isinstance(claims.get("exp"), int) or not isinstance(claims.get("iat"), int):
            raise BrainError("TOKEN_INVALID", "Fixture approval has no tick validity")
        if not claims["iat"] <= self.clock["tick"] < claims["exp"]:
            raise BrainError("TOKEN_EXPIRED", "Fixture approval is outside its tick lifetime")
        if any(claims.get(field) != intent[field] for field in intent):
            raise BrainError(
                "TOKEN_ACTION_MISMATCH", "Fixture approval binds another exact command"
            )
        if not isinstance(claims.get("jti"), str) or claims["jti"] in self.used_tokens:
            raise BrainError("TOKEN_REPLAY", "Fixture approval was already consumed")
        actions = [ActionInfo.model_validate(row) for row in self.case["actions"]]
        manifest = next((row for row in actions if row.action == intent["action"]), None)
        if manifest is None:
            raise BrainError("UNKNOWN_ACTION", "Fixture manifest does not support this command")
        nodes = [Node.model_validate(row) for row in self.case["nodes"]]
        validate_command(manifest, intent["targets"], intent["params"], nodes)
        proposal = ActionProposal(
            **intent,
            risk=manifest.risk,
            preview_required=manifest.preview_required,
            source_reading_ids=["fixture-token"],
            reason="Fixture check",
        )
        check_caps(proposal, nodes, self.case.get("caps", {}))
        if manifest.preview_required and self.case.get("preview", {}).get("safe") is not True:
            raise BrainError("PREVIEW_UNSAFE", "Fixture preview did not establish a safe command")
        result = copy.deepcopy(self.case.get("twin_outcome") or {"status": "committed"})
        if result.get("status") not in {"committed", "pending", "rejected"}:
            raise BrainError("PEER_SCHEMA_INVALID", "Fixture outcome status is invalid")
        self.used_tokens.add(claims["jti"])
        self.receipts[key] = (copy.deepcopy(intent), result)
        if result["status"] == "committed":
            self.effects.append(copy.deepcopy(intent))
        return result


class FixtureGuardian:
    is_fixture = True

    def __init__(self, case: dict):
        if case.get("fixture_only") is not True:
            raise ValueError("Fixture peers require fixture_only=true")
        self.case = copy.deepcopy(case)
        self.calls: list[dict] = []
        self.journal = Journal(None)
        self.sequence = 0

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"name": name, "arguments": self.journal.redact(arguments)})
        config = self.case["guardian"]
        if name == "get_capabilities":
            return {
                "protocol_version": PROTOCOL,
                "score_scale": config["score_scale"],
                "thresholds": config["thresholds"],
            }
        if name == "fixture_score":
            return {
                "scores": [
                    {
                        "reading_id": row["reading_id"],
                        "score": config.get("scores", {}).get(row["reading_id"], config["score"]),
                    }
                    for row in arguments["readings"]
                ]
            }
        if name == "fixture_approve":
            if config.get("approve") is not True:
                return {"approved": False, "code": config.get("refusal_code", "FIXTURE_DENIED")}
            self.sequence += 1
            claims = {key: arguments[key] for key in ("run_id", "action", "targets", "params")}
            claims.update(
                iss="guardian",
                aud="twin",
                jti=f"fixture-{self.sequence}",
                iat=arguments["tick"],
                exp=arguments["tick"] + config["token_lifetime_ticks"],
                score=config["score"],
                score_scale=config["score_scale"],
            )
            claims.update(config.get("claim_overrides", {}))
            token = encode_claims(claims)
            self.journal.remember_secret(token)
            return {"approved": True, "token": token, "code": "FIXTURE_APPROVED"}
        raise BrainError("TOOL_UNAVAILABLE", "Fixture Guardian does not implement this tool")


class FixturePlanProvider:
    def __init__(self, case: dict):
        if case.get("fixture_only") is not True:
            raise ValueError("Fixture provider requires fixture_only=true")
        self.case = copy.deepcopy(case)
        self.calls: list[dict] = []

    async def generate(self, context: PlanningContext) -> Plan:
        self.calls.append(
            {
                "run_id": context.batch.run_id,
                "evidence_ids": [row.reading_id for row in context.evidence_readings],
            }
        )
        return Plan.model_validate(copy.deepcopy(self.case["ai_plan"]))

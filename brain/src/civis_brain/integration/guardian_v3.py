"""Adapter for the published Guardian v3 MCP tools. No signing or synthetic scores."""

import asyncio
import math

from civis_brain.errors import BrainError

SCORE_TOOL = "guardian_v3_scores"
APPROVAL_TOOL = "guardian_v3_approval"


class GuardianV3Peer:
    is_fixture = False

    def __init__(self, peer):
        self.peer = peer

    async def call_tool(self, name, arguments):
        if name == "get_capabilities":
            reply = await self.peer.call_tool("describe_capabilities", {})
            policy = reply.get("guardian_verdict_policy", {})
            if not isinstance(policy, dict) or not isinstance(policy.get("risk_minimums"), dict):
                raise BrainError("GUARDIAN_SCHEMA_INVALID", "Guardian v3 trust policy is malformed")
            thresholds = {"reading": policy.get("trusted_min_inclusive"),
                          **policy.get("risk_minimums", {})}
            if (reply.get("protocol_version") != "2026-07-28"
                    or any(type(thresholds.get(k)) not in (int, float)
                           or not math.isfinite(thresholds[k]) or not 0 <= thresholds[k] <= 1
                           for k in ("reading", "R1", "R2", "R3"))):
                raise BrainError("GUARDIAN_SCHEMA_INVALID", "Guardian v3 must publish its trust policy")
            return {"protocol_version": reply["protocol_version"], "score_scale": 1.0,
                    "thresholds": thresholds, "transport": "guardian_v3_mcp"}
        if name == SCORE_TOOL:
            rows = arguments.get("readings", [])
            if not rows or len({r["reading_id"] for r in rows}) != len(rows):
                raise BrainError("GUARDIAN_SCHEMA_INVALID", "Distinct evidence IDs are required")
            semaphore = asyncio.Semaphore(4)

            async def verdict(row):
                async with semaphore:
                    reply = await self.peer.call_tool("get_trust_verdict", {
                        "reading_id": row["reading_id"], "fresh": True,
                    })
                score = reply.get("trust_score")
                if (reply.get("caused_by") != row["reading_id"] or reply.get("scale") != [0.0, 1.0]
                        or type(score) not in (int, float) or not math.isfinite(score)
                        or not 0 <= score <= 1):
                    raise BrainError("GUARDIAN_SCHEMA_INVALID", "Invalid evidence verdict from Guardian")
                return {"reading_id": row["reading_id"], "score": score}

            return {"scores": await asyncio.gather(*(verdict(row) for row in rows))}
        if name == APPROVAL_TOOL:
            domain = {"set_signal_plan": "Traffic", "set_valve_position": "Water",
                      "dispatch": "Emergency", "set_grid_switch": "Power"}.get(arguments["action"])
            if domain is None:
                raise BrainError("UNKNOWN_ACTION", "Action has no agreed domain mapping")
            reply = await self.peer.call_tool("authorize_action", {
                "run_id": arguments["run_id"], "reading_ids": arguments["source_reading_ids"],
                "action": arguments["action"], "targets": arguments["targets"],
                "params": arguments["params"], "risk_level": arguments["risk"],
                "domain": domain, "idempotency_key": arguments["idempotency_key"],
            })
            if reply.get("decision") == "approved" and isinstance(reply.get("token"), str):
                return {"approved": True, "token": reply["token"]}
            if reply.get("decision") != "refused":
                raise BrainError("GUARDIAN_SCHEMA_INVALID", "Unexpected Guardian authorization response")
            return {"approved": False, "code": reply.get("refusal_code")}
        raise BrainError("TOOL_UNAVAILABLE", "Unknown Guardian v3 adapter operation")

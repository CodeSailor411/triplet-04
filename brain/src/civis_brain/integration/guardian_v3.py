"""Adapter for the published Guardian v3 MCP tools. No signing or synthetic scores."""

import asyncio
import math

from civis_brain.errors import BrainError

SCORE_TOOL = "guardian_v3_scores"
APPROVAL_TOOL = "guardian_v3_approval"


class GuardianV3Peer:
    is_fixture = False

    def __init__(self, peer, *, verdict_wait_seconds=1.5):
        if (type(verdict_wait_seconds) not in (int, float)
                or not math.isfinite(verdict_wait_seconds) or verdict_wait_seconds < 0):
            raise ValueError("Guardian verdict wait must be finite and nonnegative")
        self.peer = peer
        self.verdict_wait_seconds = verdict_wait_seconds
        self.last_retrieval = None

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
            loop = asyncio.get_running_loop()
            started = loop.time()
            deadline = started + self.verdict_wait_seconds
            summary = {"reading_count": len(rows), "calls": 0, "retries": 0,
                       "not_ready_errors": 0, "unknown_tool_errors": 0,
                       "outcome": "running", "failure_code": None}
            self.last_retrieval = summary

            async def verdict(row):
                last_error = None
                retry_delay = self.verdict_wait_seconds / 3
                for attempt in range(3):
                    if attempt:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            raise last_error
                        await asyncio.sleep(min(retry_delay, remaining))
                    requested = False
                    try:
                        async with semaphore:
                            request = {"reading_id": row["reading_id"], "fresh": True}
                            if attempt:
                                remaining = deadline - loop.time()
                                if remaining <= 0:
                                    raise last_error
                                summary["calls"] += 1
                                summary["retries"] += 1
                                requested = True
                                reply = await asyncio.wait_for(
                                    self.peer.call_tool("get_trust_verdict", request), remaining)
                            else:
                                summary["calls"] += 1
                                requested = True
                                reply = await self.peer.call_tool("get_trust_verdict", request)
                            retry_delay = self.verdict_wait_seconds / 3
                            if not isinstance(reply, dict):
                                raise BrainError(
                                    "GUARDIAN_SCHEMA_INVALID", "Guardian verdict must be an object")
                            # MCP 2.3 wraps the published model-union return value.
                            if "result" in reply:
                                if set(reply) != {"result"} or not isinstance(reply["result"], dict):
                                    raise BrainError(
                                        "GUARDIAN_SCHEMA_INVALID", "Malformed Guardian verdict wrapper")
                                reply = reply["result"]
                            if reply.get("status") == "pending":
                                if (reply.get("reading_id") != row["reading_id"]
                                        or type(reply.get("retry_after_ms")) is not int
                                        or not 1 <= reply["retry_after_ms"] <= 60000
                                        or type(reply.get("last_scored_tick")) is not int
                                        or reply["last_scored_tick"] < 0
                                        or any(field in reply for field in (
                                            "trust_score", "caused_by", "scale"))):
                                    raise BrainError(
                                        "GUARDIAN_SCHEMA_INVALID", "Malformed pending Guardian verdict")
                                retry_delay = reply["retry_after_ms"] / 1000
                                raise BrainError(
                                    "GUARDIAN_VERDICT_NOT_READY", "Guardian has not scored this reading")
                    except TimeoutError:
                        if attempt == 0:
                            raise BrainError("PEER_TIMEOUT", "Guardian request timed out") from None
                        raise last_error from None
                    except BrainError as error:
                        if not requested:
                            raise
                        if attempt and error.code == "PEER_TIMEOUT" and last_error is not None:
                            raise last_error from None
                        if error.code not in {"GUARDIAN_VERDICT_NOT_READY", "PEER_ERROR"}:
                            raise
                        last_error = error
                        counter = ("not_ready_errors" if error.code == "GUARDIAN_VERDICT_NOT_READY"
                                   else "unknown_tool_errors")
                        summary[counter] += 1
                        if attempt == 2 or self.verdict_wait_seconds == 0:
                            raise
                    else:
                        break
                score = reply.get("trust_score")
                if (reply.get("caused_by") != row["reading_id"] or reply.get("scale") != [0.0, 1.0]
                        or type(score) not in (int, float) or not math.isfinite(score)
                        or not 0 <= score <= 1):
                    raise BrainError("GUARDIAN_SCHEMA_INVALID", "Invalid evidence verdict from Guardian")
                return {"reading_id": row["reading_id"], "score": score}

            tasks = [asyncio.create_task(verdict(row)) for row in rows]
            try:
                result = {"scores": await asyncio.gather(*tasks)}
                summary["outcome"] = "succeeded"
                return result
            except BrainError as error:
                summary["outcome"] = "failed"
                summary["failure_code"] = (error.code if error.code in {
                    "PEER_ERROR", "PEER_TIMEOUT", "GUARDIAN_VERDICT_NOT_READY",
                    "GUARDIAN_SCHEMA_INVALID", "PEER_SCHEMA_INVALID", "UNAUTHENTICATED",
                    "TRUST_INSUFFICIENT", "PEER_UNAVAILABLE", "TOOL_UNAVAILABLE",
                } else "OTHER_PEER_FAILURE")
                raise
            except asyncio.CancelledError:
                summary["outcome"] = "cancelled"
                raise
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                summary["elapsed_real_seconds"] = round(loop.time() - started, 6)
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

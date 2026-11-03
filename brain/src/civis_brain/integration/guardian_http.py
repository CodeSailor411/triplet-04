"""Read the published Guardian v2 HTTP verdict API through the existing internal port.

No new public endpoint or proxy signer. Its current g1 approval format cannot be
bound to Twin's exact-request JWS contract, so physical execution stays blocked.
The caller supplies the partner's published policy, never guessed trust defaults.
"""

import math
from datetime import datetime

import httpx

from civis_brain.errors import BrainError

SCORE_TOOL = "guardian_http_scores"
APPROVAL_TOOL = "guardian_http_approval"


class GuardianHTTPPeer:
    is_fixture = False

    def __init__(self, url, key, policy, timeout_seconds=3, *, allow_provisional=False):
        if not url.startswith(("http://", "https://")) or not key:
            raise ValueError("Guardian HTTP URL and caller key are required")
        trust = policy.get("trust", {}) if isinstance(policy, dict) else None
        if not isinstance(trust, dict) or not isinstance(trust.get("risk_minimums"), dict):
            raise ValueError("Explicit Guardian trust policy is required")
        cutoff = trust.get("trusted_min")
        minima = trust.get("risk_minimums", {})
        numbers = [cutoff, *(minima.get(r) for r in ("R1", "R2", "R3"))]
        if any(type(n) not in (int, float) or not math.isfinite(n) or not 0 <= n < 1
               for n in numbers):
            raise ValueError("Explicit Guardian reading and risk cutoffs are required")
        if trust.get("score_field") != "trust_score":
            raise ValueError("Unsupported Guardian score field")
        if trust.get("risk_values_provisional") is not False and not allow_provisional:
            raise ValueError("Provisional Guardian risk minima require explicit mock profile")
        self.url, self.key = url.rstrip("/"), key
        self.timeout_seconds = timeout_seconds
        self.thresholds = {"reading": math.nextafter(float(cutoff), 1.0), **minima}
        self.provisional = trust.get("risk_values_provisional") is not False
        self.run_id = None

    async def _get(self, path):
        try:
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self.key}"},
                timeout=self.timeout_seconds, follow_redirects=False,
            ) as client:
                response = await client.get(self.url + path)
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("Expected object")
                return body
        except httpx.HTTPStatusError as error:
            code = "GUARDIAN_UNAUTHENTICATED" if error.response.status_code in (401, 403) else (
                "GUARDIAN_HTTP_ERROR")
            raise BrainError(code, "Guardian HTTP request failed",
                             {"http_status": error.response.status_code}) from None
        except httpx.TimeoutException:
            raise BrainError("PEER_TIMEOUT", "Guardian HTTP read timed out") from None
        except (httpx.HTTPError, ValueError):
            raise BrainError("PEER_UNAVAILABLE", "Guardian HTTP response is unavailable") from None

    async def call_tool(self, name, arguments):
        if name == "get_capabilities":
            await self._get("/health")
            return {
                # Normalized internal contract version, not a claim of HTTP MCP tools.
                "protocol_version": "2026-07-28", "transport": "guardian_v2_http",
                "score_scale": 1.0, "thresholds": self.thresholds,
                "policy_provisional": self.provisional, "authorization_ready": False,
                "authorization_blocker": "GUARDIAN_TOKEN_CONTRACT_UNSUPPORTED",
            }
        if name == APPROVAL_TOOL:
            raise BrainError(
                "GUARDIAN_TOKEN_CONTRACT_UNSUPPORTED",
                "Guardian g1 tokens lack Twin JWS claims and exact target binding; agree the signed contract",
            )
        if name != SCORE_TOOL:
            raise BrainError("TOOL_UNAVAILABLE", "Unknown internal Guardian adapter operation")
        run_id = arguments.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise BrainError("PEER_SCHEMA_INVALID", "Guardian evidence requires run identity")
        if self.run_id is not None and self.run_id != run_id:
            raise BrainError("GUARDIAN_RUN_RESET_REQUIRED",
                             "Guardian v2 verdicts do not carry run IDs; restart with a fresh joint run")
        self.run_id = run_id
        requested = arguments.get("readings")
        if not isinstance(requested, list) or not requested:
            raise BrainError("PEER_SCHEMA_INVALID", "No evidence readings supplied")
        ids = [r.get("reading_id") for r in requested if isinstance(r, dict)]
        if len(ids) != len(requested) or len(set(ids)) != len(ids) or not all(ids):
            raise BrainError("PEER_SCHEMA_INVALID", "Evidence IDs must be unique")
        body = await self._get("/api/evaluations?limit=200")
        evaluations = body.get("evaluations")
        if not isinstance(evaluations, list):
            raise BrainError("PEER_SCHEMA_INVALID", "Guardian evaluations are malformed")
        scores = []
        for row in requested:
            if row.get("run_id") != run_id:
                raise BrainError("PEER_SCHEMA_INVALID", "Evidence run mismatch")
            evaluation = next((e for e in reversed(evaluations) if isinstance(e, dict)
                               and e.get("reading_id") == row["reading_id"]), None)
            if evaluation is None:
                raise BrainError("GUARDIAN_EVIDENCE_UNAVAILABLE",
                                 "Guardian has not published this reading in its bounded evaluation window")
            self._check_binding(row, evaluation)
            verdict = evaluation.get("guardian")
            if (evaluation.get("synthetic") is not False
                    or evaluation.get("action_blocked") is not False
                    or evaluation.get("layer_a", {}).get("status") != "passed"
                    or not isinstance(verdict, dict)):
                raise BrainError("GUARDIAN_EVIDENCE_REJECTED",
                                 "Guardian rejected this evidence; numeric trust cannot override it")
            score = verdict.get("trust_score")
            if (type(score) not in (int, float) or not math.isfinite(score)
                    or not 0 <= score <= 1 or verdict.get("reading_id") != row["reading_id"]
                    or verdict.get("sensor_id") != row["device_id"]):
                raise BrainError("PEER_SCHEMA_INVALID", "Guardian verdict binding/score is invalid")
            scores.append({"reading_id": row["reading_id"], "score": score})
        return {"scores": scores}

    @staticmethod
    def _check_binding(row, evaluation):
        original = evaluation.get("original_reading")
        if not isinstance(original, dict):
            raise BrainError("PEER_SCHEMA_INVALID", "Guardian original evidence is absent")
        try:
            stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            units = {"%": "percent", "percent": "percent"}
            sensor_types = {"congestion_index": "traffic_cam", "water_level": "water_level",
                            "load_kw": "power_load", "pm25": "air_quality",
                            "emergency_calls": "emergency_call"}
            location = original["location"]
            match = (
                stamp.utcoffset() is not None
                and original["reading_id"] == row["reading_id"]
                and original["sensor_id"] == row["device_id"]
                and original["sensor_type"] == sensor_types.get(row["sensor"])
                and original["sequence_number"] == row["tick"]
                and original["timestamp"] == stamp.timestamp()
                and original["value"] == row["value"]
                and row["value"] is not None
                and units.get(original["unit"], original["unit"]) == units.get(row["unit"], row["unit"])
                and location["lat"] == row["lat"] and location["lng"] == row["lon"]
            )
        except (KeyError, ValueError, TypeError):
            match = False
        if not match:
            raise BrainError("GUARDIAN_EVIDENCE_MISMATCH",
                             "Guardian evaluated different content for the requested reading ID")

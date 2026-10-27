import asyncio
import base64
import json
from types import SimpleNamespace
from typing import Literal

import pytest
from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from civis_brain.errors import BrainError
from civis_brain.integration import mcp_peer
from civis_brain.integration.guardian_v3 import APPROVAL_TOOL, SCORE_TOOL, GuardianV3Peer
from civis_brain.integration.mcp_peer import MCPPeer

from .helpers import harness, make_case


class PublishedPeer:
    """Recorded wire shapes, not evidence of real Guardian service acceptance."""

    def __init__(self):
        self.calls = []
        self.score = .9

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if name == "describe_capabilities":
            return {"protocol_version": "2026-07-28", "guardian_verdict_policy": {
                "trusted_min_inclusive": .7, "risk_minimums": {"R1": .5, "R2": .7, "R3": .85}}}
        if name == "get_trust_verdict":
            return {"caused_by": args["reading_id"], "trust_score": self.score, "scale": [0., 1.]}
        return {"decision": "refused", "refusal_code": "safe_preview_tool_unconfirmed"}


class DelayedVerdictPeer(PublishedPeer):
    """Explicit test partner whose own feed makes an actual verdict available later."""

    def __init__(self, pending_calls=1, error_code="GUARDIAN_VERDICT_NOT_READY"):
        super().__init__()
        self.pending_calls = pending_calls
        self.error_code = error_code
        self.attempts = {}

    async def call_tool(self, name, args):
        if name == "get_trust_verdict":
            reading_id = args["reading_id"]
            self.attempts[reading_id] = self.attempts.get(reading_id, 0) + 1
            if self.attempts[reading_id] <= self.pending_calls:
                self.calls.append((name, args))
                raise BrainError(self.error_code, "Expected test tool failure")
        return await super().call_tool(name, args)


class PendingVerdictPeer(PublishedPeer):
    """The explicit pending shape published in Guardian's final-version tag."""

    def __init__(self, pending_calls=1, retry_after_ms=5):
        super().__init__()
        self.pending_calls = pending_calls
        self.retry_after_ms = retry_after_ms
        self.attempts = {}

    async def call_tool(self, name, args):
        if name == "get_trust_verdict":
            reading_id = args["reading_id"]
            self.attempts[reading_id] = self.attempts.get(reading_id, 0) + 1
            if self.attempts[reading_id] <= self.pending_calls:
                self.calls.append((name, args))
                return {"status": "pending", "reading_id": reading_id,
                        "retry_after_ms": self.retry_after_ms, "last_scored_tick": 16}
        return await super().call_tool(name, args)


async def test_v3_published_pending_verdict_retries_original_ids_until_scored():
    raw = PendingVerdictPeer()
    peer = GuardianV3Peer(raw, verdict_wait_seconds=1.5)
    result = await peer.call_tool(SCORE_TOOL, {
        "readings": [{"reading_id": "r1"}, {"reading_id": "r2"}]})
    assert result == {"scores": [{"reading_id": "r1", "score": .9},
                                  {"reading_id": "r2", "score": .9}]}
    assert raw.attempts == {"r1": 2, "r2": 2}
    assert all(name == "get_trust_verdict" and args["fresh"] for name, args in raw.calls)
    assert peer.last_retrieval["not_ready_errors"] == 2
    assert peer.last_retrieval["unknown_tool_errors"] == 0
    assert peer.last_retrieval["outcome"] == "succeeded"


async def test_v3_actual_mcp_model_union_wraps_pending_and_scored_verdicts(monkeypatch):
    class Scored(BaseModel):
        trust_score: float
        caused_by: str
        scale: list[float]

    class Pending(BaseModel):
        status: Literal["pending"]
        reading_id: str
        retry_after_ms: int
        last_scored_tick: int

    server = MCPServer("published-guardian-union-test")
    attempts = {}

    @server.tool(structured_output=True)
    def get_trust_verdict(reading_id: str, fresh: bool = False) -> Scored | Pending:
        attempts[reading_id] = attempts.get(reading_id, 0) + 1
        if attempts[reading_id] == 1:
            return Pending(status="pending", reading_id=reading_id,
                           retry_after_ms=5, last_scored_tick=16)
        return Scored(trust_score=.9, caused_by=reading_id, scale=[0., 1.])

    monkeypatch.setattr(mcp_peer, "streamable_http_client", lambda *args, **kwargs: server)
    transport = MCPPeer("in-memory", "fixture-only-key")
    pending = await transport.call_tool("get_trust_verdict", {"reading_id": "probe", "fresh": True})
    assert pending == {"result": {"status": "pending", "reading_id": "probe",
                                  "retry_after_ms": 5, "last_scored_tick": 16}}
    scored = await transport.call_tool("get_trust_verdict", {"reading_id": "probe", "fresh": True})
    assert scored == {"result": {"trust_score": .9, "caused_by": "probe", "scale": [0., 1.]}}
    peer = GuardianV3Peer(transport, verdict_wait_seconds=.5)
    assert await peer.call_tool(SCORE_TOOL, {"readings": [{"reading_id": "r1"}]}) == {
        "scores": [{"reading_id": "r1", "score": .9}]}
    assert attempts == {"probe": 2, "r1": 2}
    assert peer.last_retrieval["not_ready_errors"] == 1


@pytest.mark.parametrize("wrapped", [
    {"result": None}, {"result": []}, {"result": "not-a-verdict"},
    {"result": {"trust_score": .9, "caused_by": "r1", "scale": [0, 1]}, "extra": True},
    {"result": {"result": {"trust_score": .9, "caused_by": "r1", "scale": [0, 1]}}},
    {"result": {}, "trust_score": .9, "caused_by": "r1", "scale": [0, 1]},
])
async def test_v3_rejects_malformed_or_mixed_union_wrappers_without_retry(wrapped):
    class WrappedPeer(PublishedPeer):
        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return wrapped

    raw = WrappedPeer()
    with pytest.raises(BrainError) as error:
        await GuardianV3Peer(raw).call_tool(SCORE_TOOL, {"readings": [{"reading_id": "r1"}]})
    assert error.value.code == "GUARDIAN_SCHEMA_INVALID"
    assert len(raw.calls) == 1


@pytest.mark.parametrize("budget,retry_after_ms,max_calls", [(0, 5, 1), (.15, 5, 3), (.06, 60000, 1)])
async def test_v3_pending_never_returns_scores_or_waits_past_retry_budget(
    budget, retry_after_ms, max_calls,
):
    raw = PendingVerdictPeer(pending_calls=100, retry_after_ms=retry_after_ms)
    peer = GuardianV3Peer(raw, verdict_wait_seconds=budget)
    with pytest.raises(BrainError) as error:
        await asyncio.wait_for(peer.call_tool(
            SCORE_TOOL, {"readings": [{"reading_id": "r1"}]}), .5)
    assert error.value.code == "GUARDIAN_VERDICT_NOT_READY"
    assert 1 <= raw.attempts["r1"] <= max_calls
    assert peer.last_retrieval["failure_code"] == "GUARDIAN_VERDICT_NOT_READY"
    assert peer.last_retrieval["outcome"] == "failed"


@pytest.mark.parametrize("override", [
    {"reading_id": "different-reading"}, {"reading_id": None},
    {"retry_after_ms": None}, {"retry_after_ms": True}, {"retry_after_ms": 1.5},
    {"retry_after_ms": 0}, {"retry_after_ms": -1}, {"retry_after_ms": 60001},
    {"last_scored_tick": None}, {"last_scored_tick": True}, {"last_scored_tick": 1.5},
    {"last_scored_tick": -1}, {"trust_score": .9}, {"caused_by": "r1"}, {"scale": [0, 1]},
])
async def test_v3_rejects_malformed_or_mismatched_pending_without_retry(override):
    class MalformedPending(PublishedPeer):
        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return {"status": "pending", "reading_id": "r1", "retry_after_ms": 5,
                    "last_scored_tick": 16, **override}

    raw = MalformedPending()
    peer = GuardianV3Peer(raw)
    with pytest.raises(BrainError) as error:
        await peer.call_tool(SCORE_TOOL, {"readings": [{"reading_id": "r1"}]})
    assert error.value.code == "GUARDIAN_SCHEMA_INVALID"
    assert len(raw.calls) == 1
    assert peer.last_retrieval["retries"] == 0


@pytest.mark.parametrize("code", ["GUARDIAN_VERDICT_NOT_READY", "PEER_ERROR"])
async def test_v3_read_only_retrieval_retries_without_ingesting_or_fabricating(code):
    raw = DelayedVerdictPeer(error_code=code)
    peer = GuardianV3Peer(raw, verdict_wait_seconds=.15)
    reply = await peer.call_tool(SCORE_TOOL, {
        "readings": [{"reading_id": "r1"}, {"reading_id": "r2"}]})
    assert reply == {"scores": [{"reading_id": "r1", "score": .9},
                                {"reading_id": "r2", "score": .9}]}
    assert raw.attempts == {"r1": 2, "r2": 2}
    assert all(name == "get_trust_verdict" and args["fresh"] for name, args in raw.calls)
    assert peer.last_retrieval["calls"] == 4
    assert peer.last_retrieval["retries"] == 2
    assert peer.last_retrieval["outcome"] == "succeeded"
    assert peer.last_retrieval["failure_code"] is None
    assert peer.last_retrieval["unknown_tool_errors"] == (2 if code == "PEER_ERROR" else 0)


@pytest.mark.parametrize("budget,max_calls", [(0, 1), (.3, 3)])
@pytest.mark.parametrize("code", ["GUARDIAN_VERDICT_NOT_READY", "PEER_ERROR"])
async def test_v3_verdict_wait_has_real_time_and_attempt_limits(budget, max_calls, code):
    raw = DelayedVerdictPeer(pending_calls=100, error_code=code)
    peer = GuardianV3Peer(raw, verdict_wait_seconds=budget)
    with pytest.raises(BrainError) as error:
        await asyncio.wait_for(peer.call_tool(
            SCORE_TOOL, {"readings": [{"reading_id": "r"}]}), 1)
    assert error.value.code == code
    # The real-time deadline may stop a loaded machine before the attempt cap.
    assert 1 <= raw.attempts["r"] <= max_calls
    assert peer.last_retrieval["outcome"] == "failed"
    assert peer.last_retrieval["failure_code"] == code
    assert "Expected test tool failure" not in str(peer.last_retrieval)


@pytest.mark.parametrize("code", ["PEER_TIMEOUT", "UNAUTHENTICATED",
                                   "GUARDIAN_SCHEMA_INVALID", "TRUST_INSUFFICIENT"])
async def test_v3_never_retries_a_denial_or_initial_network_error(code):
    class FailingPeer:
        calls = 0

        async def call_tool(self, name, args):
            self.calls += 1
            raise BrainError(code, "Expected test failure")

    raw = FailingPeer()
    with pytest.raises(BrainError) as error:
        await GuardianV3Peer(raw).call_tool(SCORE_TOOL, {"readings": [{"reading_id": "r"}]})
    assert error.value.code == code
    assert raw.calls == 1


async def test_v3_does_not_retry_a_malformed_actual_verdict():
    raw = PublishedPeer()
    raw.score = float("nan")
    with pytest.raises(BrainError) as error:
        await GuardianV3Peer(raw).call_tool(SCORE_TOOL, {"readings": [{"reading_id": "r"}]})
    assert error.value.code == "GUARDIAN_SCHEMA_INVALID"
    assert len(raw.calls) == 1


@pytest.mark.parametrize("code", ["GUARDIAN_VERDICT_NOT_READY", "PEER_ERROR"])
async def test_v3_retry_network_call_cannot_outlive_deadline_or_change_unknown_cause(code):
    class SlowRetry(DelayedVerdictPeer):
        cancelled = False

        async def call_tool(self, name, args):
            if self.attempts.get(args["reading_id"], 0):
                try:
                    await asyncio.Event().wait()
                finally:
                    self.cancelled = True
            return await super().call_tool(name, args)

    raw = SlowRetry(error_code=code)
    with pytest.raises(BrainError) as error:
        await asyncio.wait_for(GuardianV3Peer(raw, verdict_wait_seconds=.15).call_tool(
            SCORE_TOOL, {"readings": [{"reading_id": "r"}]}), .5)
    assert error.value.code == code
    assert raw.cancelled


async def test_v3_transport_timeout_after_unknown_tool_error_keeps_unknown_cause():
    class TimeoutAfterFailure(DelayedVerdictPeer):
        async def call_tool(self, name, args):
            if self.attempts.get(args["reading_id"], 0):
                raise BrainError("PEER_TIMEOUT", "Expected test transport timeout")
            return await super().call_tool(name, args)

    raw = TimeoutAfterFailure(error_code="PEER_ERROR")
    with pytest.raises(BrainError) as error:
        await GuardianV3Peer(raw, verdict_wait_seconds=.15).call_tool(
            SCORE_TOOL, {"readings": [{"reading_id": "r"}]})
    assert error.value.code == "PEER_ERROR"


async def test_v3_authorization_failure_is_never_retried():
    class UnavailableAuthorization(PublishedPeer):
        async def call_tool(self, name, args):
            self.calls.append((name, args))
            raise BrainError("PEER_ERROR", "Expected unknown authorization failure")

    raw = UnavailableAuthorization()
    with pytest.raises(BrainError) as error:
        await GuardianV3Peer(raw).call_tool(APPROVAL_TOOL, {"run_id": "run", "reading_ids": [],
            "source_reading_ids": ["r1"], "action": "set_signal_plan", "targets": ["TRA-01"],
            "params": {"plan": "normal"}, "risk": "R1", "idempotency_key": "exact-key"})
    assert error.value.code == "PEER_ERROR"
    assert len(raw.calls) == 1


async def test_v3_retrieval_summary_reaches_runtime_journal_without_payloads_or_tokens():
    runtime, _, _, _ = harness(make_case())
    raw = DelayedVerdictPeer(error_code="PEER_ERROR")
    runtime.guardian = GuardianV3Peer(raw, verdict_wait_seconds=0)
    with pytest.raises(BrainError):
        await runtime._call(runtime.guardian, SCORE_TOOL, {"run_id": "run", "tick": 1,
            "readings": [{"reading_id": "r1", "value": 999, "token": "PRIVATE_TEST_TOKEN"}]})
    summary = next(item for item in runtime.journal.events
                   if item["event"] == "guardian_verdict_retrieval")
    assert summary["calls"] == 1 and summary["failure_code"] == "PEER_ERROR"
    assert summary["unknown_tool_errors"] == 1
    assert summary["run_id"] == "run" and summary["tick"] == 1
    assert not any(key in summary for key in ("readings", "reading_ids", "value", "token"))
    assert "PRIVATE_TEST_TOKEN" not in json.dumps(summary)


async def test_v3_scoring_cancels_sibling_calls_after_a_fatal_failure():
    class FatalPeer:
        active = 0
        sibling_started = asyncio.Event()

        async def call_tool(self, name, args):
            if args["reading_id"] == "fatal":
                await self.sibling_started.wait()
                raise BrainError("UNAUTHENTICATED", "Expected test refusal")
            self.active += 1
            self.sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.active -= 1

    raw = FatalPeer()
    with pytest.raises(BrainError):
        await GuardianV3Peer(raw).call_tool(SCORE_TOOL, {
            "readings": [{"reading_id": "fatal"}, {"reading_id": "sibling"}]})
    assert raw.active == 0


async def test_v3_adapter_uses_real_tool_names_scale_and_exact_key():
    raw = PublishedPeer()
    peer = GuardianV3Peer(raw)
    assert (await peer.call_tool("get_capabilities", {}))["thresholds"]["reading"] == .7
    reply = await peer.call_tool(SCORE_TOOL, {"run_id": "run", "tick": 1,
                                             "readings": [{"reading_id": "r1"}, {"reading_id": "r2"}]})
    assert reply["scores"] == [{"reading_id": "r1", "score": .9}, {"reading_id": "r2", "score": .9}]
    assert all(args["fresh"] for name, args in raw.calls if name == "get_trust_verdict")
    result = await peer.call_tool(APPROVAL_TOOL, {"run_id": "run", "source_reading_ids": ["r1"],
        "action": "set_valve_position", "targets": ["valve"], "params": {"position": 80},
        "risk": "R3", "idempotency_key": "exact-key"})
    assert result == {"approved": False, "code": "safe_preview_tool_unconfirmed"}
    assert raw.calls[-1][0] == "authorize_action"
    assert raw.calls[-1][1]["domain"] == "Water"
    assert raw.calls[-1][1]["idempotency_key"] == "exact-key"


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), -1, 1.01])
async def test_v3_adapter_rejects_invalid_scores(score):
    raw = PublishedPeer()
    raw.score = score
    with pytest.raises(BrainError):
        await GuardianV3Peer(raw).call_tool(SCORE_TOOL, {"readings": [{"reading_id": "r"}]})


@pytest.mark.parametrize("override", [{}, {"v": True}, {"iat": 1792922460}, {"exp": 1792922600},
    {"trust_score": float("nan")}, {"token_id": ""}, {"reading_ids": ["other"]},
    {"idempotency_key": "other"}, {"risk_level": "R1"}, {"params": {"position": 40}}])
def test_g1_claim_binding_never_translates_or_signs(override):
    runtime, _, _, _ = harness(make_case())
    clock = SimpleNamespace(run_id="run", time="2026-10-25T10:00:00Z")
    from civis_brain.inputs.service import utc_time
    now = utc_time(clock.time).timestamp()
    claims = {"v": 1, "kid": "recorded-key", "iss": "guardian", "aud": "twin", "run_id": "run",
              "iat": now, "exp": now + 60, "token_id": "recorded-token", "action": "set_valve_position",
              "targets": ["valve"], "params": {"position": 80}, "trust_score": .9,
              "reading_ids": ["r1"], "risk_level": "R3", "idempotency_key": "key", **override}
    # The signature is an explicit placeholder. Twin alone verifies it in real execution.
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    token = f"g1.{payload}.recorded-signature"
    args = (token, {"action": "set_valve_position", "targets": ["valve"], "params": {"position": 80}},
            clock, .85, 1.)
    if override:
        with pytest.raises(BrainError):
            runtime._token_binding(*args, idempotency_key="key", reading_ids=["r1"], risk="R3")
    else:
        assert runtime._token_binding(*args, idempotency_key="key", reading_ids=["r1"], risk="R3") == token

import base64
import json
from types import SimpleNamespace

import pytest

from civis_brain.errors import BrainError
from civis_brain.integration.guardian_v3 import APPROVAL_TOOL, SCORE_TOOL, GuardianV3Peer

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

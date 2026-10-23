import json
from types import SimpleNamespace

import httpx
import pytest
from google import genai
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from civis_brain.contracts import ActionInfo, Node, PlanningContext, ReadingsBatch
from civis_brain.errors import BrainError
from civis_brain.integration import mcp_peer
from civis_brain.integration.mcp_peer import MappedGuardianPeer, MCPPeer
from civis_brain.planning.gemini import GeminiPlanProvider

from .helpers import SyntheticCandidate, make_case


def context():
    case = make_case()
    batch = ReadingsBatch.model_validate(case["batches"][0])
    nodes = [Node.model_validate(row) for row in case["nodes"]]
    incidents = SyntheticCandidate(case).detect(batch, nodes, case["policy"], {}).incidents
    return case, PlanningContext(
        batch=batch,
        nodes=nodes,
        incidents=incidents,
        actions=[ActionInfo.model_validate(row) for row in case["actions"]],
        evidence_readings=batch.readings,
    )


async def test_real_sdk_in_memory_transport_and_schema_refusals(monkeypatch):
    server = MCPServer("peer-test")

    @server.tool()
    def echo(tick: int) -> dict:
        return {"tick": tick}

    @server.tool()
    def deny() -> dict:
        raise ToolError("CAP_EXCEEDED: fixture-only refusal")

    # Actual SDK listing/call protocol, entirely in memory.
    monkeypatch.setattr(mcp_peer, "streamable_http_client", lambda *args, **kwargs: server)
    peer = MCPPeer("in-memory", "fixture-only-key")
    assert await peer.call_tool("echo", {"tick": 2}) == {"tick": 2}
    for name, arguments, code in [
        ("echo", {"tick": "not-integer"}, "PEER_SCHEMA_INVALID"),
        ("deny", {}, "CAP_EXCEEDED"),
        ("absent", {}, "TOOL_UNAVAILABLE"),
    ]:
        with pytest.raises(BrainError) as error:
            await peer.call_tool(name, arguments)
        assert error.value.code == code


async def test_guardian_mapping_requires_explicit_fields():
    class WirePeer:
        def __init__(self):
            self.calls = []

        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return {"assessment": {"rows": [{"reading_id": "r1", "score": 90}]}}

    wire = WirePeer()
    adapter = MappedGuardianPeer(
        wire,
        {
            "score": {
                "tool": "confirmed_score",
                "request_fields": {"run_id": "session"},
                "response_fields": {"scores": "assessment.rows"},
            },
        },
        "score",
        "approve",
    )
    assert (await adapter.call_tool("score", {"run_id": "run-1"}))["scores"][0]["score"] == 90
    assert wire.calls == [("confirmed_score", {"session": "run-1"})]
    with pytest.raises(BrainError):
        await adapter.call_tool("score", {"run_id": "run-1", "tick": 1})
    with pytest.raises(BrainError):
        await adapter.call_tool("approve", {})


async def test_gemini_schema_selected_evidence_and_one_call():
    case, ctx = context()
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(case["ai_plan"]), status="completed")

    client = SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=generate)))
    provider = GeminiPlanProvider("", "gemini-3.5-flash-lite", client=client)
    plan = await provider.generate(ctx)
    assert plan.proposals[0].risk == "R1" and len(calls) == 1
    payload = json.loads(calls[0]["input"])
    assert "selected_evidence" in payload and "batch" not in payload and "readings" not in payload
    assert calls[0]["response_format"]["mime_type"] == "application/json"
    assert calls[0]["response_format"]["schema"]["additionalProperties"] is False
    assert "tools" not in calls[0] and calls[0]["store"] is False


@pytest.mark.parametrize(
    "failure,code",
    [
        ("invalid", "AI_OUTPUT_INVALID"),
        ("quota", "AI_QUOTA_EXCEEDED"),
        ("unavailable", "AI_UNAVAILABLE"),
    ],
)
async def test_gemini_failures_do_not_retry_or_expose_secret(failure, code):
    _, ctx = context()
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        if failure == "invalid":
            return SimpleNamespace(
                output_text='{"proposals":[],"token":"invented"}', status="completed"
            )
        error = RuntimeError("PRIVATE_API_KEY")
        error.code = 429 if failure == "quota" else 500
        raise error

    client = SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=generate)))
    provider = GeminiPlanProvider("", "gemini-3.5-flash-lite", client=client)
    with pytest.raises(BrainError) as error:
        await provider.generate(ctx)
    assert error.value.code == code and "PRIVATE_API_KEY" not in str(error.value)
    assert len(calls) == 1


async def test_gemini_missing_key_and_unverified_model():
    _, ctx = context()
    with pytest.raises(BrainError) as error:
        await GeminiPlanProvider("", "gemini-3.5-flash-lite").generate(ctx)
    assert error.value.code == "AI_KEY_MISSING"
    with pytest.raises(BrainError):
        GeminiPlanProvider("", "unverified-model")


@pytest.mark.parametrize("status", [429, 503])
async def test_real_gemini_sdk_does_not_retry_failed_http_requests(monkeypatch, status):
    _, ctx = context()
    requests = []
    real_client = genai.Client

    async def respond(request):
        requests.append(request)
        return httpx.Response(
            status,
            json={"error": {"code": status, "message": "fixture refusal"}},
            request=request,
        )

    transport = httpx.AsyncClient(transport=httpx.MockTransport(respond))

    def client_factory(**kwargs):
        kwargs["http_options"].httpx_async_client = transport
        return real_client(**kwargs)

    monkeypatch.setattr(genai, "Client", client_factory)
    provider = GeminiPlanProvider("fixture-only-key", "gemini-3.5-flash-lite")
    try:
        with pytest.raises(BrainError) as error:
            await provider.generate(ctx)
        assert error.value.code == ("AI_QUOTA_EXCEEDED" if status == 429 else "AI_UNAVAILABLE")
        assert len(requests) == 1
        assert requests[0].url.path.endswith("/interactions")
    finally:
        await provider.aclose()
        await transport.aclose()

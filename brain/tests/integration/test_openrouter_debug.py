import json

import httpx
import pytest
from fastapi.testclient import TestClient

from civis_brain.app import create_app
from civis_brain.errors import BrainError
from civis_brain.planning.openrouter import MODEL, OpenRouterPlanProvider
from civis_brain.planning.smoke import synthetic_context
from civis_brain.settings import Settings


async def test_openrouter_free_only_request_and_local_schema_validation():
    calls = []

    def respond(request):
        calls.append(request)
        data = {"proposals": [], "alerts": ["Synthetic alert"]}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(data),
                            "reasoning_details": [{"text": "NEVER_EXPOSE"}],
                        },
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = OpenRouterPlanProvider("fixture-key", client=client)
        plan = await provider.generate(synthetic_context())
    assert plan.alerts == ["Synthetic alert"] and "NEVER_EXPOSE" not in str(plan)
    body = json.loads(calls[0].content)
    assert body["model"] == MODEL and body["response_format"] == {"type": "json_object"}
    assert body["provider"]["max_price"] == {"prompt": 0, "completion": 0, "request": 0}
    assert body["provider"]["allow_fallbacks"] is False and body["reasoning"]["enabled"] is False
    assert (
        "models" not in body
        and "tools" not in body
        and "fixture-key" not in calls[0].content.decode()
    )
    assert "required_json_schema" in json.loads(body["messages"][1]["content"])


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "AI_AUTH_FAILED"),
        (402, "AI_PAYMENT_REQUIRED"),
        (429, "AI_QUOTA_EXCEEDED"),
        (503, "AI_UNAVAILABLE"),
    ],
)
async def test_openrouter_failure_never_retries_or_echoes_key(status, code):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "fixture-key"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(BrainError) as error:
            await OpenRouterPlanProvider("fixture-key", client=client).generate(synthetic_context())
    assert error.value.code == code and "fixture-key" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "output",
    [
        '{"proposals":[],"alerts":[],"token":"invented"}',
        '{"proposals":[{"action":"invented"}],"alerts":[]}',
        "not json",
    ],
)
async def test_openrouter_rejects_json_or_plan_outside_schema(output):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"choices": [{"finish_reason": "stop", "message": {"content": output}}]}
            )
        )
    ) as client:
        with pytest.raises(BrainError) as error:
            await OpenRouterPlanProvider("fixture-key", client=client).generate(synthetic_context())
    assert error.value.code == "AI_OUTPUT_INVALID"


async def test_openrouter_timeout_and_paid_model_rejected():
    def respond(request):
        raise httpx.ReadTimeout("fixture-key")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(BrainError) as error:
            await OpenRouterPlanProvider("fixture-key", client=client).generate(synthetic_context())
    assert error.value.code == "AI_TIMEOUT"
    with pytest.raises(BrainError):
        OpenRouterPlanProvider("fixture-key", model="google/paid-model")


def test_home_debug_session_and_real_case_replay():
    settings = Settings(_env_file=None, llm_mode="fixture")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.get("/debug/state").status_code == 401
        home = client.get("/")
        assert home.status_code == 200 and "Brain console" in home.text
        assert "httponly" in home.headers["set-cookie"].lower()
        assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
        assert client.get("/favicon.ico").status_code == 204
        state = client.get("/debug/state").json()
        assert state["llm_mode"] == "fixture" and "api_key" not in str(state)
        assert client.post("/debug/case/S04/base", json={}).status_code == 403
        result = client.post(
            "/debug/case/S04/base", json={}, headers={"Origin": "http://localhost"}
        ).json()
        assert result["effects"] == result["provider_calls"] == 0
        assert result["batches"][-1]["decisions"][0]["status"] == "alert"
        assert (
            client.post(
                "/debug/case/S01/base", json={}, headers={"Origin": "http://localhost"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/debug/ai-smoke", json={}, headers={"Origin": "http://localhost"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/debug/case/S03/base", json={}, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )


def test_rebinding_host_and_disabled_debug_are_rejected():
    with TestClient(create_app(Settings(_env_file=None)), base_url="http://evil.example") as client:
        assert client.get("/").status_code == 403
    with TestClient(
        create_app(Settings(_env_file=None, brain_debug_enabled=False)), base_url="http://localhost"
    ) as client:
        assert client.get("/").status_code == 404


def test_debug_exposes_key_presence_only():
    settings = Settings(_env_file=None, llm_mode="openrouter", openrouter_api_key="fixture-secret")
    assert "fixture-secret" not in repr(settings)
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/")
        response = client.get("/debug/state")
        assert response.json()["key_configured"] is True
        assert "fixture-secret" not in response.text and "authorization" not in response.text


def test_browser_ai_smoke_is_bounded_and_never_calls_peers(monkeypatch):
    from civis_brain.contracts import Plan

    app = create_app(
        Settings(
            _env_file=None,
            llm_mode="openrouter",
            openrouter_api_key="fixture-secret",
            ai_max_calls_per_run=2,
        )
    )
    runtime = app.state.runtime
    calls = []

    async def generate(context):
        calls.append(context)
        return Plan(proposals=[], alerts=["Synthetic test only"])

    monkeypatch.setattr(runtime.provider, "generate", generate)
    with TestClient(app, base_url="http://localhost") as client:
        client.get("/")
        for _ in range(2):
            result = client.post("/debug/ai-smoke", json={}, headers={"Origin": "http://localhost"})
            assert result.json()["status"] == "validated" and result.json()["effects"] == 0
        assert (
            client.post(
                "/debug/ai-smoke", json={}, headers={"Origin": "http://localhost"}
            ).status_code
            == 429
        )
        assert len(calls) == 2 and runtime.twin.calls == runtime.guardian.calls == []
        assert "fixture-secret" not in client.get("/debug/state").text


def test_openrouter_credentials_are_redacted_in_nested_trace(tmp_path):
    from civis_brain.integration.journal import Journal

    journal = Journal(tmp_path / "trace.jsonl")
    journal.append(
        {
            "openrouter_api_key": "fixture-secret",
            "detail": {"text": "Unexpected key sk-or-v1-fixture-only-do-not-use"},
        }
    )
    text = journal.path.read_text(encoding="utf-8")
    assert "fixture-secret" not in text and "sk-or-v1-" not in text
    assert text.count("<redacted>") == 2

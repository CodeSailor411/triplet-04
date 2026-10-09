from fastapi.testclient import TestClient

from civis_brain.app import create_app
from civis_brain.settings import Settings


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
    settings = Settings(_env_file=None, llm_mode="gemini", gemini_api_key="fixture-secret")
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
            llm_mode="gemini",
            gemini_api_key="fixture-secret",
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

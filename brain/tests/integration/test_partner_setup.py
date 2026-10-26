import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civis_brain.app import create_app
from civis_brain.integration.bootstrap import configured_runtime
from civis_brain.settings import Settings, load_settings

ROOT = Path(__file__).resolve().parents[2]


def test_explicit_environment_reaches_app_factory(tmp_path, monkeypatch):
    path = tmp_path / ".env.partner"
    path.write_text("PEER_MODE=live\nLLM_MODE=gemini\nGEMINI_API_KEY=test-key-only\n")
    monkeypatch.setenv("CIVIS_ENV_FILE", str(path))
    app = create_app()
    assert app.state.runtime.twin.is_fixture is False
    assert app.state.runtime.guardian.is_fixture is False
    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["peer_mode"] == "live" and health["llm_mode"] == "gemini"
        assert health["guardian_contract_confirmed"] is True
        assert "test-key-only" not in str(health)


def test_explicit_missing_environment_never_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("CIVIS_ENV_FILE", str(tmp_path / "missing.env"))
    with pytest.raises(ValueError, match="does not exist"):
        load_settings()


def test_live_startup_does_not_read_any_fixture_case(tmp_path):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    runtime = configured_runtime(Settings(_env_file=None, brain_config_root=str(tmp_path),
        peer_mode="live", llm_mode="gemini", gemini_api_key="test-key-only",
        brain_fixture_case="missing-case.json"))
    assert runtime.twin.is_fixture is False
    assert runtime.guardian.is_fixture is False
    assert not (tmp_path / "mocks").exists()


def test_live_defaults_use_published_guardian_v3_contract_with_bounded_wait():
    from civis_brain.integration.guardian_v3 import GuardianV3Peer

    runtime = configured_runtime(Settings(
        _env_file=None, peer_mode="live", llm_mode="gemini", gemini_api_key="test-only-key",
        peer_timeout_seconds=1, guardian_verdict_wait_seconds=5))
    assert isinstance(runtime.guardian, GuardianV3Peer)
    assert runtime.guardian.peer.url == "http://127.0.0.1:5000/mcp"
    assert runtime.guardian.verdict_wait_seconds == 0.5
    assert runtime.features["guardian_contract_confirmed"] is True
    assert runtime.features["guardian_exact_idempotency"] is True


@pytest.mark.parametrize("mode,key,message", [
    ("fixture", "", "recorded fixture plans"),
    ("gemini", "", "GEMINI_API_KEY"),
])
def test_live_startup_rejects_offline_or_missing_ai(mode, key, message):
    with pytest.raises(ValueError, match=message):
        configured_runtime(Settings(_env_file=None, peer_mode="live",
            llm_mode=mode, gemini_api_key=key))


async def test_preflight_reports_configuration_failure_without_secret():
    from civis_brain.preflight import check
    result = await check(Settings(_env_file=None, peer_mode="live", llm_mode="fixture",
                                  gemini_api_key="test-secret-never-print"))
    assert result["ready"] is False
    assert any(row["check"] == "configuration" and not row["passed"] for row in result["checks"])
    assert "test-secret-never-print" not in str(result)


def test_private_handover_separates_roles_and_preserves_keys(tmp_path):
    import runpy

    from dotenv import dotenv_values

    prepare = runpy.run_path(str(ROOT / "scripts/prepare_partner_handover.py"))["prepare"]
    source = tmp_path / "source.env"
    source.write_text("GEMINI_API_KEY=private-test-gemini\nTWIN_BRAIN_KEY=dev-brain-to-twin\n")
    target = prepare(source, tmp_path / "handover")
    full = dotenv_values(target)
    dali = dotenv_values(target.parent / "dali.env")
    houssem = dotenv_values(target.parent / "houssem.env")
    assert dali["TWIN_KEY_CITY_BRAIN"] == full["TWIN_BRAIN_KEY"]
    assert houssem["BRAIN_GUARDIAN_CALLER_KEY"] == full["BRAIN_GUARDIAN_CALLER_KEY"]
    assert houssem["GUARDIAN_BRAIN_BEARER_KEY"] == full["BRAIN_GUARDIAN_CALLER_KEY"]
    assert "private-test-gemini" not in str(dali) + str(houssem)
    assert full["PEER_MODE"] == "live" and full["TWIN_FEED_ENABLED"] == "true"
    assert full["GUARDIAN_TRANSPORT"] == "mcp_v3"
    assert full["GUARDIAN_CONTRACT_CONFIRMED"] == "true"
    assert full["GUARDIAN_MCP_URL"] == "http://127.0.0.1:5000/mcp"
    assert houssem["GUARDIAN_BRAIN_MCP_BEARER_KEY"] == full["GUARDIAN_BRAIN_KEY"]
    assert "GUARDIAN_BRAIN_KEY" not in houssem
    prepare(source, target.parent)
    assert dotenv_values(target) == full


def test_private_handover_updates_stale_contract_without_changing_custom_addresses(tmp_path):
    import runpy

    from dotenv import dotenv_values

    prepare = runpy.run_path(str(ROOT / "scripts/prepare_partner_handover.py"))["prepare"]
    source = tmp_path / "source.env"
    source.write_text("GEMINI_API_KEY=private-test-gemini\n")
    output = tmp_path / "handover"
    output.mkdir()
    (output / ".env.partner").write_text(
        "GUARDIAN_TRANSPORT=mcp\nGUARDIAN_CONTRACT_CONFIRMED=false\n"
        "GUARDIAN_SCORE_TOOL=CONFIRM_WITH_9ANTRA\n"
        "GUARDIAN_MCP_URL=http://guardian.test:5000/mcp\n"
        "TWIN_MCP_URL=http://twin.test:8000/mcp\n"
        "SCENARIO_POLICY_FILE=.artifacts/reviewed.json\n")
    result = dotenv_values(prepare(source, output))
    assert result["GUARDIAN_TRANSPORT"] == "mcp_v3"
    assert result["GUARDIAN_CONTRACT_CONFIRMED"] == "true"
    assert result["GUARDIAN_SCORE_TOOL"] == "get_trust_verdict"
    assert result["GUARDIAN_MCP_URL"] == "http://guardian.test:5000/mcp"
    assert result["TWIN_MCP_URL"] == "http://twin.test:8000/mcp"
    assert result["SCENARIO_POLICY_FILE"] == ".artifacts/reviewed.json"


def test_private_handover_refuses_git_checkout(tmp_path):
    import runpy
    prepare = runpy.run_path(str(ROOT / "scripts/prepare_partner_handover.py"))["prepare"]
    with pytest.raises(ValueError, match="outside the Git checkout"):
        prepare(tmp_path / "unused", ROOT / ".private")


async def test_medical_restricts_general_twin_manifest_before_gemini(tmp_path):
    from civis_brain.planning.gemini import response_schema

    from .test_member_integration import case_for, evaluate, harness
    case = case_for("emergency")
    units = next(p for p in case["actions"][0]["params"] if p["name"] == "units")
    units.update(min_value=1, max_value=10)
    runtime, twin, _, provider = harness(case, tmp_path)
    contexts = []
    generate = provider.generate

    async def capture(context):
        contexts.append(context)
        return await generate(context)

    provider.generate = capture
    result = await evaluate(case, runtime, twin)
    assert result[-1].decisions[0].status == "committed"
    schema = response_schema(contexts[0])
    params = schema["properties"]["proposals"]["items"]["anyOf"][0]["properties"]["params"]["properties"]
    assert params["units"]["minimum"] == params["units"]["maximum"] == 1
    assert params["unit_type"]["enum"] == ["ambulance"]

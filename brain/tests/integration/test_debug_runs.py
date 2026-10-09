import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from civis_brain.app import create_app
from civis_brain.contracts import ReadingsBatch
from civis_brain.debug_runs import DebugRunRequest, load_case, run_debug_case
from civis_brain.errors import BrainError
from civis_brain.planning.gemini import GeminiPlanProvider
from civis_brain.settings import Settings


@pytest.mark.parametrize("scenario", ["S03", "S04", "DEMO_R1"])
@pytest.mark.parametrize("variant", ["base", "refusal"])
async def test_standard_debug_cases_run_through_actual_core(scenario, variant):
    result = await run_debug_case(
        Settings(_env_file=None), DebugRunRequest(scenario=scenario, variant=variant)
    )
    assert result["acceptance"]["passed"] is True
    assert result["requests"][0]["target"] == "mock_twin"
    assert result["requests"][0]["operation"] == "get_capabilities"
    assert "eyJ" not in json.dumps(result)
    assert result["synthetic_detector"] is (scenario == "DEMO_R1")
    if scenario == "DEMO_R1":
        assert result["batches"][0]["decisions"] == []
        assert result["provider_calls"] == 1
        assert result["effects"] == (1 if variant == "base" else 0)
        assert result["requests"][-1]["operation"] == (
            "actuate" if variant == "base" else "fixture_approve"
        )


def recorded_gemini(output, calls):
    async def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=json.dumps(output), status="completed")

    return GeminiPlanProvider(
        "",
        "gemini-3.5-flash-lite",
        client=SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=generate))),
    )


async def test_gemini_adapter_to_mock_approval_and_execution():
    settings = Settings(_env_file=None, llm_mode="gemini", gemini_api_key="fixture-secret")
    case = load_case(Path(settings.brain_config_root), "DEMO_R1", "base")
    calls = []
    result = await run_debug_case(
        settings,
        DebugRunRequest(scenario="DEMO_R1", provider_mode="gemini"),
        live_provider=recorded_gemini(case["ai_plan"], calls),
    )
    assert result["acceptance"]["passed"] is True and len(calls) == 1
    assert calls[0]["store"] is False and "tools" not in calls[0]
    payload = json.loads(calls[0]["input"])
    assert [r["reading_id"] for r in payload["selected_evidence"]] == ["demo-signal-2"]
    ai = next(row for row in result["requests"] if row["target"] == "gemini")
    assert ai["request"]["input"] == calls[0]["input"]
    assert ai["response"] == case["ai_plan"]
    approval = next(row for row in result["requests"] if row["operation"] == "fixture_approve")
    action = next(row for row in result["requests"] if row["operation"] == "actuate")
    assert approval["response"]["token"] == action["request"]["token"] == "<redacted>"
    assert result["effect_details"] == [
        {
            "action": "set_signal_plan",
            "targets": ["DEMO-SIGNAL-01"],
            "params": {"plan": "mock_priority"},
        }
    ]
    assert "fixture-secret" not in json.dumps(result)


async def test_invalid_gemini_plan_blocks_before_approval():
    calls = []
    result = await run_debug_case(
        Settings(_env_file=None),
        DebugRunRequest(scenario="DEMO_R1", provider_mode="gemini"),
        live_provider=recorded_gemini({"proposals": [], "alerts": [], "token": "invented"}, calls),
    )
    assert result["batches"][-1]["decisions"][0]["peer_code"] == "AI_OUTPUT_INVALID"
    assert result["effects"] == 0 and result["acceptance"]["passed"] is False
    assert not any(row["operation"] in {"fixture_approve", "actuate"} for row in result["requests"])
    assert len(calls) == 1


async def test_edited_baseline_is_evaluated_and_not_presented_as_preset_pass():
    settings = Settings(_env_file=None)
    case = load_case(Path(settings.brain_config_root), "DEMO_R1", "base")
    raw = copy.deepcopy(case["batches"])
    raw[-1]["readings"][0]["value"] = 20
    result = await run_debug_case(
        settings,
        DebugRunRequest(
            scenario="DEMO_R1", batches=[ReadingsBatch.model_validate(row) for row in raw]
        ),
    )
    assert result["effects"] == result["provider_calls"] == 0
    assert result["acceptance"]["passed"] is None
    assert all(batch["decisions"] == [] for batch in result["batches"])


async def test_run_id_change_cannot_reset_debug_ai_budget():
    settings = Settings(_env_file=None)
    case = load_case(Path(settings.brain_config_root), "DEMO_R1", "base")
    case["batches"][-1]["run_id"] = "another-run"
    with pytest.raises(BrainError) as error:
        await run_debug_case(
            settings,
            DebugRunRequest(
                scenario="DEMO_R1",
                batches=[ReadingsBatch.model_validate(row) for row in case["batches"]],
            ),
        )
    assert error.value.code == "INPUT_INVALID"


def test_request_editor_routes_and_redacted_export():
    with TestClient(create_app(Settings(_env_file=None)), base_url="http://localhost") as client:
        assert client.get("/debug/templates").status_code == 401
        client.get("/")
        assert client.get("/debug/export").status_code == 404
        rows = client.get("/debug/templates").json()["templates"]
        assert len(rows) == 6
        body = next(row["request"] for row in rows if row["request"]["scenario"] == "DEMO_R1")
        assert client.post("/debug/run", json=body).status_code == 403
        response = client.post("/debug/run", json=body, headers={"Origin": "http://localhost"})
        assert response.json()["acceptance"]["passed"] is True
        exported = client.get("/debug/export")
        assert exported.json() == response.json()
        assert "attachment" in exported.headers["content-disposition"]
        assert "eyJ" not in exported.text
        body["scenario"] = "S01"
        assert (
            client.post("/debug/run", json=body, headers={"Origin": "http://localhost"}).status_code
            == 422
        )

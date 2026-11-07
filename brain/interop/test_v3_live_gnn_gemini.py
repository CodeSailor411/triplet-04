"""Opt-in live Gemini check for the Twin-fed Traffic GNN shadow path."""

import asyncio
import time
from pathlib import Path

import pytest

from civis_brain.planning.gemini import GeminiPlanProvider
from civis_brain.settings import Settings

from .test_v3_shipped_acceptance import (
    shipped_stack,
    write_evidence,
)
from .test_v3_shipped_acceptance import shipped_twin as _shipped_twin_fixture


@pytest.fixture
def shipped_twin(request):
    yield from _shipped_twin_fixture.__wrapped__(request)


class RecordedPlannerWithLiveInterpreter:
    """Keep action planning recorded while exercising only Gemini graph reading."""

    def __init__(self, planner, interpreter):
        self.planner = planner
        self.interpreter = interpreter

    async def generate(self, context):
        return await self.planner.generate(context)

    async def interpret_graph(self, forecast):
        return await self.interpreter.interpret_graph(forecast)

    async def aclose(self):
        await self.interpreter.aclose()


async def wait_for_forecast(runtime, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        forecast = runtime.traffic_gnn_shadow
        if forecast.get("status") in {"ready", "unavailable"}:
            return forecast
        await asyncio.sleep(0.1)
    raise AssertionError({"forecast_timeout": runtime.traffic_gnn_shadow})


async def wait_for_interpretation(runtime, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        interpretation = runtime.traffic_gnn_interpretation
        if interpretation.get("status") in {"ready", "unavailable"}:
            return interpretation
        await asyncio.sleep(0.1)
    raise AssertionError({"interpretation_timeout": runtime.traffic_gnn_interpretation})


@pytest.mark.parametrize("shipped_twin", ["S01"], indirect=True)
async def test_live_gemini_interprets_native_twin_traffic_forecast(shipped_twin, monkeypatch):
    env_file = Path(__file__).resolve().parents[1] / ".env"
    settings = Settings(_env_file=env_file)
    assert settings.gemini_api_key, "Set GEMINI_API_KEY in brain/.env for this opt-in test"

    async with shipped_stack(shipped_twin, monkeypatch) as stack:
        interpreter = GeminiPlanProvider(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.ai_timeout_seconds,
        )
        stack.runtime.features.update(
            traffic_gnn_shadow_enabled=True,
            ai_timeout_seconds=settings.ai_timeout_seconds,
        )
        stack.runtime.provider = RecordedPlannerWithLiveInterpreter(
            stack.runtime.provider, interpreter
        )

        # Do not poll /health while Gemini is running. This test's health poll
        # uses a 3-second request timeout that can expire during model inference.
        forecast = await wait_for_forecast(stack.runtime)
        assert forecast.get("status") == "ready", forecast
        interpretation = await wait_for_interpretation(
            stack.runtime, settings.ai_timeout_seconds + 5
        )
        assert interpretation.get("status") == "ready", interpretation
        assert forecast["run_id"] == stack.runtime.run_id
        assert len(forecast["forecasts"]) == 11
        assert len(forecast["input_reading_ids"]) == 110
        assert set(forecast["input_reading_ids"]).issubset(stack.runtime.ledger)
        assert forecast["features"] == [
            {"name": "vehicle_count", "unit": "cars/min"},
            {"name": "avg_speed", "unit": "km/h"},
        ]
        assert interpretation["interpretation"]["trend"] in {
            "rising", "falling", "stable", "mixed", "unclear"
        }

        write_evidence(stack.directory, "live-traffic-graph-gemini", {
            "twin_tag": "twin-mock-3",
            "guardian_tag": "guardian_final_version",
            "scenario": "S01",
            "model": settings.gemini_model,
            "configured_timeout_seconds": settings.ai_timeout_seconds,
            "forecast_status": forecast["status"],
            "forecast_nodes": len(forecast["forecasts"]),
            "input_reading_count": len(forecast["input_reading_ids"]),
            "features": forecast["features"],
            "interpretation": interpretation["interpretation"],
            "forecast_used_for_action": False,
        })

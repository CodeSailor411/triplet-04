"""Explicit external-AI smoke using actual peer data/verdicts. Not part of CI."""

import os
import time

import httpx
import pytest

from civis_brain.contracts import ReadingsBatch
from civis_brain.integration.guardian_http import APPROVAL_TOOL, SCORE_TOOL
from civis_brain.integration.runtime import build_runtime
from civis_brain.planning.gemini import GeminiPlanProvider
from civis_brain.settings import Settings

from .test_partners import OUT, ROOT, prepare, save
from .test_v2_joint import actual_guardian, capture_batches, post_batch

pytestmark = pytest.mark.skipif(os.environ.get("CIVIS_RUN_LIVE_GEMINI") != "1",
                                reason="Explicit external Gemini opt-in required")


async def test_live_gemini_with_actual_guardian_and_twin(twin, guardian_url):
    settings = Settings(_env_file=ROOT / ".env")
    assert settings.gemini_api_key, "Local Gemini key required"
    httpx.post(guardian_url + "/api/reset", timeout=10).raise_for_status()
    app, url = twin
    client, case, _, _, _ = await prepare(url, "S02")
    provider = GeminiPlanProvider(settings.gemini_api_key, settings.gemini_model, 60)
    runtime = build_runtime(twin=client, guardian=actual_guardian(guardian_url), provider=provider,
        policies={"S02": case["policy"]}, features={"enabled_scenario_ids": ["S02"],
            "mock_integration_profile": True, "guardian_contract_confirmed": True,
            "guardian_score_tool": SCORE_TOOL, "guardian_token_tool": APPROVAL_TOOL,
            "preview_tool": "preview_action", "peer_timeout_seconds": 15,
            "max_evidence_age_seconds": 60, "ai_timeout_seconds": 60,
            "ai_max_calls_per_run": 1}, artifact_dir=OUT / "live-gemini")
    runtime.journal.remember_secret(settings.gemini_api_key)
    started = time.monotonic()
    try:
        batches = await capture_batches(url, 2)
        for batch in batches:
            await post_batch(guardian_url, batch)
            result = await runtime.evaluate_tick(ReadingsBatch.model_validate(batch))
        save("live-gemini-actual-guardian", {
            "model": settings.gemini_model, "real_seconds": round(time.monotonic() - started, 2),
            "result": result.model_dump(), "twin_effects": len(app.state.book.state),
            "provider": "ACTUAL Gemini", "guardian": "ACTUAL Guardian diagnostic layout",
            "scope": "Water reported-value fault; test valve choice, not hydraulic safety",
            "input_tick": batches[-1]["tick"], "current_tick": app.state.sim.tick})
        assert not app.state.book.state
        assert all(d.status in {"alert", "blocked"} for d in result.decisions)
    finally:
        await runtime.close()

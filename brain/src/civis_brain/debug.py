"""Local browser console. It never serves keys or bypasses MCP caller authorization."""

import asyncio
import json
import secrets
import sys
from importlib.metadata import version
from pathlib import Path

from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from civis_brain.contracts import ReadingsBatch
from civis_brain.errors import BrainError
from civis_brain.integration.runtime import build_runtime
from civis_brain.planning.service import validate_plan


def attach_debug(app, runtime, settings):
    session = secrets.token_urlsafe(32)
    lock = asyncio.Lock()
    last_case = {}
    last_ai = {}
    ai_calls = 0
    root = Path(settings.brain_config_root).resolve()

    def local(request):
        if (
            request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or request.client is None
            or request.client.host not in {"127.0.0.1", "::1", "localhost", "testclient"}
        ):
            raise HTTPException(403, "Debug console is available on loopback only")

    def authorized(request, write=False):
        local(request)
        if not secrets.compare_digest(request.cookies.get("civis_debug", ""), session):
            raise HTTPException(401, "Open the Brain home page to start a local debug session")
        if write and request.headers.get("origin") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Debug requests must originate from the Brain page")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def home(request: Request):
        local(request)
        nonce = secrets.token_urlsafe(24)
        html = Path(__file__).with_name("debug.html").read_text(encoding="utf-8")
        response = HTMLResponse(html.replace("__NONCE__", nonce))
        response.set_cookie("civis_debug", session, httponly=True, samesite="strict", max_age=3600)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'none'; connect-src 'self'; "
                    f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
                ),
            }
        )
        return response

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return Response(status_code=204)

    @app.get("/debug/state", include_in_schema=False)
    async def state(request: Request):
        authorized(request)
        return runtime.journal.redact(
            {
                "ready": False,
                "implemented_scenarios": ["S03", "S04"],
                "pending_scenarios": ["S01", "S02", "S05"],
                "peer_mode": settings.peer_mode,
                "llm_mode": settings.llm_mode,
                "model": settings.openrouter_model
                if settings.llm_mode == "openrouter"
                else settings.gemini_model
                if settings.llm_mode == "gemini"
                else "Recorded responses",
                "key_configured": bool(settings.openrouter_api_key)
                if settings.llm_mode == "openrouter"
                else bool(settings.gemini_api_key)
                if settings.llm_mode == "gemini"
                else False,
                "python": ".".join(map(str, sys.version_info[:3])),
                "versions": {
                    name: version(name) for name in ("fastapi", "pydantic", "mcp", "httpx")
                },
                "run_id": runtime.run_id,
                "ai_calls": runtime.ai_calls,
                "events": runtime.journal.events[-40:],
                "incidents": runtime.get_active_incidents(runtime.run_id)["incidents"],
                "last_case": last_case,
                "last_ai": last_ai,
            }
        )

    @app.post("/debug/case/{sid}/{variant}", include_in_schema=False)
    async def replay(request: Request, sid: str, variant: str):
        nonlocal last_case
        authorized(request, write=True)
        domains = {"S03": "power", "S04": "air_quality"}
        if sid not in domains or variant not in {"base", "refusal"}:
            raise HTTPException(404, "Only delivered Power/Air cases are available")
        async with lock:
            case = json.loads(
                (root / "mocks/cases" / domains[sid] / f"{variant}_case.json").read_text(
                    encoding="utf-8"
                )
            )
            twin, guardian, provider = (
                FixtureTwin(case),
                FixtureGuardian(case),
                FixturePlanProvider(case),
            )
            run = build_runtime(
                twin=twin,
                guardian=guardian,
                provider=provider,
                policies={sid: case["policy"]},
                features={
                    "enabled_scenario_ids": [sid],
                    "guardian_score_tool": "fixture_score",
                    "guardian_token_tool": "fixture_approve",
                },
                artifact_dir=root / ".artifacts/debug" / f"{sid}-{variant}",
            )
            batches = []
            for raw in case["batches"]:
                batch = ReadingsBatch.model_validate(raw)
                twin.advance(batch)
                batches.append((await run.evaluate_tick(batch)).model_dump())
            last_case = {
                "scenario": sid,
                "variant": variant,
                "fixture_only": True,
                "batches": batches,
                "readings": case["batches"],
                "effects": len(twin.effects),
                "provider_calls": len(provider.calls),
                "incidents": run.get_active_incidents(run.run_id)["incidents"],
                "events": run.journal.events[-40:],
            }
            return last_case

    @app.post("/debug/evaluate", include_in_schema=False)
    async def evaluate(request: Request, batch: ReadingsBatch):
        authorized(request, write=True)
        if not getattr(runtime.twin, "is_fixture", False):
            raise HTTPException(
                409, "Browser evaluation is fixture-only; live calls use authenticated MCP"
            )
        async with lock:
            runtime.twin.advance(batch)
            return (await runtime.evaluate_tick(batch)).model_dump()

    @app.post("/debug/ai-smoke", include_in_schema=False)
    async def ai_smoke(request: Request):
        nonlocal ai_calls, last_ai
        authorized(request, write=True)
        if settings.llm_mode == "fixture":
            raise HTTPException(409, "Select an AI provider locally before a live smoke test")
        async with lock:
            if ai_calls >= settings.ai_max_calls_per_run:
                raise HTTPException(
                    429, "Browser AI smoke budget exhausted for this server session"
                )
            ai_calls += 1
            # Explicitly synthetic planning proof, never a member detector or actuator test.
            from civis_brain.planning.smoke import synthetic_context

            context = synthetic_context()
            try:
                plan = validate_plan(context, await runtime.provider.generate(context))
                last_ai = {
                    "status": "validated",
                    "synthetic": True,
                    "effects": 0,
                    "plan": plan.model_dump(),
                }
            except BrainError as error:
                last_ai = {
                    "status": "blocked",
                    "code": error.code,
                    "reason": error.message,
                    "synthetic": True,
                    "effects": 0,
                }
            last_ai = runtime.journal.redact(last_ai)
            runtime.journal.append({"event": "debug_ai_smoke", **last_ai})
            return last_ai

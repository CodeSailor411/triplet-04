"""Isolated, inspectable debug runs through the actual shared Brain runtime."""

import copy
import json
from pathlib import Path
from time import perf_counter
from typing import Literal

from civis_mock_peers.demo import DemoSignalScenario
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin
from pydantic import BaseModel, ConfigDict, Field

from civis_brain.contracts import ReadingsBatch
from civis_brain.errors import BrainError
from civis_brain.integration.journal import Journal
from civis_brain.integration.runtime import BrainRuntime
from civis_brain.planning.gemini import GeminiPlanProvider
from civis_brain.scenarios.registry import SCENARIOS


class DebugRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["S03", "S04", "DEMO_R1"]
    variant: Literal["base", "refusal"] = "base"
    provider_mode: Literal["fixture", "gemini"] = "fixture"
    batches: list[ReadingsBatch] | None = Field(default=None, min_length=1, max_length=20)


def load_case(root: Path, scenario: str, variant: str) -> dict:
    if scenario == "DEMO_R1":
        case = json.loads(
            (root / "mocks/cases/integration/signal.json").read_text(encoding="utf-8")
        )
        if variant == "refusal":
            case["guardian"]["approve"] = False
            case["expected"].update(final_statuses=["blocked"], effects=0, actuate_calls=0)
        return case
    domain = {"S03": "power", "S04": "air_quality"}[scenario]
    return json.loads(
        (root / "mocks/cases" / domain / f"{variant}_case.json").read_text(encoding="utf-8")
    )


def templates(root: Path) -> list[dict]:
    result = []
    for scenario, label in [
        ("S03", "Power"),
        ("S04", "Air Quality"),
        ("DEMO_R1", "Shared action demo (synthetic detector)"),
    ]:
        for variant in ("base", "refusal"):
            case = load_case(root, scenario, variant)
            result.append(
                {
                    "label": f"{label}: {variant}",
                    "request": {
                        "scenario": scenario,
                        "variant": variant,
                        "provider_mode": "fixture",
                        "batches": case["batches"],
                    },
                }
            )
    return result


class TracePeer:
    is_fixture = True

    def __init__(self, name, peer, trace, journal):
        if not peer.is_fixture:
            raise ValueError("Debug runs must use fixture peers")
        self.name, self.peer, self.trace, self.journal = name, peer, trace, journal

    async def call_tool(self, name, arguments):
        entry = {
            "step": len(self.trace) + 1,
            "target": self.name,
            "operation": name,
            "request": self.journal.redact(copy.deepcopy(arguments)),
        }
        self.trace.append(entry)
        started = perf_counter()
        try:
            response = await self.peer.call_tool(name, arguments)
            entry["response"] = self.journal.redact(response)
            return response
        except BrainError as error:
            entry["error"] = {"code": error.code, "message": error.message}
            raise
        finally:
            entry["elapsed_ms"] = round((perf_counter() - started) * 1000, 1)


class TraceProvider:
    def __init__(self, provider, mode, trace, journal):
        self.provider, self.mode, self.trace, self.journal = provider, mode, trace, journal
        self.calls = 0

    async def generate(self, context):
        request = (
            self.provider.request(context)
            if hasattr(self.provider, "request")
            else context.model_dump(mode="json")
        )
        entry = {
            "step": len(self.trace) + 1,
            "target": self.mode,
            "operation": "interactions.create" if self.mode == "gemini" else "recorded_plan",
            "request": self.journal.redact(request),
        }
        self.trace.append(entry)
        self.calls += 1
        started = perf_counter()
        try:
            plan = await self.provider.generate(context)
            entry["response"] = self.journal.redact(plan.model_dump(mode="json"))
            return plan
        except BrainError as error:
            entry["error"] = {"code": error.code, "message": error.message}
            raise
        finally:
            # Only final output text/status; never model thoughts or hidden reasoning steps.
            entry["provider_response"] = self.journal.redact(
                getattr(self.provider, "last_response", {})
            )
            entry["elapsed_ms"] = round((perf_counter() - started) * 1000, 1)


async def run_debug_case(settings, request: DebugRunRequest, *, live_provider=None, ai_budget=3):
    root = Path(settings.brain_config_root).resolve()
    case = load_case(root, request.scenario, request.variant)
    batches = request.batches or [ReadingsBatch.model_validate(row) for row in case["batches"]]
    if len({batch.run_id for batch in batches}) != 1:
        raise BrainError("INPUT_INVALID", "A debug request must use one run_id")
    trace = []
    journal = Journal(secrets=[settings.gemini_api_key])
    twin, guardian = FixtureTwin(case), FixtureGuardian(case)
    owned = request.provider_mode == "gemini" and live_provider is None
    provider = (
        live_provider
        or GeminiPlanProvider(
            settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds
        )
        if request.provider_mode == "gemini"
        else FixturePlanProvider(case)
    )
    traced_provider = TraceProvider(provider, request.provider_mode, trace, journal)
    sid = case["scenario_id"]
    scenarios = (DemoSignalScenario(),) if request.scenario == "DEMO_R1" else SCENARIOS
    run = BrainRuntime(
        twin=TracePeer("mock_twin", twin, trace, journal),
        guardian=TracePeer("mock_guardian", guardian, trace, journal),
        provider=traced_provider,
        scenarios=scenarios,
        policies={sid: case["policy"]},
        features={
            "enabled_scenario_ids": [sid],
            "guardian_score_tool": "fixture_score",
            "guardian_token_tool": "fixture_approve",
            "peer_timeout_seconds": 5,
            "ai_timeout_seconds": settings.ai_timeout_seconds,
            "ai_max_calls_per_run": ai_budget,
        },
        artifact_dir=root / ".artifacts/debug" / f"{request.scenario}-{request.variant}",
    )
    run.journal.remember_secret(settings.gemini_api_key)
    results = []
    try:
        for batch in batches:
            twin.advance(batch)
            results.append((await run.evaluate_tick(batch)).model_dump(mode="json"))
        submitted = [batch.model_dump(mode="json") for batch in batches]
        actual = {
            "final_statuses": [row["status"] for row in results[-1]["decisions"]],
            "effects": len(twin.effects),
            "provider_calls": traced_provider.calls,
            "actuate_calls": sum(row["name"] == "actuate" for row in twin.calls),
        }
        checks = {
            key: actual.get(key) == expected
            for key, expected in case["expected"].items()
            if key != "reason_contains"
        }
        if case["expected"].get("reason_contains"):
            checks["reason_contains"] = any(
                case["expected"]["reason_contains"] in row["reason"]
                for row in results[-1]["decisions"]
            )
        unchanged = submitted == case["batches"]
        result = journal.redact(
            {
                "scenario": request.scenario,
                "variant": request.variant,
                "fixture_only": True,
                "provider_mode": request.provider_mode,
                "synthetic_detector": request.scenario == "DEMO_R1",
                "submitted_request": request.model_copy(update={"batches": batches}).model_dump(
                    mode="json"
                ),
                "readings": submitted,
                "batches": results,
                "requests": trace,
                "effects": len(twin.effects),
                "effect_details": twin.effects,
                "provider_calls": traced_provider.calls,
                "events": run.journal.events,
                "incidents": run.get_active_incidents(run.run_id)["incidents"],
                "mock_configuration": {
                    key: case[key] for key in ("nodes", "actions", "policy", "guardian", "caps")
                },
                "acceptance": {
                    "uses_original_readings": unchanged,
                    "expected": case["expected"],
                    "actual": actual,
                    "checks": checks,
                    "passed": all(checks.values()) if unchanged else None,
                },
            }
        )
        artifact = root / ".artifacts/debug/last-run.json"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        return result
    finally:
        if owned:
            await provider.aclose()

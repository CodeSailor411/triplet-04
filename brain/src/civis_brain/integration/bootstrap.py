import json
from pathlib import Path

from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.integration.mcp_peer import MappedGuardianPeer, MCPPeer
from civis_brain.integration.runtime import build_runtime
from civis_brain.planning.gemini import GeminiPlanProvider


def configured_runtime(settings):
    root = Path(settings.brain_config_root).resolve()
    domains = {
        "S01": "traffic",
        "S02": "water",
        "S03": "power",
        "S04": "air_quality",
        "S05": "emergency",
    }
    policies = {
        sid: json.loads((root / "config" / "scenarios" / f"{domain}.json").read_text())
        for sid, domain in domains.items()
    }
    case_path = root / settings.brain_fixture_case
    case = json.loads(case_path.read_text(encoding="utf-8"))
    features = {
        "ai_max_calls_per_run": settings.ai_max_calls_per_run,
        "ai_timeout_seconds": settings.ai_timeout_seconds,
        "peer_timeout_seconds": settings.peer_timeout_seconds,
    }
    if settings.peer_mode == "fixture":
        if not any(row["node_id"] == "POW-01" for row in case["nodes"]):
            case["nodes"].append(
                {
                    "node_id": "POW-01",
                    "domains": ["power"],
                    "role": "sensor",
                    "actuators": [],
                    "neighbours": [],
                }
            )
        twin, guardian = FixtureTwin(case), FixtureGuardian(case)
        features.update(
            guardian_score_tool="fixture_score",
            guardian_token_tool="fixture_approve",
            preview_tool="fixture_preview",
            commit_tool="fixture_commit",
        )
    else:
        twin = MCPPeer(
            settings.twin_mcp_url, settings.twin_brain_key, settings.peer_timeout_seconds
        )
        mapping = {}
        if settings.guardian_mapping_file:
            mapping = json.loads(
                (root / settings.guardian_mapping_file).read_text(encoding="utf-8")
            )
        guardian = MappedGuardianPeer(
            MCPPeer(
                settings.guardian_mcp_url,
                settings.guardian_brain_key,
                settings.peer_timeout_seconds,
            ),
            mapping,
            settings.guardian_score_tool,
            settings.guardian_token_tool,
        )
        features.update(
            guardian_score_tool=settings.guardian_score_tool,
            guardian_token_tool=settings.guardian_token_tool,
            guardian_contract_confirmed=settings.guardian_contract_confirmed,
            preview_tool=settings.twin_preview_tool,
            commit_tool=settings.twin_commit_tool,
        )
    provider = (
        GeminiPlanProvider(
            settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds
        )
        if settings.llm_mode == "gemini"
        else FixturePlanProvider(case)
    )
    artifacts = root / ".artifacts" / "service"
    artifacts.mkdir(parents=True, exist_ok=True)
    runtime = build_runtime(
        twin=twin,
        guardian=guardian,
        provider=provider,
        policies=policies,
        features=features,
        artifact_dir=artifacts,
    )
    for key in (
        settings.gemini_api_key,
        settings.twin_brain_key,
        settings.guardian_brain_key,
        settings.brain_twin_caller_key,
        settings.brain_guardian_caller_key,
        settings.brain_scenario_key,
    ):
        if key:
            runtime.journal.remember_secret(key)
    return runtime

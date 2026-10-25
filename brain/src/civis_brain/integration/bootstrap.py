import json
from pathlib import Path

from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.integration.guardian_http import APPROVAL_TOOL, SCORE_TOOL, GuardianHTTPPeer
from civis_brain.integration.guardian_v3 import APPROVAL_TOOL as V3_APPROVAL
from civis_brain.integration.guardian_v3 import SCORE_TOOL as V3_SCORE
from civis_brain.integration.guardian_v3 import GuardianV3Peer
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
        "S06": "traffic_accident",
        "S07": "water_low",
        "S08": "emergency_fire",
    }
    policies = {
        sid: json.loads((root / "config" / "scenarios" / f"{domain}.json").read_text())
        for sid, domain in domains.items()
    }
    if settings.scenario_policy_file:
        overrides = json.loads((root / settings.scenario_policy_file).read_text(encoding="utf-8"))
        if (not isinstance(overrides, dict) or not set(overrides).issubset(domains)
                or any(not isinstance(value, dict) for value in overrides.values())):
            raise ValueError("Scenario policy overrides must map known S01-S08 IDs to objects")
        for sid, values in overrides.items():
            policies[sid] = {**policies[sid], **values}
    case = None
    if settings.peer_mode == "live" and settings.llm_mode != "gemini":
        raise ValueError("Live peers require LLM_MODE=gemini; recorded fixture plans are offline only")
    if settings.peer_mode == "live" and not settings.gemini_api_key:
        raise ValueError("Live peers require GEMINI_API_KEY in the selected local environment")
    features = {
        "ai_max_calls_per_run": settings.ai_max_calls_per_run,
        "ai_timeout_seconds": settings.ai_timeout_seconds,
        "peer_timeout_seconds": settings.peer_timeout_seconds,
        "max_evidence_age_seconds": settings.max_evidence_age_seconds,
        "mock_integration_profile": settings.mock_integration_profile,
        "evidence_recovery_enabled": settings.peer_mode == "live",
        "one_response_per_episode": settings.peer_mode == "live",
        "run_log_dir": str(root / "run-logs"),
    }
    if settings.peer_mode == "fixture":
        case_path = root / settings.brain_fixture_case
        case = json.loads(case_path.read_text(encoding="utf-8"))
        policies[case["scenario_id"]] = case["policy"]
        features["enabled_scenario_ids"] = [case["scenario_id"]]
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
        if settings.guardian_transport == "mcp_v3":
            guardian = GuardianV3Peer(MCPPeer(settings.guardian_mcp_url, settings.guardian_brain_key,
                                            settings.peer_timeout_seconds))
            features.update(guardian_score_tool=V3_SCORE, guardian_token_tool=V3_APPROVAL,
                            guardian_exact_idempotency=True)
        if settings.guardian_transport == "http_v2":
            if not settings.guardian_http_policy_file:
                raise ValueError("HTTP Guardian needs its explicit published policy file")
            policy = json.loads((root / settings.guardian_http_policy_file).read_text(encoding="utf-8"))
            guardian = GuardianHTTPPeer(
                settings.guardian_http_url, settings.guardian_brain_key, policy,
                settings.peer_timeout_seconds, allow_provisional=settings.mock_integration_profile,
            )
            features.update(guardian_score_tool=SCORE_TOOL, guardian_token_tool=APPROVAL_TOOL)
    provider = configured_provider(settings, case)
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


def configured_provider(settings, case=None):
    if settings.llm_mode == "gemini":
        return GeminiPlanProvider(
            settings.gemini_api_key, settings.gemini_model, settings.ai_timeout_seconds
        )
    if case is None:
        raise ValueError("Fixture provider requires an explicit case")
    return FixturePlanProvider(case)

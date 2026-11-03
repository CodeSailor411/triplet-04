"""Read-only live connection check. Does not plan, authorize, inject faults or actuate."""

import argparse
import asyncio
import json
from pathlib import Path

from civis_brain.errors import BrainError
from civis_brain.integration.bootstrap import configured_runtime
from civis_brain.integration.mcp_peer import MCPPeer
from civis_brain.integration.water_policy import validate_water_choices
from civis_brain.settings import Settings


async def check(settings):
    checks = []

    def record(name, passed, detail):
        checks.append({"check": name, "passed": passed, "detail": detail})

    record("live_peers", settings.peer_mode == "live", "PEER_MODE must be live")
    record("live_planner", settings.llm_mode == "gemini" and bool(settings.gemini_api_key),
           "Gemini mode and a local key are required; this check does not call Google")
    record("continuous_feed", settings.twin_feed_enabled, "TWIN_FEED_ENABLED must be true")
    try:
        runtime = configured_runtime(settings)
    except (ValueError, OSError, KeyError):
        record("configuration", False, "Check selected environment, policy and mapping files")
        return {"ready": False, "checks": checks}
    try:
        record("mock_policy", settings.mock_integration_profile,
               "Enable explicit illustrative policy for partner mock runs only")
        twin = MCPPeer(settings.twin_mcp_url, settings.twin_brain_key,
                       settings.peer_timeout_seconds)
        try:
            required = {"get_capabilities", "get_clock", "list_nodes", "list_actions",
                        "get_readings", "get_containment_state", "actuate", "preview_action"}
            names = set(await twin.list_tool_names())
            missing = sorted(required - names)
            record("twin_tools", not missing, {"missing": missing})
            nodes = await twin.call_tool("list_nodes", {})
            actions = await twin.call_tool("list_actions", {})
            try:
                detail = validate_water_choices(runtime.policies["S02"], nodes, actions,
                                                mock_profile=settings.mock_integration_profile)
                record("water_topology", True, detail)
            except (BrainError, ValueError, KeyError, TypeError) as error:
                record("water_topology", False,
                       error.code if isinstance(error, BrainError) else "PEER_SCHEMA_INVALID")
            # Reading clock/data is also an authentication check, unlike public discovery.
            clock = await twin.call_tool("get_clock", {})
            batch = await twin.call_tool("get_readings", {})
            runtime._validate_clock(batch_model(batch), await twin.call_tool("get_clock", {}))
            record("twin_clock", True, {"run_id": clock["run_id"], "tick": clock["tick"]})
            record("traffic_metric", any(r.get("sensor") == "congestion_index"
                                        for r in batch["readings"]),
                   "S01 needs congestion_index; speed/count are not silently converted")
            if settings.twin_commit_tool:
                record("confirmation_tool", settings.twin_commit_tool in names,
                       "Configured confirmation must be advertised by Twin")
        except (BrainError, ValueError, KeyError, TypeError) as error:
            record("twin_connection", False,
                   error.code if isinstance(error, BrainError) else "PEER_SCHEMA_INVALID")
        if settings.guardian_transport == "http_v2":
            try:
                capabilities = await runtime.guardian.call_tool("get_capabilities", {})
                record("guardian_http", True,
                       "HTTP verdict transport; start Guardian's own Twin feed bridge separately")
                record("guardian_contract", settings.guardian_contract_confirmed,
                       "HTTP evidence mapping must be explicitly confirmed")
                record("guardian_authorization", capabilities.get("authorization_ready") is True,
                       capabilities.get("authorization_blocker"))
                record("guardian_policy", not capabilities.get("policy_provisional"),
                       "Current risk minima are provisional; confirm with partners")
            except BrainError as error:
                record("guardian_connection", False, error.code)
            return {"ready": all(row["passed"] for row in checks),
                    "scope": "HTTP evidence support does not certify signed-action interoperability",
                    "checks": checks}
        if settings.guardian_transport == "mcp_v3":
            try:
                names = set(await MCPPeer(settings.guardian_mcp_url, settings.guardian_brain_key,
                                          settings.peer_timeout_seconds).list_tool_names())
                required = {"describe_capabilities", "get_trust_verdict", "authorize_action"}
                record("guardian_v3_tools", required.issubset(names), {"missing": sorted(required - names)})
                capabilities = await runtime.guardian.call_tool("get_capabilities", {})
                record("guardian_policy", isinstance(capabilities.get("thresholds"), dict),
                       "Published v3 inclusive reading cutoff and risk minima")
                record("guardian_contract", settings.guardian_contract_confirmed,
                       "Explicit confirmation is required before live evidence use")
            except BrainError as error:
                record("guardian_connection", False, error.code)
            return {"ready": all(row["passed"] for row in checks),
                    "scope": "Connection prerequisites only; actual signed actions need joint acceptance",
                    "checks": checks}
        try:
            names = await MCPPeer(settings.guardian_mcp_url, settings.guardian_brain_key,
                                  settings.peer_timeout_seconds).list_tool_names()
            record("guardian_inventory", True, {"tools": names})
            record("guardian_contract", settings.guardian_contract_confirmed,
                   "Keep false until Guardian supplies actual score and exact-action token APIs")
            if settings.guardian_contract_confirmed:
                mapped = runtime.guardian
                required = [spec.get("tool", "") for spec in mapped.mapping.values()]
                complete = all(role in mapped.mapping for role in ("capabilities", "score", "approval"))
                record("guardian_mapping", complete and all(t in names for t in required),
                       "All three mapped tools must exist")
                capabilities = await mapped.call_tool("get_capabilities", {})
                record("guardian_policy",
                       capabilities.get("protocol_version") == "2026-07-28"
                       and isinstance(capabilities.get("thresholds"), dict)
                       and all(k in capabilities["thresholds"] for k in ("reading", "R1", "R2", "R3")),
                       "Guardian must publish reading/risk cutoffs and protocol")
        except (BrainError, ValueError, KeyError, TypeError) as error:
            record("guardian_connection", False,
                   error.code if isinstance(error, BrainError) else "PEER_SCHEMA_INVALID")
    finally:
        await runtime.close()
    return {"ready": all(row["passed"] for row in checks),
            "scope": "Connection prerequisites only; passing does not certify joint acceptance",
            "checks": checks}


def batch_model(raw):
    from civis_brain.contracts import ReadingsBatch
    return ReadingsBatch.model_validate(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env.partner")
    args = parser.parse_args()
    if not Path(args.env_file).is_file():
        parser.error("Selected partner environment does not exist")
    result = asyncio.run(check(Settings(_env_file=args.env_file)))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ready"] else 2)


if __name__ == "__main__":
    main()

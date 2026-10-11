"""Real localhost HTTP/MCP for the submitted scenarios; stand-in partner logic, no API."""

import pytest
from civis_mock_peers.http import peer_app, serve
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.app import create_app
from civis_brain.errors import BrainError
from civis_brain.integration.mcp_peer import MCPPeer
from civis_brain.integration.runtime import build_runtime
from civis_brain.settings import Settings

from .test_member_integration import case_for


class LocalFixtureTransport(MCPPeer):
    """HTTP transport to our test fixture, never used for configured real partners."""
    is_fixture = True


@pytest.mark.parametrize("domain", ["traffic", "water", "emergency"])
@pytest.mark.parametrize("variant", ["base", "refusal"])
async def test_submitted_workflow_over_three_actual_mcp_servers(domain, variant, tmp_path):
    case = case_for(domain, variant)
    twin, guardian, provider = FixtureTwin(case), FixtureGuardian(case), FixturePlanProvider(case)
    with serve(peer_app(twin, "twin-fixture-key")) as twin_url, serve(
        peer_app(guardian, "guardian-fixture-key")
    ) as guardian_url:
        twin_transport = LocalFixtureTransport(twin_url, "twin-fixture-key")
        twin_transport.advance = twin.advance  # Simulated clock control, not a network tool.
        runtime = build_runtime(
            twin=twin_transport, guardian=LocalFixtureTransport(guardian_url, "guardian-fixture-key"),
            provider=provider, policies={case["scenario_id"]: case["policy"]},
            features={"enabled_scenario_ids": [case["scenario_id"]],
                      "guardian_score_tool": "fixture_score", "guardian_token_tool": "fixture_approve",
                      "preview_tool": "fixture_preview"},
            artifact_dir=tmp_path)
        settings = Settings(_env_file=None)
        with serve(create_app(settings, runtime)) as brain_url:
            caller = MCPPeer(brain_url, settings.brain_scenario_key)
            assert (await caller.call_tool("get_capabilities", {}))["protocol_version"] == "2026-07-28"
            for raw in case["batches"]:
                twin.advance(raw)
                fetched = await twin_transport.call_tool("get_readings", {})
                result = await caller.call_tool("evaluate_tick", {"batch": fetched})
            expected = case["expected"]
            assert [d["status"] for d in result["decisions"]] == expected["final_statuses"]
            assert len(twin.effects) == expected["effects"]
            assert len(provider.calls) == expected["provider_calls"]
            decision = result["decisions"][0]
            assert decision["params"] == expected["params"]
            assert decision["source_reading_ids"] == expected["source_reading_ids"]
            assert (await caller.call_tool("explain_decision", {
                "decision_id": decision["decision_id"]
            }))["found"]
            with pytest.raises(BrainError) as error:
                await MCPPeer(brain_url, "wrong-key").call_tool("evaluate_tick", {"batch": fetched})
            assert error.value.code == "UNAUTHENTICATED"
            assert len(twin.effects) == expected["effects"]

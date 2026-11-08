"""Opt-in real_jam/SH-05 and Guardian callback check against reviewed sources.

Uses actual Twin readings, Guardian's own SSE reader and signed authorization.
The planner is recorded; this is not a live Gemini or teammate-attended run.
"""

import asyncio
import json
import os
import time

import httpx
from civis_mock_peers.http import serve

from civis_brain.app import create_app
from civis_brain.contracts import Plan
from civis_brain.integration import bootstrap
from civis_brain.integration.action_caps import discover_action_caps
from civis_brain.settings import Settings

from .test_partners import GKEY, KEY, OUT, ROOT, SKEY, TWIN, MCPPeer
from .test_v3_joint import API_KEY, BRAIN_KEY, actual_guardian
from .test_v3_shipped_acceptance import INBOUND, guardian_bridge, write_evidence


class SharedJamPlanner:
    async def generate(self, context):
        incident = next(item for item in context.incidents if "SH-05" in item.node_ids)
        action = next(item for item in context.actions if item.action == "set_signal_plan")
        choice = next(item for item in action.params if item["name"] == "plan")["choices"][0]
        return Plan.model_validate({"proposals": [{
            "action": action.action, "targets": ["SH-05"], "params": {"plan": choice},
            "risk": action.risk, "preview_required": action.preview_required,
            "source_reading_ids": incident.source_reading_ids,
            "reason": "Recorded SH-05 intent; real readings and Guardian approval required",
        }], "alerts": []})


async def test_real_jam_shared_carrier_and_guardian_callback(monkeypatch):
    from twin.app import create_app as twin_app
    from twin.settings import Secrets, load_config
    from twin.settings import Settings as TwinSettings

    directory = OUT / "current-sh05"
    directory.mkdir(parents=True, exist_ok=True)
    config = load_config(TWIN / "config/twin.yaml")
    config.clock.autorun, config.clock.speed = True, 1
    config.logging.enabled = False
    config.tokens.mode = "signed"
    config.tokens.guardian_public_key = os.environ["GUARDIAN_TOKEN_PUBLIC_KEY"]
    twin = twin_app(TwinSettings(config=config, secrets=Secrets(
        _env_file=None, city_brain=KEY, guardian=GKEY, scenario=SKEY)))
    monkeypatch.setattr(bootstrap, "configured_provider", lambda *_: SharedJamPlanner())
    policy_file = directory / "policy.json"
    policy_file.write_text(json.dumps({
        sid: {"enabled": sid == "S01"}
        for sid in ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08")
    }), encoding="utf-8")
    with serve(twin) as twin_url:
        settings = Settings(_env_file=None, brain_config_root=str(ROOT),
            peer_mode="live", llm_mode="gemini", gemini_api_key="recorded-test-only",
            brain_twin_caller_key=INBOUND["twin"], brain_guardian_caller_key=INBOUND["guardian"],
            brain_scenario_key=INBOUND["scenario"], twin_mcp_url=twin_url, twin_brain_key=KEY,
            twin_feed_enabled=False, mock_integration_profile=True,
            guardian_mcp_url="http://127.0.0.1:1/mcp", guardian_brain_key=BRAIN_KEY,
            guardian_transport="mcp_v3", guardian_contract_confirmed=True,
            scenario_policy_file=str(policy_file), max_evidence_age_seconds=60,
            peer_timeout_seconds=8, ai_max_calls_per_run=20)
        app = create_app(settings)
        with serve(app) as brain_url:
            monkeypatch.setenv("BRAIN_MCP_URL", brain_url)
            monkeypatch.setenv("BRAIN_GUARDIAN_CALLER_KEY", INBOUND["guardian"])
            monkeypatch.setenv("BRAIN_TIMEOUT_SECONDS", "3")
            with actual_guardian(twin_url, audit_dir=directory / "guardian-logs") as guardian_url:
                # Configure the dynamically allocated endpoint before the first evaluation.
                app.state.runtime.guardian.peer.url = guardian_url + "/mcp"
                with guardian_bridge(twin_url, guardian_url, directory):
                    peer = MCPPeer(twin_url, KEY, 10)
                    caller = MCPPeer(brain_url, INBOUND["scenario"], 20)
                    nodes = await peer.call_tool("list_nodes", {})
                    actions = await peer.call_tool("list_actions", {})
                    caps = discover_action_caps(nodes, actions, {})
                    shared = next(row for row in nodes["nodes"] if row["node_id"] == "SH-05")
                    assert set(shared["domains"]) == {"traffic", "air_quality"}
                    assert caps["air_quality"] is None
                    assert caps["traffic"] == twin.state.book.caps["traffic"]["action_cap"]
                    started = await MCPPeer(twin_url, SKEY).call_tool("run_scenario", {
                        "name": "real_jam", "params": {"node_id": "SH-05", "spread": 0}})
                    seen = -1
                    deadline = time.monotonic() + 65
                    while not twin.state.book.committed and time.monotonic() < deadline:
                        batch = await peer.call_tool("get_readings", {})
                        if batch["tick"] != seen:
                            seen = batch["tick"]
                            await caller.call_tool("evaluate_tick", {"batch": batch})
                        await asyncio.sleep(.15)
                    decisions = [item.model_dump() for item in app.state.runtime.decisions.values()]
                    write_evidence(directory, "real-jam-result", {
                        "scenario": started, "node": shared, "resolved_action_caps": caps,
                        "decisions": decisions,
                        "commits": [item.model_dump() for item in twin.state.book.committed.values()],
                        "planner": "recorded, not live Gemini", "manual_guardian_ingestion": False,
                    })
                    assert twin.state.book.committed, decisions
                    assert all(item.targets == ["SH-05"] for item in twin.state.book.committed.values())
                    device = "SH-05.congestion_index"
                    # No further evaluate_tick/poll runs until callback proof is captured.
                    async with httpx.AsyncClient(timeout=15) as http:
                        response = await http.post(guardian_url + "/quarantine_device/" + device,
                            headers={"Authorization": "Bearer " + API_KEY})
                    response.raise_for_status()
                    callbacks = [item for item in app.state.runtime.journal.events
                                 if item.get("event") == "containment_notice"
                                 and device in item.get("device_ids", [])
                                 and not item.get("event_id", "").startswith("poll-")]
                    write_evidence(directory, "callback-result", {
                        "guardian_reply": response.json(), "callback_events": callbacks,
                        "blocked_in_brain": device in app.state.runtime.blocked_devices,
                        "twin_state": await peer.call_tool("get_containment_state", {}),
                    })
                    assert response.json()["brain_notification"]["status"] == "notified"
                    assert callbacks and device in app.state.runtime.blocked_devices

"""Opt-in test against a local Twin source checkout. Synthetic readings, mock Guardian."""
import argparse
import asyncio
import base64
import copy
import json
import logging
import sys
from pathlib import Path

from civis_mock_peers.http import peer_app, serve
from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, decode_claims
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civis_brain.app import create_app
from civis_brain.integration.mcp_peer import MCPPeer
from civis_brain.integration.runtime import build_runtime
from civis_brain.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


async def probe(twin_url, twin_app, variant, output, signing_key=None):
    client = MCPPeer(twin_url, "brain-local-test-key")
    sent_commands = []
    original_call = client.call_tool

    async def capture_command(name, arguments):
        if name == "actuate":
            sent_commands.append(copy.deepcopy(arguments))
        return await original_call(name, arguments)
    client.call_tool = capture_command
    wire_batch = await client.call_tool("get_readings", {})
    nodes = (await client.call_tool("list_nodes", {}))["nodes"]
    actions = (await client.call_tool("list_actions", {}))["actions"]
    sid, domain, action_name = (
        ("S01", "traffic", "set_signal_plan") if variant == "traffic_metric_missing"
        else ("S02", "water", "set_valve_position") if variant == "water_preview_missing"
        else ("S05", "emergency", "dispatch")
    )
    case = json.loads((ROOT / f"mocks/cases/{domain}/base_case.json").read_text(encoding="utf-8"))
    action = next(a for a in actions if a["action"] == action_name)
    carrier = next(n["node_id"] for n in nodes if n["node_id"] in action["target_nodes"]
                   and len(n["domains"]) == 1)
    if sid == "S01":
        rows = [copy.deepcopy(r) for r in wire_batch["readings"]
                if r["sensor"] in {"vehicle_count", "avg_speed"} and r["node_id"] == carrier]
        assert rows and not any(r["sensor"] == "congestion_index" for r in wire_batch["readings"])
        params = {}
    elif sid == "S05":
        event = next(copy.deepcopy(r) for r in wire_batch["readings"]
                     if r["sensor"] == "emergency_calls" and r["channel"] == "medical"
                     and r["node_id"] != carrier)
        availability = next(copy.deepcopy(r) for r in wire_batch["readings"]
                            if r["sensor"] == "units_free" and r["channel"] == "ambulance"
                            and r["node_id"] == carrier)
        event["value"], availability["value"] = 2.0, 1.0
        rows = [event, availability]
        params = {"unit_type": "ambulance", "destination": event["node_id"], "units": 1}
    else:
        event = next(copy.deepcopy(r) for r in wire_batch["readings"]
                     if r["sensor"] == "water_level" and r["node_id"] == carrier)
        event["value"] = 180.0
        rows = [event]
        params = {"position": 30}
        case["policy"]["safe_valve_choices"] = [
            {"incident_node_id": event["node_id"], "targets": [carrier], "params": params}]
        case["policy"]["persistence_ticks"] = 1
    batch = {**wire_batch, "readings": rows, "count": len(rows)}
    # This is an explicit synthetic test policy, injected only into this temporary runtime.
    # The configured live service retains fixture_only=true and cannot use it automatically.
    case["policy"]["fixture_only"] = False
    case["batches"] = [batch]
    case["guardian"]["approve"] = variant != "medical_denied"
    proposal = case["ai_plan"]["proposals"][0]
    proposal.update(targets=[carrier], params=params, source_reading_ids=[r["reading_id"] for r in rows])
    guardian, provider = FixtureGuardian(case), FixturePlanProvider(case)
    if signing_key is not None:
        from twin.tokens import make_token
        original = guardian.call_tool

        async def signed_approval(name, arguments):
            result = await original(name, arguments)
            if name == "fixture_approve" and result.get("approved"):
                token = make_token(decode_claims(result["token"]), signing_key)
                if variant == "medical_bad_signature":
                    head, body, signature = token.split(".")
                    raw = bytearray(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
                    raw[0] ^= 1
                    signature = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
                    token = f"{head}.{body}.{signature}"
                result["token"] = token
            return result
        guardian.call_tool = signed_approval
    with serve(peer_app(guardian, "guardian-local-test-key")) as guardian_url:
        runtime = build_runtime(
            twin=client, guardian=MCPPeer(guardian_url, "guardian-local-test-key"),
            provider=provider, policies={sid: case["policy"]},
            features={"enabled_scenario_ids": [sid], "guardian_contract_confirmed": True,
                      "guardian_score_tool": "fixture_score", "guardian_token_tool": "fixture_approve"},
            artifact_dir=output / variant)
        settings = Settings(_env_file=None)
        before = len(twin_app.state.book.committed)
        with serve(create_app(settings, runtime)) as brain_url:
            caller = MCPPeer(brain_url, settings.brain_scenario_key)
            result = await caller.call_tool("evaluate_tick", {"batch": batch})
            repeated = await caller.call_tool("evaluate_tick", {"batch": batch})
            assert repeated == result, "A duplicate tick must return its saved result"
        decision = result["decisions"][0]
        expected = {
            "medical_approved": ("committed", None, 1),
            "medical_signed": ("committed", None, 1),
            "medical_bad_signature": ("rejected", "TOKEN_INVALID", 0),
            "traffic_metric_missing": ("alert", "EVIDENCE_WARNING", 0),
            "medical_denied": ("blocked", "GUARDIAN_DENIED", 0),
            "water_preview_missing": ("blocked", "PREVIEW_UNAVAILABLE", 0),
        }[variant]
        actual = decision["status"], decision["peer_code"], len(twin_app.state.book.committed) - before
        assert actual == expected, (variant, actual, expected, decision["reason"])
        assert decision["params"] == params
        if actual[0] == "committed":
            assert len(sent_commands) == 1
            command = sent_commands[0]
            repeated = await original_call("actuate", command)
            assert repeated["status"] == "committed" and repeated["replayed"] is True
            changed = copy.deepcopy(command)
            changed["params"]["destination"] = carrier
            conflict = await original_call("actuate", changed)
            assert conflict["status"] == "rejected" and conflict["code"] == "IDEMPOTENCY_CONFLICT"
            reused = await original_call("actuate", {**command, "idempotency_key": "test-token-reuse"})
            assert reused["status"] == "rejected" and reused["code"] == "TOKEN_REUSED"
            assert len(twin_app.state.book.committed) - before == 1
        # Confirm the real Twin's merge utility accepts the Brain part-file schema.
        from twin.logmerge import merge_parts
        parts = list((output / variant / "run-logs").glob("*.brain.jsonl"))
        assert parts
        merge_parts(parts, output / variant / "merged.jsonl")
        print(json.dumps({"case": variant, "status": actual[0], "code": actual[1],
                          "actual_twin_commits": actual[2], "brain_log_merge": "passed",
                          "duplicate_tick": "passed",
                          "replay_conflict_token_reuse": "passed" if actual[0] == "committed" else "not_applicable"}))


def main():
    logging.basicConfig(level=logging.CRITICAL)
    for name in ("twin", "mcp", "httpx", "httpx2"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--twin-root", type=Path, required=True)
    parser.add_argument("--extra-deps", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.twin_root.resolve() / "src"))
    if args.extra_deps:
        sys.path.insert(0, str(args.extra_deps.resolve()))
    from twin.app import create_app as twin_create_app
    from twin.settings import Secrets, load_config
    from twin.settings import Settings as TwinSettings
    config = load_config(args.twin_root.resolve() / "config/twin.yaml")
    config.clock.autorun = False
    config.logging.enabled = False
    secrets = Secrets(_env_file=None, city_brain="brain-local-test-key",
                      guardian="guardian-local-test-key", scenario="scenario-local-test-key")
    output = ROOT / ".artifacts/partner-compatibility"
    output.mkdir(parents=True, exist_ok=True)
    for variant in ("medical_approved", "medical_denied", "medical_signed",
                    "medical_bad_signature", "water_preview_missing", "traffic_metric_missing"):
        local_config = config.model_copy(deep=True)
        signing_key = None
        if variant in {"medical_signed", "medical_bad_signature"}:
            signing_key = Ed25519PrivateKey.generate()
            local_config.tokens.mode = "signed"
            local_config.tokens.guardian_public_key = base64.b64encode(
                signing_key.public_key().public_bytes_raw()).decode()
        app = twin_create_app(TwinSettings(config=local_config, secrets=secrets))
        with serve(app) as url:
            asyncio.run(probe(url, app, variant, output, signing_key))


if __name__ == "__main__":
    main()

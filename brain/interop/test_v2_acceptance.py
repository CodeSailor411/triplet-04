"""Required joint behaviours: defects remain ordinary failing assertions."""


from .test_partners import KEY, MCPPeer, save
from .test_v2_joint import native_authorization, post_batch, token_crosscheck


async def test_guardian_approval_must_be_accepted_by_twin(twin, guardian_url):
    receipt = await token_crosscheck(twin, guardian_url)
    assert receipt["status"] == "committed", receipt


async def test_guardian_must_not_reuse_a_verdict_for_another_run(twin, guardian_url):
    _, _, _, _, response = await native_authorization(twin, guardian_url, wrong_run=True)
    save("acceptance-guardian-run-binding", {"status": response.status_code,
        "decision": response.json().get("decision"), "token_returned": bool(response.json().get("token"))})
    assert response.status_code in {400, 403, 409}, "Guardian authorized evidence from a different run"


async def test_all_emergency_channels_at_one_tick_must_remain_distinct(twin, guardian_url):
    import httpx

    httpx.post(guardian_url + "/api/reset", timeout=10).raise_for_status()
    _, url = twin
    batch = await MCPPeer(url, KEY).call_tool("get_readings", {})
    emergency = [r for r in batch["readings"] if r["sensor"] == "emergency_calls"]
    result = await post_batch(guardian_url, {**batch, "count": len(emergency), "readings": emergency})
    rejected = [r["reading_id"] for r in result["results"]
                if r["evaluation"].get("rejection_reason") == "replay_or_out_of_order_sequence_number"]
    save("acceptance-emergency-channels", {"native_readings": len(emergency),
                                           "incorrect_replay_rejections": rejected})
    assert not rejected, "Different channels share device/tick and were rejected as replay"


async def test_guardian_audit_must_be_readable_by_shared_timeline(twin, guardian_url):
    import os
    from pathlib import Path

    from twin.runlog import read_part

    _, _, _, payload, _ = await native_authorization(twin, guardian_url)
    path = Path(os.environ["GUARDIAN_AUDIT_DIR"]) / (payload["run_id"] + ".guardian.jsonl")
    events, rejected = read_part(path)
    save("acceptance-shared-timeline", {"accepted_guardian_events": len(events),
        "discarded_guardian_events": rejected,
        "required_fields": ["event_id", "run_id", "tick", "layer", "event_type"]})
    assert events and not rejected, "Shared timeline reader discards Guardian audit records"


async def test_guardian_containment_must_reach_actual_twin(twin, guardian_url):
    import httpx

    _, client, row, _, _ = await native_authorization(twin, guardian_url)
    response = httpx.post(guardian_url + "/quarantine_device/" + row["device_id"], timeout=10)
    response.raise_for_status()
    state = await client.call_tool("get_containment_state", {})
    save("acceptance-real-containment", {"guardian_result": response.json(), "twin_state": state})
    assert any(d["device_id"] == row["device_id"] for d in state["devices"]), (
        "Guardian reported simulated quarantine but Twin containment did not change")

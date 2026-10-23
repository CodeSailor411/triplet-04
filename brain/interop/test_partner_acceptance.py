"""Required partner boundary assertions. Known failures stay visible until partners fix them."""

import base64
from datetime import datetime, timedelta

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .test_partners import KEY, MCPPeer, save


@pytest.mark.parametrize("variant", ["valid", "future_iat", "long_lifetime",
                                    "score_above_one", "nonfinite_score", "empty_token_id"])
async def test_twin_enforces_signed_claim_semantics(variant, twin):
    from twin.tokens import make_token

    app, url = twin
    private = Ed25519PrivateKey.generate()
    config = app.state.settings.config.tokens
    config.mode = "signed"
    config.guardian_public_key = base64.b64encode(private.public_key().public_bytes_raw()).decode()
    config.min_score = {"R1": .5}
    peer = MCPPeer(url, KEY)
    clock = await peer.call_tool("get_clock", {})
    action = next(a for a in (await peer.call_tool("list_actions", {}))["actions"]
                  if a["action"] == "set_signal_plan")
    plan = next(p for p in action["params"] if p["name"] == "plan")["choices"][0]
    now = datetime.fromisoformat(clock["time"].replace("Z", "+00:00"))
    claims = {"iss": "guardian", "aud": "twin", "jti": "local-acceptance-" + variant,
              "run_id": clock["run_id"], "iat": now.isoformat(),
              "exp": (now + timedelta(seconds=60)).isoformat(),
              "action": "set_signal_plan", "targets": [action["target_nodes"][0]],
              "params": {"plan": plan}, "score": .9, "score_scale": "0..1"}
    if variant == "future_iat":
        claims["iat"] = (now + timedelta(seconds=30)).isoformat()
    elif variant == "long_lifetime":
        claims["exp"] = (now + timedelta(seconds=120)).isoformat()
    elif variant == "score_above_one":
        claims["score"] = 2.0
    elif variant == "nonfinite_score":
        claims["score"] = float("nan")
    elif variant == "empty_token_id":
        claims["jti"] = ""
    response = await peer.call_tool("actuate", {"action": claims["action"],
        "targets": claims["targets"], "params": claims["params"],
        "token": make_token(claims, private), "idempotency_key": "local-acceptance-" + variant})
    save("acceptance-twin-" + variant, {"result": response,
        "expected": "committed" if variant == "valid" else "rejected",
        "signer": "local test signer, not real Guardian"})
    assert response["status"] == ("committed" if variant == "valid" else "rejected"), response


def reading():
    return {"sensor_id": "local-acceptance.water", "sensor_type": "water_level",
            "value": 40.0, "unit": "cm", "timestamp": 1791532800.0,
            "location": {"lat": 36.8, "lng": 10.1}, "sequence_number": 1,
            "reading_id": "local-acceptance-r1"}


def test_guardian_rejects_unauthenticated_mutation(guardian_url):
    response = httpx.post(guardian_url + "/quarantine_device/local-acceptance-device", timeout=10)
    save("acceptance-guardian-auth", {"status": response.status_code, "body": response.json()})
    assert response.status_code in {401, 403}


def test_guardian_rollback_withdraws_trust(guardian_url):
    with httpx.Client(base_url=guardian_url, timeout=15) as client:
        assert client.post("/api/reset").status_code == 200
        row = reading()
        assert client.post("/ingest", json=row).status_code == 200
        rollback = client.post("/rollback_reading", json={"sensor_id": row["sensor_id"], "reading_id": row["reading_id"]})
        verdict = client.get(f'/trust_verdict/{row["sensor_id"]}/{row["reading_id"]}')
        save("acceptance-guardian-rollback", {"rollback": rollback.json(), "verdict": verdict.json()})
        assert rollback.status_code == 200
        assert verdict.status_code != 200 or verdict.json().get("trust_score", 0) == 0


def test_guardian_caller_cannot_disable_signature_requirement(guardian_url):
    with httpx.Client(base_url=guardian_url, timeout=15) as client:
        assert client.post("/api/reset").status_code == 200
        row = {**reading(), "signature": "invalid", "require_signature": True}
        strict = client.post("/ingest", json=row)
        bypass = client.post("/ingest", json={**row, "require_signature": False})
        save("acceptance-guardian-signature", {"required_status": strict.status_code,
                                             "disabled_status": bypass.status_code})
        assert strict.status_code == 401
        assert bypass.status_code == 401

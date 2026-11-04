"""
Step 1 of real security: prove a reading actually came from the Twin and
wasn't altered in transit, BEFORE running any statistical detection.

This uses HMAC-SHA256. In a real deployment the shared secret would be
provisioned out-of-band (e.g. injected as an env var at boot, or per-sensor
keys from a key management service). For the hackathon, one shared secret
between Twin and Guardian is enough -- the point is that an attacker who
doesn't know the secret cannot forge a valid signature for fake data.
"""

import hmac
import hashlib
import os

# In real deployment: load from environment variable / secrets manager.
# Never hardcode in production -- this default is ONLY for local dev/demo.
SHARED_SECRET = os.environ.get("GUARDIAN_SHARED_SECRET", "dev-only-change-me").encode()


def _canonical_message(sensor_id: str, sensor_type: str, value: float,
                        timestamp: float, sequence_number: int) -> bytes:
    """
    Build a deterministic byte string to sign/verify.
    Field order and formatting MUST match exactly on both the signing side
    (Twin) and verifying side (Guardian), or every signature will fail.
    """
    msg = f"{sensor_id}|{sensor_type}|{value}|{timestamp}|{sequence_number}"
    return msg.encode()


def sign_reading(sensor_id: str, sensor_type: str, value: float,
                  timestamp: float, sequence_number: int,
                  secret: bytes = SHARED_SECRET) -> str:
    """Called on the Twin side when emitting a reading."""
    msg = _canonical_message(sensor_id, sensor_type, value, timestamp, sequence_number)
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def verify_signature(sensor_id: str, sensor_type: str, value: float,
                      timestamp: float, sequence_number: int,
                      signature: str, secret: bytes = SHARED_SECRET) -> bool:
    """Called on the Guardian side when a reading arrives."""
    expected = sign_reading(sensor_id, sensor_type, value, timestamp, sequence_number, secret)
    # hmac.compare_digest prevents timing-attack leakage -- always use it,
    # never a plain == comparison for secrets/signatures.
    return hmac.compare_digest(expected, signature)

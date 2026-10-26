"""Loads Guardian's public Ed25519 key from the three shapes the partners may hand us.

Our config used a raw base64 key. Guardian's own tools write a PEM file. So the Twin accepts all of these:
  1. base64 of the raw 32 key bytes            (what the config always took)
  2. the PEM text itself                       ("-----BEGIN PUBLIC KEY-----" ...)
  3. a path to a PEM file                      (what Guardian's generate_token_keys.py writes)
A public key is not a secret, so having it in the repo or in the config is fine. Private keys never belong here.
"""
import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def load_public_key(value: str | None) -> Ed25519PublicKey:
    """Return the key, or raise ValueError with a plain message saying what was wrong."""
    text = (value or "").strip()
    if not text:
        raise ValueError("no public key given")
    if text.startswith("-----BEGIN"):
        return _from_pem(text.encode())
    if len(text) < 1024 and os.path.isfile(text):           # a path (a base64 key is never an existing file)
        with open(text, "rb") as f:
            return _from_pem(f.read())
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception:
        raise ValueError("the key is not base64, not PEM text and not a path to a file that exists") from None
    if len(raw) != 32:
        raise ValueError(f"a raw 32-byte Ed25519 public key must be exactly 32 bytes, this one is {len(raw)}")
    return Ed25519PublicKey.from_public_bytes(raw)


def _from_pem(data: bytes) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(data)
    except Exception:
        raise ValueError("the PEM text is not a valid public key") from None
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("the PEM key is not an Ed25519 key")
    return key

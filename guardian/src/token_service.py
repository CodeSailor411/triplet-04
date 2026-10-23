"""Versioned Ed25519 action tokens bound to canonical action parameters."""
from __future__ import annotations

import base64
import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    if not value or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in value):
        raise ValueError("malformed_token")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class TokenError(ValueError):
    pass


class ReplayStore:
    def __init__(self):
        self._used: set[str] = set()

    def consume(self, token_id: str) -> bool:
        if token_id in self._used:
            return False
        self._used.add(token_id)
        return True


class ActionTokenService:
    def __init__(self, private_key: Ed25519PrivateKey | None = None,
                 public_key: Ed25519PublicKey | None = None, *, issuer: str = "guardian",
                 audience: str = "twin", clock=time.time, replay_store: ReplayStore | None = None,
                 lifetime_seconds: int = 60, kid: str | None = None):
        self.private_key = private_key
        self.public_key = public_key or (private_key.public_key() if private_key else None)
        if private_key is not None and not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("private key must be Ed25519")
        if public_key is not None and not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("public key must be Ed25519")
        if private_key is not None and public_key is not None:
            derived = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            configured = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            if derived != configured:
                raise ValueError("configured Ed25519 public key does not match the private key")
        self.issuer, self.audience, self.clock = issuer, audience, clock
        self.kid = kid or os.environ.get("GUARDIAN_TOKEN_KID", "guardian-ed25519-v1")
        if not self.kid or len(self.kid) > 128:
            raise ValueError("key id must be a non-empty string of at most 128 characters")
        self.replay_store = replay_store or ReplayStore()
        self.lifetime_seconds = lifetime_seconds
        if lifetime_seconds != 60:
            raise ValueError("action token lifetime is fixed at 60 simulated seconds")

    @classmethod
    def from_env(cls, *, clock=time.time, replay_store: ReplayStore | None = None):
        private_path = os.environ.get("GUARDIAN_TOKEN_PRIVATE_KEY")
        public_path = os.environ.get("GUARDIAN_TOKEN_PUBLIC_KEY")
        private = None
        public = None
        if private_path:
            private = serialization.load_pem_private_key(Path(private_path).read_bytes(), password=None)
            if not isinstance(private, Ed25519PrivateKey):
                raise ValueError("private key must be Ed25519")
        if public_path:
            public = serialization.load_pem_public_key(Path(public_path).read_bytes())
            if not isinstance(public, Ed25519PublicKey):
                raise ValueError("public key must be Ed25519")
        return cls(private, public, issuer=os.environ.get("GUARDIAN_TOKEN_ISSUER", "guardian"),
                   audience=os.environ.get("GUARDIAN_TOKEN_AUDIENCE", "twin"), clock=clock,
                   kid=os.environ.get("GUARDIAN_TOKEN_KID", "guardian-ed25519-v1"),
                   replay_store=replay_store)

    def issue(self, *, run_id: str, action: str, parameters: dict[str, Any], reading_id: str,
              trust_score: float, risk_level: str, targets: list[str] | None = None,
              idempotency_key: str = "", reading_ids: list[str] | None = None,
              preview_id: str | None = None) -> tuple[str, dict[str, Any]]:
        if self.private_key is None:
            raise TokenError("signing_key_unavailable")
        now = self.clock()
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            raise TokenError("invalid_clock_value")
        claims = {
            "v": 1, "kid": self.kid, "token_id": str(uuid.uuid4()),
            "run_id": run_id, "action": action,
            "targets": list(targets or []), "params": parameters,
            "idempotency_key": idempotency_key,
            "reading_ids": list(reading_ids or [reading_id]),
            "preview_id": preview_id,
            "iss": self.issuer, "aud": self.audience,
            "iat": now, "exp": now + 60,
            "trust_score": trust_score, "risk_level": risk_level,
        }
        payload = _b64(canonical_json(claims))
        signing_input = f"g1.{payload}".encode("ascii")
        return f"g1.{payload}.{_b64(self.private_key.sign(signing_input))}", claims

    def verify(self, token: str, *, action: str, parameters: dict[str, Any], consume: bool = True,
               targets: list[str] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if self.public_key is None:
            raise TokenError("verification_key_unavailable")
        try:
            parts = token.split(".")
            if len(parts) != 3 or parts[0] != "g1":
                raise TokenError("malformed_token")
            payload_bytes, signature = _unb64(parts[1]), _unb64(parts[2])
            if _b64(payload_bytes) != parts[1] or _b64(signature) != parts[2]:
                raise TokenError("noncanonical_base64")
            claims = json.loads(payload_bytes)
            if not isinstance(claims, dict):
                raise TokenError("malformed_claims")
            if canonical_json(claims) != payload_bytes:
                raise TokenError("noncanonical_token")
            expected_claims = {"v", "kid", "token_id", "iss", "aud", "run_id", "action", "targets",
                               "params", "idempotency_key", "reading_ids", "preview_id",
                               "iat", "exp", "trust_score", "risk_level"}
            if set(claims) != expected_claims or not isinstance(claims["params"], dict):
                raise TokenError("malformed_claims")
            self.public_key.verify(signature, f"g1.{parts[1]}".encode("ascii"))
        except TokenError:
            raise
        except (ValueError, TypeError, json.JSONDecodeError, InvalidSignature) as exc:
            raise TokenError("invalid_signature_or_malformed_token") from exc
        if (isinstance(claims.get("v"), bool) or claims.get("v") != 1
                or claims.get("kid") != self.kid
                or claims.get("iss") != self.issuer or claims.get("aud") != self.audience):
            raise TokenError("wrong_kid_issuer_or_audience")
        if (not all(isinstance(claims.get(k), str) and claims[k] for k in ("token_id", "run_id", "action", "risk_level"))
                or not isinstance(claims.get("targets"), list)
                or not isinstance(claims.get("reading_ids"), list)
                or not all(isinstance(v, str) and v for v in claims["reading_ids"])
                or not isinstance(claims.get("idempotency_key"), str)
                or isinstance(claims.get("trust_score"), bool)
                or not isinstance(claims.get("trust_score"), (int, float))
                or not math.isfinite(claims["trust_score"]) or not 0 <= claims["trust_score"] <= 1):
            raise TokenError("malformed_claims")
        if (isinstance(claims.get("iat"), bool) or not isinstance(claims.get("iat"), (int, float))
                or isinstance(claims.get("exp"), bool) or not isinstance(claims.get("exp"), (int, float))
                or not math.isfinite(claims["iat"]) or not math.isfinite(claims["exp"])
                or claims["exp"] - claims["iat"] != 60):
            raise TokenError("invalid_expiry")
        if self.clock() >= claims["exp"]:
            raise TokenError("expired_token")
        if claims.get("action") != action or canonical_json(claims.get("params")) != canonical_json(parameters):
            raise TokenError("action_or_parameters_mismatch")
        if ((targets is not None and canonical_json(claims.get("targets")) != canonical_json(targets))
                or (idempotency_key is not None and claims.get("idempotency_key") != idempotency_key)):
            raise TokenError("targets_or_idempotency_mismatch")
        if consume and not self.replay_store.consume(str(claims.get("token_id", ""))):
            raise TokenError("replayed_token")
        return claims


def generate_keypair(private_path: str | Path, public_path: str | Path) -> None:
    private = Ed25519PrivateKey.generate()
    private_target, public_target = Path(private_path), Path(public_path)
    if private_target.resolve() == public_target.resolve():
        raise ValueError("private and public key destinations must be different files")
    private_target.parent.mkdir(parents=True, exist_ok=True)
    public_target.parent.mkdir(parents=True, exist_ok=True)
    private_target.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        os.chmod(private_target, 0o600)
    except OSError:
        pass
    public_target.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))

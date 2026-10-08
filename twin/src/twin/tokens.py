"""Guardian's permission token: "this exact action, this score, valid until this time, usable once".

Format (our proposal for 9antra to confirm, not agreed yet; JWS compact, the same shape as a JWT):
    base64url(header) . base64url(payload) . base64url(signature)
The mode (signed or unsigned) comes from the Twin's config and never from the token, so a token cannot
argue its way into being "unsigned". In signed mode only EdDSA (Ed25519) is accepted.

This file only reads and checks a token. Whether it matches the request, is expired, or was used before
is decided in actions.py, because that needs the clock and the request.
"""
import base64
import json
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, ValidationError

from .settings import TokensCfg

MAX_TOKEN_CHARS = 4096


class TokenError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class TokenClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")        # unknown fields are ignored, as agreed with the partners
    iss: str
    aud: str
    jti: str
    run_id: str
    iat: str
    exp: str
    action: str
    targets: list[str]
    params: dict
    score: float
    score_scale: str | None = None

    def expires_at(self) -> datetime:
        return datetime.fromisoformat(self.exp)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(payload: dict, private_key: Ed25519PrivateKey | None = None) -> str:
    """FOR MOCKS AND TESTS (Guardian's real code signs its own tokens). No key = unsigned token."""
    header = {"alg": "EdDSA" if private_key else "none", "typ": "JWT"}
    if private_key:
        header["kid"] = "guardian-dev"
    head = _b64e(json.dumps(header, separators=(",", ":")).encode())
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(private_key.sign(f"{head}.{body}".encode())) if private_key else ""
    return f"{head}.{body}.{sig}"


def read_token(token: str, cfg: TokensCfg) -> TokenClaims:
    """Check shape and signature (per the configured mode) and return the claims. Raises TokenError."""
    if not token or not token.strip():
        raise TokenError("TOKEN_MISSING", "This action needs a token from Guardian. Send it in the `token` field.")
    if len(token) > MAX_TOKEN_CHARS:
        raise TokenError("TOKEN_INVALID", "Token is far too long.")
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise TokenError("TOKEN_INVALID", "Token must have three parts separated by dots: header.payload.signature")
    try:
        header = json.loads(_b64d(parts[0]))
        payload = json.loads(_b64d(parts[1]))
        signature = _b64d(parts[2]) if parts[2] else b""
    except Exception:
        raise TokenError("TOKEN_INVALID", "Token parts are not valid base64url JSON.") from None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise TokenError("TOKEN_INVALID", "Token header and payload must be JSON objects.")

    alg = header.get("alg")
    if cfg.mode == "signed":
        if alg != "EdDSA":
            raise TokenError("TOKEN_INVALID", "This Twin only accepts signed tokens (alg EdDSA).")
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(cfg.guardian_public_key))
        try:
            key.verify(signature, f"{parts[0]}.{parts[1]}".encode())
        except InvalidSignature:
            raise TokenError("TOKEN_INVALID", "Signature not accepted.") from None     # never say which part failed
    else:
        if alg != "none" or parts[2]:
            raise TokenError("TOKEN_INVALID", "This Twin is in unsigned mode: header alg must be 'none' and the "
                                              "signature part empty.")
    try:
        claims = TokenClaims.model_validate(payload)
        claims.expires_at()
        datetime.fromisoformat(claims.iat)
    except (ValidationError, ValueError) as e:
        missing = sorted({str(err["loc"][0]) for err in e.errors()}) if isinstance(e, ValidationError) else ["exp/iat"]
        raise TokenError("TOKEN_INVALID", f"Token payload is missing or has wrong fields: {', '.join(missing)}.") from None
    if claims.iss != "guardian" or claims.aud != "twin":
        raise TokenError("TOKEN_INVALID", "Token must have iss 'guardian' and aud 'twin'.")
    return claims

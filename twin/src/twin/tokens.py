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
import math
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, ValidationError

from .keys import load_public_key
from .settings import TokensCfg

MAX_TOKEN_CHARS = 4096
MAX_LIFETIME_SECONDS = 60       # a token lives at most 60 simulated seconds (CIVIS asked for this check, 19 Oct)


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
    idempotency_key: str | None = None               # g1 tokens carry it; if set, it must match the request's key

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


def _sane(claims: TokenClaims) -> None:
    """Checks that hold for every token format. A token that fails these is broken or hostile, not just unlucky."""
    if not claims.jti.strip():
        raise TokenError("TOKEN_INVALID", "Token has an empty id (jti).")
    if isinstance(claims.score, bool) or not math.isfinite(claims.score) or not 0 <= claims.score <= 1:
        raise TokenError("TOKEN_INVALID", "Token score must be a number from 0 to 1.")
    life = (datetime.fromisoformat(claims.exp) - datetime.fromisoformat(claims.iat)).total_seconds()
    if not 0 < life <= MAX_LIFETIME_SECONDS:
        raise TokenError("TOKEN_INVALID", f"Token lifetime must be more than 0 and at most {MAX_LIFETIME_SECONDS} seconds.")


def _epoch_to_iso(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("not a finite number")
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_g1(token: str, parts: list[str], cfg: TokensCfg) -> TokenClaims:
    """Guardian's own format (9antra, docs/TOKEN.md): g1.<payload>.<signature>, always signed with Ed25519.

    Differences from our first proposal: the first part is the fixed word "g1" (not a JSON header), the claims are
    called token_id and trust_score, times are numbers (seconds since 1970, from the Twin's simulated clock), and
    the token also carries the idempotency_key it was issued for. The signature covers "g1.<payload>".
    """
    if cfg.mode != "signed":
        raise TokenError("TOKEN_INVALID", "g1 tokens are always signed, but this Twin is in unsigned mode.")
    try:
        payload_bytes, signature = _b64d(parts[1]), _b64d(parts[2])
        payload = json.loads(payload_bytes)
    except Exception:
        raise TokenError("TOKEN_INVALID", "Token parts are not valid base64url JSON.") from None
    try:
        load_public_key(cfg.guardian_public_key).verify(signature, f"g1.{parts[1]}".encode())
    except InvalidSignature:
        raise TokenError("TOKEN_INVALID", "Signature not accepted.") from None
    if not isinstance(payload, dict) or payload.get("v") != 1 or isinstance(payload.get("v"), bool):
        raise TokenError("TOKEN_INVALID", "Unsupported g1 token version.")
    if isinstance(payload.get("trust_score"), bool):         # JSON true would otherwise be read as the score 1.0
        raise TokenError("TOKEN_INVALID", "Token score must be a number from 0 to 1.")
    try:
        claims = TokenClaims.model_validate({
            "iss": payload.get("iss"), "aud": payload.get("aud"), "jti": payload.get("token_id"),
            "run_id": payload.get("run_id"), "iat": _epoch_to_iso(payload.get("iat")),
            "exp": _epoch_to_iso(payload.get("exp")), "action": payload.get("action"),
            "targets": payload.get("targets"), "params": payload.get("params"),
            "score": payload.get("trust_score"), "score_scale": "0-1",
            "idempotency_key": payload.get("idempotency_key")})
    except (ValidationError, ValueError):
        raise TokenError("TOKEN_INVALID", "g1 token payload is missing or has wrong fields.") from None
    return claims


def read_token(token: str, cfg: TokensCfg) -> TokenClaims:
    """Check shape and signature (per the configured mode) and return the claims. Raises TokenError."""
    if not token or not token.strip():
        raise TokenError("TOKEN_MISSING", "This action needs a token from Guardian. Send it in the `token` field.")
    if len(token) > MAX_TOKEN_CHARS:
        raise TokenError("TOKEN_INVALID", "Token is far too long.")
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise TokenError("TOKEN_INVALID", "Token must have three parts separated by dots: header.payload.signature")
    if parts[0] == "g1":                      # Guardian's own format (see _read_g1)
        claims = _read_g1(token, parts, cfg)
        if claims.iss != "guardian" or claims.aud != "twin":
            raise TokenError("TOKEN_INVALID", "Token must have iss 'guardian' and aud 'twin'.")
        _sane(claims)
        return claims
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
        key = load_public_key(cfg.guardian_public_key)
        try:
            key.verify(signature, f"{parts[0]}.{parts[1]}".encode())
        except InvalidSignature:
            raise TokenError("TOKEN_INVALID", "Signature not accepted.") from None     # never say which part failed
    else:
        if alg != "none" or parts[2]:
            raise TokenError("TOKEN_INVALID", "This Twin is in unsigned mode: header alg must be 'none' and the "
                                              "signature part empty.")
    if isinstance(payload.get("score"), bool):               # JSON true would otherwise be read as the score 1.0
        raise TokenError("TOKEN_INVALID", "Token score must be a number from 0 to 1.")
    try:
        claims = TokenClaims.model_validate(payload)
        claims.expires_at()
        datetime.fromisoformat(claims.iat)
    except (ValidationError, ValueError) as e:
        missing = sorted({str(err["loc"][0]) for err in e.errors()}) if isinstance(e, ValidationError) else ["exp/iat"]
        raise TokenError("TOKEN_INVALID", f"Token payload is missing or has wrong fields: {', '.join(missing)}.") from None
    if claims.iss != "guardian" or claims.aud != "twin":
        raise TokenError("TOKEN_INVALID", "Token must have iss 'guardian' and aud 'twin'.")
    _sane(claims)
    return claims

import base64, json, sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
token, public_pem, kid, twin_now = sys.argv[1:5]
expected_action, expected_target, expected_key = sys.argv[5:8]
_, payload, signature = token.split(".")
decode = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
raw = decode(payload)
claims = json.loads(raw)
assert json.dumps(claims, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() == raw
key = serialization.load_pem_public_key(public_pem.encode())
assert isinstance(key, Ed25519PublicKey) and claims["kid"] == kid
key.verify(decode(signature), f"g1.{payload}".encode("ascii"))
assert claims["action"] == expected_action and expected_target in claims["targets"]
assert claims["idempotency_key"] == expected_key and twin_now < claims["exp"]
assert claims["exp"] - claims["iat"] == 60
print("verified")

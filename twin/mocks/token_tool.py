"""Make test tokens, the way Guardian would (for mocks and tests only; the real Guardian signs its own).

    python mocks/token_tool.py keygen
    python mocks/token_tool.py make --run-id run-42-001 --action set_valve_position --targets WAT-01 \
        --params '{"position": 40}' [--private-key <base64>] [--score 0.9] [--ttl 30] [--now 2026-10-05T08:00:00.000Z]

Without --private-key the token is UNSIGNED (works only while tokens.mode is "unsigned" in config/twin.yaml).
--now is the simulated time to issue the token at (ask get_clock). Default: the clock's start time.
"""
import argparse
import base64
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey          # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat  # noqa: E402

from twin.settings import load_config                                                    # noqa: E402
from twin.tokens import make_token                                                       # noqa: E402
from twin.util import format_rfc3339                                                     # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="new Ed25519 key pair (base64 raw bytes)")
    m = sub.add_parser("make", help="make a token")
    m.add_argument("--run-id", required=True)
    m.add_argument("--action", required=True)
    m.add_argument("--targets", required=True, help="comma separated node ids")
    m.add_argument("--params", default="{}", help="JSON")
    m.add_argument("--score", type=float, default=0.9)
    m.add_argument("--ttl", type=float, default=30, help="lifetime in simulated seconds")
    m.add_argument("--now", default=None)
    m.add_argument("--private-key", default=None, help="base64 raw private key from keygen; omit for an unsigned token")
    a = ap.parse_args()

    if a.cmd == "keygen":
        key = Ed25519PrivateKey.generate()
        print("private (keep secret, never commit):", base64.b64encode(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode())
        print("public  (goes in tokens.guardian_public_key):", base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode())
        return
    now = datetime.fromisoformat(a.now or load_config().clock.start)
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(a.private_key)) if a.private_key else None
    print(make_token({
        "iss": "guardian", "aud": "twin", "jti": f"tk-{uuid.uuid4().hex[:8]}", "run_id": a.run_id,
        "iat": format_rfc3339(now), "exp": format_rfc3339(now + timedelta(seconds=a.ttl)),
        "action": a.action, "targets": sorted(a.targets.split(",")), "params": json.loads(a.params),
        "score": a.score, "score_scale": "0-1"}, key))


if __name__ == "__main__":
    main()

"""Generate a one-time Ed25519 keypair for local/deployment provisioning."""
from __future__ import annotations

import argparse
from token_service import generate_keypair

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--private", required=True, help="Private PEM destination; keep outside version control")
parser.add_argument("--public", required=True, help="Public PEM destination to distribute to Twin")
args = parser.parse_args()
generate_keypair(args.private, args.public)
print(f"Created Ed25519 keypair. Distribute only the public key: {args.public}")

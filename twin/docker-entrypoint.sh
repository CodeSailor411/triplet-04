#!/bin/sh
# Build the container-only config so the service is reachable on the Compose
# network and can verify Guardian's signed g1 action tokens. The checked-in
# config remains the source of every other Twin setting.
set -e

python - <<'PY'
import os
from pathlib import Path

import yaml

config = yaml.safe_load(Path("config/twin.yaml").read_text(encoding="utf-8"))
config.setdefault("server", {})["host"] = "0.0.0.0"

mode = os.environ.get("TWIN_TOKEN_MODE")
if mode:
    if mode not in {"signed", "unsigned"}:
        raise SystemExit("TWIN_TOKEN_MODE must be signed or unsigned")
    tokens = config.setdefault("tokens", {})
    tokens["mode"] = mode
    if mode == "signed":
        public_key = os.environ.get("TWIN_GUARDIAN_PUBLIC_KEY", "").strip()
        if not public_key:
            raise SystemExit("TWIN_GUARDIAN_PUBLIC_KEY is required when TWIN_TOKEN_MODE=signed")
        tokens["guardian_public_key"] = public_key
    else:
        tokens["guardian_public_key"] = None

target = Path("/tmp/twin-compose.yaml")
target.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
PY

export TWIN_CONFIG=/tmp/twin-compose.yaml
exec "$@"

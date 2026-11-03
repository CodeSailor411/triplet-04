"""Create a private live environment and separate per-layer credentials outside Git."""

import argparse
import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("BRAIN_TWIN_CALLER_KEY", "BRAIN_GUARDIAN_CALLER_KEY", "BRAIN_SCENARIO_KEY",
        "TWIN_BRAIN_KEY", "GUARDIAN_BRAIN_KEY")


def prepare(source: Path, output: Path):
    output = output.resolve()
    if output.is_relative_to(ROOT.parent.resolve()):
        raise ValueError("Private handover must be outside the Git checkout")
    config = dotenv_values(source)
    if not config.get("GEMINI_API_KEY"):
        raise ValueError("Source environment has no Gemini key")
    output.mkdir(parents=True, exist_ok=True)
    target = output / ".env.partner"
    existing = dotenv_values(target) if target.exists() else {}
    if not target.exists():
        target.write_text((ROOT / "config/partner.env.example").read_text(), encoding="utf-8")
    for name in ("BRAIN_HOST", "BRAIN_PORT", "TWIN_MCP_URL", "TWIN_EVENTS_URL",
                 "GUARDIAN_MCP_URL", "GEMINI_MODEL", "PEER_TIMEOUT_SECONDS",
                 "MAX_EVIDENCE_AGE_SECONDS", "AI_TIMEOUT_SECONDS", "AI_MAX_CALLS_PER_RUN"):
        if not existing.get(name) and config.get(name):
            set_key(str(target), name, config[name])
    current = dotenv_values(target)
    # Migrate previously generated v2 bundles as well as creating usable v3 ones.
    for name, value in {
        "GUARDIAN_TRANSPORT": "mcp_v3",
        "GUARDIAN_CONTRACT_CONFIRMED": "true",
        "GUARDIAN_SCORE_TOOL": "get_trust_verdict",
        "GUARDIAN_TOKEN_TOOL": "authorize_action",
        "GUARDIAN_VERDICT_WAIT_SECONDS": "1.5",
    }.items():
        set_key(str(target), name, value)
    if current.get("GUARDIAN_MCP_URL") in (None, "", "http://127.0.0.1:8002/mcp"):
        set_key(str(target), "GUARDIAN_MCP_URL", "http://127.0.0.1:5000/mcp")
    if not existing.get("SCENARIO_POLICY_FILE"):
        set_key(str(target), "SCENARIO_POLICY_FILE",
                config.get("SCENARIO_POLICY_FILE") or "config/integration/twin-mock-3.json")
    for name in KEYS:
        # Re-running preserves handed-over credentials. Development defaults are replaced.
        value = existing.get(name) or config.get(name)
        if not value or value.startswith("dev-"):
            value = secrets.token_urlsafe(32)
        set_key(str(target), name, value)
    set_key(str(target), "GEMINI_API_KEY", config["GEMINI_API_KEY"])
    values = dotenv_values(target)
    role_files = {
        "dali.env": {"BRAIN_MCP_URL": "http://127.0.0.1:8001/mcp",
                     "BRAIN_TWIN_CALLER_KEY": values["BRAIN_TWIN_CALLER_KEY"],
                     "TWIN_KEY_CITY_BRAIN": values["TWIN_BRAIN_KEY"]},
        "houssem.env": {"BRAIN_MCP_URL": "http://127.0.0.1:8001/mcp",
                        "BRAIN_GUARDIAN_CALLER_KEY": values["BRAIN_GUARDIAN_CALLER_KEY"],
                        "GUARDIAN_BRAIN_BEARER_KEY": values["BRAIN_GUARDIAN_CALLER_KEY"],
                        "GUARDIAN_BRAIN_MCP_BEARER_KEY": values["GUARDIAN_BRAIN_KEY"]},
    }
    for filename, fields in role_files.items():
        destination = output / filename
        destination.touch(exist_ok=True)
        if filename == "houssem.env" and "GUARDIAN_BRAIN_KEY" in dotenv_values(destination):
            unset_key(str(destination), "GUARDIAN_BRAIN_KEY")
        for name, value in fields.items():
            set_key(str(destination), name, value)
    (output / "README.txt").write_text(
        "PRIVATE CIVIS development configuration, codex/civis-elyes. Never publish.\n\n"
        "Brain operator: copy .env.partner to brain/.env.partner. It includes the Gemini key.\n"
        "Windows: scripts/start_partner.ps1. Linux: from brain, set CIVIS_ENV_FILE to\n"
        "the absolute .env.partner path and run .venv/bin/python -m civis_brain.\n"
        "Dali: use dali.env. TWIN_KEY_CITY_BRAIN must be installed on Twin or replaced\n"
        "with Dali's issued value in BOTH Twin and Brain's TWIN_BRAIN_KEY.\n"
        "BRAIN_TWIN_CALLER_KEY is the Bearer key for Twin calls to Brain.\n"
        "Houssem: use houssem.env. BRAIN_GUARDIAN_CALLER_KEY authorizes callbacks to Brain.\n"
        "Its Guardian-side name is GUARDIAN_BRAIN_BEARER_KEY. This sets a credential,\n"
        "not a callback implementation or an HTTP verdict endpoint on Brain.\n"
        "GUARDIAN_BRAIN_MCP_BEARER_KEY on Guardian must equal GUARDIAN_BRAIN_KEY on Brain.\n"
        "Guardian and Brain each consume Twin's real feed independently. Neither\n"
        "role file configures that bridge automatically. Guardian must give Twin\n"
        "its public verification key; compare its fingerprint on both machines.\n"
        "Never distribute Guardian's private signing key to Brain.\n\n"
        "Each peer receives only its role file unless it will host Brain itself.\n"
        "Localhost URLs assume all services run on one machine. For separate computers,\n"
        "replace URLs with the actual service addresses and bind Brain to the agreed\n"
        "network address. The selected v3 contract uses describe_capabilities,\n"
        "get_trust_verdict and authorize_action. A missing verdict is retried briefly\n"
        "then blocks; Brain never creates a score. The included Water policy permits\n"
        "only a virtual WAT-01 valve command for Twin mock3 seed42. It does not\n"
        "establish hydraulic safety or enable low-water supply actions.\n"
        "These files coordinate credentials, not proof of joint acceptance.\n",
        encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print("Private handover prepared at:", prepare(args.source, args.output).parent)

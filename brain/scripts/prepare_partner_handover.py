"""Create a private live environment and separate per-layer credentials outside Git."""

import argparse
import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key

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
                        "GUARDIAN_BRAIN_KEY": values["GUARDIAN_BRAIN_KEY"]},
    }
    for filename, fields in role_files.items():
        destination = output / filename
        destination.touch(exist_ok=True)
        for name, value in fields.items():
            set_key(str(destination), name, value)
    (output / "README.txt").write_text(
        "PRIVATE CIVIS brain-mock-2 configuration. Never attach these files to GitHub.\n\n"
        "Brain operator: copy .env.partner to brain/.env.partner. It includes the Gemini key.\n"
        "Start with scripts/start_partner.ps1. Keep ordinary .env for offline debugging.\n"
        "Dali: use dali.env. TWIN_KEY_CITY_BRAIN must be installed on Twin or replaced\n"
        "with Dali's issued value in BOTH Twin and Brain's TWIN_BRAIN_KEY.\n"
        "BRAIN_TWIN_CALLER_KEY is the Bearer key for Twin calls to Brain.\n"
        "Houssem: use houssem.env. BRAIN_GUARDIAN_CALLER_KEY authorizes callbacks to Brain.\n"
        "GUARDIAN_BRAIN_KEY is the proposed inbound Brain key for Guardian; Houssem must\n"
        "install it or supply his issued value for Brain to use. This file does not\n"
        "configure the current Guardian server automatically or create missing APIs.\n\n"
        "Each peer receives only its role file unless it will host Brain itself.\n"
        "Localhost URLs assume all services run on one machine. For separate computers,\n"
        "replace URLs with the actual service addresses and bind Brain to the agreed\n"
        "network address. Keep GUARDIAN_CONTRACT_CONFIRMED=false until the real mapping\n"
        "is agreed. Supply reviewed Water choices via SCENARIO_POLICY_FILE.\n"
        "These files coordinate credentials, not proof of joint acceptance.\n",
        encoding="utf-8")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / ".env")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print("Private handover prepared at:", prepare(args.source, args.output).parent)

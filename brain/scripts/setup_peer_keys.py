"""Create local Brain caller credentials without printing or replacing custom keys."""
import re
import secrets
from pathlib import Path

CALLER_KEYS = {
    "BRAIN_TWIN_CALLER_KEY": "dev-twin-to-brain",
    "BRAIN_GUARDIAN_CALLER_KEY": "dev-guardian-to-brain",
    "BRAIN_SCENARIO_KEY": "dev-scenario-to-brain",
}


def initialize_caller_keys(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    changed = []
    for name in CALLER_KEYS:
        pattern = re.compile(r"^" + name + r"=(.*)$", re.MULTILINE)
        matches = list(pattern.finditer(text))
        if len(matches) > 1:
            raise ValueError("Duplicate caller key setting: " + name)
        value = matches[0].group(1).strip().strip("\\\"'") if matches else ""
        if value and value != CALLER_KEYS[name]:
            continue
        line = name + "=" + secrets.token_urlsafe(32)
        if matches:
            text = pattern.sub(lambda _: line, text)
        else:
            text = text.rstrip() + "\n" + line + "\n"
        changed.append(name)
    if changed:
        path.write_text(text.lstrip("\n"), encoding="utf-8", newline="\n")
    return changed


if __name__ == "__main__":
    env_path = Path(__file__).resolve().parents[1] / ".env"
    changed = initialize_caller_keys(env_path)
    print("Generated caller keys: " + (", ".join(changed) if changed else "none; custom keys preserved"))
    print("Stored only in brain/.env. Partner-issued outbound credentials still need configuration.")

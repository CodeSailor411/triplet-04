"""Check every installed lockfile package, without displaying keys or making API calls."""

import sys
from importlib.metadata import version
from pathlib import Path

from packaging.requirements import Requirement

from civis_brain.settings import Settings

if sys.version_info[:2] != (3, 12):
    raise SystemExit("Use the brain/.venv Python 3.12 interpreter")
root = Path(__file__).resolve().parents[1]
count = 0
for line in (root / "requirements-lock.txt").read_text(encoding="utf-8").splitlines():
    line = line.split("#", 1)[0].strip()
    if not line:
        continue
    requirement = Requirement(line)
    if requirement.marker and not requirement.marker.evaluate():
        continue
    actual = version(requirement.name)
    if not requirement.specifier.contains(actual):
        raise SystemExit(f"{requirement.name}: {actual} disagrees with the lock; rerun setup.ps1")
    count += 1
print(f"OK: all {count} applicable locked packages match")
print(f"OK Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
for name in ("fastapi", "uvicorn", "pydantic", "pydantic-settings", "mcp", "httpx", "httpx2"):
    print(f"OK {name} {version(name)}")
settings = Settings()
present = bool(settings.gemini_api_key) if settings.llm_mode == "gemini" else False
print(f"AI mode: {settings.llm_mode}; key present: {present}")
print("MCP protocol: 2026-07-28. Exact library pins are repo/Twin compatibility choices.")

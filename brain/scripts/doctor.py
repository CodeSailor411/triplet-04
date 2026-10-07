"""Check the common environment without exposing keys or calling external services."""

import sys
from importlib.metadata import version

from civis_brain.settings import Settings

if sys.version_info[:2] != (3, 12):
    raise SystemExit("Use the brain/.venv Python 3.12 interpreter")
expected = {
    "fastapi": "0.142.2", "uvicorn": "0.54.0", "pydantic": "2.13.5",
    "pydantic-settings": "2.15.0", "mcp": "2.3.0", "google-genai": "2.28.0",
    "pytest": "9.1.1", "pytest-asyncio": "1.4.0", "ruff": "0.16.10",
}
for name, pin in expected.items():
    actual = version(name)
    if actual != pin:
        raise SystemExit(f"{name}: expected {pin}, found {actual}; rerun setup.ps1")
    print(f"OK {name} {actual}")
settings = Settings()
print(f"OK Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
print(f"AI mode: {settings.llm_mode}; AI key present: {bool(settings.gemini_api_key)}")
print("Environment ready. Business modules remain assigned and NOT_IMPLEMENTED.")

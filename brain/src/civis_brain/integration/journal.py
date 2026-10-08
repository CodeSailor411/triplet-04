import json
import re
from pathlib import Path

SENSITIVE_FIELDS = {
    "token",
    "api_key",
    "authorization",
    "private_key",
    "gemini_api_key",
    "openrouter_api_key",
}


class Journal:
    def __init__(self, path: Path | None = None, secrets: list[str] | None = None):
        self.path = path
        self.secrets = set(filter(None, secrets or []))
        self.events: list[dict] = []

    def remember_secret(self, value: str) -> None:
        if value:
            self.secrets.add(value)

    def redact(self, value):
        if isinstance(value, dict):
            return {
                key: "<redacted>" if key.lower() in SENSITIVE_FIELDS else self.redact(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            for secret in sorted(self.secrets, key=len, reverse=True):
                value = value.replace(secret, "<redacted>")
            value = re.sub(r"Bearer\s+\S+", "Bearer <redacted>", value, flags=re.I)
            value = re.sub(
                r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*", "<redacted>", value
            )
            value = re.sub(r"sk-or-v1-[A-Za-z0-9_-]+", "<redacted>", value)
            return value[:4000]
        return value

    def append(self, event: dict) -> None:
        safe = self.redact(event)
        self.events.append(safe)
        self.events = self.events[-1000:]
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(safe, allow_nan=False, ensure_ascii=False) + "\n")

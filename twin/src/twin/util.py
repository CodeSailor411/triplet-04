"""Small shared helpers."""
from datetime import datetime, timezone


def format_rfc3339(dt: datetime) -> str:
    """CIVIS convention: UTC, milliseconds, a literal Z. Example: 2026-10-05T08:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    """Wall-clock time in the same format. Used for /health and the feed's hello and heartbeat only.
    Readings use the simulated clock (clock.py)."""
    return format_rfc3339(datetime.now(timezone.utc))

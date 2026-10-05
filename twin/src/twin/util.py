"""Small shared helpers."""
from datetime import datetime, timezone


def now_iso() -> str:
    """Wall-clock time, ISO 8601 UTC. Used for health and feed hello only.
    Readings will use the simulated clock instead (CIVIS convention: RFC 3339 UTC with Z, e.g.
    2026-10-04T08:00:00.000Z, plus an integer tick). That arrives on 6 Oct. One function, one edit."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

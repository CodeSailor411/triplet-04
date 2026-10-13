"""History storage. `open_history` picks the backend from config; the default is `memory` (nothing to install)."""
import os
from pathlib import Path

from dotenv import dotenv_values

from .base import HistoryStore
from .memory import MemoryHistory
from .writer import HistoryWriter

__all__ = ["HistoryStore", "HistoryWriter", "MemoryHistory", "open_history"]


def _lookup(name: str, environ, env_file: Path | None) -> str | None:
    """The real environment wins; twin/.env is the fallback (the same file the secrets are read from)."""
    if environ is not None:
        return environ.get(name)
    if os.environ.get(name):
        return os.environ[name]
    if env_file is not None and env_file.exists():
        return dotenv_values(env_file).get(name)
    return None


def open_history(storage_cfg, environ=None, env_file: Path | None = None) -> HistoryWriter:
    """Build the store named in config and wrap it in a writer. A missing DSN for `timescale` is a config error
    and stops the start with a clear message. A database that is merely DOWN does not: the Twin starts anyway."""
    if storage_cfg.history == "timescale":
        dsn = _lookup(storage_cfg.timescale_dsn_env, environ, env_file)
        if not dsn:
            raise SystemExit(f"storage.history is 'timescale' but the environment variable {storage_cfg.timescale_dsn_env} "
                             "is not set. Put the connection string in twin/.env (see .env.example), or set "
                             "storage.history to 'memory'.")
        from .timescale import TimescaleHistory       # imported here so a memory-only Twin never needs psycopg
        store: HistoryStore = TimescaleHistory(dsn)
    else:
        store = MemoryHistory()
    return HistoryWriter(store, queue_max=storage_cfg.queue_max, flush_seconds=storage_cfg.flush_seconds,
                         batch_max=storage_cfg.batch_max)

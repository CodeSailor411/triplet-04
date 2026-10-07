"""Blast-radius caps: how many nodes one request may touch. Only computed here for now,
enforced from 7 Oct. Rounded down, never below the minimum."""
from .settings import CapsCfg, GeneratorCfg


def compute_caps(gen: GeneratorCfg, caps: CapsCfg) -> dict[str, dict[str, int | None]]:
    out: dict[str, dict[str, int | None]] = {}
    for domain, dcfg in gen.domains.items():
        n = dcfg.count
        iso_pct = caps.isolation_pct_overrides.get(domain, caps.isolation_pct)
        isolation = min(n, max(caps.min_nodes, n * iso_pct // 100))
        action = min(n, max(caps.min_nodes, n * caps.action_pct // 100)) if dcfg.actuator else None
        out[domain] = {
            "nodes": n,
            "action_cap": action,          # None: this domain has no actuator
            "isolation_cap": isolation,    # isolate + quarantine share this pool
            "rollback_cap": isolation,     # own pool, same sizes
        }
    return out

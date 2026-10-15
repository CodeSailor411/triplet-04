"""
Guardian Layer -- synthetic labeled dataset generator, v2 (corrected).

Reuses the node graph, neighbour links and incident/corroboration table from the
original generate_dataset.py (left untouched) and fixes the issues that made v1 too
easy and partly circular:

1. LABELS COME FROM GROUND TRUTH, NOT FROM EVIDENCE.
   v1 labelled a genuine incident "suspect" whenever corroboration was weak. Here a
   reading is `trusted` if the underlying event is real (even if neighbours have not
   confirmed it yet) and `suspect`/`compromised` only if the generator forged it.
   `out_of_bounds` / `correlation_strength` are now noisy evidence, not the label rule.
2. HARDER ATTACKS: marginal out-of-range spoofs, in-range spoofs, in-range spoofs with
   forged neighbour corroboration, a slow-drift attack that stays in bounds, and an ADAPTIVE
   attacker that forges a gradual incident ramp together with neighbour corroboration
   (numerically the same story as a genuine, well-corroborated incident).
3. REPUTATION THAT DECAYS: `decayed_flags` is an exponentially decayed count of past
   non-trusted verdicts of a simple rule scorer (not of ground truth), using only
   events strictly before the current reading.
4. HISTORY FEATURES computed uniformly from past readings only: short-window z-score,
   deviation from a 30-tick baseline, and the length of a flat (stuck) run.
5. CIVIS-ALIGNED SENSOR CONFIG (units/quantities as in the 4 Oct CIVIS conventions),
   exported to sensor_config.json so nothing downstream hard-codes ranges. Missing
   values are JSON null / empty CSV cell, never zero.
6. `ref_rule_score`: a re-implementation of the penalty table in the Guardian report
   (NOT the real scoring.py) so the ML model can be compared with a rules baseline.

Everything is synthetic. Results on this data do not measure real-world performance.
"""

import csv
import importlib.util
import json
import math
import random
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---- reuse the original topology (read-only) --------------------------------
_spec = importlib.util.spec_from_file_location("generate_dataset_v1", HERE / "generate_dataset.py")
_v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v1)
NEIGHBOURS = _v1.NEIGHBOURS
INCIDENT_CORROBORATION = _v1.INCIDENT_CORROBORATION
node_domains = _v1.node_domains
NODE_POOLS = {"traffic": _v1.TRAFFIC_NODES, "water": _v1.WATER_NODES, "power": _v1.POWER_NODES,
              "air_quality": _v1.AIR_NODES, "emergency": _v1.EMERGENCY_NODES}

# ---- configuration -----------------------------------------------------------
# Quantities/units follow CIVIS conventions (4 Oct 2026). The traffic<->index mapping is
# listed there as still pending; 0-100 percent is an ASSUMPTION used here.
SENSOR_CONFIG = {
    "traffic":     {"quantity": "traffic_congestion_index", "unit": "percent",      "lo": 0,   "hi": 100, "max_rate": 15},
    "water":       {"quantity": "water_level",              "unit": "cm",           "lo": 20,  "hi": 120, "max_rate": 6},
    "power":       {"quantity": "power_load",               "unit": "kW",           "lo": 200, "hi": 800, "max_rate": 120},
    "air_quality": {"quantity": "pm25",                     "unit": "ug/m3",        "lo": 5,   "hi": 35,  "max_rate": 12},
    "emergency":   {"quantity": "emergency_calls",          "unit": "calls_per_min", "lo": 0,  "hi": 3,   "max_rate": 1.5},
}
HISTORY_TICKS = 30          # baseline history before the first emitted reading
SHORT_WINDOW = 6            # z-score window (past readings only)
TICK_SECONDS = 5            # declared tick duration
SCENARIO_SPACING_S = 600    # simulated gap between scenario starts
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
REPUTATION_HALF_LIFE = 80   # in scenarios (a node is hit roughly once per 38 scenarios)
NOISE_FRAC = 0.03           # normal sensor noise as a fraction of range
HEAVY_TAIL_P = 0.03         # chance a normal reading has 4x noise (false-alarm material)

SCENARIO_WEIGHTS = {
    "normal": 26, "benign_spike": 5,
    "genuine_incident_full_evidence": 5, "genuine_incident_partial_evidence": 5,
    "spoofed_isolated": 9, "spoofed_coordinated": 5,
    "spoofed_in_range": 7, "spoofed_in_range_corroborated": 4, "spoofed_ramp_corroborated": 4, "attack_drift": 3,
    "natural_drift": 4, "stuck_sensor": 4, "replay_exact": 5, "dropout": 2,
}

FIELDNAMES = ["scenario_id", "scenario_type", "node_id", "domain", "tick", "timestamp", "value",
              "z_score", "rate_of_change", "out_of_bounds", "correlation_strength", "incident_claimed",
              "decayed_flags", "baseline_dev_norm", "flat_run_len", "ref_rule_score", "label"]


def write_sensor_config(path) -> None:
    payload = {"source": "generate_dataset_v2.py (CIVIS 4 Oct 2026 conventions; traffic mapping assumed)",
               "domains": SENSOR_CONFIG}
    Path(path).write_text(json.dumps(payload, indent=2))


def _span(domain):
    c = SENSOR_CONFIG[domain]
    return c["hi"] - c["lo"]


# ---- features from past readings only ---------------------------------------
def compute_features(past, value, domain):
    c = SENSOR_CONFIG[domain]
    span = _span(domain)
    window = past[-SHORT_WINDOW:]
    if len(window) >= 3:
        sigma = max(statistics.pstdev(window), 0.005 * span)   # floor avoids 1e6 z-scores on flat windows
        z = (value - statistics.mean(window)) / sigma
    else:
        z = 0.0
    base = statistics.median(past[-HISTORY_TICKS:])
    run = 0
    for p in reversed(past):
        if abs(p - value) < 1e-9:
            run += 1
        else:
            break
    return {"z_score": z, "rate_of_change": abs(value - past[-1]),
            "out_of_bounds": int(not (c["lo"] <= value <= c["hi"])),
            "baseline_dev_norm": (value - base) / span, "flat_run_len": run}


def ref_rule_score(f, claimed, corr, decayed, domain):
    """Penalty table from the Guardian report (section 5). Thresholds for z and rate are assumptions
    (|z|>3, rate > per-domain max). Correlation only applies to incident-tagged readings."""
    s = 1.0
    if f["out_of_bounds"]:
        s -= 0.50
    if f["rate_of_change"] > SENSOR_CONFIG[domain]["max_rate"]:
        s -= 0.35
    if abs(f["z_score"]) > 3:
        s -= 0.25
    if claimed:
        if corr < 0.34:
            s -= 0.45
        elif corr <= 0.67:
            s -= 0.20
    s -= min(0.25, 0.05 * decayed)
    return max(0.0, min(1.0, s))


class Generator:
    def __init__(self, seed=42):
        self.rng = random.Random(seed)
        self.flags = {}     # node -> [scenario_index of each past non-trusted verdict]
        self.rows = []

    # -- helpers -------------------------------------------------------------
    def decayed(self, node, now):
        return sum(0.5 ** ((now - t) / REPUTATION_HALF_LIFE) for t in self.flags.get(node, []))

    def baseline_series(self, domain, n=HISTORY_TICKS):
        c, rng = SENSOR_CONFIG[domain], self.rng
        span = _span(domain)
        base = rng.uniform(c["lo"] + 0.2 * span, c["hi"] - 0.2 * span)
        out = []
        for _ in range(n):
            sigma = NOISE_FRAC * span * (4 if rng.random() < HEAVY_TAIL_P else 1)
            out.append(max(0.0, base + rng.gauss(0, sigma)))
        return out

    def corroboration(self, node, incident, evidence_fraction):
        expected = INCIDENT_CORROBORATION.get(incident, [])
        neigh = set()
        for nb in NEIGHBOURS.get(node, []):
            neigh.update(node_domains(nb))
        relevant = [d for d in expected if d in neigh]
        if not relevant:
            return 0.0          # nobody around could corroborate
        return sum(1 for _ in relevant if self.rng.random() < evidence_fraction) / len(relevant)

    def pick_incident_node(self):
        incident = self.rng.choice(list(INCIDENT_CORROBORATION))
        domain = self.rng.choice([d for d in INCIDENT_CORROBORATION[incident] if d in SENSOR_CONFIG])
        return incident, domain, self.rng.choice(NODE_POOLS[domain])

    def emit(self, sid, stype, node, domain, tick, past, value, claimed, corr, label):
        if value is None:                                   # dropout: JSON null / empty cell, never zero
            self.rows.append({"scenario_id": sid, "scenario_type": stype, "node_id": node, "domain": domain,
                              "tick": tick, "timestamp": self._ts(sid, tick), "value": "", "z_score": "",
                              "rate_of_change": "", "out_of_bounds": "", "correlation_strength": "",
                              "incident_claimed": claimed, "decayed_flags": round(self.decayed(node, sid), 4),
                              "baseline_dev_norm": "", "flat_run_len": "", "ref_rule_score": "", "label": label})
            return
        f = compute_features(past, value, domain)
        dec = self.decayed(node, sid)                        # strictly BEFORE this reading
        score = ref_rule_score(f, claimed, corr, dec, domain)
        self.rows.append({
            "scenario_id": sid, "scenario_type": stype, "node_id": node, "domain": domain, "tick": tick,
            "timestamp": self._ts(sid, tick), "value": round(value, 3), "z_score": round(f["z_score"], 3),
            "rate_of_change": round(f["rate_of_change"], 3), "out_of_bounds": f["out_of_bounds"],
            "correlation_strength": round(corr, 3), "incident_claimed": claimed,
            "decayed_flags": round(dec, 4), "baseline_dev_norm": round(f["baseline_dev_norm"], 4),
            "flat_run_len": f["flat_run_len"], "ref_rule_score": round(score, 3), "label": label})
        if score <= 0.7:                                     # simple rule scorer said "not trusted" -> reputation flag
            lst = self.flags.setdefault(node, [])
            if not lst or lst[-1] != sid:                    # at most one flag per scenario
                lst.append(sid)

    @staticmethod
    def _ts(sid, tick):
        return (T0 + timedelta(seconds=sid * SCENARIO_SPACING_S + tick * TICK_SECONDS)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # -- scenarios -----------------------------------------------------------
    def scenario(self, sid, stype):
        rng = self.rng
        H = HISTORY_TICKS
        if stype in ("normal", "benign_spike", "replay_exact", "dropout", "stuck_sensor",
                     "natural_drift", "attack_drift", "spoofed_in_range",
                     "spoofed_in_range_corroborated"):
            domain = rng.choice(list(SENSOR_CONFIG))
            node = rng.choice(NODE_POOLS[domain])
        c_span = None

        if stype == "normal":
            s = self.baseline_series(domain, H + 1)
            self.emit(sid, stype, node, domain, H, s[:-1], s[-1], 0, 1.0, "trusted")

        elif stype == "benign_spike":      # real, unclaimed, moderate change (e.g. rush hour); in range
            past = self.baseline_series(domain)
            c = SENSOR_CONFIG[domain]
            span = _span(domain)
            step = rng.uniform(0.5, 1.0) * c["max_rate"]       # within the plausible per-tick change
            v = min(c["hi"], max(c["lo"], past[-1] + rng.choice([-1, 1]) * step))
            self.emit(sid, stype, node, domain, H, past, v, 0, 1.0, "trusted")

        elif stype in ("genuine_incident_full_evidence", "genuine_incident_partial_evidence",
                       "spoofed_ramp_corroborated"):
            incident, domain, node = self.pick_incident_node()
            past = self.baseline_series(domain)
            c, span = SENSOR_CONFIG[domain], _span(domain)
            rise = span * rng.uniform(0.35, 0.7)
            # A real event ramps up over several ticks at a physically plausible rate (<= 0.8 x max_rate per tick);
            # v1 used a single-tick jump that violated its own MAX_RATE.
            n = max(2, min(12, math.ceil(rise / (0.8 * c["max_rate"]))))
            frac = 0.85 if stype.endswith(("full_evidence", "ramp_corroborated")) else rng.uniform(0.3, 0.6)
            corr = self.corroboration(node, incident, frac)     # one corroboration outcome per incident
            # spoofed_ramp_corroborated = the HARD adaptive attacker: forges a plausible ramp AND neighbour evidence,
            # so it is numerically the same story as a genuine, fully corroborated incident.
            truth = "suspect" if stype == "spoofed_ramp_corroborated" else "trusted"
            start = past[-1]
            for i in range(1, n + 1):
                v = min(start + rise * i / n + rng.gauss(0, NOISE_FRAC * span * 0.5), c["hi"] * 1.15)
                # GROUND TRUTH: genuine events are trusted regardless of corroboration; the forged ramp is not.
                self.emit(sid, stype, node, domain, H + i - 1, past, v, 1, corr, truth)
                past = past + [v]

        elif stype in ("spoofed_isolated", "spoofed_coordinated"):
            incident, domain, node = self.pick_incident_node()
            past = self.baseline_series(domain)
            c = SENSOR_CONFIG[domain]
            # 70% blatant (1.3x-20x upper bound), 30% marginal (just over the bound)
            mult = rng.uniform(1.3, 20.0) if rng.random() < 0.7 else rng.uniform(1.02, 1.3)
            v = c["hi"] * mult
            frac = 0.6 if stype == "spoofed_coordinated" else 0.0
            corr = self.corroboration(node, incident, frac)
            self.emit(sid, stype, node, domain, H, past, v, 1, corr, "compromised")

        elif stype in ("spoofed_in_range", "spoofed_in_range_corroborated"):
            incident = rng.choice(list(INCIDENT_CORROBORATION))
            domain = rng.choice([d for d in INCIDENT_CORROBORATION[incident] if d in SENSOR_CONFIG])
            node = rng.choice(NODE_POOLS[domain])
            past = self.baseline_series(domain)
            c, span = SENSOR_CONFIG[domain], _span(domain)
            v = min(c["hi"], max(c["lo"], past[-1] + rng.choice([-1, 1]) * span * rng.uniform(0.25, 0.55)))
            if stype == "spoofed_in_range_corroborated":
                claimed, corr = 1, self.corroboration(node, incident, 0.85)   # attacker also forged neighbours
            else:
                claimed = 1 if rng.random() < 0.7 else 0
                corr = self.corroboration(node, incident, 0.0) if claimed else 1.0
            self.emit(sid, stype, node, domain, H, past, v, claimed, corr, "suspect")

        elif stype in ("attack_drift", "natural_drift"):
            past = self.baseline_series(domain)
            c, span = SENSOR_CONFIG[domain], _span(domain)
            mag = rng.uniform(0.25, 0.45) if stype == "attack_drift" else rng.uniform(0.10, 0.20)
            target = rng.choice([-1, 1]) * span * mag
            start = statistics.mean(past[-SHORT_WINDOW:])
            label = "suspect" if stype == "attack_drift" else "degraded"
            for i in range(1, 9):
                v = start + target * (i / 8) + rng.gauss(0, NOISE_FRAC * span)
                v = min(c["hi"], max(c["lo"], v)) if stype == "attack_drift" else max(0.0, v)
                self.emit(sid, stype, node, domain, H + i - 1, past, v, 0, 1.0, label)
                past = past + [v]

        elif stype == "stuck_sensor":
            past = self.baseline_series(domain)
            stuck = past[-1]
            for i in range(6):
                self.emit(sid, stype, node, domain, H + i, past, stuck, 0, 1.0, "degraded" if i >= 3 else "trusted")
                past = past + [stuck]

        elif stype == "replay_exact":
            past = self.baseline_series(domain)
            self.emit(sid, stype, node, domain, H, past, past[rng.randrange(5, H - 2)], 0, 1.0, "rejected_replay")

        elif stype == "dropout":
            past = self.baseline_series(domain)
            self.emit(sid, stype, node, domain, H, past, None, 0, 1.0, "degraded")
        else:
            raise ValueError(stype)


def generate(n_scenarios, out_path, seed=42, config_path=None):
    g = Generator(seed)
    types, weights = list(SCENARIO_WEIGHTS), list(SCENARIO_WEIGHTS.values())
    for sid in range(n_scenarios):
        g.scenario(sid, g.rng.choices(types, weights=weights, k=1)[0])
    with open(out_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(g.rows)
    if config_path:
        write_sensor_config(config_path)
    return g.rows


if __name__ == "__main__":
    from collections import Counter
    rows = generate(4000, HERE / "data" / "guardian_dataset_synthetic.csv", config_path=HERE / "data" / "sensor_config.json")
    print(len(rows), "rows")
    print(Counter(r["label"] for r in rows))
    print(Counter(r["scenario_type"] for r in rows))

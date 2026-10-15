# Feature engineering for the Guardian Random Forest demo.
#
# Kept in its own module so a pickled pipeline can be reloaded in any process
# (put this folder on PYTHONPATH). Pure functions apart from reading sensor_config.json
# next to this file. No secrets.
import json
from pathlib import Path

import pandas as pd

CONFIG_PATH = Path(__file__).with_name("sensor_config.json")
_DOMAINS = json.loads(CONFIG_PATH.read_text())["domains"]
NORMAL_RANGES = {d: (c["lo"], c["hi"]) for d, c in _DOMAINS.items()}   # per-domain normal range
MAX_RATE = {d: c["max_rate"] for d, c in _DOMAINS.items()}             # max plausible change per tick
UNITS = {d: c["unit"] for d, c in _DOMAINS.items()}

RAW_INPUT_COLUMNS = ["domain", "value", "z_score", "rate_of_change", "out_of_bounds",
                     "correlation_strength", "incident_claimed", "decayed_flags",
                     "baseline_dev_norm", "flat_run_len"]
NUMERIC_FEATURES = ["value_norm", "z_score", "rate_norm", "out_of_bounds", "correlation_strength",
                    "incident_claimed", "decayed_flags", "baseline_dev_norm", "flat_run_len"]
CATEGORICAL_FEATURES = ["domain"]


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in RAW_INPUT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing input columns: {missing}")
    lo = df["domain"].map({k: v[0] for k, v in NORMAL_RANGES.items()})
    hi = df["domain"].map({k: v[1] for k, v in NORMAL_RANGES.items()})
    max_rate = df["domain"].map(MAX_RATE)
    num = lambda c: pd.to_numeric(df[c])
    out = pd.DataFrame(index=df.index)
    out["value_norm"] = (num("value") - lo) / (hi - lo)       # NaN for unknown domain or missing value
    out["z_score"] = num("z_score")
    out["rate_norm"] = num("rate_of_change") / max_rate
    out["out_of_bounds"] = num("out_of_bounds")
    out["correlation_strength"] = num("correlation_strength")
    out["incident_claimed"] = num("incident_claimed")
    out["decayed_flags"] = num("decayed_flags")
    out["baseline_dev_norm"] = num("baseline_dev_norm")
    out["flat_run_len"] = num("flat_run_len")
    out["domain"] = df["domain"].astype(object)
    return out[NUMERIC_FEATURES + CATEGORICAL_FEATURES]

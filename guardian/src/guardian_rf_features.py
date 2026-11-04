"""Feature engineering module required when loading the attached model."""
import json
from pathlib import Path

import pandas as pd

CONFIG_PATH = Path(__file__).with_name("sensor_config.json")
_DOMAINS = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["domains"]
NORMAL_RANGES = {d: (c["lo"], c["hi"]) for d, c in _DOMAINS.items()}
MAX_RATE = {d: c["max_rate"] for d, c in _DOMAINS.items()}
RAW_INPUT_COLUMNS = ["domain", "value", "z_score", "rate_of_change", "out_of_bounds", "correlation_strength", "incident_claimed", "decayed_flags", "baseline_dev_norm", "flat_run_len"]
NUMERIC_FEATURES = ["value_norm", "z_score", "rate_norm", "out_of_bounds", "correlation_strength", "incident_claimed", "decayed_flags", "baseline_dev_norm", "flat_run_len"]


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in RAW_INPUT_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Missing input columns: {missing}")
    lo = df["domain"].map({key: val[0] for key, val in NORMAL_RANGES.items()})
    hi = df["domain"].map({key: val[1] for key, val in NORMAL_RANGES.items()})
    max_rate = df["domain"].map(MAX_RATE)
    numeric = lambda column: pd.to_numeric(df[column])
    out = pd.DataFrame(index=df.index)
    out["value_norm"] = (numeric("value") - lo) / (hi - lo)
    out["z_score"] = numeric("z_score")
    out["rate_norm"] = numeric("rate_of_change") / max_rate
    for column in RAW_INPUT_COLUMNS[4:]:
        out[column] = numeric(column)
    out["domain"] = df["domain"].astype(object)
    return out[NUMERIC_FEATURES + ["domain"]]

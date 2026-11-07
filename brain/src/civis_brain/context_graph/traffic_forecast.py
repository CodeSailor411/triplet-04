"""Pure-Python inference for the optional CIVIS Traffic GraphSAGE shadow model."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from civis_brain.contracts import Node, Reading

MODEL_PATH = Path(__file__).with_name("traffic_gnn_v1.json")
FEATURES = ("vehicle_count", "avg_speed")
UNITS = {"vehicle_count": "cars/min", "avg_speed": "km/h"}


@lru_cache(maxsize=2)
def _load_model(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if (data.get("schema_version") != 1
            or data.get("model_id") != "civis-twin-traffic-graphsage-5tick-v1"
            or data.get("feature_order") != list(FEATURES)
            or data.get("units") != UNITS
            or data.get("history_ticks") != 5
            or data.get("horizon_ticks") != 5):
        raise ValueError("Traffic GNN model metadata does not match the Brain contract")
    return data


def _mlp(model: dict, features: list[float]) -> list[float]:
    weights = model["hidden_weights"]
    w1, b1, w2, b2 = (weights[name] for name in ("w1", "b1", "w2", "b2"))
    if len(w1) != len(features) or any(len(row) != len(b1) for row in w1):
        raise ValueError("Traffic GNN first layer dimensions are invalid")
    if len(w2) != len(b1) or any(len(row) != 2 for row in w2) or len(b2) != 2:
        raise ValueError("Traffic GNN output dimensions are invalid")
    hidden = [
        max(0.0, b1[j] + sum(features[i] * w1[i][j] for i in range(len(features))))
        for j in range(len(b1))
    ]
    output = [b2[k] + sum(hidden[j] * w2[j][k] for j in range(len(hidden)))
              for k in range(2)]
    if not all(math.isfinite(value) for value in output):
        raise ValueError("Traffic GNN produced a non-finite forecast")
    return output


def forecast_traffic(
    nodes: list[Node],
    readings: list[Reading],
    *,
    run_id: str,
    tick: int,
    tick_seconds: float,
    graph_version: str,
    invalid_ids: set[str] | None = None,
    blocked_devices: set[str] | None = None,
    model_path: Path = MODEL_PATH,
) -> dict:
    """Forecast two Traffic sensor reports, only when every input window is complete.

    Inputs are raw Twin-reported readings. This output is deliberately advisory and
    must never be used as a trusted reading, incident label or action authorization.
    """
    model = _load_model(str(model_path.resolve()))
    traffic = sorted((node for node in nodes if "traffic" in node.domains),
                     key=lambda node: node.node_id)
    if not traffic:
        return {"status": "unavailable", "reason": "Twin discovery has no Traffic nodes"}
    trained_node_ids = set(model.get("representative_adjacency", {}))
    if trained_node_ids and {node.node_id for node in traffic} != trained_node_ids:
        return {"status": "unavailable", "reason": "Twin Traffic node set differs from training graph"}
    start_tick = tick - model["history_ticks"] + 1
    if start_tick < 0:
        return {"status": "waiting_for_complete_window", "needed_ticks": model["history_ticks"]}
    tick_window = set(range(start_tick, tick + 1))
    invalid_ids = invalid_ids or set()
    blocked_devices = blocked_devices or set()
    node_ids = {node.node_id for node in traffic}
    values: dict[tuple[str, int, str], Reading] = {}
    for reading in readings:
        if (reading.run_id != run_id or reading.node_id not in node_ids
                or reading.tick not in tick_window or reading.sensor not in FEATURES):
            continue
        if reading.reading_id in invalid_ids or reading.device_id in blocked_devices:
            continue
        if reading.unit != UNITS[reading.sensor] or reading.value is None:
            return {"status": "waiting_for_complete_window", "reason": "missing or invalid sensor input"}
        key = (reading.node_id, reading.tick, reading.sensor)
        prior = values.get(key)
        if prior is not None and prior.reading_id != reading.reading_id:
            return {"status": "unavailable", "reason": "duplicate node/sensor/tick input"}
        values[key] = reading

    if any((node.node_id, sample_tick, sensor) not in values
           for node in traffic for sample_tick in tick_window for sensor in FEATURES):
        return {"status": "waiting_for_complete_window", "needed_ticks": model["history_ticks"]}

    adjacency = {node.node_id: set() for node in traffic}
    for node in traffic:
        for neighbour in node.neighbours:
            if neighbour in adjacency and neighbour != node.node_id:
                adjacency[node.node_id].add(neighbour)
                adjacency[neighbour].add(node.node_id)

    means = model["normalization_mean"]
    scales = model["normalization_scale"]
    if len(means) != 2 or len(scales) != 2 or any(
        not math.isfinite(x) for x in [*means, *scales]
    ) or any(x <= 0 for x in scales):
        raise ValueError("Traffic GNN normalization metadata is invalid")

    forecasts = []
    input_ids = []
    for node in traffic:
        own_window = []
        neighbour_window = []
        for sample_tick in sorted(tick_window):
            row = [float(values[(node.node_id, sample_tick, feature)].value) for feature in FEATURES]
            own_window.append([(row[i] - means[i]) / scales[i] for i in range(2)])
            linked_values = [
                [float(values[(neighbour, sample_tick, feature)].value) for feature in FEATURES]
                for neighbour in sorted(adjacency[node.node_id])
            ]
            if linked_values:
                neighbour_row = [sum(item[i] for item in linked_values) / len(linked_values)
                                 for i in range(2)]
                neighbour_window.append([(neighbour_row[i] - means[i]) / scales[i] for i in range(2)])
            else:
                neighbour_window.append([0.0, 0.0])
            input_ids.extend(values[(node.node_id, sample_tick, feature)].reading_id
                             for feature in FEATURES)
        flat = [item for row in own_window for item in row]
        flat.extend(item for row in neighbour_window for item in row)
        normalized_forecast = _mlp(model, flat)
        forecast = [normalized_forecast[i] * scales[i] + means[i] for i in range(2)]
        latest = own_window[-1]
        latest_raw = [latest[i] * scales[i] + means[i] for i in range(2)]
        forecasts.append({
            "node_id": node.node_id,
            "latest": {FEATURES[i]: {"value": latest_raw[i], "unit": UNITS[FEATURES[i]]}
                       for i in range(2)},
            "forecast": {FEATURES[i]: {"value": forecast[i], "unit": UNITS[FEATURES[i]]}
                         for i in range(2)},
            "neighbour_count": len(adjacency[node.node_id]),
        })

    return {
        "status": "ready",
        "model_id": model["model_id"],
        "run_id": run_id,
        "graph_version": graph_version,
        "input_window_ticks": [start_tick, tick],
        "forecast_tick": tick + model["horizon_ticks"],
        "horizon_ticks": model["horizon_ticks"],
        "tick_seconds": tick_seconds,
        "features": [{"name": name, "unit": UNITS[name]} for name in FEATURES],
        "graph_relation": "Twin same-domain neighbours; geographic proxy, not road links",
        "input_quality": "Twin sensor reports not individually Guardian-verified for this model",
        "use_limit": "shadow interpretation only; not evidence, an incident, a trust score or an action input",
        "model_test_mae": model["test_mae"],
        "input_reading_ids": sorted(set(input_ids)),
        "forecasts": forecasts,
    }

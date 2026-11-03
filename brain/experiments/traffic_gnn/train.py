"""Train and evaluate a small shadow-only traffic GraphSAGE forecaster.

The examples come from the checked-in Twin simulator, not real city measurements.
No incident labels are invented: the target is each sensor's reported value five
Twin ticks later. Training and evaluation runs use disjoint Twin seeds.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "twin" / "src"))

from twin.generator import generate  # noqa: E402
from twin.settings import load_config  # noqa: E402
from twin.sim import Simulation  # noqa: E402

HISTORY_TICKS = 5
FORECAST_HORIZON = 5
TICK_COUNT = 1200
WINDOW_STRIDE = 5
FEATURES = ("vehicle_count", "avg_speed")
UNITS = {"vehicle_count": "cars/min", "avg_speed": "km/h"}
SEED_SPLIT = {"train": list(range(100, 108)), "validation": [108, 109], "test": [110, 111]}


def twin_source_hash() -> str:
    digest = hashlib.sha256()
    for relative in (
        "twin/config/twin.yaml",
        "twin/src/twin/generator.py",
        "twin/src/twin/sensors.py",
        "twin/src/twin/sim.py",
    ):
        digest.update((ROOT / relative).read_bytes())
    return digest.hexdigest()


def collect_run(config, seed: int) -> dict:
    topology, _layout = generate(config, seed)
    sim = Simulation(topology, config)
    nodes = sorted(
        (node for node in topology.nodes if "traffic" in node.domains),
        key=lambda node: node.node_id,
    )
    node_index = {node.node_id: index for index, node in enumerate(nodes)}
    feature_index = {name: index for index, name in enumerate(FEATURES)}
    values = np.full((TICK_COUNT, len(nodes), len(FEATURES)), np.nan, dtype=np.float32)

    for tick in range(TICK_COUNT):
        batch = sim.readings_at(tick, domain="traffic")
        for reading in batch.readings:
            if reading.sensor not in feature_index:
                continue
            if reading.unit != UNITS[reading.sensor] or reading.value is None:
                raise ValueError(f"Twin training input has invalid {reading.sensor} unit/value")
            values[tick, node_index[reading.node_id], feature_index[reading.sensor]] = reading.value

    if not np.isfinite(values).all():
        raise ValueError(f"Twin run seed {seed} has an incomplete traffic feature window")

    neighbours = {node.node_id: set(node.neighbours) for node in nodes}
    adjacency = [set() for _ in nodes]
    for source_id, targets in neighbours.items():
        for target_id in targets:
            if target_id in node_index and target_id != source_id:
                a, b = node_index[source_id], node_index[target_id]
                adjacency[a].add(b)
                adjacency[b].add(a)

    return {
        "seed": seed,
        "nodes": nodes,
        "values": values,
        "adjacency": [sorted(row) for row in adjacency],
    }


def build_examples(runs: list[dict], means: np.ndarray, scales: np.ndarray) -> dict:
    feature_rows = []
    target_rows = []
    last_rows = []
    first_rows = []
    target_raw_rows = []
    for run in runs:
        normalized = (run["values"] - means) / scales
        adjacency = run["adjacency"]
        count = len(run["nodes"])
        for anchor in range(HISTORY_TICKS - 1, TICK_COUNT - FORECAST_HORIZON, WINDOW_STRIDE):
            own = normalized[anchor - HISTORY_TICKS + 1 : anchor + 1]
            neighbours = np.zeros_like(own)
            for node_i, linked in enumerate(adjacency):
                if linked:
                    neighbours[:, node_i, :] = own[:, linked, :].mean(axis=1)
            own_features = own.transpose(1, 0, 2).reshape(count, -1)
            neighbour_features = neighbours.transpose(1, 0, 2).reshape(count, -1)
            feature_rows.append(np.concatenate((own_features, neighbour_features), axis=1))
            target_rows.append(normalized[anchor + FORECAST_HORIZON])
            last_rows.append(run["values"][anchor])
            first_rows.append(run["values"][anchor - HISTORY_TICKS + 1])
            target_raw_rows.append(run["values"][anchor + FORECAST_HORIZON])
    return {
        "x": np.concatenate(feature_rows).astype(np.float32),
        "y": np.concatenate(target_rows).astype(np.float32),
        "last": np.concatenate(last_rows).astype(np.float32),
        "first": np.concatenate(first_rows).astype(np.float32),
        "target_raw": np.concatenate(target_raw_rows).astype(np.float32),
    }


def fit_mlp(train_x, train_y, validation_x, validation_y, *, seed: int, epochs: int = 100):
    rng = np.random.default_rng(seed)
    input_size = train_x.shape[1]
    hidden_size = 16
    w1 = rng.normal(0, math.sqrt(2 / input_size), (input_size, hidden_size)).astype(np.float32)
    b1 = np.zeros(hidden_size, dtype=np.float32)
    w2 = rng.normal(0, math.sqrt(2 / hidden_size), (hidden_size, 2)).astype(np.float32)
    b2 = np.zeros(2, dtype=np.float32)
    params = [w1, b1, w2, b2]
    first_moments = [np.zeros_like(value) for value in params]
    second_moments = [np.zeros_like(value) for value in params]
    step = 0
    best = None
    best_loss = float("inf")
    batch_size = 1024
    beta1, beta2, epsilon, learning_rate = 0.9, 0.999, 1e-8, 0.01

    for _epoch in range(epochs):
        order = rng.permutation(len(train_x))
        for start in range(0, len(order), batch_size):
            indexes = order[start : start + batch_size]
            x, y = train_x[indexes], train_y[indexes]
            z1 = x @ w1 + b1
            hidden = np.maximum(z1, 0)
            predicted = hidden @ w2 + b2
            grad_prediction = (2.0 / y.size) * (predicted - y)
            grad_w2 = hidden.T @ grad_prediction
            grad_b2 = grad_prediction.sum(axis=0)
            grad_hidden = grad_prediction @ w2.T
            grad_z1 = grad_hidden * (z1 > 0)
            grad_w1 = x.T @ grad_z1
            grad_b1 = grad_z1.sum(axis=0)
            step += 1
            for index, gradient in enumerate((grad_w1, grad_b1, grad_w2, grad_b2)):
                first_moments[index] *= beta1
                first_moments[index] += (1 - beta1) * gradient
                second_moments[index] *= beta2
                second_moments[index] += (1 - beta2) * gradient * gradient
                m_hat = first_moments[index] / (1 - beta1**step)
                v_hat = second_moments[index] / (1 - beta2**step)
                params[index] -= learning_rate * m_hat / (np.sqrt(v_hat) + epsilon)

        validation_prediction = np.maximum(validation_x @ w1 + b1, 0) @ w2 + b2
        validation_loss = float(np.mean((validation_prediction - validation_y) ** 2))
        if validation_loss < best_loss:
            best_loss = validation_loss
            best = [value.copy() for value in params]

    assert best is not None
    return {"w1": best[0], "b1": best[1], "w2": best[2], "b2": best[3]}, best_loss


def mae_by_feature(predicted: np.ndarray, target: np.ndarray) -> dict[str, float]:
    values = np.mean(np.abs(predicted - target), axis=0)
    return {name: float(value) for name, value in zip(FEATURES, values, strict=True)}


def predict_mlp(model: dict, x: np.ndarray) -> np.ndarray:
    return np.maximum(x @ model["w1"] + model["b1"], 0) @ model["w2"] + model["b2"]


def serial_weights(model: dict) -> dict:
    return {name: value.tolist() for name, value in model.items()}


def main() -> None:
    config = load_config(str(ROOT / "twin" / "config" / "twin.yaml"))
    runs = {seed: collect_run(config, seed) for group in SEED_SPLIT.values() for seed in group}
    expected_nodes = [node.node_id for node in runs[SEED_SPLIT["train"][0]]["nodes"]]
    if any([node.node_id for node in run["nodes"]] != expected_nodes for run in runs.values()):
        raise ValueError("Twin traffic node IDs changed across the experiment seeds")

    train_runs = [runs[seed] for seed in SEED_SPLIT["train"]]
    train_values = np.concatenate([run["values"].reshape(-1, 2) for run in train_runs])
    means = train_values.mean(axis=0).astype(np.float32)
    scales = train_values.std(axis=0).astype(np.float32)
    scales[scales < 1e-6] = 1.0
    data = {name: build_examples([runs[seed] for seed in seeds], means, scales)
            for name, seeds in SEED_SPLIT.items()}

    graph_model, graph_validation_loss = fit_mlp(
        data["train"]["x"], data["train"]["y"], data["validation"]["x"],
        data["validation"]["y"], seed=1701,
    )
    no_graph_model, no_graph_validation_loss = fit_mlp(
        data["train"]["x"][:, : HISTORY_TICKS * 2], data["train"]["y"],
        data["validation"]["x"][:, : HISTORY_TICKS * 2], data["validation"]["y"], seed=1702,
    )

    test = data["test"]
    graph_pred = predict_mlp(graph_model, test["x"]) * scales + means
    no_graph_pred = predict_mlp(no_graph_model, test["x"][:, : HISTORY_TICKS * 2]) * scales + means
    persistence = test["last"]
    trend = test["last"] + FORECAST_HORIZON * (
        test["last"] - test["first"]
    ) / (HISTORY_TICKS - 1)
    metrics = {
        "graphsage_mean": mae_by_feature(graph_pred, test["target_raw"]),
        "temporal_mlp_no_graph": mae_by_feature(no_graph_pred, test["target_raw"]),
        "persistence": mae_by_feature(persistence, test["target_raw"]),
        "linear_trend": mae_by_feature(trend, test["target_raw"]),
    }

    representative = runs[SEED_SPLIT["train"][0]]
    adjacency = {
        node.node_id: [representative["nodes"][index].node_id for index in linked]
        for node, linked in zip(representative["nodes"], representative["adjacency"], strict=True)
    }
    model_path = ROOT / "brain" / "src" / "civis_brain" / "context_graph" / "traffic_gnn_v1.json"
    evaluation_path = ROOT / "brain" / "experiments" / "traffic_gnn" / "artifacts" / "evaluation.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    evaluation = {
        "experiment": "CIVIS S01 traffic five-tick-ahead shadow forecast",
        "data_source": "Twin SensorModel observed_value generated from checked-in twin/config/twin.yaml",
        "data_kind": "synthetic mock telemetry; no real measurements and no incident labels",
        "twin_source_sha256": twin_source_hash(),
        "seed_split": SEED_SPLIT,
        "ticks_per_seed": TICK_COUNT,
        "history_ticks": HISTORY_TICKS,
        "horizon_ticks": FORECAST_HORIZON,
        "window_stride_ticks": WINDOW_STRIDE,
        "traffic_nodes": expected_nodes,
        "test_windows": len(test["y"]) // len(expected_nodes),
        "validation_mse": {
            "graphsage_mean": graph_validation_loss,
            "temporal_mlp_no_graph": no_graph_validation_loss,
        },
        "test_mae": metrics,
        "units": UNITS,
        "interpretation": "Forecast accuracy on this deterministic simulator is not real-world traffic validation.",
    }
    model = {
        "schema_version": 1,
        "model_id": "civis-twin-traffic-graphsage-5tick-v1",
        "architecture": "shared GraphSAGE mean-neighbour aggregation plus a two-layer MLP",
        "feature_order": ["vehicle_count", "avg_speed"],
        "units": UNITS,
        "history_ticks": HISTORY_TICKS,
        "horizon_ticks": FORECAST_HORIZON,
        "normalization_mean": means.tolist(),
        "normalization_scale": scales.tolist(),
        "hidden_weights": serial_weights(graph_model),
        "graph_scope": "undirected union of Twin list_nodes.neighbours within the traffic domain",
        "graph_version_seed": representative["seed"],
        "training_data_scope": evaluation["data_kind"],
        "input_quality": "raw Twin reports; not independently Guardian-verified for model inference",
        "output_scope": "shadow forecast only; never an incident label, trust score, risk tier or action input",
        "test_mae": metrics["graphsage_mean"],
        "training_source_sha256": evaluation["twin_source_sha256"],
        "representative_adjacency": adjacency,
    }
    model_path.write_text(json.dumps(model, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    evaluation_path.write_text(json.dumps(evaluation, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"model": str(model_path), "evaluation": str(evaluation_path), **evaluation}, indent=2))


if __name__ == "__main__":
    main()

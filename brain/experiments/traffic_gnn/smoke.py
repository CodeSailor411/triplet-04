"""Manual inference and Brain-to-interpreter smoke check for the Twin mock."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "brain" / "src"))
sys.path.insert(0, str(ROOT / "twin" / "src"))
print("Import Brain and Twin modules...", flush=True)

from twin.generator import generate  # noqa: E402
from twin.settings import load_config  # noqa: E402
from twin.sim import Simulation  # noqa: E402

from civis_brain.context_graph import ContextGraph  # noqa: E402
from civis_brain.context_graph.traffic_forecast import forecast_traffic  # noqa: E402
from civis_brain.contracts import Node, Reading  # noqa: E402
from civis_brain.integration.runtime import BrainRuntime  # noqa: E402
from civis_brain.planning.gemini import GeminiPlanProvider  # noqa: E402
from civis_brain.settings import load_settings  # noqa: E402

print("Imports loaded.", flush=True)

class StubInterpreter:
    def __init__(self):
        self.calls = 0

    async def interpret_graph(self, forecast: dict) -> dict:
        self.calls += 1
        return {
            "summary": "Synthetic forecast available for review.",
            "trend": "unclear",
            "uncertainty": "high",
            "caveats": ["Mock telemetry only."],
        }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gemini",
        action="store_true",
        help="also send this synthetic forecast to the configured Gemini model",
    )
    args = parser.parse_args()
    print("Load Twin mock and build five Traffic ticks...", flush=True)
    config = load_config(ROOT / "twin" / "config" / "twin.yaml")
    topology, _layout = generate(config, 100)
    simulation = Simulation(topology, config)
    nodes = [
        Node(
            node_id=node.node_id,
            domains=node.domains,
            role=node.role,
            actuators=node.actuators,
            neighbours=node.neighbours,
            lat=node.lat,
            lon=node.lon,
        )
        for node in topology.nodes
    ]
    run_id = simulation.run_id
    readings = []
    for tick in range(5):
        batch = simulation.readings_at(tick, domain="traffic")
        readings.extend(
            Reading(
                run_id=run_id,
                reading_id=row.reading_id,
                tick=row.tick,
                timestamp=row.timestamp,
                node_id=row.node_id,
                device_id=row.device_id,
                sensor=row.sensor,
                channel=row.channel,
                value=row.value,
                unit=row.unit,
                lat=row.lat,
                lon=row.lon,
            )
            for row in batch.readings
        )

    forecast = forecast_traffic(
        nodes,
        readings,
        run_id=run_id,
        tick=4,
        tick_seconds=config.clock.tick_seconds,
        graph_version=ContextGraph(nodes).version,
    )
    if forecast.get("status") != "ready" or len(forecast.get("forecasts", [])) != 11:
        raise RuntimeError(f"Expected a forecast for 11 Twin Traffic nodes, got {forecast}")
    if len(forecast.get("input_reading_ids", [])) != 110:
        raise RuntimeError("Expected 110 readings across five ticks and 11 Traffic nodes")
    print("Forecast inference passed; verify Brain interpreter handoff...", flush=True)

    interpreter = StubInterpreter()
    runtime = BrainRuntime(
        twin=None,
        guardian=None,
        provider=interpreter,
        policies={},
        features={"traffic_gnn_shadow_enabled": True, "ai_max_calls_per_run": 2},
        scenarios=[],
    )
    runtime.ledger = {reading.reading_id: reading for reading in readings}
    batch = SimpleNamespace(run_id=run_id, tick=4, tick_seconds=config.clock.tick_seconds)
    runtime._update_traffic_gnn_shadow(batch, nodes)
    runtime._schedule_traffic_gnn_interpretation(batch)
    await asyncio.gather(*runtime._traffic_gnn_tasks)
    if runtime.traffic_gnn_interpretation.get("status") != "ready" or interpreter.calls != 1:
        raise RuntimeError("Brain did not deliver one shadow forecast to its interpreter")
    await runtime.close()
    print("Brain interpreter handoff passed.", flush=True)

    live_interpretation = None
    if args.gemini:
        settings = load_settings()
        if not settings.gemini_api_key:
            raise RuntimeError("Gemini key is not configured in the selected private environment")
        provider = GeminiPlanProvider(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.ai_timeout_seconds,
        )
        try:
            live_interpretation = await provider.interpret_graph(forecast)
        finally:
            await provider.aclose()

    print(
        json.dumps(
            {
                "forecast_status": forecast["status"],
                "traffic_nodes": len(forecast["forecasts"]),
                "input_readings": len(forecast["input_reading_ids"]),
                "forecast_tick": forecast["forecast_tick"],
                "units": {item["name"]: item["unit"] for item in forecast["features"]},
                "brain_interpreter_handoff": "passed",
                "gemini_live_call": "passed" if live_interpretation is not None else "not_requested",
                "gemini_interpretation": live_interpretation,
                "forecast_used_for_actions": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())

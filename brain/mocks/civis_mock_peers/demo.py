"""Debug-only detector for the shared action pipeline, separate from member code."""

from civis_brain.contracts import DetectionResult, Incident, Observation


class DemoSignalScenario:
    scenario_id = "S01"

    def detect(self, batch, nodes, policy, state):
        assert policy.get("fixture_only") is True
        observations, incidents, warnings = [], [], []
        for row in batch.readings:
            usable = (
                row.sensor == "congestion_index"
                and row.channel is None
                and row.unit == "percent"
                and row.value is not None
                and 0 <= row.value <= 100
            )
            observations.append(Observation(reading=row, domains=["traffic"], usable=usable))
            if not usable:
                warnings.append("DEMO_EVIDENCE_INVALID: expected congestion_index, percent, 0..100")
            elif row.value >= policy["threshold_min"]:
                incidents.append(
                    Incident(
                        incident_id="demo-congestion-" + row.node_id,
                        kind="congestion",
                        run_id=batch.run_id,
                        domains=["traffic"],
                        node_ids=[row.node_id],
                        source_reading_ids=[row.reading_id],
                        facts={
                            "fixture_only": True,
                            "congestion_index": row.value,
                            "mock_threshold": policy["threshold_min"],
                        },
                    )
                )
        return DetectionResult(observations=observations, incidents=incidents, warnings=warnings)

    async def draft_plan(self, context, provider):
        return await provider.generate(context)

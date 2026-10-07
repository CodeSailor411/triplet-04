"""Reserved integration harness. Elyes implements it after reviewing scenario PRs."""

from pathlib import Path

from civis_brain.contracts import DecisionBatch, ReadingsBatch
from civis_brain.ports import PlanProvider, ToolPeer


class BrainRuntime:
    async def evaluate_tick(self, batch: ReadingsBatch) -> DecisionBatch:
        raise NotImplementedError("Elyes: compose the five scenario modules and shared trust flow")


def build_runtime(
    *, twin: ToolPeer, guardian: ToolPeer, provider: PlanProvider,
    policies: dict[str, dict], features: dict, artifact_dir: Path | None = None,
) -> BrainRuntime:
    raise NotImplementedError("Elyes: implement shared runtime factory; see docs/mock-team/CONTRACT.md")

from civis_brain.contracts import DecisionBatch, ReadingsBatch


async def evaluate_tick(batch: ReadingsBatch) -> DecisionBatch:
    """Elyes: compose the assigned modules, validate proposals, and request guarded actions."""
    raise NotImplementedError("Elyes: integrate modules; see docs/mock-team/ELYES.md")

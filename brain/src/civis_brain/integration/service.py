from civis_brain.contracts import DecisionBatch, ReadingsBatch
from civis_brain.errors import BrainError
from civis_brain.integration.runtime import BrainRuntime

_runtime: BrainRuntime | None = None


def bind_runtime(runtime: BrainRuntime) -> None:
    global _runtime
    _runtime = runtime


async def evaluate_tick(batch: ReadingsBatch) -> DecisionBatch:
    if _runtime is None:
        raise BrainError("RUNTIME_UNCONFIGURED", "Bind a shared runtime before evaluating")
    return await _runtime.evaluate_tick(batch)

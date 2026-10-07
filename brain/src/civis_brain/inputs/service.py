from civis_brain.contracts import Node, ReadingsBatch


def normalize_batch(batch: ReadingsBatch, nodes: list[Node]) -> ReadingsBatch:
    """Elyes: validate shared batch semantics before calling scenario detectors."""
    raise NotImplementedError("Elyes: shared normalization; see docs/mock-team/ELYES.md")

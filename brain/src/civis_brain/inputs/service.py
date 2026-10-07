from civis_brain.contracts import DetectionResult, Node, ReadingsBatch


def analyze_batch(batch: ReadingsBatch, nodes: list[Node], policy: dict, state: dict) -> DetectionResult:
    """Yassine: normalize readings and find incidents using the frozen task card."""
    raise NotImplementedError("Yassine: implement analyze_batch; see docs/mock-team/YASSINE.md")

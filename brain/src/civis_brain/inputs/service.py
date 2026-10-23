from datetime import datetime, timezone

from civis_brain.contracts import Node, ReadingsBatch


def utc_time(value: str) -> datetime:
    if not isinstance(value, str) or "T" not in value or not value.endswith("Z"):
        raise ValueError("Timestamp must use UTC RFC 3339 with Z")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError("Timestamp must be valid UTC RFC 3339") from None
    if result.tzinfo is None or result.utcoffset() != timezone.utc.utcoffset(result):
        raise ValueError("Timestamp must include the UTC offset")
    return result


def normalize_batch(batch: ReadingsBatch, nodes: list[Node]) -> ReadingsBatch:
    """Validate semantics without filling missing data or changing original evidence."""
    if len(batch.readings) > 2000 or len(nodes) > 2000:
        raise ValueError("Mock batch or node limit exceeded")
    current_time = utc_time(batch.time)
    node_ids = {node.node_id for node in nodes}
    if len(node_ids) != len(nodes):
        raise ValueError("Node discovery contains duplicate IDs")
    if batch.count != len(batch.readings):
        raise ValueError("Batch count does not match readings")
    ids = set()
    devices = set()
    for reading in batch.readings:
        if reading.run_id != batch.run_id or reading.tick != batch.tick:
            raise ValueError("Reading run/tick does not match batch")
        if reading.node_id not in node_ids:
            raise ValueError("Reading references an unknown node")
        if reading.reading_id in ids:
            raise ValueError("Duplicate reading ID")
        key = (reading.device_id, reading.sensor, reading.channel)
        if key in devices:
            raise ValueError("Duplicate device/sensor/channel in the same tick")
        ids.add(reading.reading_id)
        devices.add(key)
        # Twin applies small device timestamp wobble. Do not require exact equality.
        if abs((utc_time(reading.timestamp) - current_time).total_seconds()) > batch.tick_seconds:
            raise ValueError("Reading timestamp is outside the current tick window")
    return batch

"""Bounded evidence recovery. Corroboration never replaces Guardian permission."""

import asyncio

from civis_brain.contracts import ReadingsBatch
from civis_brain.errors import BrainError
from civis_brain.inputs.service import normalize_batch


async def recover(runtime, batch, ids, nodes):
    """Three steps within 10 real seconds, including the final Guardian call."""
    original = [runtime.ledger[source] for source in ids]
    original_channels = {(r.sensor, r.channel, r.unit) for r in original}
    original_devices = {(r.node_id, r.device_id, r.sensor, r.channel, r.unit) for r in original}
    neighbour_ids = {n for node in nodes if node.node_id in {r.node_id for r in original}
                     for n in node.neighbours}

    def validate(raw):
        current = raw if isinstance(raw, ReadingsBatch) else ReadingsBatch.model_validate(raw)
        normalize_batch(current, nodes)
        runtime._validate_clock(batch, current.model_dump(exclude={"readings", "count"}))
        return current

    def usable(row):
        return (row.value is not None and row.device_id not in runtime.blocked_devices
                and row.reading_id not in runtime.invalid_ids)

    async def latest():
        if runtime.feed_connected is False:
            raise BrainError("FEED_DISCONNECTED", "Evidence recovery lost the Twin feed")
        if runtime.feed_connected is True and runtime.latest_feed is not None:
            return validate(runtime.latest_feed)
        return validate(await runtime._call(runtime.twin, "get_readings", {}))

    try:
        async with asyncio.timeout(10):
            # Step 1: only advertised neighbours with matching sensor/channel/unit.
            snapshot = await latest()
            neighbours = [r for r in snapshot.readings if r.node_id in neighbour_ids
                          and (r.sensor, r.channel, r.unit) in original_channels and usable(r)]
            runtime.journal.append({"event": "recovery_neighbours", "run_id": batch.run_id,
                                    "tick": snapshot.tick,
                                    "source_reading_ids": [r.reading_id for r in neighbours]})
            # Step 2: wait for one later simulated tick, at most 3 real seconds.
            # SSE reception continues in its own task. Manual-driver mode uses bounded
            # one-off reads, never a replacement background polling scheduler.
            try:
                async with asyncio.timeout(3):
                    while snapshot.tick <= batch.tick:
                        await asyncio.sleep(.05)
                        snapshot = await latest()
            except TimeoutError:
                raise BrainError("RECOVERY_NEXT_TICK_TIMEOUT", "No later sensor tick within 3 real seconds") from None
            later = [r for r in snapshot.readings
                     if (r.node_id, r.device_id, r.sensor, r.channel, r.unit) in original_devices
                     and usable(r)]
            if {(r.node_id, r.device_id, r.sensor, r.channel, r.unit) for r in later} != original_devices:
                raise BrainError("RECOVERY_EVIDENCE_MISSING", "Later tick lacks usable evidence from the same sensors")
            runtime.journal.append({"event": "recovery_later_tick", "run_id": batch.run_id,
                                    "tick": snapshot.tick,
                                    "source_reading_ids": [r.reading_id for r in later]})
            # Preserve current observations for stale-plan withdrawal even with a
            # manual driver. They cannot authorize a command or erase old evidence.
            runtime.latest_feed = snapshot
            readings = {r.reading_id: r for r in [*original, *neighbours, *later]}
            if not runtime._eligible(ids):
                raise BrainError("EVIDENCE_INVALIDATED", "Original evidence was invalidated during recovery")
            # Step 3: fresh Guardian assessment of original AND supporting evidence.
            response = await runtime._call(runtime.guardian,
                runtime.features.get("guardian_score_tool"),
                {"run_id": batch.run_id, "tick": snapshot.tick,
                 "readings": [r.model_dump() for r in readings.values()]})
            runtime.journal.append({"event": "recovery_fresh_verdict", "run_id": batch.run_id,
                                    "tick": snapshot.tick, "source_reading_ids": list(readings)})
            return response, set(readings)
    except TimeoutError:
        raise BrainError("RECOVERY_TIMEOUT", "Evidence recovery exceeded 10 real seconds") from None

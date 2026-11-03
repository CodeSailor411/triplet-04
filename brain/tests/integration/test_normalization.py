import copy

import pytest

from civis_brain.contracts import Node, ReadingsBatch
from civis_brain.inputs.service import normalize_batch

from .helpers import make_case


@pytest.mark.parametrize("mutation", ["count", "run", "tick", "unknown", "duplicate", "time"])
def test_malformed_batch(mutation):
    case = make_case()
    raw = copy.deepcopy(case["batches"][0])
    if mutation == "count":
        raw["count"] = 0
    elif mutation == "run":
        raw["readings"][0]["run_id"] = "other-run"
    elif mutation == "tick":
        raw["readings"][0]["tick"] = 2
    elif mutation == "unknown":
        raw["readings"][0]["node_id"] = "unknown"
    elif mutation == "duplicate":
        raw["readings"].append(copy.deepcopy(raw["readings"][0]))
        raw["count"] = 2
    else:
        raw["readings"][0]["timestamp"] = "2026-10-08T08:00:05.000Z"
    with pytest.raises(ValueError):
        normalize_batch(ReadingsBatch.model_validate(raw), [Node.model_validate(case["nodes"][0])])


def test_null_and_device_timestamp_wobble_are_preserved():
    case = make_case()
    raw = case["batches"][0]
    raw["readings"][0].update(value=None, timestamp="2026-10-08T08:00:00.950Z")
    batch = ReadingsBatch.model_validate(raw)
    assert normalize_batch(batch, [Node.model_validate(case["nodes"][0])]) is batch
    assert batch.readings[0].value is None

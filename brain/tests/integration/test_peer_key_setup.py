import runpy
from pathlib import Path

import pytest


def setup():
    script = Path(__file__).resolve().parents[2] / "scripts/setup_peer_keys.py"
    return runpy.run_path(str(script))["initialize_caller_keys"]


def test_caller_keys_are_distinct_and_existing_secrets_are_preserved(tmp_path):
    path = tmp_path / ".env"
    path.write_text("GEMINI_API_KEY=existing-test-value\n"
                    "BRAIN_TWIN_CALLER_KEY=dev-twin-to-brain\n", encoding="utf-8")
    initialize = setup()
    assert len(initialize(path)) == 3
    first = path.read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in first.splitlines())
    callers = [v for k, v in values.items() if k.startswith("BRAIN_")]
    assert len(set(callers)) == 3 and all(len(v) >= 32 for v in callers)
    assert values["GEMINI_API_KEY"] == "existing-test-value"
    assert initialize(path) == []
    assert path.read_text(encoding="utf-8") == first


def test_ambiguous_env_is_not_modified(tmp_path):
    path = tmp_path / ".env"
    original = "BRAIN_TWIN_CALLER_KEY=one\nBRAIN_TWIN_CALLER_KEY=two\n"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate caller key"):
        setup()(path)
    assert path.read_text(encoding="utf-8") == original

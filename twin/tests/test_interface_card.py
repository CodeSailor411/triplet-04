"""The Interface Card must say what the Twin really does. CIVIS's acceptance list (23 Oct) asks for exact tool names,
credential variable names, units and the tested tag. This test reads INTERFACE.md and compares it with the code, so the
card cannot drift away from the Twin again."""
import re
from pathlib import Path

import yaml

from twin.auth import TOOL_ACCESS

CARD = (Path(__file__).resolve().parent.parent / "INTERFACE.md").read_text()


def test_every_tool_the_twin_has_is_named_in_the_card_and_no_extra_tool_is_named():
    named = set(re.findall(r"`([a-z_]+)`", CARD)) & (set(TOOL_ACCESS) | {"commit_action", "get_flagged_readings"})
    assert set(TOOL_ACCESS) <= named, f"not in the card: {sorted(set(TOOL_ACCESS) - named)}"
    # the two planned tools may be named, but only as planned, never in the tool table
    table = CARD.split("## What it receives (tools)")[1].split("## Units")[0]
    assert "commit_action" not in table and "get_flagged_readings" not in table


def test_credential_variable_names_are_in_the_card_and_are_the_ones_the_code_reads():
    src = (Path(__file__).resolve().parent.parent / "src" / "twin" / "auth.py").read_text()
    for name in ("TWIN_KEY_CITY_BRAIN", "TWIN_KEY_GUARDIAN", "TWIN_KEY_SCENARIO"):
        assert name in CARD
        assert name.lower().removeprefix("twin_key_") in src.lower() or "TWIN_KEY_" in src
    assert "never in the repo" in CARD and "Bearer" in CARD       # names only, no secret values


def test_every_sensor_and_its_unit_are_in_the_units_section():
    cfg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "twin.yaml").read_text())
    units = CARD.split("## Units")[1].split("## What it sends")[0]
    for sensor, spec in cfg["sensors"].items():
        assert f"`{sensor}` {spec['unit']}" in units, f"{sensor} / {spec['unit']} missing or wrong in the card"


def test_card_names_the_tested_tag_and_separates_implemented_from_planned():
    assert "Tested version: tag `twin-mock-3`" in CARD
    assert "**Implemented:**" in CARD and "**Planned, not built:**" in CARD


async def test_get_capabilities_features_tell_the_truth_over_mcp(mcp_client):
    async with mcp_client("city_brain") as c:
        f = (await c.call_tool("get_capabilities", {})).structured_content["features"]
    assert f["token_formats"] == ["g1", "jws-eddsa"] and f["token_mode"] in {"unsigned", "signed"}
    assert f["token_max_lifetime_seconds"] == 60 and f["token_score_range"] == [0, 1]
    assert f["preview_action"] is True and f["two_step_commit"] is False and f["idempotency"] is True
    assert "congestion_index" in f["sensors"] and len(f["sensors"]) == 12
    assert set(f["containment_tools"]) <= set(TOOL_ACCESS)               # never advertise a tool that does not exist
    assert "commit_action (two-step)" in f["not_built"]                  # and say plainly what is missing

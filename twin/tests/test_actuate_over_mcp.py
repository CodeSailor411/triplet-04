"""actuate and list_actions through the real Twin, as a partner would call them."""
import itertools

import pytest

from twin.tokens import make_token

_n = itertools.count(1)


def token_for(action, targets, params, **over):
    c = {"iss": "guardian", "aud": "twin", "jti": f"mcp-tk-{next(_n)}", "run_id": "run-42-001",
         "iat": "2026-10-05T08:00:00.000Z", "exp": "2026-10-05T08:05:00.000Z",
         "action": action, "targets": targets, "params": params, "score": 0.9}
    c.update(over)
    return make_token(c)


async def call(c, targets, params, action="set_valve_position", token="auto", key=None):
    return await c.call_tool("actuate", {
        "action": action, "targets": targets, "params": params, "idempotency_key": key or f"mcp-key-{next(_n)}",
        **({"token": token_for(action, targets, params) if token == "auto" else token} if token != "omit" else {})})


async def test_only_the_brain_may_actuate(mcp_client):
    for who in ("guardian", "scenario", None):
        async with mcp_client(who) as c:
            r = await call(c, ["WAT-01"], {"position": 10})
        assert r.is_error
        assert ("UNAUTHENTICATED" if who is None else "FORBIDDEN") in r.content[0].text


async def test_list_actions_for_both_layers(mcp_client):
    for who in ("city_brain", "guardian"):
        async with mcp_client(who) as c:
            data = (await c.call_tool("list_actions", {})).structured_content
        assert {a["action"] for a in data["actions"]} == {"set_signal_plan", "set_valve_position", "set_grid_switch", "dispatch"}
        assert data["token_mode"] == "unsigned"


async def test_commit_then_exact_retry_gives_the_same_answer(mcp_client):
    async with mcp_client("city_brain") as c:
        first = (await call(c, ["WAT-03"], {"position": 25}, key="mcp-retry")).structured_content
        again = (await call(c, ["WAT-03"], {"position": 25}, key="mcp-retry")).structured_content
        changed = (await call(c, ["WAT-03"], {"position": 26}, key="mcp-retry")).structured_content
    assert first["status"] == "committed" and first["action_id"].startswith("ac-") and first["run_id"] == "run-42-001"
    assert again["replayed"] is True and again["action_id"] == first["action_id"]
    assert changed["status"] == "rejected" and changed["code"] == "IDEMPOTENCY_CONFLICT"


async def test_cap_exceeded_arrives_as_structured_fields(mcp_client):
    async with mcp_client("city_brain") as c:
        r = await call(c, ["WAT-01", "WAT-03", "SH-03"], {"position": 5})
    assert not r.is_error                                    # a refusal is a normal answer, not a failed call
    d = r.structured_content
    assert d["status"] == "rejected" and d["code"] == "CAP_EXCEEDED"
    assert {k: d["details"][k] for k in ("domain", "cap", "in_use", "requested", "remaining")} == \
           {"domain": "water", "cap": 2, "in_use": 0, "requested": 3, "remaining": 2}


async def test_missing_token_and_bad_input(mcp_client):
    async with mcp_client("city_brain") as c:
        no_token = (await call(c, ["WAT-01"], {"position": 5}, token="omit")).structured_content
        bad_param = await call(c, ["WAT-01"], {"position": 500})
        bad_action = await call(c, ["WAT-01"], {}, action="self_destruct")
        bad_node = await call(c, ["NOPE-1"], {"position": 5})
    assert no_token["status"] == "rejected" and no_token["code"] == "TOKEN_MISSING"
    assert bad_param.is_error and "INVALID_PARAMS" in bad_param.content[0].text and "at most 100" in bad_param.content[0].text
    assert bad_action.is_error and "UNKNOWN_ACTION" in bad_action.content[0].text and "set_valve_position" in bad_action.content[0].text
    assert bad_node.is_error and "UNKNOWN_NODE" in bad_node.content[0].text


async def test_nothing_secret_in_the_new_tools(mcp_client):
    import json
    async with mcp_client("guardian") as c:
        text = json.dumps([t.model_dump(mode="json") for t in (await c.list_tools()).tools]) + \
               (await c.call_tool("list_actions", {})).content[0].text
    for forbidden in ("truth", "bias", "noise", "private", "secret"):
        assert forbidden not in text.lower()

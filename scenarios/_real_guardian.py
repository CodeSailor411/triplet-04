"""Helper for T5 and T8 with --layers real: ask the REAL Guardian for a token, the way the Brain does.

Not a scenario: do not run this file. It is imported by the T5 and T8 scripts.

What it does
  1. waits a few seconds after the reset, so the Twin has made readings (and the Guardian can receive them)
  2. picks one reading of TRF-01 from the Twin (the oldest one it gets, because the Guardian scores slower than the Twin)
  3. calls the Guardian's MCP tool `authorize_action` until it answers "approved" with a token, or the time is up
Nothing is hard-coded: the Guardian's address comes from --guardian-url, then GUARDIAN_URL, then http://127.0.0.1:5000.
The key is GUARDIAN_BRAIN_MCP_BEARER_KEY, from the environment or from the .env file in the repo root (the one
docker compose reads). A key is never printed.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import _kit as kit
from mock_common import MockError, TwinClient      # a plain MCP client: it only needs an address and a key

NODE, SENSOR = "TRF-01", "congestion_index"
ACTION, DOMAIN, RISK = "set_signal_plan", "Traffic", "R1"


def add_args(ap):
    ap.add_argument("--guardian-url", help="where the real Guardian runs (default: GUARDIAN_URL, then http://127.0.0.1:5000)")
    ap.add_argument("--warmup", type=float, default=10,
                    help="real mode: seconds to wait after the reset so the Twin has made readings (default 10)")
    ap.add_argument("--guardian-wait", type=float, default=120,
                    help="real mode: seconds to wait for the real Guardian to issue a token. It scores slower than the Twin (default 120)")


def _dotenv(name: str) -> str | None:
    try:
        lines = (kit.ROOT / ".env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return None


def guardian_url(args) -> str:
    return (args.guardian_url or os.environ.get("GUARDIAN_URL") or "http://127.0.0.1:5000").rstrip("/")


def guardian_key() -> str:
    name = "GUARDIAN_BRAIN_MCP_BEARER_KEY"
    value = os.environ.get(name) or _dotenv(name)
    if not value:
        kit.setup_exit(f"No key for the Guardian. Set {name} in the environment or in the .env file in the repo root.")
    return value


def guardian_call(url: str, key: str, tool: str, args: dict) -> dict:
    """One MCP call to the real Guardian. Returns the answer as a dict. A failed call raises MockError."""
    async def go():
        try:
            async with TwinClient(url, key) as g:
                result = await g._client.call_tool(tool, args)
        except MockError as exc:
            raise MockError(str(exc).replace("the Twin", "the Guardian")) from None
        text = " ".join(getattr(c, "text", "") or "" for c in (result.content or []))
        if result.is_error:
            raise MockError(f"{tool} failed: {text or 'no message'}")
        out = result.structured_content
        if not out:                                         # some replies come as plain text that holds JSON
            for c in result.content or []:
                try:
                    out = json.loads(getattr(c, "text", "") or "")
                    break
                except ValueError:
                    continue
        if isinstance(out, dict) and set(out) == {"result"} and isinstance(out["result"], dict):
            out = out["result"]
        return out or {}
    return asyncio.run(go())


def _readings(obj):
    """Every dict with a reading_id, wherever it sits in the Twin's answer."""
    if isinstance(obj, dict):
        if "reading_id" in obj:
            yield obj
        for v in obj.values():
            yield from _readings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _readings(v)


def pick_reading(run) -> str:
    """Wait a little, then take the oldest reading the Twin gives for TRF-01. (The Guardian scores slower than the Twin,
    so a newer reading would not be scored yet.)"""
    run.wait(run.args.warmup, "so the Twin has made some readings")
    try:
        found = list(_readings(run.call("city_brain", "get_readings", {"node_id": NODE, "sensor": SENSOR})))
    except MockError as exc:
        kit.setup_exit(f"Could not read {NODE} from the Twin: {exc}")
    if not found:
        kit.setup_exit(f"The Twin gave no readings for {NODE} {SENSOR}.")
    pick = min(found, key=lambda r: r["tick"] if isinstance(r.get("tick"), (int, float)) else 0)
    print(f"  using reading {pick['reading_id']} (tick {pick.get('tick')}) of {NODE}")
    return pick["reading_id"]


def ask_token(run, reading_id: str, idempotency_key: str) -> tuple[str | None, str]:
    """Ask the real Guardian for a token for set_signal_plan {"plan": "normal"} on TRF-01.
    Returns (token, why). The token is None when the Guardian gave none in time; `why` then says what it last said."""
    url, key = guardian_url(run.args), guardian_key()
    body = {"run_id": run.run_id, "reading_ids": [reading_id], "action": ACTION, "targets": [NODE],
            "params": {"plan": "normal"}, "risk_level": RISK, "domain": DOMAIN, "idempotency_key": idempotency_key}
    deadline, last, seen = time.time() + run.args.guardian_wait, "no answer", set()
    print(f"  asking the real Guardian at {url} for a token (up to {run.args.guardian_wait:g} s)", flush=True)
    while True:
        try:
            reply = guardian_call(url, key, "authorize_action", body)
            if reply.get("decision") == "approved" and reply.get("token"):
                print(f"  real Guardian approved: token id {reply.get('token_id')}")
                return reply["token"], "approved"
            shown = {k: v for k, v in reply.items() if k != "token"}
            last = f"answer without a token: {json.dumps(shown)[:250]}"
        except MockError as exc:
            last = f"error: {str(exc)[:250]}"
        if last not in seen:                                  # print each different answer once
            print(f"  Guardian said: {last}")
            seen.add(last)
        if time.time() >= deadline:
            return None, last
        time.sleep(5)


def no_token(run, why: str):
    """The real Guardian gave no token in time. Save the run as a FAIL so the evidence stays, then stop.
    Nothing happened on the Twin yet, so it has no log file for this run. Ending the run makes it write one."""
    run.close_run = True
    kit.finish(run, {}, lambda events: [(False, f"the real Guardian issued a token (last answer: {why})")])
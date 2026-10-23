"""Bridge configured Twin SSE into the local Guardian API process.

Run with: python .\src\twin_runner.py
Optional one-off MCP call: pass a configured tool name with --tool and JSON arguments.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from brain_client import BrainDeliveryError, VerdictOutbox, brain_config, post_verdict, verdict_payload
from twin_adapter import TwinSSEAdapter, twin_config, twin_mcp_session


def post_event(url: str, key: str, event: dict) -> dict:
    body = json.dumps(event).encode("utf-8")
    req = Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


async def deliver_pending_verdicts(outbox: VerdictOutbox, cfg: dict) -> int:
    delivered = 0
    for payload in outbox.pending():
        try:
            status = await asyncio.to_thread(
                post_verdict,
                payload,
                url=cfg["url"],
                bearer_key=cfg["bearer_key"],
                timeout=cfg["timeout"],
                max_retries=cfg["max_retries"],
                retry_base_seconds=cfg["retry_base_seconds"],
            )
        except BrainDeliveryError as exc:
            print(json.dumps({
                "event": "brain_verdict_delivery_failed",
                "event_id": payload["event_id"],
                "reading_id": payload["reading_id"],
                "error": str(exc),
                "queued_for_retry": True,
            }), file=sys.stderr, flush=True)
            raise
        outbox.mark_delivered(payload["event_id"])
        delivered += 1
        print(json.dumps({
            "event": "brain_verdict_delivered",
            "event_id": payload["event_id"],
            "reading_id": payload["reading_id"],
            "verdict": payload["verdict"],
            "http_status": status,
        }), flush=True)
    return delivered


async def run_stream() -> None:
    cfg = twin_config()
    guardian_url = os.environ.get("GUARDIAN_LOCAL_URL", "http://127.0.0.1:5000").rstrip("/")
    api_key = os.environ.get("GUARDIAN_API_BEARER_KEY", "")
    if not api_key:
        raise RuntimeError("GUARDIAN_API_BEARER_KEY is required to submit validated Twin events")
    brain = brain_config()
    outbox = VerdictOutbox(brain["outbox"]) if brain else None
    if brain:
        pending = await deliver_pending_verdicts(outbox, brain)
        print(json.dumps({"event": "brain_outbox_recovered", "delivered": pending}), flush=True)
    else:
        print("Brain verdict delivery is disabled; set BRAIN_VERDICT_URL and GUARDIAN_BRAIN_BEARER_KEY to enable it.",
              file=sys.stderr, flush=True)
    adapter = TwinSSEAdapter(base_url=cfg["base_url"], bearer_key=cfg["bearer_key"],
        timeout=cfg["timeout"], max_retries=cfg["max_retries"], retry_base_seconds=cfg["retry_base_seconds"])
    async for event in adapter.events():
        if event["event"] != "readings":
            continue
        result = await asyncio.to_thread(post_event, guardian_url + "/api/integrations/twin/event", api_key, event)
        queued = 0
        if outbox is not None:
            for item in result.get("results", []):
                payload = verdict_payload(result["run_id"], item["evaluation"])
                if payload is not None:
                    outbox.enqueue(payload)
                    queued += 1
            delivered = await deliver_pending_verdicts(outbox, brain)
            brain_status = {"enabled": True, "queued": queued, "delivered": delivered,
                            "skipped_without_verdict": result["processed"] - queued}
        else:
            brain_status = {"enabled": False, "skipped_without_verdict": result["processed"]}
        print(json.dumps({"run_id": result["run_id"], "processed": result["processed"],
                          "brain_delivery": brain_status}), flush=True)


async def run_tool(name: str, arguments: dict) -> None:
    cfg = twin_config()
    async with twin_mcp_session(base_url=cfg["base_url"], bearer_key=cfg["bearer_key"], timeout=cfg["timeout"]) as session:
        result = await session.call_tool(name, arguments)
        print(json.dumps(result.model_dump(mode="json"), default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", help="Call one Twin MCP tool instead of consuming the SSE feed")
    parser.add_argument("--arguments", default="{}", help="JSON object of MCP tool arguments")
    args = parser.parse_args()
    try:
        if args.tool:
            arguments = json.loads(args.arguments)
            if not isinstance(arguments, dict):
                raise ValueError("--arguments must decode to a JSON object")
            asyncio.run(run_tool(args.tool, arguments))
        else:
            asyncio.run(run_stream())
    except KeyboardInterrupt:
        pass
    except (RuntimeError, ValueError, URLError, HTTPError) as exc:
        print(f"Guardian/Twin/Brain integration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

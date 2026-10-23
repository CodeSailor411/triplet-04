"""Bounded Twin SSE receiver, independent from the sequential decision worker."""

import asyncio
import contextlib
import json

import httpx
from pydantic import ValidationError

from civis_brain.contracts import ReadingsBatch


class TwinFeed:
    def __init__(self, runtime, url, key, *, queue_size=64):
        self.runtime, self.url, self.key = runtime, url, key
        self.queue = asyncio.Queue(maxsize=queue_size)
        self.tasks = []
        self.closing = False
        self.last = None
        self.status = {"state": "stopped", "received": 0, "evaluated": 0,
                       "dropped": 0, "reconnects": 0, "last_error": None}

    def start(self):
        self.closing = False
        self.tasks = [asyncio.create_task(self.receive()), asyncio.create_task(self.consume())]

    async def close(self):
        self.closing = True
        for task in self.tasks:
            task.cancel()
        for task in self.tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.status["state"] = "stopped"

    def discard_queue(self):
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
            self.status["dropped"] += 1

    def accept(self, event, data):
        # hello/heartbeat.time is wall time, never the simulated authorization clock.
        if event != "readings":
            return
        batch = ReadingsBatch.model_validate(data)
        skipped = data.get("skipped_ticks", 0)
        if type(skipped) is not int or skipped < 0:
            raise ValueError("Invalid skipped_ticks")
        gap = bool(skipped)
        if self.last:
            run, tick = self.last
            if run == batch.run_id:
                if batch.tick <= tick:
                    raise ValueError("Feed tick repeated or reversed")
                gap |= batch.tick != tick + 1
            else:
                self.discard_queue()
                gap = True
        if self.queue.full():
            self.discard_queue()
            gap = True
        self.last = (batch.run_id, batch.tick)
        self.runtime.observe_feed(batch, discontinuity=gap)
        self.queue.put_nowait(batch)
        self.status.update(state="connected", received=self.status["received"] + 1,
                           run_id=batch.run_id, tick=batch.tick, last_error=None)

    async def receive(self):
        while not self.closing:
            try:
                async with httpx.AsyncClient(
                    headers={"Authorization": f"Bearer {self.key}"},
                    timeout=httpx.Timeout(35, connect=3), follow_redirects=False,
                ) as client:
                    async with client.stream("GET", self.url) as response:
                        response.raise_for_status()
                        if "text/event-stream" not in response.headers.get("content-type", ""):
                            raise ValueError("Expected SSE content type")
                        self.runtime.observe_feed(connected=True)
                        self.status["state"] = "connected"
                        event, data, size = "message", [], 0
                        async for line in response.aiter_lines():
                            size += len(line)
                            if size > 2_000_000:
                                raise ValueError("SSE event too large")
                            if not line:
                                if data:
                                    self.accept(event, json.loads("\n".join(data)))
                                event, data, size = "message", [], 0
                            elif line.startswith("event:"):
                                event = line[6:].strip()
                            elif line.startswith("data:"):
                                data.append(line[5:].lstrip(" "))
                self.status["last_error"] = "FEED_ENDED"
            except httpx.HTTPStatusError as error:
                self.status["last_error"] = f"HTTP_{error.response.status_code}"
                if error.response.status_code in {401, 403}:
                    self.runtime.observe_feed(connected=False)
                    self.discard_queue()
                    self.status["state"] = "authentication_failed"
                    return
            except (httpx.HTTPError, ValueError, ValidationError):
                self.status["last_error"] = "FEED_UNAVAILABLE_OR_INVALID"
            self.runtime.observe_feed(connected=False)
            self.discard_queue()
            self.last = None
            self.status["state"] = "reconnecting"
            self.status["reconnects"] += 1
            await asyncio.sleep(1)

    async def consume(self):
        while not self.closing:
            batch = await self.queue.get()
            try:
                result = await self.runtime.evaluate_tick(batch)
                self.status["evaluated"] += 1
                self.status["last_decisions"] = [
                    {"status": row.status, "code": row.peer_code} for row in result.decisions
                ]
            except Exception:
                self.status.update(state="processor_failed", last_error="PROCESSOR_FAILED")
                self.runtime.observe_feed(connected=False)
                for task in self.tasks:
                    if task is not asyncio.current_task():
                        task.cancel()
                return
            finally:
                self.queue.task_done()

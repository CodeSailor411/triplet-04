"""Mock City Brain: a thin, scripted stand-in made by the Twin team (rule R1). It is NOT CIVIS's Brain.

It follows one fixed script, with no AI and no real decision-making:
  1. (watch) read a traffic sensor on the Twin every fraction of a second;
  2. (trigger) if the congestion index is at or above the threshold (default 80 %) on N ticks in a row (default 2),
     that is "a jam". The 80 % and the two ticks are the Brain team's S01 numbers, copied so the story matches theirs;
  3. (ask) ask the mock Guardian for a permission token for exactly one action (set_signal_plan on that node);
     for an action that needs a preview (valve, grid switch) it previews first, like the Twin demands;
  4. (act) send `actuate` with that token and an idempotency key. If Guardian refuses, is silent, or the preview says
     "no", the mock Brain does NOT act, and says why.
It can also send the same request twice with the same key, to show the Twin carries it out only once.

IMPORTANT, say it in the demo: the Twin cannot make a REAL incident yet, only a fake reading (`run_scenario`). So the
jam here is a lie told by a sensor, and this mock acts on it. The real Guardian is what is supposed to distrust that.

Run log: it writes <run_id>.brain.jsonl (decision, partner_failure, escalation events, all marked stand_in), and the mock
Guardian writes <run_id>.guardian.jsonl. Next to the Twin's own part file they give the dashboard a full chain: reading
(Twin) -> verdict (Guardian) -> decision (Brain) -> action (Twin). The commands write the logs by default (--no-log turns
them off, --log-dir changes the folder). Library use: pass log=PartLog("brain").

Commands (start the Twin first: `python -m twin`):

    python mocks/mock_brain.py incident                  # waits up to 60 s for a jam; a calm Twin gives "no_incident"
    python mocks/mock_brain.py incident --fake-jam       # starts the fake jam itself (needs the scenario key)
    python mocks/mock_brain.py incident --fake-jam --guardian-mode refuse     # Guardian says no: nothing is sent
    python mocks/mock_brain.py incident --fake-jam --guardian-mode silent     # Guardian never answers: timeout
    python mocks/mock_brain.py act --action set_signal_plan --targets TRF-01 --params '{"plan":"favor_main_road"}'
    python mocks/mock_brain.py act ... --sends 2         # same request twice, same key: the second is a replay

Keys: --key, or TWIN_KEY_CITY_BRAIN / TWIN_KEY_GUARDIAN / TWIN_KEY_SCENARIO, or twin/.env. Address: --url or config.
"""
import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_common import MockError, PartLog, TwinClient, key_for, twin_url                 # noqa: E402
from mock_guardian import MODES, MockGuardian                                            # noqa: E402

GUARDIAN_TIMEOUT_SECONDS = 3.0       # the Brain team's page: a peer call gets 3 real seconds
JAM_THRESHOLD = 80.0                 # S01 of the Brain team: congestion index at or above 80 %
JAM_TICKS = 2                        # ... on two ticks in a row
JAM_ACTION, JAM_PARAMS = "set_signal_plan", {"plan": "favor_main_road"}


class MockBrain:
    def __init__(self, twin: TwinClient, guardian: MockGuardian, guardian_timeout: float = GUARDIAN_TIMEOUT_SECONDS,
                 log: PartLog | None = None):
        self.twin, self.guardian, self.guardian_timeout, self.log = twin, guardian, guardian_timeout, log

    async def _log(self, event_type: str, data: dict, caused_by: list[str | None] | None = None) -> str | None:
        """Write one event of the Brain's run log (stamped with the Twin's clock). No log set: nothing happens."""
        if self.log is None:
            return None
        return self.log.write(await self.twin.call("get_clock"), event_type, data, [c for c in (caused_by or []) if c])

    async def _decision(self, incident: str, action: str | None, key: str | None, reason: str | None,
                        caused_by: list[str | None] | None) -> str | None:
        data = {"incident": incident, "chosen_action": action}
        if action and key:
            data["idempotency_key"] = key               # the Twin's action event carries the same key: that joins them
        if reason:
            data["reason"] = reason
        return await self._log("decision", data, caused_by)

    async def _gave_up(self, incident: str, reason: str, caused_by: list[str | None] | None) -> None:
        """No action will be sent: say why (decision with no action) and hand it to a person (escalation)."""
        decision = await self._decision(incident, None, None, reason, caused_by)
        await self._log("escalation", {"incident": incident, "reason": f"{reason}. A person must check: {incident}."},
                        [decision])

    async def act(self, action: str, targets: list[str], params: dict, idempotency_key: str | None = None,
                  sends: int = 1, incident: str | None = None, reading_ids: list[str] | None = None,
                  device_id: str | None = None) -> dict:
        """Preview if needed, get a token, then actuate. `sends` > 1 repeats the SAME request with the SAME key.
        `incident`, `reading_ids` and `device_id` only describe WHY (for the token and the run log)."""
        key = idempotency_key or f"mock-brain-{uuid.uuid4().hex[:10]}"
        what = incident or f"{action} on {', '.join(targets)}"
        needs_preview = any(a["action"] == action and a["preview_required"]
                            for a in (await self.twin.call("list_actions"))["actions"])
        if needs_preview:
            preview = await self.twin.call("preview_action", {"action": action, "targets": targets, "params": params})
            if not preview["would_pass_checks"]:
                await self._gave_up(what, f"The Twin's preview says it would be refused ({', '.join(preview['blocked_by'])})", None)
                return {"outcome": "not_sent", "reason": "PREVIEW_BLOCKED", "blocked_by": preview["blocked_by"]}
        try:
            verdict = await asyncio.wait_for(
                self.guardian.authorize(action, targets, params, key, reading_ids=reading_ids, device_id=device_id),
                self.guardian_timeout)
        except asyncio.TimeoutError:
            failure = await self._log("partner_failure", {"partner": "guardian", "handled": "no action was sent",
                                                          "failure": f"no answer within {self.guardian_timeout:g} s"})
            await self._gave_up(what, "Guardian did not answer", [failure])
            return {"outcome": "not_sent", "reason": "GUARDIAN_TIMEOUT", "waited_seconds": self.guardian_timeout}
        if verdict["decision"] != "approved":
            await self._gave_up(what, "Guardian refused", [verdict.get("event_id")])
            return {"outcome": "not_sent", "reason": "GUARDIAN_REFUSED", "refusal_code": verdict.get("refusal_code")}
        await self._decision(what, action, key, None, [verdict.get("event_id")])
        answers = [await self.twin.call("actuate", {"action": action, "targets": targets, "params": params,
                                                    "token": verdict["token"], "idempotency_key": key})
                   for _ in range(max(1, sends))]
        return {"outcome": answers[0]["status"], "idempotency_key": key, "token_id": verdict["token_id"],
                "token_format": verdict["token_format"], "twin_answers": answers}

    async def watch_for_jam(self, node_id: str, threshold: float = JAM_THRESHOLD, ticks: int = JAM_TICKS,
                            wait_seconds: float = 60.0, poll_seconds: float = 0.2) -> dict:
        """Poll the node's congestion index until it is >= threshold on `ticks` consecutive ticks, or time runs out.
        A tick the poll missed breaks the run of ticks (we only count what we really saw)."""
        deadline = time.monotonic() + wait_seconds
        last_tick, run, seen = None, 0, []
        while time.monotonic() < deadline:
            batch = await self.twin.call("get_readings", {"node_id": node_id, "sensor": "congestion_index"})
            tick = batch["tick"]
            reading = batch["readings"][0] if batch["readings"] else {}
            value = reading.get("value")
            if tick != last_tick:
                hot = value is not None and value >= threshold
                if not hot:
                    run = 0                                     # a calm tick (or no value) ends the run
                elif last_tick is not None and tick != last_tick + 1:
                    run = 1                                     # we missed a tick: start counting again from here
                else:
                    run += 1
                seen.append({"tick": tick, "value": value, "reading_id": reading.get("reading_id")})
                last_tick = tick
                if run >= ticks:
                    return {"jam": True, "node_id": node_id, "evidence": seen[-ticks:]}
            await asyncio.sleep(poll_seconds)
        return {"jam": False, "node_id": node_id, "ticks_seen": len(seen)}

    async def incident(self, node_id: str | None = None, threshold: float = JAM_THRESHOLD, ticks: int = JAM_TICKS,
                       wait_seconds: float = 60.0, poll_seconds: float = 0.2,
                       scenario: TwinClient | None = None, fake_value: float = 95.0) -> dict:
        """The scripted S01 story. With `scenario` (a Twin client that holds the scenario key) it starts the fake jam."""
        if node_id is None:
            carriers = next(a for a in (await self.twin.call("list_actions"))["actions"] if a["action"] == JAM_ACTION)
            node_id = carriers["target_nodes"][0]
        started = None
        if scenario is not None:
            started = await scenario.call("run_scenario", {"name": "fake_reading", "params": {
                "device_id": f"{node_id}.congestion_index", "value": fake_value, "delay_ticks": 2}})
        try:
            seen = await self.watch_for_jam(node_id, threshold, ticks, wait_seconds, poll_seconds)
            if not seen["jam"]:
                return {"outcome": "no_incident", **seen}
            latest = seen["evidence"][-1].get("reading_id")
            result = await self.act(JAM_ACTION, [node_id], JAM_PARAMS, incident=f"traffic jam at {node_id}",
                                    reading_ids=[latest] if latest else None, device_id=f"{node_id}.congestion_index")
            return {**result, "trigger": "fake reading started by this script" if started else "readings from the feed",
                    "evidence": seen["evidence"]}
        finally:
            if started is not None:                     # leave the Twin clean: stop the fake jam we started
                await scenario.call("run_scenario", {"name": "stop", "params": {"scenario_id": started["scenario_id"]}})


async def _run(args: argparse.Namespace) -> dict:
    url = twin_url(args.url)
    async with TwinClient(url, key_for("city_brain", args.key)) as brain_twin, \
            TwinClient(url, key_for("guardian", args.guardian_key)) as guardian_twin:
        guardian = MockGuardian(guardian_twin, mode=args.guardian_mode, private_key=args.private_key,
                                slow_seconds=args.slow_seconds,
                                log=None if args.no_log else PartLog("guardian", args.log_dir))
        brain = MockBrain(brain_twin, guardian, args.guardian_timeout,
                          log=None if args.no_log else PartLog("brain", args.log_dir))
        if args.cmd == "act":
            return await brain.act(args.action, args.targets.split(","), json.loads(args.params),
                                   args.idempotency_key, args.sends)
        if args.fake_jam:
            async with TwinClient(url, key_for("scenario", args.scenario_key)) as scenario:
                return await brain.incident(args.node, args.threshold, args.ticks, args.wait_seconds, scenario=scenario)
        return await brain.incident(args.node, args.threshold, args.ticks, args.wait_seconds)


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)             # options every command accepts, written AFTER the command
    common.add_argument("--url", help="where the Twin runs (default: TWIN_URL, then config/twin.yaml)")
    common.add_argument("--key", help="the Brain key (default: TWIN_KEY_CITY_BRAIN from the environment or twin/.env)")
    common.add_argument("--guardian-key", help="the Guardian key (default: TWIN_KEY_GUARDIAN)")
    common.add_argument("--scenario-key", help="the scenario key (default: TWIN_KEY_SCENARIO), only for --fake-jam")
    common.add_argument("--guardian-mode", default="approve", choices=MODES, help="how the mock Guardian behaves")
    common.add_argument("--guardian-timeout", type=float, default=GUARDIAN_TIMEOUT_SECONDS,
                        help="real seconds the Brain waits for Guardian")
    common.add_argument("--slow-seconds", type=float, default=2.0, help="delay in slow mode")
    common.add_argument("--private-key", help="base64 Ed25519 private key (only for a Twin in signed mode)")
    common.add_argument("--no-log", action="store_true", help="do not write the run logs")
    common.add_argument("--log-dir", help="folder for the run logs (default: the Twin's logging.parts_dir)")
    ap = argparse.ArgumentParser(description="Mock City Brain (Twin team stand-in).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("incident", parents=[common], help="the scripted jam: watch, ask Guardian, act")
    i.add_argument("--node", help="a traffic node that carries a signal (default: the first one)")
    i.add_argument("--threshold", type=float, default=JAM_THRESHOLD)
    i.add_argument("--ticks", type=int, default=JAM_TICKS)
    i.add_argument("--wait-seconds", type=float, default=60.0)
    i.add_argument("--fake-jam", action="store_true", help="start a fake jam first (run_scenario fake_reading)")
    a = sub.add_parser("act", parents=[common], help="one action through the whole path (preview, token, actuate)")
    a.add_argument("--action", required=True)
    a.add_argument("--targets", required=True, help="comma separated node ids")
    a.add_argument("--params", default="{}", help="JSON")
    a.add_argument("--idempotency-key")
    a.add_argument("--sends", type=int, default=1, help="send the same request this many times")
    args = ap.parse_args()
    try:
        print(json.dumps(asyncio.run(_run(args)), indent=2))
    except MockError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

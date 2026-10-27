"""Mock Guardian: a thin, scripted stand-in made by the Twin team (rule R1). It is NOT 9antra's Guardian.

What it does, on cue and with no logic of its own:
  * answers a request for a permission token the way you tell it to: approve, refuse, slow (approve after a delay),
    or silent (never answers). The mode is set by you, it does not judge anything.
  * signs the token in the format the Twin is set up for (it asks the Twin, `list_actions` -> `token_mode`):
        unsigned Twin -> our own JWT-style token with no signature (alg "none")
        signed Twin   -> Guardian's real "g1" token, signed with Ed25519 (needs a private key, see below)
  * can call the containment tools (isolate, quarantine, release) with the Guardian key.
  * writes its own run log (<run_id>.guardian.jsonl, every event marked stand_in) so the dashboard timeline shows a
    verdict between the Twin's reading and the Brain's decision. Library use: pass log=PartLog("guardian"). The command
    line writes the log by default (--no-log turns it off, --log-dir changes the folder).

Use as a library (the mock Brain does) or from the command line:

    python mocks/mock_guardian.py token --action set_signal_plan --targets TRF-01 --params '{"plan":"normal"}' --idempotency-key try-1
    python mocks/mock_guardian.py isolate --devices WAT-01.water_level --reason "stuck sensor"
    python mocks/mock_guardian.py release --devices WAT-01.water_level

Signed mode: make a key pair with `python mocks/token_tool.py keygen`, put the PUBLIC key in a copy of config/twin.yaml
(tokens.mode: signed, tokens.guardian_public_key: <public>), start the Twin with TWIN_CONFIG pointing at that copy,
and give this tool the PRIVATE key with --private-key or the environment variable MOCK_GUARDIAN_PRIVATE_KEY.
Never commit a private key.
"""
import argparse
import asyncio
import base64
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey        # noqa: E402

from mock_common import MockError, PartLog, TwinClient, key_for, twin_url                # noqa: E402

MODES = ("approve", "refuse", "slow", "silent")
TOKEN_LIFETIME_SECONDS = 60       # the Twin accepts at most 60 simulated seconds (decided 9 Oct, checked in the Twin)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _private_key(text: str | None) -> Ed25519PrivateKey | None:
    if not text:
        return None
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(text))
    except Exception:
        raise MockError("The private key is not a base64 Ed25519 key. Make one with: python mocks/token_tool.py keygen") from None


def make_g1_token(key: Ed25519PrivateKey, claims: dict) -> str:
    """Guardian's own format: g1.<payload>.<signature>. The signature covers the text "g1.<payload>"."""
    payload = _b64url(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    return f"g1.{payload}." + _b64url(key.sign(f"g1.{payload}".encode()))


def make_jws_token(claims: dict, key: Ed25519PrivateKey | None) -> str:
    """Our own first proposal (a JWT shape). With no key the signature part is empty and the header says alg none."""
    header = {"alg": "EdDSA" if key else "none", "typ": "JWT"}
    if key:
        header["kid"] = "guardian-dev"
    head = _b64url(json.dumps(header, separators=(",", ":")).encode())
    body = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    return f"{head}.{body}." + (_b64url(key.sign(f"{head}.{body}".encode())) if key else "")


class MockGuardian:
    def __init__(self, twin: TwinClient, mode: str = "approve", private_key: str | None = None, score: float = 0.9,
                 slow_seconds: float = 2.0, log: PartLog | None = None, refuse_score: float = 0.15):
        if mode not in MODES:
            raise MockError(f"Unknown mode {mode!r}. Use one of: {', '.join(MODES)}.")
        self.twin, self.mode, self.score, self.slow_seconds = twin, mode, score, slow_seconds
        self.log, self.refuse_score = log, refuse_score        # refuse_score: the low score logged when this mock says no
        self._key = _private_key(private_key or os.environ.get("MOCK_GUARDIAN_PRIVATE_KEY"))
        self._actions: dict | None = None

    async def _action_info(self, action: str) -> tuple[str, str | None]:
        if self._actions is None:
            self._actions = await self.twin.call("list_actions")
        for a in self._actions["actions"]:
            if a["action"] == action:
                return self._actions["token_mode"], a["risk"]
        raise MockError(f"The Twin has no action called {action!r}. Ask it: list_actions.")

    def _verdict(self, clock: dict, device_id: str | None, score: float, reading_ids: list[str] | None,
                 extra: dict) -> str | None:
        """Write one verdict event (a score for one device, pointing at the reading it judged). No log, no event."""
        if self.log is None:
            return None
        data = {"device_id": device_id, "score": score, "mode": self.mode, **extra}
        return self.log.write(clock, "verdict", data, caused_by=list(reading_ids or []))

    async def authorize(self, action: str, targets: list[str], params: dict, idempotency_key: str,
                        reading_ids: list[str] | None = None, device_id: str | None = None) -> dict:
        """The Brain asks: may I do exactly this? The answer depends only on the mode this mock was given.
        `reading_ids` and `device_id` say which reading and sensor the Brain relied on. They only go into the token and
        the log, this mock never looks at them (it judges nothing)."""
        if self.mode == "silent":
            await asyncio.Event().wait()                    # never answers (and logs nothing); the caller's timeout ends it
        if self.mode == "slow":
            await asyncio.sleep(self.slow_seconds)
        clock = await self.twin.call("get_clock")           # token times come from the Twin's simulated clock
        if self.mode == "refuse":
            event_id = self._verdict(clock, device_id, self.refuse_score, reading_ids,
                                     {"refused": True, "requested_action": action, "idempotency_key": idempotency_key})
            return {"decision": "refused", "refusal_code": "MOCK_REFUSED", "mode": self.mode, "event_id": event_id}
        token_mode, risk = await self._action_info(action)
        issued = datetime.fromisoformat(clock["time"])
        token_id = f"mock-{uuid.uuid4().hex[:10]}"
        if token_mode == "signed":
            if self._key is None:
                raise MockError("This Twin checks signatures (tokens.mode: signed). Give the mock Guardian a private "
                                "key: --private-key or MOCK_GUARDIAN_PRIVATE_KEY (see the top of this file).")
            token = make_g1_token(self._key, {
                "v": 1, "kid": "mock-guardian", "token_id": token_id, "run_id": clock["run_id"], "action": action,
                "targets": sorted(targets), "params": params, "idempotency_key": idempotency_key,
                "reading_ids": list(reading_ids or []), "preview_id": None, "iss": "guardian", "aud": "twin",
                "iat": issued.timestamp(), "exp": issued.timestamp() + TOKEN_LIFETIME_SECONDS,
                "trust_score": self.score, "risk_level": risk or "NONE"})
            kind = "g1"
        else:
            token = make_jws_token({
                "iss": "guardian", "aud": "twin", "jti": token_id, "run_id": clock["run_id"], "iat": _iso(issued),
                "exp": _iso(datetime.fromtimestamp(issued.timestamp() + TOKEN_LIFETIME_SECONDS, tz=timezone.utc)),
                "action": action, "targets": sorted(targets), "params": params, "score": self.score,
                "score_scale": "0-1"}, None)
            kind = "unsigned"
        event_id = self._verdict(clock, device_id, self.score, reading_ids,
                                 {"token_id": token_id, "approved_action": action, "idempotency_key": idempotency_key})
        return {"decision": "approved", "token": token, "token_id": token_id, "trust_score": self.score,
                "token_format": kind, "mode": self.mode, "event_id": event_id}

    # Containment: thin wrappers. The Twin only lets the Guardian key call these. With a log, each device first gets a
    # low-score verdict (the scripted "I distrust this one") and the containment call points at it, so the dashboard
    # draws verdict -> containment.
    async def _distrust(self, device_ids: list[str], reason: str | None) -> list[str]:
        if self.log is None:
            return []
        clock = await self.twin.call("get_clock")
        return [self._verdict(clock, d, self.refuse_score, None, {"reason": reason}) for d in device_ids]

    async def isolate(self, device_ids: list[str], reason: str | None = None) -> dict:
        caused_by = await self._distrust(device_ids, reason)
        return await self.twin.call("isolate_sensor", {"device_ids": device_ids, "reason": reason,
                                                       **({"caused_by": caused_by} if caused_by else {})})

    async def quarantine(self, device_ids: list[str], reason: str | None = None) -> dict:
        caused_by = await self._distrust(device_ids, reason)
        return await self.twin.call("quarantine_device", {"device_ids": device_ids, "reason": reason,
                                                          **({"caused_by": caused_by} if caused_by else {})})

    async def release(self, device_ids: list[str]) -> dict:
        return await self.twin.call("release_device", {"device_ids": device_ids})


async def _run(args: argparse.Namespace) -> dict:
    async with TwinClient(twin_url(args.url), key_for("guardian", args.key)) as twin:
        guardian = MockGuardian(twin, mode=args.mode, private_key=args.private_key, score=args.score,
                                slow_seconds=args.slow_seconds,
                                log=None if args.no_log else PartLog("guardian", args.log_dir))
        if args.cmd == "token":
            return await guardian.authorize(args.action, args.targets.split(","), json.loads(args.params),
                                            args.idempotency_key)
        devices = args.devices.split(",")
        if args.cmd == "isolate":
            return await guardian.isolate(devices, args.reason)
        if args.cmd == "quarantine":
            return await guardian.quarantine(devices, args.reason)
        return await guardian.release(devices)


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)             # options every command accepts, written AFTER the command
    common.add_argument("--url", help="where the Twin runs (default: TWIN_URL, then config/twin.yaml)")
    common.add_argument("--key", help="the Guardian key (default: TWIN_KEY_GUARDIAN from the environment or twin/.env)")
    common.add_argument("--mode", default="approve", choices=MODES)
    common.add_argument("--score", type=float, default=0.9, help="trust score put in the token, 0 to 1")
    common.add_argument("--slow-seconds", type=float, default=2.0)
    common.add_argument("--private-key", help="base64 Ed25519 private key (only for a Twin in signed mode)")
    common.add_argument("--no-log", action="store_true", help="do not write the run log")
    common.add_argument("--log-dir", help="folder for the run log (default: the Twin's logging.parts_dir)")
    ap = argparse.ArgumentParser(description="Mock Guardian (Twin team stand-in).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("token", parents=[common], help="make a token for one exact action")
    t.add_argument("--action", required=True)
    t.add_argument("--targets", required=True, help="comma separated node ids")
    t.add_argument("--params", default="{}", help="JSON")
    t.add_argument("--idempotency-key", required=True, help="the key the Brain will send with the action")
    for name in ("isolate", "quarantine", "release"):
        c = sub.add_parser(name, parents=[common])
        c.add_argument("--devices", required=True, help="comma separated device ids, e.g. WAT-01.water_level")
        if name != "release":
            c.add_argument("--reason")
    args = ap.parse_args()
    try:
        print(json.dumps(asyncio.run(_run(args)), indent=2))
    except MockError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

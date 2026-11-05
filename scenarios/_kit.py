"""Shared helper for the scenario scripts (R2). Every script in this folder is: one command, one trigger, one log.

Not a scenario itself: do not run this file. It does the boring parts every script needs:

  1. check that the Twin answers (it never starts the Twin, it only prints a clear message if it cannot reach it)
  2. reset the run (new run id, clock back to 0, old faults forgotten)
  3. let the script pull its ONE trigger and wait
  4. merge the part files of all layers into one log and save it as logs/<ID>-<n>.jsonl, for example logs/T3-1.jsonl
  5. check the expected outcome, print one line per check and one verdict line, exit with 0 (pass), 1 (fail) or 2 (setup problem)

It imports nothing from twin/src. It talks to the Twin the same way a partner would (MCP calls through
twin/mocks/mock_common.py) and calls the stand-ins in twin/mocks/ as normal commands.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the repo root: scenarios/ sits right beside twin/
TWIN_DIR = ROOT / "twin"
LOGS_DIR = ROOT / "logs"
sys.path.insert(0, str(TWIN_DIR / "mocks"))             # so we can reuse the stand-ins' small MCP client

try:
    from mock_common import MockError, TwinClient, twin_url, key_for      # noqa: E402
except ImportError as exc:                                                 # the Twin's libraries are not installed here
    print(f"Cannot load the Twin's helper libraries ({exc}).\n"
          f"Use the same Python environment you use for the Twin: cd twin && pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(2)

PASS, FAIL, SETUP = 0, 1, 2                             # exit codes


def setup_exit(message: str):
    """Something outside the scenario is wrong (Twin not running, a stand-in crashed, the merge failed).
    That is exit code 2, not a failed scenario: the scenario did not get a fair run."""
    print(f"\nSETUP PROBLEM: {message}", file=sys.stderr)
    raise SystemExit(SETUP)


# ------------------------------------------------------------------------------------------------ reading logs
def read_events(path: Path) -> list[dict]:
    """Read a JSON Lines file (one JSON object per line). Lines that are not valid JSON are skipped."""
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events


def of(events: list[dict], layer: str | None = None, event_type: str | None = None) -> list[dict]:
    """The events of one layer and/or one type."""
    return [e for e in events if (layer is None or e.get("layer") == layer) and (event_type is None or e.get("event_type") == event_type)]


def actions(events: list[dict], status: str | None = None, code: str | None = None) -> list[dict]:
    """The Twin's `action` events, optionally only one status (committed / rejected) or one refusal code."""
    out = of(events, "twin", "action")
    if status:
        out = [e for e in out if e["data"].get("status") == status]
    if code:
        out = [e for e in out if e["data"].get("code") == code]
    return out


def layer_label(events: list[dict], layer: str) -> str:
    """Is this layer's part of the log from our stand-in or from the partner's real code? Read from the events themselves
    (every stand-in event carries data.stand_in = true), so the label cannot be wrong by a forgotten flag."""
    mine = of(events, layer)
    if not mine:
        return "no events"
    marks = [bool(e.get("data", {}).get("stand_in")) for e in mine]
    return "stand-in" if all(marks) else "real" if not any(marks) else "mixed"


# ------------------------------------------------------------------------------------------------ the run
class Run:
    """One scenario run. Created by begin()."""

    def __init__(self, scenario_id: str, title: str, args: argparse.Namespace):
        self.id, self.title, self.args = scenario_id, title, args
        self.url = twin_url(args.url)
        self.run_id = ""
        self.real = getattr(args, "layers", "standin") == "real"
        self.started: list[str] = []                    # scenario ids we started on the Twin (stopped again before the log is saved)
        self.close_run = False                          # True: end the run (reset) before saving, so the Twin writes its log

    # --- talking to the Twin
    def call(self, who: str, tool: str, params: dict | None = None) -> dict:
        """One MCP call to the Twin, with the key of `who` (city_brain, guardian or scenario)."""
        async def go():
            async with TwinClient(self.url, key_for(who)) as twin:
                return await twin.call(tool, params)
        return asyncio.run(go())

    def scenario(self, name: str, params: dict | None = None) -> dict:
        """run_scenario on the Twin (hidden tool, needs the scenario key). Remembers what it started."""
        out = self.call("scenario", "run_scenario", {"name": name, "params": params or {}})
        if out.get("status") == "started" and out.get("scenario_id"):
            self.started.append(out["scenario_id"])
        return out

    def tick(self) -> int:
        return self.call("city_brain", "get_clock")["tick"]

    def wait(self, seconds: float, why: str) -> None:
        print(f"  waiting {seconds:g} s: {why}", flush=True)
        time.sleep(seconds)

    # --- the stand-ins (normal commands, run from twin/ so they share run-logs/ with the Twin)
    def stand_in(self, script: str, *argv: str) -> dict:
        """Run mocks/<script> with the given arguments and return the JSON it prints."""
        # `--url` must come AFTER the command word (incident / act / token ...): argv[0] is that word.
        cmd = [sys.executable, str(TWIN_DIR / "mocks" / script), argv[0], "--url", self.url, *argv[1:]]
        shown = " ".join(["python", f"mocks/{script}", *argv])
        print(f"  running: {shown}", flush=True)
        done = subprocess.run(cmd, cwd=TWIN_DIR, capture_output=True, text=True)
        if done.returncode != 0:
            setup_exit(f"{shown} failed: {(done.stderr or done.stdout).strip()[:400]}")
        try:
            return json.loads(done.stdout)
        except json.JSONDecodeError:
            setup_exit(f"{shown} printed something that is not JSON: {done.stdout[:200]}")

    # --- the log
    def part_files(self) -> list[Path]:
        """Every part file of THIS run we can find: the stand-ins write into twin/run-logs/, the partners' real layers
        write into their own folders (the documented place), plus anything given with --parts."""
        name = lambda layer: f"{self.run_id}.{layer}.jsonl"                      # noqa: E731
        candidates = [TWIN_DIR / "run-logs" / name("guardian"), TWIN_DIR / "run-logs" / name("brain"),
                      ROOT / "guardian" / "run-logs" / name("guardian"), ROOT / "brain" / "run-logs" / name("brain"),
                      *map(Path, getattr(self.args, "parts", None) or [])]
        return [p for p in candidates if p.exists()]

    def save_log(self) -> tuple[Path, list[dict]]:
        """Merge all part files of this run, save the result as logs/<ID>-<n>.jsonl, return (path, events)."""
        for sid in self.started:                                    # stop what we started, so the log shows the end too
            try:
                self.call("scenario", "run_scenario", {"name": "stop", "params": {"scenario_id": sid}})
            except MockError:
                pass                                                # it ended by itself (a jam does): nothing to stop
        if self.close_run:
            # A calm run logs nothing, so the Twin has no log file for it yet. Ending the run makes it write one
            # (a `run_ended` event). We keep merging the run that just ended: self.run_id is still its id.
            self.call("scenario", "run_scenario", {"name": "reset"})
        LOGS_DIR.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, "-m", "twin.logmerge", self.run_id, "--out", tmp]
            parts = self.part_files()
            if parts:
                cmd += ["--parts", *map(str, parts)]
            env = {**os.environ, "PYTHONPATH": str(TWIN_DIR / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")}
            done = subprocess.run(cmd, cwd=TWIN_DIR, capture_output=True, text=True, env=env)
            merged = Path(tmp) / f"{self.run_id}.jsonl"
            if done.returncode != 0 or not merged.exists():
                setup_exit("Could not merge the log: " + (done.stderr or done.stdout).strip()[:400])
            n = 1 + max([int(m.group(1)) for p in LOGS_DIR.glob(f"{self.id}-*.jsonl")
                         if (m := re.fullmatch(rf"{self.id}-(\d+)\.jsonl", p.name))] or [0])
            target = LOGS_DIR / f"{self.id}-{n}.jsonl"
            target.write_bytes(merged.read_bytes())
        return target, read_events(target)


# ------------------------------------------------------------------------------------------------ script frame
def begin(scenario_id: str, title: str, doc: str, real_ok: bool = False, extra=None) -> Run:
    """Parse the command line, check the Twin, reset the run. `real_ok`: this scenario also works with --layers real."""
    ap = argparse.ArgumentParser(description=f"{scenario_id} {title}\n\n{doc}", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="where the Twin runs (default: TWIN_URL, then config/twin.yaml)")
    if real_ok:
        ap.add_argument("--layers", choices=["standin", "real"], default="standin",
                        help="standin (default): our stand-ins play Brain and Guardian. real: the partners' real layers must be "
                             "running already and watching this Twin; the script only pulls the trigger and reads the logs")
        ap.add_argument("--parts", nargs="*", default=[], help="part files of the real layers, if they are not in brain/run-logs or guardian/run-logs")
    if extra:
        extra(ap)
    args = ap.parse_args()
    run = Run(scenario_id, title, args)
    print(f"{scenario_id}  {title}   (layers: {'real' if run.real else 'stand-ins'})")
    try:
        run.tick()                                                  # does the Twin answer?
    except Exception as exc:                                        # noqa: BLE001  (any failure means: cannot reach it)
        print(f"\nCannot reach the Twin at {run.url}.\nStart it first, in another terminal:  cd twin && python -m twin\n"
              f"(then run this script again)  [{type(exc).__name__}]", file=sys.stderr)
        raise SystemExit(SETUP)
    reset = run.scenario("reset")
    run.run_id = reset["run_id"]
    print(f"  new run {run.run_id}, clock at tick {reset['tick']}")
    return run


def finish(run: Run, outputs: dict, checks) -> None:
    """Save the log, run the checks (a function that gets the events), print the verdict, write logs/INDEX.md, exit."""
    path, events = run.save_log()
    results = checks(events)
    for ok, text in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {text}")
    passed = all(ok for ok, _ in results)
    label = f"brain: {layer_label(events, 'brain')}, guardian: {layer_label(events, 'guardian')}"
    index = LOGS_DIR / "INDEX.md"
    if not index.exists():
        index.write_text("# logs/\n\nOne file per scenario run, named `<scenario ID>-<run number>.jsonl`. Written by the scripts in `scenarios/`.\n"
                         "The label says whether each layer's events come from a stand-in or from the real layer.\n\n"
                         "| File | Scenario | When (UTC) | Twin run id | Layers | Result |\n|---|---|---|---|---|---|\n", encoding="utf-8")
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    with index.open("a", encoding="utf-8") as f:
        f.write(f"| {path.name} | {run.id} {run.title} | {now} | {run.run_id} | {label} | {'PASS' if passed else 'FAIL'} |\n")
    print(f"\n{'PASS' if passed else 'FAIL'} {run.id} {run.title}: {len(events)} events saved to logs/{path.name} ({label})")
    raise SystemExit(PASS if passed else FAIL)

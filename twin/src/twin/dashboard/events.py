"""Reading the run logs, live, and turning events into what the screen shows.

LogFollower  reads new lines from the part files and merged files as they grow. Safe against half-written lines, files that
             get replaced (the merge writes a new file each time) and the same event showing up in two files.
build_state  turns the events of one run into device and node states, attacks, escalations.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any

from ..models import Node, Topology
from ..runlog import LAYER_ORDER
from .style import SYSTEM_PHASES, TRUST_ORDER

REQUIRED = {"run_id", "event_id", "tick", "layer", "event_type"}
Event = dict[str, Any]


def sort_key(e: Event) -> tuple:
    """Same order as the merge: tick, then real clock, then layer, then event id."""
    return (e["tick"], e.get("wall", ""), LAYER_ORDER.get(e["layer"], 9), e["event_id"])


def as_list(x: Any) -> list:
    """Logs come from other teams. A field that should be a list but is not (a number, a string, null) counts as empty."""
    return x if isinstance(x, list) else []


# ---------------------------------------------------------------------- real clock, system events, sessions
def wall_time(e: Event) -> datetime | None:
    """The real-clock time an event was written (`wall`, optional in the shared format). None if missing or unreadable.
    A time without a zone is read as UTC, because the Twin writes UTC ('...Z')."""
    w = e.get("wall")
    if not isinstance(w, str):
        return None
    try:
        t = datetime.fromisoformat(w.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def format_wall(e: Event, tz: tzinfo | None = None) -> str:
    """'14:03:22.481': the real time of an event, to the millisecond, in `tz` (default: this computer's own time zone).
    Empty text when the event has no real time. This is the time that puts events of the SAME tick in order."""
    t = wall_time(e)
    if t is None:
        return ""
    t = t.astimezone(tz)                                      # tz=None means the local zone of the machine that runs the dashboard
    return t.strftime("%H:%M:%S.") + f"{t.microsecond // 1000:03d}"


def _phase(e: Event) -> str | None:
    d = e.get("data")
    return d.get("phase") if e.get("event_type") == "scenario" and isinstance(d, dict) and isinstance(d.get("phase"), str) else None


def is_system(e: Event) -> bool:
    """The Twin writing about itself (it started, a run started, a run ended). Not something that happened in the city."""
    return _phase(e) in SYSTEM_PHASES


def display_type(e: Event) -> str:
    """What the Type column says. The log keeps type 'scenario' for these (the partners read that format), the screen says 'system'."""
    return "system" if is_system(e) else e["event_type"]


def _is_start(e: Event) -> bool:
    return _phase(e) in ("run_started", "twin_started")


TICK_BACK = 10          # a tick this far behind the newest tick of the session means the clock started over


def split_sessions(events: list[Event]) -> list[list[Event]]:
    """A restarted Twin keeps the run id (`run-42-001`) but its tick counts from 0 again, so one run id can hold several
    SESSIONS (one per Twin start). This cuts the events of one run id into sessions, oldest first.

    How: put the events in real-clock order, then start a new session when (1) a `run_started` / `twin_started` event
    arrives after the session already holds other events, or (2) a tick is more than TICK_BACK behind the newest tick of the
    session (the clock fell back). Events without a real clock (`wall` is optional) go to the newest session that started at
    or before their tick. Every session comes back in the usual display order (tick, real time, layer, event id)."""
    walled = sorted((e for e in events if wall_time(e) is not None),
                    key=lambda e: (wall_time(e), e["tick"], LAYER_ORDER.get(e["layer"], 9), e["event_id"]))
    sessions: list[list[Event]] = []
    cur: list[Event] = []
    has_work, newest = False, 0
    for e in walled:
        starts = _is_start(e)
        if cur and ((starts and has_work) or e["tick"] < newest - TICK_BACK):
            sessions.append(cur)
            cur, has_work, newest = [], False, 0
        cur.append(e)
        has_work = has_work or not starts
        newest = max(newest, e["tick"])
    if cur:
        sessions.append(cur)
    loose = [e for e in events if wall_time(e) is None]
    if not sessions:
        sessions = [[]]
    for e in loose:
        home = [s for s in sessions if s and min(x["tick"] for x in s) <= e["tick"]]
        (home[-1] if home else sessions[0]).append(e)
    return [sorted(s, key=sort_key) for s in sessions]


def _is_event(obj: Any) -> bool:
    return isinstance(obj, dict) and REQUIRED <= obj.keys() and isinstance(obj["tick"], int) and not isinstance(obj["tick"], bool)


class LogFollower:
    def __init__(self, sources: list[str]):
        self.sources = [Path(s) for s in sources]
        self._pos: dict[Path, int] = {}
        self._ino: dict[Path, int] = {}
        self._tail: dict[Path, bytes] = {}
        self._events: dict[tuple[str, str], Event] = {}
        self.bad_lines = 0
        self.version = 0                                   # goes up whenever something new was read

    def files(self) -> list[Path]:
        found: list[Path] = []
        for s in self.sources:
            if s.is_file():
                found.append(s)
            elif s.is_dir():
                found += sorted(s.glob("*.jsonl"))
        # The Twin's private file holds TRUE values. The dashboard must never read it, whatever folder it is pointed at.
        return [p for p in dict.fromkeys(found) if "private" not in p.name]

    def poll(self) -> bool:
        changed = False
        for p in self.files():
            try:
                st = p.stat()
            except OSError:
                continue
            if self._ino.get(p) != st.st_ino or st.st_size < self._pos.get(p, 0):
                self._pos[p], self._tail[p], self._ino[p] = 0, b"", st.st_ino      # new or replaced file: read it from the start
            if st.st_size == self._pos[p]:
                continue
            try:
                with open(p, "rb") as f:
                    f.seek(self._pos[p])
                    chunk = f.read()
            except OSError:
                continue
            self._pos[p] += len(chunk)
            lines = (self._tail[p] + chunk).split(b"\n")
            self._tail[p] = lines.pop()                    # the last piece may be a half-written line: keep it for next time
            if self._tail[p] and self._take(self._tail[p], quiet=True):
                self._tail[p], changed = b"", True         # it was a complete line that only lacks the final newline
            for line in lines:
                changed |= self._take(line)
        if changed:
            self.version += 1
        return changed

    def _take(self, line: bytes, quiet: bool = False) -> bool:
        if not line.strip():
            return False
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            if not quiet:
                self.bad_lines += 1
            return False
        if not _is_event(obj):
            if not quiet:
                self.bad_lines += 1
            return False
        key = (obj["layer"], obj["event_id"])
        if key in self._events:
            return False
        self._events[key] = obj
        return True

    def runs(self) -> dict[str, list[Event]]:
        out: dict[str, list[Event]] = {}
        for e in self._events.values():
            out.setdefault(e["run_id"], []).append(e)
        return {r: sorted(v, key=sort_key) for r, v in out.items()}

    def latest_run(self) -> str | None:
        newest = max(self._events.values(), key=lambda e: (e.get("wall", ""), e["tick"]), default=None)
        return newest["run_id"] if newest else None


# ---------------------------------------------------------------------- state of one run
@dataclass
class DeviceStatus:
    device_id: str
    node_id: str
    score: float | None = None
    trust: str = "unknown"
    cut: str | None = None                 # "isolated" or "quarantined"
    corrections: int = 0


@dataclass
class RunState:
    run_id: str
    events: list[Event] = field(default_factory=list)
    by_id: dict[str, Event] = field(default_factory=dict)
    tick: int = 0
    time: str = ""
    devices: dict[str, DeviceStatus] = field(default_factory=dict)
    scenarios: list[dict[str, Any]] = field(default_factory=list)      # {scenario_id, name, faults[], stopped}
    escalations: list[Event] = field(default_factory=list)
    failures: list[Event] = field(default_factory=list)
    causes: dict[str, list[str]] = field(default_factory=dict)       # event_id -> event_ids it came from
    seed: int | None = None                                           # from the run_started event
    sessions: int = 1                                                 # how many Twin starts this run id holds (set by the Hub)

    def attacks(self) -> list[dict[str, Any]]:
        """Faults that are running right now (the dashboard may show them, it is a viewer for people)."""
        out = []
        for sc in self.scenarios:
            if sc["stopped"]:
                continue                                    # a stopped scenario is over, even if its last tick is not
            for f in sc["faults"]:
                end = f.get("end_tick")
                if f["start_tick"] <= self.tick and (end is None or self.tick < end):
                    out.append({**f, "scenario_id": sc["scenario_id"], "name": sc["name"]})
        return out


def resolve_causes(events: list[Event]) -> dict[str, list[str]]:
    """Who caused what. Three ways an event can point at its cause:
      1. `caused_by` holds an event id.
      2. `caused_by` holds a reading_id (a verdict points at the reading it judged).
      3. The Twin's `action` event is joined by `token_id` (to the Guardian event that carries the same token_id) and by
         `idempotency_key` (to the Brain event that carries the same key). The Twin cannot know who asked, so the others say it.
    Nothing is guessed: an event with no link simply has no arrow."""
    ids = {e["event_id"] for e in events}
    by_reading: dict[str, str] = {}
    by_token: dict[str, list[str]] = {}
    by_key: dict[str, list[str]] = {}
    for e in events:
        d = e.get("data") if isinstance(e.get("data"), dict) else {}
        if e["event_type"] == "reading" and isinstance(d.get("reading_id"), str):
            by_reading.setdefault(d["reading_id"], e["event_id"])
        if e["layer"] != "twin":
            if isinstance(d.get("token_id"), str):
                by_token.setdefault(d["token_id"], []).append(e["event_id"])
            if isinstance(d.get("idempotency_key"), str):
                by_key.setdefault(d["idempotency_key"], []).append(e["event_id"])
    out: dict[str, list[str]] = {}
    for e in events:
        found: list[str] = []
        for c in e.get("caused_by") or []:
            c = by_reading.get(c, c) if isinstance(c, str) else c
            if c in ids and c != e["event_id"] and c not in found:
                found.append(c)
        d = e.get("data") if isinstance(e.get("data"), dict) else {}
        if e["event_type"] == "action" and e["layer"] == "twin":
            for src in (by_token.get(d.get("token_id"), []) if isinstance(d.get("token_id"), str) else []) + \
                       (by_key.get(d.get("idempotency_key"), []) if isinstance(d.get("idempotency_key"), str) else []):
                if src not in found:
                    found.append(src)
        if found:
            out[e["event_id"]] = found
    return out


def trust_from_score(score: float, cutoffs: dict[str, float]) -> str:
    """Placeholder cut-offs until Guardian publishes its own (decision report: a verdict is a score only, no label)."""
    if score >= cutoffs["trusted"]:
        return "trusted"
    if score >= cutoffs["degraded"]:
        return "degraded"
    return "untrusted"


def build_state(events: list[Event], topology: Topology, cutoffs: dict[str, float], run_id: str) -> RunState:
    st = RunState(run_id=run_id, events=events, by_id={e["event_id"]: e for e in events})
    st.causes = resolve_causes(events)
    node_ids = {n.node_id for n in topology.nodes}
    for n in topology.nodes:
        for s in n.sensors:
            st.devices[s.device_id] = DeviceStatus(s.device_id, n.node_id)

    def device(device_id: Any) -> DeviceStatus | None:
        return st.devices.get(device_id) if isinstance(device_id, str) else None

    for e in events:
        if e["tick"] >= st.tick:                           # events are sorted, so the last one gives the current tick and time
            st.tick, st.time = e["tick"], e.get("timestamp", st.time)
        d, t = e.get("data") or {}, e["event_type"]
        if not isinstance(d, dict):
            continue
        if t == "verdict":
            dev, score = device(d.get("device_id")), d.get("score")
            if dev and isinstance(score, (int, float)) and not isinstance(score, bool):
                dev.score, dev.trust = float(score), trust_from_score(float(score), cutoffs)
        elif t == "containment" and d.get("status") == "applied":
            tool = d.get("tool")
            for dev_id in as_list(d.get("changed")):
                dev = device(dev_id)
                if dev:
                    dev.cut = {"isolate_sensor": "isolated", "quarantine_device": "quarantined", "release_device": None}.get(tool, dev.cut)
            if tool == "rollback_reading":
                for c in as_list(d.get("corrections")):
                    dev = device(c.get("device_id")) if isinstance(c, dict) else None
                    if dev:
                        dev.corrections += 1
        elif t == "scenario" and d.get("phase") == "run_started" and isinstance(d.get("seed"), int) and not isinstance(d.get("seed"), bool):
            st.seed = d["seed"]
        elif t == "scenario" and d.get("phase") == "started":
            st.scenarios.append({"scenario_id": d.get("scenario_id"), "name": d.get("name"), "stopped": False,
                                 "faults": [dict(f) for f in as_list(d.get("faults")) if isinstance(f, dict) and "start_tick" in f]})
        elif t == "scenario" and d.get("phase") == "stopped":
            for sc in st.scenarios:
                if sc["scenario_id"] == d.get("scenario_id"):
                    sc["stopped"] = True
                    ends = {f.get("fault_id"): f.get("end_tick") for f in as_list(d.get("faults")) if isinstance(f, dict)}
                    for f in sc["faults"]:
                        f["end_tick"] = ends.get(f.get("fault_id"), f.get("end_tick"))
        elif t == "escalation":
            st.escalations.append(e)
        elif t == "partner_failure":
            st.failures.append(e)
    return st


def node_status(node: Node, st: RunState) -> dict[str, Any]:
    """What to draw for one node: worst trust of its devices, and whether its devices are cut off or under attack."""
    devs = [st.devices[s.device_id] for s in node.sensors if s.device_id in st.devices]
    trust = max((d.trust for d in devs), key=lambda x: TRUST_ORDER[x], default="unknown")
    cut = [d.cut for d in devs if d.cut]
    attacked = {f["device_id"] for f in st.attacks()}
    return {"trust": trust,
            "cut": None if not cut else ("isolated" if len(cut) == len(devs) and set(cut) == {"isolated"} else
                                         "quarantined" if "quarantined" in cut else "partly"),
            "attack": any(d.device_id in attacked for d in devs)}


def _token_outcome(d: dict[str, Any]) -> str:
    """A verdict with no device is Guardian's answer to a token request: 'approved' or 'refused'."""
    refused = d.get("refused") or d.get("approved") is False or d.get("decision") in ("refused", "denied", "rejected")
    return "refused" if refused else "approved"


def _system_text(e: Event) -> str:
    d = e.get("data") if isinstance(e.get("data"), dict) else {}
    phase = _phase(e)
    if phase == "twin_started":
        return "Twin started"
    if phase == "run_ended":
        return "Run ended"
    bits = [f"seed {d['seed']}"] if "seed" in d else []
    bits += [f"{d['nodes']} nodes"] if "nodes" in d else []
    return "Run started" + (f" ({', '.join(bits)})" if bits else "")


def summarize(e: Event) -> str:
    """One short line for the event table and the timeline labels. Never raises on odd data."""
    d, t = e.get("data"), e["event_type"]
    if not isinstance(d, dict):
        return t
    g = d.get

    def short(x: Any) -> str:
        return f"{x:g}" if isinstance(x, float) else str(x)

    if t == "reading":
        return f"{g('device_id')} = {short(g('value'))} {g('unit') or ''}".strip()
    if t == "verdict":
        score = f"score {short(g('score'))}"
        if g("device_id"):
            return f"{g('device_id')} {score}"
        what = f" for {g('approved_action')}" if g("approved_action") else ""      # no device: the answer to a token request
        return f"token {_token_outcome(d)}{what}, {score}"
    if t == "decision":
        incident, action = g("incident"), g("chosen_action")
        if incident and action and str(action) not in str(incident):               # 'set_signal_plan on TRF-01' already says the action
            return f"{incident} -> {action}"
        return str(incident or action or "decision")
    if t == "action":
        return f"{g('action')} {','.join(map(str, as_list(g('targets'))))}: {g('status')}" + (f" ({g('code')})" if g("code") else "")
    if t == "containment":
        what = ", ".join(map(str, as_list(g("changed")))) or ", ".join(str(c.get("device_id")) for c in as_list(g("corrections")) if isinstance(c, dict))
        return f"{g('tool')} {what}: {g('status')}" + (f" ({g('code')})" if g("code") else "")
    if t == "escalation":
        return f"Human review: {g('reason') or g('incident') or 'needs a person'}"
    if t == "scenario":
        if is_system(e):
            return _system_text(e)
        return f"{g('phase')} {g('name') or ''}".strip()
    if t == "partner_failure":
        return f"{g('partner') or g('layer') or 'partner'}: {g('failure') or g('what') or 'failed'}"
    return t


def short_label(e: Event) -> str:
    """A few words that fit under a glyph on the timeline (the full text is in the hover title and the event table)."""
    d, t = e.get("data"), e["event_type"]
    if not isinstance(d, dict):
        return t
    g = d.get
    node = lambda x: str(x).split(".")[0]                                        # noqa: E731  WAT-01.water_level -> WAT-01
    if t == "reading":
        v = g("value")
        return f"{v:g} {g('unit') or ''}".strip() if isinstance(v, (int, float)) else "reading"
    if t == "verdict":
        sc = g("score")
        who = node(g("device_id")) if g("device_id") else f"token {'ok' if _token_outcome(d) == 'approved' else 'refused'}"
        return f"{who} {sc:g}" if isinstance(sc, (int, float)) and not isinstance(sc, bool) else who
    if t == "decision":
        return str(g("chosen_action") or g("incident") or "decision")[:20]
    if t == "action":
        return f"{str(g('action', '')).replace('set_', '')[:14]} {'ok' if g('status') == 'committed' else 'refused'}".strip()
    if t == "containment":
        tool = {"isolate_sensor": "isolate", "quarantine_device": "quarantine", "rollback_reading": "rollback",
                "release_device": "release"}.get(g("tool"), str(g("tool")))
        ids = as_list(g("changed")) or [c.get("device_id") for c in as_list(g("corrections")) if isinstance(c, dict)]
        return f"{tool} {node(ids[0])}" if ids else f"{tool} refused"
    if t == "escalation":
        return "Human review"
    if t == "partner_failure":
        return f"{g('partner') or 'partner'} failed"
    if t == "scenario":
        return _system_text(e) if is_system(e) else f"{g('name') or ''} {g('phase') or ''}".strip()
    return t


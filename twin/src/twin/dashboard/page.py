"""The dashboard page (NiceGUI). One page: a city map, the four-lane timeline, details and a table of events.

Everything it shows comes from the run logs (events.py reads them, svg.py draws them). It refreshes by itself once a second,
but only redraws when a log really changed or you clicked something.
"""
import json
import time
from datetime import datetime, timezone
from typing import Any

from nicegui import ui

from ..models import Layout, Topology
from ..settings import DashboardCfg
from .events import Event, LogFollower, RunState, as_list, build_state, node_status, summarize
from .style import DOMAIN_COLORS, DOMAIN_NAMES, ISOLATED_COLOR, LANES, QUARANTINE_COLOR, TRUST_COLORS, TRUST_NAMES
from .svg import Scene, city_scene, timeline_scene

TABLE_ROWS = 400
WINDOWS = {30: "Last 30 ticks", 60: "Last 60 ticks", 120: "Last 120 ticks", 0: "Whole run"}


class Hub:
    """Shared by every open browser tab: one reader of the logs, one cache of the computed state."""

    def __init__(self, cfg: DashboardCfg, topology: Topology, layout: Layout, sources: list[str] | None = None,
                 fingerprint: str | None = None):
        self.cfg, self.topology, self.layout, self.fingerprint = cfg, topology, layout, fingerprint
        self.follower = LogFollower(sources if sources is not None else cfg.sources)
        self.cutoffs = {"trusted": cfg.trusted_from, "degraded": cfg.degraded_from}
        self._cache: tuple[Any, ...] | None = None
        self._runs: list[str] = []
        self._states: dict[str, RunState] = {}

    def poll(self) -> None:
        self.follower.poll()
        key = self.follower.version
        if self._cache != (key,):
            self._cache = (key,)
            runs = self.follower.runs()
            self._runs = sorted(runs, key=lambda r: max((e.get("wall", ""), e["tick"]) for e in runs[r]), reverse=True)
            self._states = {r: build_state(ev, self.topology, self.cutoffs, r) for r, ev in runs.items()}

    def run_ids(self) -> list[str]:
        return self._runs

    def state(self, run_id: str | None) -> RunState | None:
        return self._states.get(run_id or (self._runs[0] if self._runs else ""))

    def city_mismatch(self, st: RunState) -> str | None:
        """The map is drawn from OUR config. If the log came from a different city, say so instead of drawing a wrong map."""
        for e in st.events:
            d = e.get("data") if isinstance(e.get("data"), dict) else {}
            fp = d.get("city_fingerprint")
            if e["event_type"] == "scenario" and d.get("phase") == "run_started" and fp and self.fingerprint and fp != self.fingerprint:
                return f"This log came from another city (fingerprint {fp}, this map is {self.fingerprint}). Node positions may not match."
        return None


def _is_sample(st: RunState) -> bool:
    return any(isinstance(e.get("data"), dict) and e["data"].get("sample") for e in st.events)


def _age(st: RunState) -> tuple[str, bool]:
    """('LIVE', True) if the newest event was written a moment ago, else ('IDLE, last event 3 min ago', False)."""
    walls = [e.get("wall", "") for e in st.events if e.get("wall")]
    try:
        last = datetime.fromisoformat(max(walls).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "no clock in log", False
    secs = (datetime.now(timezone.utc) - last).total_seconds()
    if secs < 6:
        return "LIVE", True
    return "IDLE, last event " + (f"{int(secs)} s" if secs < 120 else f"{int(secs // 60)} min" if secs < 7200 else f"{int(secs // 3600)} h") + " ago", False


def _dot(color: str, ring: bool = False, dashed: bool = False) -> None:
    style = f"border:3px {'dashed' if dashed else 'solid'} {color};background:#fff" if ring else f"background:{color}"
    ui.element("div").classes("w-3 h-3 rounded-full inline-block").style(style)


def build_page(hub: Hub) -> None:
    ui.colors(primary="#0EA5E9")
    S: dict[str, Any] = {"run": None, "node": None, "event": None, "window": hub.cfg.window_ticks, "follow": True, "end": None,
                         "edges": False, "attacks": True, "seen": None}
    scenes: dict[str, Scene] = {}

    def state() -> RunState | None:
        return hub.state(S["run"])

    # -------------------------------------------------------------- actions
    def pick(which: str, e: Any) -> None:
        scene = scenes.get(which)
        if not scene:
            return
        hit = scene.nearest(e.image_x, e.image_y, 50 if which == "city" else 30)
        if which == "city":
            S["node"] = hit if hit != S["node"] else None
        else:
            S["event"] = hit if hit != S["event"] else None
        redraw(force=True)

    def select_event(event_id: str) -> None:
        S["event"] = event_id
        redraw(force=True)

    def follow_changed(on: bool) -> None:
        st = state()
        S["follow"], S["end"] = on, (None if on else (st.tick if st else 0))
        slider.set_visibility(not on)
        redraw(force=True)

    def slide(v: float) -> None:
        if not S["follow"]:
            S["end"] = int(v)
            redraw(force=True)

    # -------------------------------------------------------------- redraw
    def redraw(force: bool = False) -> None:
        hub.poll()
        ids = hub.run_ids()
        st = state()
        key = (hub.follower.version, S["run"], S["node"], S["event"], S["window"], S["follow"], S["end"], S["edges"], S["attacks"])
        if not force and key == S["seen"]:
            return
        S["seen"] = key
        run_select.set_options(ids, value=(S["run"] if S["run"] in ids else (ids[0] if ids else None)))
        empty.set_visibility(st is None)
        body.set_visibility(st is not None)
        if st is None:
            warn.set_text("")
            warn.set_visibility(False)
            status_chip.set_text("no data")
            tick_label.set_text("")
            counts_label.set_text("")
            sample_chip.set_visibility(False)
            return
        mismatch = hub.city_mismatch(st)
        warn.set_text(mismatch or "")
        warn.set_visibility(bool(mismatch))
        sample_chip.set_visibility(_is_sample(st))
        text, live = _age(st)
        status_chip.set_text(text)
        status_chip.props(f"icon={'fiber_manual_record' if live else 'pause_circle'} color={'green' if live else 'grey-7'} text-color=white")
        tick_label.set_text(f"tick {st.tick}  {st.time[11:19] if len(st.time) >= 19 else ''}")
        cut = sum(1 for d in st.devices.values() if d.cut)
        bad = sum(1 for d in st.devices.values() if d.trust == "untrusted")
        counts_label.set_text(f"{len(st.events)} events · {bad} untrusted · {cut} cut off · {len(st.escalations)} for a person")
        if not S["follow"]:
            slider.props(f"min=0 max={st.tick}")
        c = city_scene(hub.topology, hub.layout, st, selected=S["node"], show_edges=S["edges"], show_attacks=S["attacks"])
        t = timeline_scene(st, selected=S["event"], window_ticks=S["window"], end_tick=S["end"])
        scenes["city"], scenes["timeline"] = c, t
        city_img.set_content(c.content)
        timeline_img.set_content(t.content)
        rows = [{"id": e["event_id"], "time": (e.get("timestamp") or "")[11:19], "tick": e["tick"], "layer": e["layer"],
                 "type": e["event_type"], "what": summarize(e)} for e in reversed(st.events[-TABLE_ROWS:])]
        table.rows = rows
        table.update()
        side.refresh()

    # -------------------------------------------------------------- side panels
    @ui.refreshable
    def side() -> None:
        st = state()
        if st is None:
            return
        if S["event"] and S["event"] in st.by_id:
            event_card(st, st.by_id[S["event"]])
        if S["node"]:
            node_card(st, S["node"])
        attacks = st.attacks()
        with ui.card().classes("w-full"):
            ui.label("Scenarios").classes("text-lg font-bold")
            if not st.scenarios:
                ui.label("None started in this run.").classes("text-slate-500")
            for sc in st.scenarios:
                for f in sc["faults"]:
                    running = sc["scenario_id"] in {a["scenario_id"] for a in attacks}
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("warning" if running else "check_circle", color="red" if running else "grey").classes("text-lg")
                        ui.label(f"{sc['name']} on {f['device_id']}" + (f" = {f['value']:g}" if f.get("value") is not None else "")
                                 + (" (running)" if running else " (stopped)" if sc["stopped"] else " (not started yet)")).classes("text-sm")
        with ui.card().classes("w-full" + (" bg-red-50" if st.escalations else "")):
            ui.label("Needs a person").classes("text-lg font-bold")
            if not st.escalations:
                ui.label("Nothing was escalated.").classes("text-slate-500")
            for e in st.escalations:
                d = e.get("data") if isinstance(e.get("data"), dict) else {}
                with ui.column().classes("gap-0 cursor-pointer").on("click", lambda _, i=e["event_id"]: select_event(i)):
                    ui.label(f"tick {e['tick']} · {d.get('reason') or d.get('incident') or 'human review'}").classes("text-sm text-red-800")
        if st.failures:
            with ui.card().classes("w-full"):
                ui.label("Partner failures").classes("text-lg font-bold")
                for e in st.failures:
                    d = e.get("data") if isinstance(e.get("data"), dict) else {}
                    ui.label(f"tick {e['tick']} · {d.get('partner', '?')}: {d.get('failure', '?')}").classes("text-sm")
                    if d.get("handled"):
                        ui.label(f"handled: {d['handled']}").classes("text-xs text-slate-500")

    def node_card(st: RunState, node_id: str) -> None:
        n = next((x for x in hub.topology.nodes if x.node_id == node_id), None)
        if n is None:
            return
        s = node_status(n, st)
        with ui.card().classes("w-full border-l-4").style(f"border-color:{TRUST_COLORS[s['trust']]}"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(f"{n.node_id} · {n.label}").classes("text-lg font-bold")
                ui.button(icon="close", on_click=lambda: (S.update(node=None), redraw(force=True))).props("flat dense round")
            ui.label(f"{n.zone} · {', '.join(DOMAIN_NAMES.get(d, d) for d in n.domains)}" + (f" · {n.role.replace('_', ' ')}" if n.role != "standard" else "")).classes("text-slate-500 text-sm")
            for sen in n.sensors:
                dv = st.devices.get(sen.device_id)
                with ui.row().classes("items-center gap-2"):
                    _dot(TRUST_COLORS[dv.trust] if dv else TRUST_COLORS["unknown"], ring=True)
                    ui.label(f"{sen.device_id}").classes("text-sm font-mono")
                    ui.label(f"{TRUST_NAMES[dv.trust] if dv else '?'}" + (f" ({dv.score:g})" if dv and dv.score is not None else "")
                             + (f", {dv.cut}" if dv and dv.cut else "") + (f", {dv.corrections} corrected" if dv and dv.corrections else "")).classes("text-sm")
            if n.actuators:
                ui.label("Actuators: " + ", ".join(n.actuators)).classes("text-sm")
            ui.label("Neighbours: " + (", ".join(n.neighbours) or "none")).classes("text-sm text-slate-500")
            mine = [e for e in st.events if _touches(e, n.node_id)][-6:]
            if mine:
                ui.label("Latest events").classes("text-sm font-bold mt-2")
                for e in reversed(mine):
                    ui.label(f"tick {e['tick']} · {e['layer']} · {summarize(e)}").classes("text-xs cursor-pointer").on("click", lambda _, i=e["event_id"]: select_event(i))

    def event_card(st: RunState, e: Event) -> None:
        with ui.card().classes("w-full border-l-4 border-sky-500"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(f"{e['layer']} · {e['event_type']}").classes("text-lg font-bold")
                ui.button(icon="close", on_click=lambda: (S.update(event=None), redraw(force=True))).props("flat dense round")
            ui.label(f"tick {e['tick']} · {e.get('timestamp', '')}").classes("text-slate-500 text-sm")
            ui.label(summarize(e)).classes("text-sm")
            causes = st.causes.get(e["event_id"], [])
            if causes:
                ui.label("Came from: " + ", ".join(f"{st.by_id[c]['layer']} {st.by_id[c]['event_type']}" for c in causes if c in st.by_id)).classes("text-sm")
            ui.code(json.dumps(e.get("data"), indent=2, ensure_ascii=False)[:2500], language="json").classes("w-full text-xs")

    # -------------------------------------------------------------- header
    with ui.header().classes("items-center bg-slate-800 text-white gap-4 px-4 py-2"):
        ui.label("Triplet 04 · Twin layer · live timeline").classes("text-lg font-bold")
        run_select = ui.select([], label="Run", on_change=lambda e: (S.update(run=e.value, node=None, event=None), redraw(force=True))) \
            .props("dense outlined dark options-dark").classes("w-48")
        status_chip = ui.chip("", icon="radio_button_unchecked").props("dense")
        sample_chip = ui.chip("SAMPLE DATA: the Guardian and Brain events are made up", color="amber").props("dense text-color=black")
        ui.space()
        tick_label = ui.label("").classes("font-mono")
        counts_label = ui.label("").classes("text-sm opacity-80")

    warn = ui.label("").classes("w-full bg-amber-100 text-amber-900 px-4 py-2 text-sm")
    empty = ui.column().classes("w-full items-center p-8")
    with empty:
        ui.icon("hourglass_empty", size="xl").classes("text-slate-400")
        ui.label("Waiting for run logs").classes("text-xl text-slate-600")
        ui.label("Looking in: " + (", ".join(str(src) for src in hub.follower.sources) or "nowhere (no sources set)")).classes("text-slate-500 text-sm")
        ui.label("Start the Twin and run a scenario, or look at made-up data with:  python -m twin.dashboard --sample").classes("text-slate-500 text-sm")

    # -------------------------------------------------------------- body
    body = ui.column().classes("w-full gap-3 p-3")
    with body:
        with ui.row().classes("w-full no-wrap gap-3 items-start"):
            with ui.card().classes("w-2/3 p-2"):
                with ui.row().classes("w-full items-center gap-4 px-2"):
                    ui.label("City map").classes("text-lg font-bold")
                    ui.switch("Neighbour links", value=False, on_change=lambda e: (S.update(edges=e.value), redraw(force=True)))
                    ui.switch("Show injected attacks", value=True, on_change=lambda e: (S.update(attacks=e.value), redraw(force=True)))
                    ui.label("click a node for details").classes("text-slate-500 text-sm")
                city_img = ui.interactive_image(size=(1920, 1080), content="", events=["click"], sanitize=False,
                                                on_mouse=lambda e: pick("city", e)).classes("w-full")
                with ui.row().classes("w-full items-center gap-x-4 gap-y-1 px-2 text-sm"):
                    for dom, col in DOMAIN_COLORS.items():
                        with ui.row().classes("items-center gap-1"):
                            _dot(col)
                            ui.label(DOMAIN_NAMES[dom])
                    ui.label("|").classes("text-slate-300")
                    for k, col in TRUST_COLORS.items():
                        with ui.row().classes("items-center gap-1"):
                            _dot(col, ring=True)
                            ui.label(TRUST_NAMES[k])
                    with ui.row().classes("items-center gap-1"):
                        _dot(ISOLATED_COLOR, ring=True, dashed=True)
                        ui.label("Isolated")
                    with ui.row().classes("items-center gap-1"):
                        _dot(QUARANTINE_COLOR, ring=True, dashed=True)
                        ui.label("Quarantined (Q)")
                    ui.label("Split colour = shared node. Square = call place. Hexagon = dispatch centre. Red triangle = attack running.").classes("text-slate-500")
            with ui.column().classes("w-1/3 gap-3"):
                side()

        with ui.card().classes("w-full p-2"):
            with ui.row().classes("w-full items-center gap-4 px-2"):
                ui.label("Timeline: reading → verdict → decision → action").classes("text-lg font-bold")
                ui.select(WINDOWS, value=S["window"], on_change=lambda e: (S.update(window=e.value), redraw(force=True))).props("dense outlined").classes("w-40")
                ui.switch("Follow live", value=True, on_change=lambda e: follow_changed(e.value))
                slider = ui.slider(min=0, max=1, value=0, on_change=lambda e: slide(e.value)).props("label").classes("w-64")
                slider.set_visibility(False)
                ui.label("click an event to follow its chain").classes("text-slate-500 text-sm")
            timeline_img = ui.interactive_image(size=(1800, 660), content="", events=["click"], sanitize=False,
                                                on_mouse=lambda e: pick("timeline", e)).classes("w-full")

        with ui.card().classes("w-full p-2"):
            ui.label("All events (newest first)").classes("text-lg font-bold px-2")
            columns = [{"name": "time", "label": "Sim time", "field": "time", "align": "left"},
                       {"name": "tick", "label": "Tick", "field": "tick", "align": "right"},
                       {"name": "layer", "label": "Layer", "field": "layer", "align": "left"},
                       {"name": "type", "label": "Type", "field": "type", "align": "left"},
                       {"name": "what", "label": "What happened", "field": "what", "align": "left"}]
            table = ui.table(columns=columns, rows=[], row_key="id", pagination=15).classes("w-full")
            table.on("rowClick", lambda e: select_event(e.args[1]["id"]))
    ui.label("Reads run logs only. Trust cut-offs are placeholders until Guardian publishes its own.").classes("text-xs text-slate-400 px-4 pb-2")

    ui.timer(hub.cfg.refresh_seconds, redraw)
    redraw(force=True)


def _touches(e: Event, node_id: str) -> bool:
    d = e.get("data") if isinstance(e.get("data"), dict) else {}
    if d.get("node_id") == node_id or node_id in as_list(d.get("targets")):
        return True
    ids = [d.get("device_id")] + as_list(d.get("changed")) + [c.get("device_id") for c in as_list(d.get("corrections")) if isinstance(c, dict)]
    return any(isinstance(i, str) and i.split(".")[0] == node_id for i in ids)

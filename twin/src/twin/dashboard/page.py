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
from .nodes import glyph
from .style import BG, DIM, DOMAIN_COLORS, DOMAIN_NAMES, LANE_OF_TYPE, LANES, LINE, PANEL, TEXT, TRUST_COLORS, TRUST_NAMES
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


CSS = f"""
body, .q-page, .nicegui-content {{ background:{BG} !important; color:{TEXT}; }}
.q-header {{ background:{PANEL} !important; border-bottom:1px solid {LINE}; }}
.q-card {{ background:{PANEL} !important; color:{TEXT}; border:1px solid {LINE}; box-shadow:none !important; border-radius:10px; }}
.text-dim {{ color:{DIM}; }}
.warnbar {{ background:#3A2A0B; color:#FBBF24; }}
.step {{ border:1px solid {LINE}; border-radius:999px; padding:2px 12px; font-size:13px; }}
.step-on {{ color:{TEXT}; }}
.step-off {{ color:{DIM}; opacity:.7; }}
.q-table__card, .q-table {{ background:transparent !important; color:{TEXT}; }}
"""


def legend_svg() -> str:
    """The legend is drawn with the real node pictures, so it can never disagree with the map."""
    items = [("Trusted", "trusted"), ("Degraded", "degraded"), ("Untrusted", "untrusted"), ("Isolated", "isolated")]
    out, x = [], 24
    for label, st in items:
        out.append(glyph(x + 14, 20, 28, ["water"], st, None))
        out.append(f'<text x="{x + 38}" y="26" font-size="14" fill="{TEXT}">{label}</text>')
        x += 38 + 9 * len(label) + 26
    out.append(glyph(x + 14, 20, 28, ["water", "power"], "trusted", None))
    out.append(f'<text x="{x + 38}" y="26" font-size="14" fill="{TEXT}">Shared node (two colours)</text>')
    x += 38 + 9 * 26 + 26
    out.append(glyph(x + 14, 20, 28, ["water"], "trusted", None, unknown=True))
    out.append(f'<text x="{x + 38}" y="26" font-size="14" fill="{TEXT}">No verdict yet</text>')
    x += 38 + 9 * 14 + 10
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x} 40" width="{x}" height="40" font-family="DejaVu Sans, Arial, sans-serif">{"".join(out)}</svg>'


def _dot(color: str, ring: bool = False, dashed: bool = False) -> None:
    style = f"border:3px {'dashed' if dashed else 'solid'} {color};background:{BG}" if ring else f"background:{color}"
    ui.element("div").classes("w-3 h-3 rounded-full inline-block").style(style)


def build_page(hub: Hub) -> None:
    ui.dark_mode(True)
    ui.add_css(CSS)
    ui.colors(primary="#00D4FF")
    S: dict[str, Any] = {"run": None, "node": None, "event": None, "window": hub.cfg.window_ticks, "follow": True, "end": None,
                         "edges": False, "attacks": True, "seen": None, "hidden": set()}
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

    layer_btns: dict[str, Any] = {}
    step_chips: list[Any] = []

    def style_layer(dom: str) -> None:
        on = dom not in S["hidden"]
        col = DOMAIN_COLORS[dom]
        layer_btns[dom].style(f"border:1px solid {col if on else LINE};color:{col if on else DIM};opacity:{1 if on else .55};padding:0 10px")

    def toggle_layer(dom: str) -> None:
        S["hidden"] ^= {dom}
        style_layer(dom)
        redraw(force=True)

    # -------------------------------------------------------------- redraw
    def redraw(force: bool = False) -> None:
        hub.poll()
        ids = hub.run_ids()
        st = state()
        key = (hub.follower.version, S["run"], S["node"], S["event"], S["window"], S["follow"], S["end"], S["edges"], S["attacks"], frozenset(S["hidden"]))
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
        per_lane = [0] * len(LANES)
        for e in st.events:
            k = LANE_OF_TYPE.get(e["event_type"])
            if k is not None:
                per_lane[k] += 1
        for i, chip in enumerate(step_chips):
            chip.set_text(f"{LANES[i]['title']} · {per_lane[i]}" + ("" if per_lane[i] else f"  (waiting for {LANES[i]['who']})"))
            chip.classes(replace="step " + ("step-on" if per_lane[i] else "step-off"))
        if not S["follow"]:
            slider.props(f"min=0 max={st.tick}")
        c = city_scene(hub.topology, hub.layout, st, selected=S["node"], show_edges=S["edges"], show_attacks=S["attacks"], hidden=set(S["hidden"]))
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
                ui.label("None started in this run.").classes("text-dim")
            for sc in st.scenarios:
                for f in sc["faults"]:
                    running = sc["scenario_id"] in {a["scenario_id"] for a in attacks}
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("warning" if running else "check_circle", color="red" if running else "grey").classes("text-lg")
                        ui.label(f"{sc['name']} on {f['device_id']}" + (f" = {f['value']:g}" if f.get("value") is not None else "")
                                 + (" (running)" if running else " (stopped)" if sc["stopped"] else " (not started yet)")).classes("text-sm")
        with ui.card().classes("w-full" + (" border-red-500" if st.escalations else "")):
            ui.label("Needs a person").classes("text-lg font-bold")
            if not st.escalations:
                ui.label("Nothing was escalated.").classes("text-dim")
            for e in st.escalations:
                d = e.get("data") if isinstance(e.get("data"), dict) else {}
                with ui.column().classes("gap-0 cursor-pointer").on("click", lambda _, i=e["event_id"]: select_event(i)):
                    ui.label(f"tick {e['tick']} · {d.get('reason') or d.get('incident') or 'human review'}").classes("text-sm").style("color:#FF5A5F")
        if st.failures:
            with ui.card().classes("w-full"):
                ui.label("Partner failures").classes("text-lg font-bold")
                for e in st.failures:
                    d = e.get("data") if isinstance(e.get("data"), dict) else {}
                    ui.label(f"tick {e['tick']} · {d.get('partner', '?')}: {d.get('failure', '?')}").classes("text-sm")
                    if d.get("handled"):
                        ui.label(f"handled: {d['handled']}").classes("text-xs text-dim")

    def node_card(st: RunState, node_id: str) -> None:
        n = next((x for x in hub.topology.nodes if x.node_id == node_id), None)
        if n is None:
            return
        s = node_status(n, st)
        with ui.card().classes("w-full border-l-4").style(f"border-color:{TRUST_COLORS[s['trust']]}"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label(f"{n.node_id} · {n.label}").classes("text-lg font-bold")
                ui.button(icon="close", on_click=lambda: (S.update(node=None), redraw(force=True))).props("flat dense round")
            ui.label(f"{n.zone} · {', '.join(DOMAIN_NAMES.get(d, d) for d in n.domains)}" + (f" · {n.role.replace('_', ' ')}" if n.role != "standard" else "")).classes("text-dim text-sm")
            for sen in n.sensors:
                dv = st.devices.get(sen.device_id)
                with ui.row().classes("items-center gap-2"):
                    _dot(TRUST_COLORS[dv.trust] if dv else TRUST_COLORS["unknown"], ring=True)
                    ui.label(f"{sen.device_id}").classes("text-sm font-mono")
                    ui.label(f"{TRUST_NAMES[dv.trust] if dv else '?'}" + (f" ({dv.score:g})" if dv and dv.score is not None else "")
                             + (f", {dv.cut}" if dv and dv.cut else "") + (f", {dv.corrections} corrected" if dv and dv.corrections else "")).classes("text-sm")
            if n.actuators:
                ui.label("Actuators: " + ", ".join(n.actuators)).classes("text-sm")
            ui.label("Neighbours: " + (", ".join(n.neighbours) or "none")).classes("text-sm text-dim")
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
            ui.label(f"tick {e['tick']} · {e.get('timestamp', '')}").classes("text-dim text-sm")
            ui.label(summarize(e)).classes("text-sm")
            causes = st.causes.get(e["event_id"], [])
            if causes:
                ui.label("Came from: " + ", ".join(f"{st.by_id[c]['layer']} {st.by_id[c]['event_type']}" for c in causes if c in st.by_id)).classes("text-sm")
            ui.code(json.dumps(e.get("data"), indent=2, ensure_ascii=False)[:2500], language="json").classes("w-full text-xs")

    # -------------------------------------------------------------- header
    with ui.header().classes("items-center text-white gap-4 px-4 py-2"):
        ui.label("Triplet 04 · Twin · city and timeline").classes("text-lg font-bold")
        run_select = ui.select([], label="Run", on_change=lambda e: (S.update(run=e.value, node=None, event=None), redraw(force=True))) \
            .props("dense outlined dark options-dark").classes("w-48")
        status_chip = ui.chip("", icon="radio_button_unchecked").props("dense")
        sample_chip = ui.chip("SAMPLE DATA: the Guardian and Brain events are made up", color="amber").props("dense text-color=black")
        ui.space()
        tick_label = ui.label("").classes("font-mono")
        counts_label = ui.label("").classes("text-sm opacity-80")

    warn = ui.label("").classes("w-full warnbar px-4 py-2 text-sm")
    empty = ui.column().classes("w-full items-center p-8")
    with empty:
        ui.icon("hourglass_empty", size="xl").classes("text-dim")
        ui.label("Waiting for a run").classes("text-xl")
        ui.label("The map and timeline fill in when something happens. A quiet Twin writes almost nothing, on purpose: normal readings are not logged.").classes("text-dim text-sm")
        ui.label("To see it work, start a scenario:").classes("text-dim text-sm")
        ui.code('python mocks/example_client.py --key dev-scenario-key-change-me --tool run_scenario --args \'{"name": "fake_reading"}\'', language="bash")
        ui.label("or look at made-up data with:  python -m twin.dashboard --sample").classes("text-dim text-sm")
        ui.label("Looking in: " + (", ".join(str(src) for src in hub.follower.sources) or "nowhere (no sources set)")).classes("text-dim text-xs")

    # -------------------------------------------------------------- body
    body = ui.column().classes("w-full gap-3 p-3")
    with body:
        with ui.row().classes("w-full no-wrap gap-3 items-start"):
            with ui.card().classes("w-2/3 p-2"):
                with ui.row().classes("w-full items-center gap-3 px-2"):
                    ui.label("City map").classes("text-lg font-bold")
                    with ui.row().classes("items-center gap-1"):
                        ui.label("Layers").classes("text-dim text-sm")
                        doms = [d for d in DOMAIN_COLORS if any(d in n.domains for n in hub.topology.nodes)]
                        for dom in doms:
                            layer_btns[dom] = ui.button(DOMAIN_NAMES[dom], on_click=lambda _, d=dom: toggle_layer(d)).props("flat dense no-caps size=sm")
                            style_layer(dom)
                    ui.space()
                    ui.switch("Connections", value=False, on_change=lambda e: (S.update(edges=e.value), redraw(force=True)))
                    ui.switch("Attacks", value=True, on_change=lambda e: (S.update(attacks=e.value), redraw(force=True)))
                city_img = ui.interactive_image(size=(1920, 1080), content="", events=["click"], sanitize=False,
                                                on_mouse=lambda e: pick("city", e)).classes("w-full")
                ui.html(legend_svg(), sanitize=False).classes("px-2")
                ui.label("Click a node for details. The shape of a node is its trust. A pulsing red ring with ! = an attack is running there. "
                         "Q = quarantined. Dimmer nodes: Guardian has not judged them yet.").classes("text-dim text-xs px-2")
            with ui.column().classes("w-1/3 gap-3"):
                side()

        with ui.card().classes("w-full p-2"):
            with ui.row().classes("w-full items-center gap-4 px-2"):
                ui.label("Timeline").classes("text-lg font-bold")
                with ui.row().classes("items-center gap-1"):
                    for i, lane in enumerate(LANES):
                        if i:
                            ui.label("→").classes("text-dim")
                        step_chips.append(ui.label(lane["title"]).classes("step step-off"))
                ui.select(WINDOWS, value=S["window"], on_change=lambda e: (S.update(window=e.value), redraw(force=True))).props("dense outlined dark options-dark").classes("w-40")
                ui.switch("Follow live", value=True, on_change=lambda e: follow_changed(e.value))
                slider = ui.slider(min=0, max=1, value=0, on_change=lambda e: slide(e.value)).props("label").classes("w-64")
                slider.set_visibility(False)
                ui.label("click an event to follow its chain").classes("text-dim text-sm")
            timeline_img = ui.interactive_image(size=(1800, 660), content="", events=["click"], sanitize=False,
                                                on_mouse=lambda e: pick("timeline", e)).classes("w-full")

        with ui.card().classes("w-full p-2"):
            ui.label("All events (newest first)").classes("text-lg font-bold px-2")
            columns = [{"name": "time", "label": "Sim time", "field": "time", "align": "left"},
                       {"name": "tick", "label": "Tick", "field": "tick", "align": "right"},
                       {"name": "layer", "label": "Layer", "field": "layer", "align": "left"},
                       {"name": "type", "label": "Type", "field": "type", "align": "left"},
                       {"name": "what", "label": "What happened", "field": "what", "align": "left"}]
            table = ui.table(columns=columns, rows=[], row_key="id", pagination=15).props("dark flat dense").classes("w-full")
            table.on("rowClick", lambda e: select_event(e.args[1]["id"]))
    ui.label("Reads run logs only. Trust cut-offs are placeholders until Guardian publishes its own.").classes("text-xs text-dim px-4 pb-2")

    ui.timer(hub.cfg.refresh_seconds, redraw)
    redraw(force=True)


def _touches(e: Event, node_id: str) -> bool:
    d = e.get("data") if isinstance(e.get("data"), dict) else {}
    if d.get("node_id") == node_id or node_id in as_list(d.get("targets")):
        return True
    ids = [d.get("device_id")] + as_list(d.get("changed")) + [c.get("device_id") for c in as_list(d.get("corrections")) if isinstance(c, dict)]
    return any(isinstance(i, str) and i.split(".")[0] == node_id for i in ids)

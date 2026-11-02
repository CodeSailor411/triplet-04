"""Drawing: the city map and the timeline lanes, as SVG text.

Pure functions: data in, SVG out, nothing else. That keeps them testable (no browser needed) and easy to look at
(the tests can turn them into pictures). Every piece of text that comes from a log is escaped before it goes into the SVG,
because logs can hold anything (a partner's reason text, a device name with odd characters).
"""
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from typing import Any

from ..models import Layout, Node, Topology
from .events import Event, RunState, format_wall, is_system, node_status, short_label, summarize
from .basemap import basemap
from .nodes import glyph
from .style import (ATTACK_COLOR, DOMAIN_COLORS, FONT, BG, DIM, LAND, MAP_BG, LANE_OF_TYPE, LANES, LINE, PANEL, PANEL_2, RUN_STRIP_TYPES, TEXT)

NODE_W = 58             # width of a node on the 1920-pixel-wide map (about 32 px on a normal screen, the spec's minimum is 24)
MIN_GAP = 87            # 1.5 x the node width (spec section 5). Nodes closer than this are pushed apart ON SCREEN ONLY, the city data is never changed


def display_positions(topology: Topology) -> dict[str, tuple[float, float]]:
    """Where to draw each node. The city data is never changed. A few nodes sit very close, so those are pushed apart a little."""
    pos = {n.node_id: [n.x, n.y] for n in topology.nodes}
    ids = list(pos)
    for _ in range(60):
        moved = False
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                dx, dy = pos[b][0] - pos[a][0], pos[b][1] - pos[a][1]
                d = math.hypot(dx, dy)
                if d < MIN_GAP:
                    ux, uy = (dx / d, dy / d) if d > 0.01 else (1.0, 0.0)
                    push = (MIN_GAP - d) / 2
                    pos[a][0] -= ux * push; pos[a][1] -= uy * push
                    pos[b][0] += ux * push; pos[b][1] += uy * push
                    moved = True
        if not moved:
            break
    return {k: (round(v[0], 1), round(v[1], 1)) for k, v in pos.items()}


def esc(x: Any) -> str:
    return escape(str(x), quote=True)


def document(content: str, width: float, height: float) -> str:
    """A full SVG file around the inner content (the app only needs the inner part, tests and pictures need the whole file)."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" width="{width:g}" height="{height:g}" '
            f'font-family="{FONT}">{content}</svg>')


@dataclass
class Scene:
    content: str
    width: float
    height: float
    hits: list[tuple[str, float, float]] = field(default_factory=list)     # (id, x, y) of things you can click

    def nearest(self, x: float, y: float, max_dist: float) -> str | None:
        best = min(self.hits, key=lambda h: (h[1] - x) ** 2 + (h[2] - y) ** 2, default=None)
        if best and math.hypot(best[1] - x, best[2] - y) <= max_dist:
            return best[0]
        return None


# ====================================================================== city map
def trust_state(s: dict[str, Any]) -> str:
    """Which of the four node shapes: isolated (also for quarantined and partly cut nodes), untrusted, degraded, trusted."""
    if s["cut"]:
        return "isolated"
    return s["trust"] if s["trust"] in ("degraded", "untrusted") else "trusted"


def city_scene(topology: Topology, layout: Layout, state: RunState, selected: str | None = None,
               show_edges: bool = False, show_attacks: bool = True, hidden: set[str] | None = None) -> Scene:
    """The map. `hidden` = domains whose layer is switched off: their nodes turn dim grey but stay in place (an isolated node keeps its lock)."""
    w, h = topology.canvas.width, topology.canvas.height
    xy = display_positions(topology)
    out = [basemap([xy[n.node_id] for n in topology.nodes], w, h)]                  # one connected city drawn around the node positions
    all_domains = {d for n in topology.nodes for d in n.domains}
    active = all_domains - (hidden or set())
    by_id = {n.node_id: n for n in topology.nodes}
    for a, b in topology.edges:                                                  # connection lines: all on request, always for the selected node
        mine = selected in (a, b)
        if (show_edges or mine) and a in by_id and b in by_id:
            live = any(d in active for d in by_id[a].domains) and any(d in active for d in by_id[b].domains)
            out.append(f'<line x1="{xy[a][0]:.1f}" y1="{xy[a][1]:.1f}" x2="{xy[b][0]:.1f}" y2="{xy[b][1]:.1f}" stroke="{TEXT if mine else LAND}" '
                       f'stroke-width="{4 if mine else 2}" opacity="{0.9 if mine else (0.32 if live else 0.1)}"/>')
    hits = []
    labels = []
    for n in topology.nodes:
        s = node_status(n, state)
        cx, cy = xy[n.node_id]
        hits.append((n.node_id, cx, cy))
        shape = trust_state(s)
        attack = bool(s["attack"]) and show_attacks
        g = [f'<g data-node="{esc(n.node_id)}"><title>{esc(n.node_id)} ({esc(n.label)}), {esc(", ".join(n.domains))}, trust: {esc(s["trust"])}'
             f'{", " + esc(s["cut"]) if s["cut"] else ""}{", ATTACK" if attack else ""}</title>']
        if selected == n.node_id:
            g.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{NODE_W * 0.82:.1f}" fill="{TEXT}" fill-opacity="0.08" stroke="{TEXT}" stroke-width="3" stroke-dasharray="10 8"/>')
        if attack:                                                               # a pulsing ring around a node that is being attacked
            g.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{NODE_W * 0.7:.1f}" fill="none" stroke="{ATTACK_COLOR}" stroke-width="4">'
                     f'<animate attributeName="r" values="{NODE_W * 0.62:.0f};{NODE_W * 0.95:.0f}" dur="1.6s" repeatCount="indefinite"/>'
                     f'<animate attributeName="opacity" values="0.9;0" dur="1.6s" repeatCount="indefinite"/></circle>')
        g.append(glyph(cx, cy, NODE_W, n.domains, shape, active, unknown=(s["trust"] == "unknown" and not s["cut"]), fill=MAP_BG))
        if s["cut"] == "quarantined":
            g.append(f'<circle cx="{cx + NODE_W * 0.5:.1f}" cy="{cy + NODE_W * 0.45:.1f}" r="11" fill="{MAP_BG}" stroke="{TEXT}" stroke-width="2.5"/>'
                     f'<text x="{cx + NODE_W * 0.5:.1f}" y="{cy + NODE_W * 0.45 + 7:.1f}" font-size="18" font-weight="bold" fill="{TEXT}" text-anchor="middle">Q</text>')
        if attack:
            tx, ty = cx + NODE_W * 0.55, cy - NODE_W * 0.6
            g.append(f'<polygon points="{tx:.1f},{ty - 15:.1f} {tx + 14:.1f},{ty + 11:.1f} {tx - 14:.1f},{ty + 11:.1f}" fill="{ATTACK_COLOR}" stroke="{MAP_BG}" stroke-width="2"/>'
                     f'<text x="{tx:.1f}" y="{ty + 8:.1f}" font-size="17" font-weight="bold" fill="{MAP_BG}" text-anchor="middle">!</text>')
        g.append("</g>")
        out.append("".join(g))
        if selected == n.node_id or attack or s["cut"] or s["trust"] in ("degraded", "untrusted"):      # names only where something is going on
            ly = cy + NODE_W * 0.5 + 30
            labels.append(f'<text x="{cx:.1f}" y="{ly:.1f}" font-size="24" font-weight="bold" text-anchor="middle" fill="{MAP_BG}" stroke="{MAP_BG}" '
                          f'stroke-width="7" stroke-linejoin="round">{esc(n.node_id)}</text>'
                          f'<text x="{cx:.1f}" y="{ly:.1f}" font-size="24" font-weight="bold" text-anchor="middle" fill="{TEXT}">{esc(n.node_id)}</text>')
    out.extend(labels)
    return Scene("".join(out), w, h, hits)


# ====================================================================== timeline
def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def tick_clock(events: list[Event]):
    """tick -> 'HH:MM:SS' of simulated time, fitted on the first and last event (the simulated clock is a straight line)."""
    pts = [(e["tick"], _parse(e.get("timestamp", ""))) for e in events]
    pts = [(t, d) for t, d in pts if d]
    if len(pts) < 2 or pts[0][0] == pts[-1][0]:
        return lambda t: ""
    (t0, d0), (t1, d1) = pts[0], pts[-1]
    step = (d1 - d0) / (t1 - t0)
    return lambda t: (d0 + step * (t - t0)).strftime("%H:%M:%S")


def chain_of(state: RunState, event_id: str | None) -> set[str]:
    """The selected event plus everything it came from and everything that came from it."""
    if not event_id or event_id not in state.by_id:
        return set()
    children: dict[str, list[str]] = {}
    for eid, causes in state.causes.items():
        for c in causes:
            children.setdefault(c, []).append(eid)
    seen, todo = {event_id}, [event_id]
    while todo:                                                    # up: causes
        cur = todo.pop()
        for c in state.causes.get(cur, []):
            if c in state.by_id and c not in seen:
                seen.add(c); todo.append(c)
    todo = [event_id]
    while todo:                                                    # down: effects
        cur = todo.pop()
        for c in children.get(cur, []):
            if c not in seen:
                seen.add(c); todo.append(c)
    return seen


def _glyph(e: Event, x: float, y: float, color: str) -> str:
    t, d = e["event_type"], e.get("data") if isinstance(e.get("data"), dict) else {}
    if t == "containment":
        ok = d.get("status") == "applied"
        return f'<polygon points="{x},{y - 15} {x + 15},{y} {x},{y + 15} {x - 15},{y}" fill="{color if ok else "#3B1219"}" stroke="{color if ok else "#FF5A5F"}" stroke-width="3"/>'
    if t == "escalation":
        return (f'<circle cx="{x}" cy="{y}" r="16" fill="#FF5A5F" stroke="{PANEL}" stroke-width="2"/>'
                f'<text x="{x}" y="{y + 7}" font-size="22" font-weight="bold" fill="{PANEL}" text-anchor="middle">!</text>')
    if t == "action":
        ok = d.get("status") == "committed"
        return f'<circle cx="{x}" cy="{y}" r="13" fill="{color if ok else "#3B1219"}" stroke="{color if ok else "#FF5A5F"}" stroke-width="3.5"/>'
    if t == "decision":
        return f'<rect x="{x - 13}" y="{y - 13}" width="26" height="26" rx="6" fill="{color}" stroke="{PANEL}" stroke-width="2"/>'
    if t == "reading":                                             # the Twin only logs readings a fault touched
        return f'<circle cx="{x}" cy="{y}" r="12" fill="{color}" stroke="{ATTACK_COLOR}" stroke-width="3.5"/>'
    return f'<circle cx="{x}" cy="{y}" r="12" fill="{color}" stroke="{PANEL}" stroke-width="2"/>'


LABEL_ROWS = 2              # label rows under the glyphs of one lane (the lane is 128 high: a third row would hang out of it)
CHAR_W = 10.0               # about how wide one character of a label is at font size 17 (Inter), used to stop labels from overlapping


def timeline_scene(state: RunState, selected: str | None = None, window_ticks: int = 60, end_tick: int | None = None,
                   width: int = 1800, labels: bool = False, show_system: bool = False) -> Scene:
    """The four-lane timeline.

    labels=False (default): glyphs only, no text under them. The text appears for the selected event and everything in its chain,
    and in the hover text of every glyph. labels=True: every glyph gets a label if there is room (a label that would overlap another
    one is left out; its hover text stays). show_system=True also draws the Twin's own start / run started / run ended markers.

    Layout: the lane titles live in a fixed column on the left (0 to `left`). Everything that belongs to the plot is drawn inside a
    clip rectangle that starts at `left`, so nothing can spill over the titles or off the edge of the picture."""
    left, right, top, strip, lane_h, bottom = 200, 60, 64, 60, 128, 24
    plot_left = left + 34                                           # first tick sits a little right of the column, so its glyph is not cut
    height = top + strip + lane_h * len(LANES) + bottom
    end = state.tick if end_tick is None else end_tick
    if window_ticks <= 0:                                           # 0 = show the whole run
        start = min((e["tick"] for e in state.events), default=0)
    else:
        start = max(0, end - window_ticks)
    span = max(1, end - start)
    plot = width - plot_left - right

    def x_of(t: float) -> float:
        return round(plot_left + (t - start) / span * plot, 1)

    clock, chain = tick_clock(state.events), chain_of(state, selected)
    dim = lambda eid: bool(chain) and eid not in chain               # noqa: E731
    out = ['<defs><marker id="tl-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           '<path d="M0,0 L10,5 L0,10 z" fill="#6E6E6E"/></marker>'
           f'<clipPath id="tl-clip"><rect x="{left}" y="0" width="{width - left}" height="{height}"/></clipPath></defs>',
           f'<rect width="{width}" height="{height}" fill="{PANEL}"/>']

    # lanes: background bands, titles (fixed column), gridlines
    ys = {}
    for i, lane in enumerate(LANES):
        y0 = top + strip + i * lane_h
        ys[i] = y0 + lane_h / 2
        out.append(f'<rect x="0" y="{y0}" width="{width}" height="{lane_h}" fill="{PANEL if i % 2 == 0 else PANEL_2}"/>'
                   f'<rect x="0" y="{y0}" width="10" height="{lane_h}" fill="{lane["color"]}"/>'
                   f'<text x="28" y="{ys[i] - 4}" font-size="28" font-weight="bold" fill="{TEXT}">{esc(lane["title"])}</text>'
                   f'<text x="28" y="{ys[i] + 26}" font-size="22" fill="{DIM}">{esc(lane["who"])}</text>')
    step = next((s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000) if span / s <= 9), 1000)
    first = (start // step) * step
    out.append(f'<text x="{left - 20}" y="22" font-size="20" fill="{DIM}" text-anchor="end">tick</text>')
    for t in range(first, end + 1, step):
        if t < start:
            continue
        x = x_of(t)
        out.append(f'<line x1="{x}" y1="{top - 8}" x2="{x}" y2="{top + strip + lane_h * len(LANES)}" stroke="{LINE}" stroke-width="2"/>'
                   f'<text x="{x}" y="24" font-size="22" font-weight="bold" fill="#D2D2D2" text-anchor="middle">{t}</text>'
                   f'<text x="{x if x - 46 >= left else left + 6}" y="48" font-size="18" fill="#6E6E6E" '
                   f'text-anchor="{"middle" if x - 46 >= left else "start"}">{esc(clock(t))}</text>')       # the first time label must not run under the lane column
    out.append(f'<rect x="0" y="0" width="{left}" height="{top + strip}" fill="{PANEL}"/>')          # keeps the left column clean at the top too
    out.append(f'<text x="{left - 20}" y="22" font-size="20" fill="{DIM}" text-anchor="end">tick</text>')

    # which events are inside the window (system events only when asked for)
    shown = [e for e in state.events if start <= e["tick"] <= end and (show_system or not is_system(e))]
    linked = {i for i, c in state.causes.items() for i in [i, *c]}          # events that have an arrow in or out
    pos: dict[str, tuple[float, float]] = {}
    clusters: dict[tuple[int, int], list[Event]] = {}                       # events of one lane on one tick with no arrow collapse into one count bubble
    groups: dict[tuple, list[Event]] = {}
    for e in shown:
        t = e["event_type"]
        if is_system(e):                                                      # a system marker sits exactly on its tick and takes no slot
            pos[e["event_id"]] = (x_of(e["tick"]), top + strip / 2)
            continue
        lane = -1 if t in RUN_STRIP_TYPES else LANE_OF_TYPE.get(t)
        if lane is None:
            continue
        groups.setdefault((lane, e["tick"]), []).append(e)
    for (lane, tick), evs in groups.items():
        loose = [e for e in evs if e["event_id"] not in linked and e["event_id"] != selected and lane >= 0]
        if len(loose) > 1:
            clusters[(lane, tick)] = loose
            evs = [e for e in evs if e not in loose]
        n = len(evs) + (1 if (lane, tick) in clusters else 0)
        slots = [(k - (n - 1) / 2) * 34 for k in range(n)]                    # side by side, centred on the tick
        for k, e in enumerate(evs):
            pos[e["event_id"]] = (round(x_of(tick) + slots[k], 1), top + strip / 2 if lane == -1 else ys[lane])
        if (lane, tick) in clusters:
            for e in clusters[(lane, tick)]:
                pos[e["event_id"]] = (round(x_of(tick) + slots[-1], 1), ys[lane])
    clustered = {e["event_id"] for evs in clusters.values() for e in evs}

    body: list[str] = []                                                      # everything inside the clip rectangle

    # arrows first, so glyphs sit on top
    for e in shown:
        for c in state.causes.get(e["event_id"], []):
            if c in pos and e["event_id"] in pos and c != e["event_id"]:
                (x1, y1), (x2, y2) = pos[c], pos[e["event_id"]]
                if y1 == y2 == top + strip / 2:
                    continue                                                  # start and stop of a scenario: no arrow across the strip
                x1, x2 = x1 + (17 if x2 >= x1 else -17), x2 - (19 if x2 >= x1 else -19)       # stop at the edge of the glyphs
                dx = max(30.0, abs(x2 - x1) / 2)
                faded = bool(chain) and not (c in chain and e["event_id"] in chain)
                body.append(f'<path d="M{x1},{y1} C{x1 + dx:.1f},{y1} {x2 - dx:.1f},{y2} {x2},{y2}" fill="none" stroke="{TEXT if chain and not faded else "#6E6E6E"}" '
                            f'stroke-width="{3.5 if chain and not faded else 2.5}" marker-end="url(#tl-arrow)" opacity="{0.15 if faded else 0.9}"/>')

    hits = []
    taken: dict[tuple, list[tuple[float, float]]] = {}                        # (lane, row) -> x ranges already used by a label
    strip_y = (top + 22, top + 44)                                            # the two text rows of the run strip

    def place_strip(x: float, text: str) -> tuple[int, str, float] | None:
        """Where the text of a run-strip marker goes: to the right of its flag, or to the left near the right edge. Two rows;
        None = no room (the marker keeps its hover text). This is what stops 'run started' and 'twin started' from piling up."""
        w = len(text) * CHAR_W * 18 / 17                                      # strip text is 18 px, the lane labels 17
        lo, anchor, tx = (x - 24 - w, "end", x - 24) if x + 24 + w > width - 8 else (x + 24, "start", x + 24)
        if lo < left + 6:
            return None
        for row in range(len(strip_y)):
            used = taken.setdefault(("strip", row), [])
            if all(lo + w + 8 <= a or lo >= b + 8 for a, b in used):
                used.append((lo, lo + w))
                return row, anchor, tx
        return None

    def place_label(lane: int, x: float, text: str) -> tuple[int, str, float] | None:
        """Pick a label row where the text does not touch another label of the lane. Near the left or right edge the text grows inward
        (anchor start / end) instead of being cut. None = no room, the glyph keeps only its hover text."""
        w = len(text) * CHAR_W
        anchor, lo = ("start", x - 14) if x - w / 2 < left + 6 else ("end", x + 14 - w) if x + w / 2 > width - 8 else ("middle", x - w / 2)
        for row in range(LABEL_ROWS):
            used = taken.setdefault((lane, row), [])
            if all(lo + w + 8 <= a or lo >= b + 8 for a, b in used):
                used.append((lo, lo + w))
                tx = {"start": x - 14, "end": x + 14, "middle": x}[anchor]
                return row, anchor, tx
        return None

    for e in sorted(shown, key=lambda ev: (pos.get(ev["event_id"], (0, 0))[0], ev["tick"])):
        if e["event_id"] not in pos:
            continue
        x, y = pos[e["event_id"]]
        t = e["event_type"]
        opa = 0.22 if dim(e["event_id"]) else 1
        real = format_wall(e)
        title = f'{e["layer"]} {t} @ tick {e["tick"]} {e.get("timestamp", "")}' + (f' (real time {real})' if real else "") + f': {summarize(e)}'
        if t in RUN_STRIP_TYPES:
            hits.append((e["event_id"], x, y))
            if is_system(e):
                continue                                                      # system markers are merged and drawn after this loop
            col = "#FF5A5F" if t == "partner_failure" else "#D2D2D2"
            slot = place_strip(x, short_label(e))
            text = ""
            if slot:
                row, anchor, tx = slot
                text = f'<text x="{tx}" y="{strip_y[row]}" font-size="18" fill="{col}" text-anchor="{anchor}">{esc(short_label(e))}</text>'
            body.append(f'<g opacity="{opa}"><path d="M{x},{y + 14} L{x},{y - 16} L{x + 18},{y - 9} L{x},{y - 2}" fill="{col}" stroke="{col}" stroke-width="3"/>'
                        f'{text}<title>{esc(title)}</title></g>')
            continue
        lane = LANE_OF_TYPE[t]
        color = LANES[lane]["color"]
        sel = e["event_id"] == selected
        halo = f'<circle cx="{x}" cy="{y}" r="24" fill="none" stroke="{TEXT}" stroke-width="4"/>' if sel else ""
        if e["event_id"] in clustered:
            # one glyph for the whole group, drawn once (for the first member)
            members = next(v for v in clusters.values() if e in v)
            if e is members[0]:
                names = ", ".join(summarize(m) for m in members[:8]) + (" ..." if len(members) > 8 else "")
                body.append(f'<g opacity="{opa}"><circle cx="{x}" cy="{y}" r="17" fill="{color}" fill-opacity="0.25" stroke="{color}" stroke-width="3"/>'
                            f'<text x="{x}" y="{y + 7}" font-size="19" font-weight="bold" fill="{color}" text-anchor="middle">{len(members)}</text>'
                            f'<title>{len(members)} events on tick {e["tick"]}: {esc(names)}</title></g>')
                hits.append((e["event_id"], x, y))
            continue
        label = ""
        if labels or chain and not dim(e["event_id"]):
            text = short_label(e)
            slot = place_label(lane, x, text)
            if slot:
                row, anchor, tx = slot
                ty = y + 36 + 18 * row
                label = (f'<text x="{tx}" y="{ty}" font-size="17" fill="#D2D2D2" text-anchor="{anchor}" stroke="{PANEL}" stroke-width="5" '
                         f'stroke-linejoin="round">{esc(text)}</text>'
                         f'<text x="{tx}" y="{ty}" font-size="17" fill="#D2D2D2" text-anchor="{anchor}">{esc(text)}</text>')
        body.append(f'<g opacity="{opa}">{halo}{_glyph(e, x, y, color)}{label}<title>{esc(title)}</title></g>')
        hits.append((e["event_id"], x, y))
    # system markers (Twin started, run started, run ended): markers within 50 px of each other become ONE dashed line with one text
    sys_events = sorted((e for e in shown if is_system(e) and e["event_id"] in pos), key=lambda ev: pos[ev["event_id"]][0])
    groups_x: list[list[Event]] = []
    for e in sys_events:
        if groups_x and pos[e["event_id"]][0] - pos[groups_x[-1][-1]["event_id"]][0] < 50:
            groups_x[-1].append(e)
        else:
            groups_x.append([e])
    sys_svg = []
    for grp in groups_x:
        x = pos[grp[0]["event_id"]][0]
        counts: dict[str, int] = {}
        for e in grp:
            name = str((e.get("data") or {}).get("phase", "")).replace("_", " ")
            counts[name] = counts.get(name, 0) + 1
        text = ", ".join(f"{n} x{c}" if c > 1 else n for n, c in counts.items())
        tick0 = grp[0]["tick"]
        slot = place_strip(x, text)
        label = ""
        if slot:
            row, anchor, tx = slot
            label = f'<text x="{tx}" y="{strip_y[row]}" font-size="18" fill="#D2D2D2" text-anchor="{anchor}">{esc(text)}</text>'
        opa = 0.22 if chain and not any(e["event_id"] in chain for e in grp) else 1
        sys_svg.append(f'<g opacity="{opa}"><line x1="{x}" y1="{top + 6}" x2="{x}" y2="{top + strip + lane_h * len(LANES)}" stroke="#D2D2D2" stroke-width="3" stroke-dasharray="3 8"/>'
                       f'{label}<title>{esc(f"System: {text} (tick {tick0})")}</title></g>')
    body[0:0] = sys_svg
    out.append(f'<g clip-path="url(#tl-clip)">{"".join(body)}</g>')

    # hints for lanes nobody has written to yet
    layers_seen = {e["layer"] for e in state.events}
    for i, who, key in ((1, "guardian", "verdict"), (2, "brain", "decision")):
        if who not in layers_seen:
            out.append(f'<text x="{plot_left + plot / 2}" y="{ys[i] + 8}" font-size="24" fill="#6E6E6E" text-anchor="middle">waiting for {who.title()} events '
                       f'(no {key} in this run yet)</text>')
    out.append(f'<text x="{left - 20}" y="{top + strip / 2 + 7}" font-size="22" fill="{DIM}" text-anchor="end">Run</text>')
    return Scene("".join(out), width, height, hits)

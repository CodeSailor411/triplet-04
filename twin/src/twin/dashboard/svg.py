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
from .events import Event, RunState, node_status, short_label, summarize
from .basemap import basemap
from .nodes import glyph
from .style import (ATTACK_COLOR, BG, DIM, LAND, LANE_OF_TYPE, LANES, LINE, PANEL, PANEL_2, RUN_STRIP_TYPES, TEXT)

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
            f'font-family="DejaVu Sans, Arial, sans-serif">{content}</svg>')


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
    """The map. `hidden` = domains whose layer is switched off (their nodes fade to grey, an isolated node keeps its lock)."""
    w, h = topology.canvas.width, topology.canvas.height
    out = [basemap(layout, w, h, layout.seed)]
    all_domains = {d for n in topology.nodes for d in n.domains}
    active = all_domains - (hidden or set())
    by_id = {n.node_id: n for n in topology.nodes}
    xy = display_positions(topology)
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
        g.append(glyph(cx, cy, NODE_W, n.domains, shape, active, unknown=(s["trust"] == "unknown" and not s["cut"])))
        if s["cut"] == "quarantined":
            g.append(f'<circle cx="{cx + NODE_W * 0.5:.1f}" cy="{cy + NODE_W * 0.45:.1f}" r="11" fill="{BG}" stroke="{TEXT}" stroke-width="2.5"/>'
                     f'<text x="{cx + NODE_W * 0.5:.1f}" y="{cy + NODE_W * 0.45 + 7:.1f}" font-size="18" font-weight="bold" fill="{TEXT}" text-anchor="middle">Q</text>')
        if attack:
            tx, ty = cx + NODE_W * 0.55, cy - NODE_W * 0.6
            g.append(f'<polygon points="{tx:.1f},{ty - 15:.1f} {tx + 14:.1f},{ty + 11:.1f} {tx - 14:.1f},{ty + 11:.1f}" fill="{ATTACK_COLOR}" stroke="{BG}" stroke-width="2"/>'
                     f'<text x="{tx:.1f}" y="{ty + 8:.1f}" font-size="17" font-weight="bold" fill="{BG}" text-anchor="middle">!</text>')
        g.append("</g>")
        out.append("".join(g))
        if selected == n.node_id or attack or s["cut"] or s["trust"] in ("degraded", "untrusted"):      # names only where something is going on
            ly = cy + NODE_W * 0.5 + 30
            labels.append(f'<text x="{cx:.1f}" y="{ly:.1f}" font-size="24" font-weight="bold" text-anchor="middle" fill="{BG}" stroke="{BG}" '
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
        return (f'<circle cx="{x}" cy="{y}" r="16" fill="#FF5A5F" stroke="#0A0E17" stroke-width="2"/>'
                f'<text x="{x}" y="{y + 7}" font-size="22" font-weight="bold" fill="#0A0E17" text-anchor="middle">!</text>')
    if t == "action":
        ok = d.get("status") == "committed"
        return f'<circle cx="{x}" cy="{y}" r="13" fill="{color if ok else "#3B1219"}" stroke="{color if ok else "#FF5A5F"}" stroke-width="3.5"/>'
    if t == "decision":
        return f'<rect x="{x - 13}" y="{y - 13}" width="26" height="26" rx="6" fill="{color}" stroke="#0A0E17" stroke-width="2"/>'
    if t == "reading":                                             # the Twin only logs readings a fault touched
        return f'<circle cx="{x}" cy="{y}" r="12" fill="{color}" stroke="{ATTACK_COLOR}" stroke-width="3.5"/>'
    return f'<circle cx="{x}" cy="{y}" r="12" fill="{color}" stroke="#0A0E17" stroke-width="2"/>'


def timeline_scene(state: RunState, selected: str | None = None, window_ticks: int = 60, end_tick: int | None = None,
                   width: int = 1800) -> Scene:
    left, right, top, strip, lane_h, bottom = 200, 60, 64, 60, 128, 24
    height = top + strip + lane_h * len(LANES) + bottom
    end = state.tick if end_tick is None else end_tick
    if window_ticks <= 0:                                           # 0 = show the whole run
        start = min((e["tick"] for e in state.events), default=0)
    else:
        start = max(0, end - window_ticks)
    span = max(1, end - start)
    plot = width - left - right

    def x_of(t: float) -> float:
        return round(left + (t - start) / span * plot, 1)

    clock, chain = tick_clock(state.events), chain_of(state, selected)
    dim = lambda eid: bool(chain) and eid not in chain               # noqa: E731
    out = ['<defs><marker id="tl-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           '<path d="M0,0 L10,5 L0,10 z" fill="#5B6B85"/></marker></defs>', f'<rect width="{width}" height="{height}" fill="{PANEL}"/>']

    # lanes: background bands, titles, gridlines
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
                   f'<text x="{x}" y="24" font-size="22" font-weight="bold" fill="#C9D3E3" text-anchor="middle">{t}</text>'
                   f'<text x="{x}" y="48" font-size="18" fill="#5B6B85" text-anchor="middle">{esc(clock(t))}</text>')

    # which events are inside the window
    shown = [e for e in state.events if start <= e["tick"] <= end]
    linked = {i for i, c in state.causes.items() for i in [i, *c]}          # events that have an arrow in or out
    pos: dict[str, tuple[float, float]] = {}
    clusters: dict[tuple[int, int], list[Event]] = {}                       # many unlinked events on one tick collapse into one glyph
    groups: dict[tuple, list[Event]] = {}
    for e in shown:
        t = e["event_type"]
        lane = -1 if t in RUN_STRIP_TYPES else LANE_OF_TYPE.get(t)
        if lane is None:
            continue
        groups.setdefault((lane, e["tick"]), []).append(e)
    for (lane, tick), evs in groups.items():
        loose = [e for e in evs if e["event_id"] not in linked and e["event_id"] != selected and lane >= 0]
        if len(loose) > 3:
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
                out.append(f'<path d="M{x1},{y1} C{x1 + dx:.1f},{y1} {x2 - dx:.1f},{y2} {x2},{y2}" fill="none" stroke="{"#00D4FF" if chain and not faded else "#5B6B85"}" '
                           f'stroke-width="{3.5 if chain and not faded else 2.5}" marker-end="url(#tl-arrow)" opacity="{0.15 if faded else 0.9}"/>')

    hits = []
    label_row: dict[int, int] = {}                                         # labels in one lane alternate between two rows so they do not collide
    for e in shown:
        if e["event_id"] not in pos:
            continue
        x, y = pos[e["event_id"]]
        t = e["event_type"]
        opa = 0.22 if dim(e["event_id"]) else 1
        title = f'{e["layer"]} {t} @ tick {e["tick"]} {e.get("timestamp", "")}: {summarize(e)}'
        if t in RUN_STRIP_TYPES:
            d = e.get("data") if isinstance(e.get("data"), dict) else {}
            phase = str(d.get("phase", ""))
            col = "#FF5A5F" if t == "partner_failure" else "#C9D3E3"
            right_side = x > width - 330                                      # near the edge the text goes to the left
            tx, anchor = (x - 24, "end") if right_side else (x + 24, "start")
            if phase in ("run_started", "run_ended", "twin_started"):
                out.append(f'<g opacity="{opa}"><line x1="{x}" y1="{top + 6}" x2="{x}" y2="{top + strip + lane_h * len(LANES)}" stroke="{col}" stroke-width="3" stroke-dasharray="3 8"/>'
                           f'<text x="{(x - 8) if right_side else (x + 8)}" y="{top + strip - 4}" font-size="16" fill="{col}" text-anchor="{anchor}">{esc(phase.replace("_", " "))}</text><title>{esc(title)}</title></g>')
            else:
                text = short_label(e)
                strip_row = label_row.get(-1, 0)
                label_row[-1] = 1 - strip_row
                out.append(f'<g opacity="{opa}"><path d="M{x},{y + 14} L{x},{y - 16} L{x + 18},{y - 9} L{x},{y - 2}" fill="{col}" stroke="{col}" stroke-width="3"/>'
                           f'<text x="{tx}" y="{y - 6 + 22 * strip_row}" font-size="18" fill="{col}" text-anchor="{anchor}">{esc(text)}</text><title>{esc(title)}</title></g>')
            hits.append((e["event_id"], x, y))
            continue
        lane = LANE_OF_TYPE[t]
        color = LANES[lane]["color"]
        sel = e["event_id"] == selected
        halo = f'<circle cx="{x}" cy="{y}" r="24" fill="none" stroke="#00D4FF" stroke-width="4"/>' if sel else ""
        if e["event_id"] in clustered:
            # one glyph for the whole group, drawn once (for the first member)
            members = next(v for v in clusters.values() if e in v)
            if e is members[0]:
                names = ", ".join(summarize(m) for m in members[:8]) + (" ..." if len(members) > 8 else "")
                out.append(f'<g opacity="{opa}"><circle cx="{x}" cy="{y}" r="17" fill="{color}" fill-opacity="0.25" stroke="{color}" stroke-width="3"/>'
                           f'<text x="{x}" y="{y + 7}" font-size="19" font-weight="bold" fill="{color}" text-anchor="middle">{len(members)}</text>'
                           f'<title>{len(members)} events on tick {e["tick"]}: {esc(names)}</title></g>')
                hits.append((e["event_id"], x, y))
            continue
        label = ""
        row = label_row.get(lane, 0)
        label_row[lane] = 1 - row
        label = (f'<text x="{x}" y="{y + 36 + 18 * row}" font-size="17" fill="#C9D3E3" text-anchor="middle" stroke="#121826" stroke-width="5" '
                 f'stroke-linejoin="round">{esc(short_label(e))}</text>'
                 f'<text x="{x}" y="{y + 36 + 18 * row}" font-size="17" fill="#C9D3E3" text-anchor="middle">{esc(short_label(e))}</text>')
        out.append(f'<g opacity="{opa}">{halo}{_glyph(e, x, y, color)}{label}<title>{esc(title)}</title></g>')
        hits.append((e["event_id"], x, y))

    # hints for lanes nobody has written to yet
    layers_seen = {e["layer"] for e in state.events}
    for i, who, key in ((1, "guardian", "verdict"), (2, "brain", "decision")):
        if who not in layers_seen:
            out.append(f'<text x="{left + plot / 2}" y="{ys[i] + 8}" font-size="24" fill="#5B6B85" text-anchor="middle">waiting for {who.title()} events '
                       f'(no {key} in this run yet)</text>')
    out.append(f'<text x="{left - 20}" y="{top + strip / 2 + 7}" font-size="22" fill="{DIM}" text-anchor="end">Run</text>')
    return Scene("".join(out), width, height, hits)

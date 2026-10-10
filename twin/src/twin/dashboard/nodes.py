"""Node drawing, exactly as in `node-style-spec.md`. Pure functions: numbers in, SVG text out.

Grid: 48 x 48, y points down, flat-top hexagon, centre (24, 24), circumradius 22. Sides are numbered 0..5 clockwise from the TOP.
Trust states: trusted = hexagon + core dot, degraded = only the 4 slanted sides + dot, untrusted = hexagon + X (no dot),
isolated = hexagon + closed padlock + 4 corner brackets (no dot). A shared node hands its 6 sides out to its active domains.
"""
from .style import BG, DOMAIN_COLORS, SHARED_CORE, SWITCHED_OFF, TEXT

HEX = [(46, 24), (35, 43.05), (13, 43.05), (2, 24), (13, 4.95), (35, 4.95)]
SIDES = [((13, 4.95), (35, 4.95)), ((35, 4.95), (46, 24)), ((46, 24), (35, 43.05)),
         ((35, 43.05), (13, 43.05)), ((13, 43.05), (2, 24)), ((2, 24), (13, 4.95))]     # side 0 = top, clockwise
DOMAIN_ORDER = ["traffic", "water", "power", "emergency", "air_quality", "waste", "telecom"]    # order in which shared nodes hand out sides
HEX_WIDTH = 44            # vertex to vertex, in grid units
_PTS = " ".join(f"{x:g},{y:g}" for x, y in HEX)


def side_colors(domains: list[str], active: set[str] | None = None) -> list[str] | None:
    """The colour of each of the 6 sides, or None if no domain of this node is active. Switched-off domains are ignored."""
    act = [d for d in DOMAIN_ORDER if d in domains and (active is None or d in active)]
    act += [d for d in domains if d not in DOMAIN_ORDER and (active is None or d in active)]
    if not act:
        return None
    n = len(act)
    return [DOMAIN_COLORS.get(act[min(n - 1, side * n // 6)], "#94A3B8") for side in range(6)]


def glyph(cx: float, cy: float, width: float, domains: list[str], state: str = "trusted", active: set[str] | None = None,
          unknown: bool = False) -> str:
    """One node. `width` = hexagon width on the canvas. `active` = domains whose layer is on (None = all)."""
    s = width / HEX_WIDTH
    colors = side_colors(domains, active)
    dim = colors is None
    if dim:
        colors = [SWITCHED_OFF] * 6
    shared = len({c for c in colors}) > 1
    main = colors[0]
    core = SWITCHED_OFF if dim else (SHARED_CORE if shared else main)
    x_col = SHARED_CORE if shared else main
    g = [f'<g transform="translate({cx - 24 * s:.1f} {cy - 24 * s:.1f}) scale({s:.4f})"' + (' opacity="0.7"' if unknown and not dim else "") + ">"]
    if not dim:                                                       # halo: two faint hexagon-shaped glows
        for k, op in ((1.4, 0.06), (1.2, 0.14)):
            g.append(f'<polygon points="{_PTS}" fill="{main}" fill-opacity="{op}" transform="translate(24 24) scale({k}) translate(-24 -24)"/>')
    g.append(f'<polygon points="{_PTS}" fill="{BG}"/>')
    if state == "degraded":                                           # sides 0 (top) and 3 (bottom) are not drawn
        for i in (1, 2, 4, 5):
            (x1, y1), (x2, y2) = SIDES[i]
            g.append(f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{colors[i]}" stroke-width="3" stroke-linecap="round"/>')
    elif not shared:
        g.append(f'<polygon points="{_PTS}" fill="none" stroke="{main}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
    else:
        for i, ((x1, y1), (x2, y2)) in enumerate(SIDES):
            g.append(f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{colors[i]}" stroke-width="3" stroke-linecap="round"/>')
    if state in ("trusted", "degraded"):
        g.append(f'<circle cx="24" cy="24" r="4" fill="{core}"/>')
    elif state == "untrusted":
        g.append(f'<line x1="14" y1="14" x2="34" y2="34" stroke="{x_col}" stroke-width="3" stroke-linecap="round"/>'
                 f'<line x1="34" y1="14" x2="14" y2="34" stroke="{x_col}" stroke-width="3" stroke-linecap="round"/>')
    elif state == "isolated":
        g.append(f'<path d="M18 27 V18 A6 6 0 0 1 30 18 V27" fill="none" stroke="{TEXT}" stroke-width="2.5"/>'
                 f'<rect x="14" y="25" width="20" height="13" rx="2" fill="{BG}" stroke="{TEXT}" stroke-width="2.5"/>'
                 f'<circle cx="24" cy="30.5" r="2.2" fill="{TEXT}"/><rect x="23.2" y="31.5" width="1.6" height="4" fill="{TEXT}"/>'
                 f'<path d="M1.5 9.5 V1.5 H9.5" fill="none" stroke="{TEXT}" stroke-width="2"/>'
                 f'<path d="M38.5 1.5 H46.5 V9.5" fill="none" stroke="{TEXT}" stroke-width="2"/>'
                 f'<path d="M1.5 38.5 V46.5 H9.5" fill="none" stroke="{TEXT}" stroke-width="2"/>'
                 f'<path d="M38.5 46.5 H46.5 V38.5" fill="none" stroke="{TEXT}" stroke-width="2"/>')
    g.append("</g>")
    return "".join(g)

"""The city map background: a black and white wireframe MAP SECTION. Pure functions: node positions in, SVG text out.

What it draws:
  * one street network that connects every node, so each node sits on a street and there are no separate "districts",
  * "outskirt" streets that leave the picture at the frame, so the picture looks like a cut-out of a bigger city, not an island,
  * a map-sheet frame (double line with tick marks) that the streets are clipped to, like the border of a printed map,
  * a soft glow around the roads and the frame.
Nothing else: no river, no parks, no district names, no grid, no boundary line. Colour is kept for things that mean something.

How the streets are made (the same positions always give the same streets, nothing random):
  1. The shortest set of roads that links all the nodes together (a "minimum spanning tree", found with Kruskal's method). These
     are the main roads. They guarantee the city is connected.
  2. Extra streets from the "Gabriel graph": two nodes get a street if no other node sits inside the circle that has the line
     between them as its diameter. This rule never makes streets cross, and it adds the loops that make a street map look real.
     Very long extra streets are dropped.
  3. Outskirts: from every node on the outer edge of the city (and every dead end) one street runs straight away from the middle
     of the city, far past the frame. The frame cuts it off, so it looks like it goes on.
The Twin's own city data (zones, `layout.json` roads) is NOT used here and is not changed. Nodes keep their real positions.

How a "hollow" road is drawn: every road first as a wide pale line (becomes the two edges), then every road again as a narrower
dark line on top (the inside). Because all pale lines go first and all dark lines second, roads that meet open up into each other.
"""
import math
from functools import lru_cache

from .style import EDGE, MAP_BG

WIDTHS = {"main": 15, "side": 10}        # inside width of a road in map pixels (the map is 1920 wide)
EDGE_W = 2.4                            # thickness of each of the two outline lines of a road
EDGE_OPACITY = {"main": 0.75, "side": 0.45}
OUTSKIRT = 1400                         # how far (in map pixels) an outskirt street runs: far past the frame, so it is cut off by it
CLIP_ID = "tw-map-clip"                 # name of the clip shape (the inside of the frame). Unique on the page
LONG_SIDE_STREET = 2.0                  # extra streets longer than this x the median main road are dropped
Point = tuple[float, float]


# ---------------------------------------------------------------- the street network
def street_graph(points: list[Point]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Returns (main roads, side streets) as pairs of point numbers. Together they connect every point."""
    n = len(points)
    dist = lambda i, j: math.hypot(points[i][0] - points[j][0], points[i][1] - points[j][1])   # noqa: E731
    pairs = sorted(((dist(i, j), i, j) for i in range(n) for j in range(i + 1, n)))
    parent = list(range(n))

    def find(a: int) -> int:                                    # union-find: which group is this point in?
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    main: list[tuple[int, int]] = []
    for _, i, j in pairs:                                       # Kruskal: shortest pair first, skip it if already linked
        a, b = find(i), find(j)
        if a != b:
            parent[a] = b
            main.append((i, j))
    lengths = sorted(dist(i, j) for i, j in main)
    limit = LONG_SIDE_STREET * (lengths[len(lengths) // 2] if lengths else 0)
    in_main = set(main)
    side = []
    for d, i, j in pairs:
        if d > limit or (i, j) in in_main:
            continue
        mx, my = (points[i][0] + points[j][0]) / 2, (points[i][1] + points[j][1]) / 2
        if all(math.hypot(points[k][0] - mx, points[k][1] - my) >= d / 2 for k in range(n) if k not in (i, j)):
            side.append((i, j))                                 # Gabriel rule: nobody inside the circle on this line
    return main, side


def _curve(a: Point, b: Point) -> str:
    """A road from a to b, bent a tiny bit so it does not look ruler-straight. The bend depends only on the two ends."""
    (x1, y1), (x2, y2) = a, b
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    bend = (((int(x1 * 7 + y1 * 13 + x2 * 17 + y2 * 19)) % 11) - 5) / 5 * 0.07          # -7 % .. +7 % of the length
    cx, cy = (x1 + x2) / 2 - (y2 - y1) / length * length * bend, (y1 + y2) / 2 + (x2 - x1) / length * length * bend
    return f"M{x1:.1f},{y1:.1f} Q{cx:.1f},{cy:.1f} {x2:.1f},{y2:.1f}"


# ---------------------------------------------------------------- the city limit and the map frame
def _hull(pts: list[Point]) -> list[Point]:
    """Convex hull (the rubber band around the points), Andrew's monotone chain."""
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(seq):
        h: list[Point] = []
        for p in seq:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h[:-1]
    return half(pts) + half(reversed(pts))


def outskirts(points: list[Point]) -> list[tuple[int, Point]]:
    """Streets that leave the picture. Returns (node number, far end point). One for every node on the hull (the outer edge of the
    city) and for every dead end, pointing away from the middle of the city."""
    if len(points) < 3:
        return []
    main, side = street_graph(points)
    degree = [0] * len(points)
    for i, j in main + side:
        degree[i] += 1
        degree[j] += 1
    cx, cy = sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
    on_hull = {points.index(p) for p in _hull(points)}
    out = []
    for i, (x, y) in enumerate(points):
        if i in on_hull or degree[i] == 1:
            dx, dy = x - cx, y - cy
            length = math.hypot(dx, dy) or 1.0
            out.append((i, (x + dx / length * OUTSKIRT, y + dy / length * OUTSKIRT)))
    return out


def _frame(width: float, height: float) -> str:
    """The map-sheet border: an outer and an inner line with tick marks between them (small every 60 px, long every 240 px)."""
    o, i = 5.0, 14.0
    out = [f'<rect x="{o}" y="{o}" width="{width - 2 * o:g}" height="{height - 2 * o:g}" fill="none" stroke="{EDGE}" stroke-opacity="0.6" stroke-width="1.6"/>',
           f'<rect x="{i}" y="{i}" width="{width - 2 * i:g}" height="{height - 2 * i:g}" fill="none" stroke="{EDGE}" stroke-opacity="0.3" stroke-width="1"/>']
    out.insert(0, f'<rect x="{o}" y="{o}" width="{width - 2 * o:g}" height="{height - 2 * o:g}" fill="none" stroke="{EDGE}" stroke-opacity="0.07" stroke-width="9"/>')
    ticks = []
    for x in range(60, int(width), 60):
        end = i if x % 240 == 0 else o + 4
        ticks.append(f"M{x},{o} V{end} M{x},{height - o:g} V{height - end:g}")
    for y in range(60, int(height), 60):
        end = i if y % 240 == 0 else o + 4
        ticks.append(f"M{o},{y} H{end} M{width - o:g},{y} H{width - end:g}")
    out.append(f'<path d="{" ".join(ticks)}" fill="none" stroke="{EDGE}" stroke-opacity="0.5" stroke-width="1.2"/>')
    return "".join(out)


# ---------------------------------------------------------------- the picture
@lru_cache(maxsize=8)
def _draw(points: tuple[Point, ...], width: float, height: float) -> str:
    pts = list(points)
    main, side = street_graph(pts)
    far = outskirts(pts)
    inset = 14                                                                       # the inner frame line: roads are cut off here
    out = [f'<rect width="{width:g}" height="{height:g}" fill="{MAP_BG}"/>',
           f'<clipPath id="{CLIP_ID}"><rect x="{inset}" y="{inset}" width="{width - 2 * inset:g}" height="{height - 2 * inset:g}"/></clipPath>']
    line = 'fill="none" stroke-linecap="round" stroke-linejoin="round"'
    # every road as (kind, path). Outskirts: every third one is a main road, the others are side streets
    roads = [("side", _curve(pts[i], pts[j])) for i, j in side] + [("main", _curve(pts[i], pts[j])) for i, j in main]
    roads += [("main" if k % 3 == 0 else "side", _curve(pts[i], end)) for k, (i, end) in enumerate(far)]
    out.append(f'<g clip-path="url(#{CLIP_ID})">')
    for kind, d in roads:                                                            # 0. glow: two wide, very faint white lines under every road
        out.append(f'<path d="{d}" {line} stroke="{EDGE}" stroke-opacity="0.035" stroke-width="{WIDTHS[kind] + 26}"/>')
        out.append(f'<path d="{d}" {line} stroke="{EDGE}" stroke-opacity="0.06" stroke-width="{WIDTHS[kind] + 12}"/>')
    for kind, d in roads:                                                            # 1. pale lines (the two edges)
        out.append(f'<path d="{d}" {line} stroke="{EDGE}" stroke-opacity="{EDGE_OPACITY[kind]}" stroke-width="{WIDTHS[kind] + 2 * EDGE_W:g}"/>')
    for kind, d in roads:                                                            # 2. dark inside
        out.append(f'<path d="{d}" {line} stroke="{MAP_BG}" stroke-width="{WIDTHS[kind]:g}"/>')
    for kind, d in roads:                                                            # 3. thin dashed centre line on main roads
        if kind == "main":
            out.append(f'<path d="{d}" {line} stroke="{EDGE}" stroke-opacity="0.22" stroke-width="1.5" stroke-dasharray="3 12"/>')
    out.append("</g>")
    out.append(_frame(width, height))
    return "".join(out)


def basemap(points: list[Point], width: float, height: float) -> str:
    """`points` = where each node is drawn on screen (the same positions the nodes use)."""
    return _draw(tuple((round(x, 1), round(y, 1)) for x, y in points), float(width), float(height))

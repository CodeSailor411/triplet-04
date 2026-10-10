"""The city map background: ONE connected city in a black and white wireframe. Pure functions: node positions in, SVG text out.

What it draws:
  * one smooth outline around all the nodes (the edge of the city),
  * one street network inside it that connects every node, so each node sits on a road and there are no separate "districts",
  * nothing else: no river, no parks, no district names, no grid. Colour is kept for things that mean something.

How the streets are made (the same positions always give the same streets, nothing random):
  1. The shortest set of roads that links all the nodes together (a "minimum spanning tree", found with Kruskal's method). These
     are the main roads. They guarantee the city is connected.
  2. Extra streets from the "Gabriel graph": two nodes get a street if no other node sits inside the circle that has the line
     between them as its diameter. This rule never makes streets cross, and it adds the loops that make a street map look real.
     Very long extra streets are dropped.
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
CITY_PAD = 95                           # empty space between the outermost nodes and the city outline
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


# ---------------------------------------------------------------- the edge of the city
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


def _outline(points: list[Point], width: float, height: float) -> str:
    """One smooth closed line around the whole city: the hull, padded, with a gentle wobble so it looks like a coast."""
    if not points:
        return ""
    ring = [(x + CITY_PAD * math.cos(a * math.pi / 12), y + CITY_PAD * math.sin(a * math.pi / 12)) for x, y in _hull(points) for a in range(24)]
    ring = _hull(ring)
    dense: list[Point] = []                                                          # put a point every ~45 px, evenly, so the curve has no hooks
    for k in range(len(ring)):
        (ax, ay), (bx, by) = ring[k], ring[(k + 1) % len(ring)]
        pieces = max(1, int(math.hypot(bx - ax, by - ay) // 45))
        dense += [(ax + (bx - ax) * t / pieces, ay + (by - ay) * t / pieces) for t in range(pieces)]
    cx, cy = sum(p[0] for p in dense) / len(dense), sum(p[1] for p in dense) / len(dense)
    out: list[Point] = []
    for x, y in dense:
        ang = math.atan2(y - cy, x - cx)
        k = 1 + 0.03 * math.sin(3 * ang + 0.7) + 0.02 * math.sin(5 * ang + 2.1)       # same shape every time
        out.append((min(width - 12, max(12, cx + (x - cx) * k)), min(height - 12, max(12, cy + (y - cy) * k))))
    n = len(out)                                                                     # closed Catmull-Rom curve turned into Beziers
    d = f"M{out[0][0]:.1f},{out[0][1]:.1f}"
    for i in range(n):
        p0, p1, p2, p3 = out[i - 1], out[i], out[(i + 1) % n], out[(i + 2) % n]
        d += (f" C{p1[0] + (p2[0] - p0[0]) / 6:.1f},{p1[1] + (p2[1] - p0[1]) / 6:.1f} "
              f"{p2[0] - (p3[0] - p1[0]) / 6:.1f},{p2[1] - (p3[1] - p1[1]) / 6:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return d + " Z"


# ---------------------------------------------------------------- the picture
@lru_cache(maxsize=8)
def _draw(points: tuple[Point, ...], width: float, height: float) -> str:
    pts = list(points)
    main, side = street_graph(pts)
    out = [f'<rect width="{width:g}" height="{height:g}" fill="{MAP_BG}"/>']
    out.append(f'<path d="{_outline(pts, width, height)}" fill="none" stroke="{EDGE}" stroke-opacity="0.7" stroke-width="2.5" stroke-linejoin="round"/>')
    line = 'fill="none" stroke-linecap="round" stroke-linejoin="round"'
    roads = [(k, i, j) for k, group in (("side", side), ("main", main)) for i, j in group]      # side streets first, main roads on top
    for kind, i, j in roads:                                                                     # 1. pale lines (the two edges)
        out.append(f'<path d="{_curve(pts[i], pts[j])}" {line} stroke="{EDGE}" stroke-opacity="{EDGE_OPACITY[kind]}" stroke-width="{WIDTHS[kind] + 2 * EDGE_W:g}"/>')
    for kind, i, j in roads:                                                                     # 2. dark inside
        out.append(f'<path d="{_curve(pts[i], pts[j])}" {line} stroke="{MAP_BG}" stroke-width="{WIDTHS[kind]:g}"/>')
    for kind, i, j in roads:                                                                     # 3. thin dashed centre line on main roads
        if kind == "main":
            out.append(f'<path d="{_curve(pts[i], pts[j])}" {line} stroke="{EDGE}" stroke-opacity="0.22" stroke-width="1.5" stroke-dasharray="3 12"/>')
    return "".join(out)


def basemap(points: list[Point], width: float, height: float) -> str:
    """`points` = where each node is drawn on screen (the same positions the nodes use)."""
    return _draw(tuple((round(x, 1), round(y, 1)) for x, y in points), float(width), float(height))

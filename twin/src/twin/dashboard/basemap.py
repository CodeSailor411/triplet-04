"""A made-up city map for the background, drawn in code from the city's own layout (roads and zones) and its seed.

Same seed, same map. It only adds scenery: a faint block grid, a river, a few parks and the district names. The roads come
straight from `layout.json`, so every road sits exactly where the Twin's generator put it. Nothing here is data: no node, no
reading. Pure function: layout in, SVG text out.
"""
import math
import random
from html import escape

from ..models import Layout
from .style import BG

ROAD_BED, MAIN, SECONDARY = "#141B29", "#5A6471", "#3A424D"      # road colours (base-map checks of 5 Oct: 3.4:1 and 1.9:1 on the background)
WIDTHS = {"ring": 7, "main": 6, "secondary": 4}
RIVER_BED, RIVER, PARK, GRID, NAME = "#0E3550", "#0A2539", "#0C2A22", "#111A29", "#26334C"


def _smooth(points: list[tuple[float, float]]) -> str:
    """A smooth curve through the points (Catmull-Rom turned into cubic Beziers)."""
    p = [points[0], *points, points[-1]]
    d = f"M{p[1][0]:.1f},{p[1][1]:.1f}"
    for i in range(1, len(p) - 2):
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = p[i - 1], p[i], p[i + 1], p[i + 2]
        d += f" C{x1 + (x2 - x0) / 6:.1f},{y1 + (y2 - y0) / 6:.1f} {x2 - (x3 - x1) / 6:.1f},{y2 - (y3 - y1) / 6:.1f} {x2:.1f},{y2:.1f}"
    return d


def basemap(layout: Layout, width: float, height: float, seed: int = 0) -> str:
    rnd = random.Random(f"basemap-{layout.seed if hasattr(layout, 'seed') else seed}-{seed}")
    out = [f'<rect width="{width:g}" height="{height:g}" fill="{BG}"/>']

    # 1. faint city blocks: a loose grid, bent a little, with gaps so it does not look like graph paper
    for horizontal in (True, False):
        length, other = (width, height) if horizontal else (height, width)
        pos = 20.0
        while pos < other:
            if rnd.random() > 0.18:
                pts = []
                for k in range(0, int(length) + 120, 120):
                    off = pos + rnd.uniform(-5, 5)
                    pts.append((k, off) if horizontal else (off, k))
                out.append(f'<polyline points="{" ".join(f"{x:.0f},{y:.0f}" for x, y in pts)}" fill="none" stroke="{GRID}" stroke-width="2"/>')
            pos += rnd.uniform(52, 82)

    # 2. a river from the top to the bottom edge, wandering a little
    x = rnd.uniform(0.62, 0.72) * width
    pts = [(x, -20.0)]
    for i in range(1, 6):
        x = min(width * 0.9, max(width * 0.35, x + rnd.uniform(-230, 150)))
        pts.append((x, height * i / 5.0))
    pts.append((x + rnd.uniform(-80, 80), height + 20))
    path = _smooth(pts)
    out.append(f'<path d="{path}" fill="none" stroke="{RIVER_BED}" stroke-width="58" stroke-linecap="round"/>'
               f'<path d="{path}" fill="none" stroke="{RIVER}" stroke-width="46" stroke-linecap="round"/>')

    # 3. parks: soft dark-green blobs
    for _ in range(7):
        cx, cy = rnd.uniform(0.08, 0.92) * width, rnd.uniform(0.1, 0.9) * height
        rx, ry, rot = rnd.uniform(60, 120), rnd.uniform(38, 80), rnd.uniform(0, 180)
        out.append(f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rx:.0f}" ry="{ry:.0f}" fill="{PARK}" transform="rotate({rot:.0f} {cx:.0f} {cy:.0f})"/>')

    # 4. the real roads from the layout, over everything else (so a road crossing the river reads as a bridge)
    for r in layout.roads:
        pts = " ".join(f"{x:g},{y:g}" for x, y in r.points)
        w = WIDTHS.get(r.kind, 4)
        col = SECONDARY if r.kind == "secondary" else MAIN
        out.append(f'<polyline points="{pts}" fill="none" stroke="{ROAD_BED}" stroke-width="{w + 9}" stroke-linecap="round" stroke-linejoin="round"/>'
                   f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round"/>')

    # 5. district names, small and dim, like a real map label
    for z in layout.zones:
        out.append(f'<text x="{z.x + 26:g}" y="{z.y + 46:g}" font-size="30" font-weight="bold" letter-spacing="6" fill="{NAME}">{escape(z.name.upper(), quote=True)}</text>')
    return "".join(out)

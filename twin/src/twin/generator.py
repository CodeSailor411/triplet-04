"""Seeded city generator.

Builds the whole city from config/twin.yaml plus a seed:
  * layout   = zones and roads only (this is what the Grok base-map job gets)
  * topology = nodes with positions, sensors, actuators and neighbour lists

Same seed + same config = byte-identical output. Each stage has its own random stream
(seeded from "<seed>:<stage>"), so changing one stage does not reshuffle the others.

Run it alone:   python -m twin.generator --out generated
"""
import argparse
import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path

from .caps import compute_caps
from .models import Canvas, Layout, Node, Road, SensorInfo, Topology, Zone
from .settings import ConfigError, GeneratorCfg, TwinConfig, load_config


def make_node_id(prefix: str, n: int) -> str:
    """Node id style, e.g. TRF-01. CIVIS asks for stable ids; they only change if the seed or config changes."""
    return f"{prefix}-{n:02d}"


SHARED_PREFIX = "SH"


def _rng(seed: int, stage: str) -> random.Random:
    return random.Random(f"{seed}:{stage}")


# ------------------------------------------------------------------ zones and roads
def _build_zones(cfg: GeneratorCfg) -> list[Zone]:
    W, H = cfg.canvas.width, cfg.canvas.height
    m, g = cfg.canvas_margin_px, cfg.road_gap_px
    cols, rows = cfg.zone_grid.cols, cfg.zone_grid.rows
    zw = (W - 2 * m - (cols - 1) * g) / cols
    zh = (H - 2 * m - (rows - 1) * g) / rows
    zones = []
    for i, name in enumerate(cfg.zones):
        c, r = i % cols, i // cols
        zones.append(Zone(id=name, name=name.replace("_", " ").title(),
                          x=round(m + c * (zw + g), 1), y=round(m + r * (zh + g), 1),
                          w=round(zw, 1), h=round(zh, 1)))
    return zones


def _build_roads(cfg: GeneratorCfg, zones: list[Zone], seed: int) -> list[Road]:
    rng = _rng(seed, "roads")
    W, H = cfg.canvas.width, cfg.canvas.height
    m, g = cfg.canvas_margin_px, cfg.road_gap_px
    cols, rows = cfg.zone_grid.cols, cfg.zone_grid.rows
    h = m / 2
    roads: list[Road] = [Road(id="ring", kind="ring",
                              points=[(h, h), (W - h, h), (W - h, H - h), (h, H - h), (h, h)])]
    z0 = zones[0]
    for c in range(cols - 1):                         # vertical main roads in the gaps between zone columns
        x = round(z0.x + (c + 1) * z0.w + c * g + g / 2, 1)
        roads.append(Road(id=f"main_v{c + 1}", kind="main", points=[(x, h), (x, H - h)]))
    for r in range(rows - 1):                         # horizontal main roads in the gaps between zone rows
        y = round(z0.y + (r + 1) * z0.h + r * g + g / 2, 1)
        roads.append(Road(id=f"main_h{r + 1}", kind="main", points=[(h, y), (W - h, y)]))
    for i, z in enumerate(zones):                     # one secondary street through every zone
        c = i % cols
        y0 = z.y + z.h / 2 + rng.uniform(-z.h * 0.15, z.h * 0.15)
        kink_x = z.x + z.w * rng.uniform(0.35, 0.65)
        kink_y = y0 + rng.uniform(-40, 40)
        x_start = h if c == 0 else z.x - g / 2
        x_end = W - h if c == cols - 1 else z.x + z.w + g / 2
        roads.append(Road(id=f"street_{z.id}", kind="secondary",
                          points=[(round(x_start, 1), round(y0, 1)), (round(kink_x, 1), round(kink_y, 1)),
                                  (round(x_end, 1), round(y0, 1))]))
    return roads


# ------------------------------------------------------------------ node specs
@dataclass
class _Spec:
    label: str
    domains: list[str]
    role: str
    zone: str | None        # None = assigned later, balanced across zones
    shared: bool
    prefix: str = ""
    num: int = 0
    id: str = ""


def _sorted_domains(cfg: GeneratorCfg, domains: list[str]) -> list[str]:
    for d in domains:
        if d not in cfg.domains:
            raise ConfigError(f"Unknown domain '{d}' in generator config")
    return sorted(domains, key=cfg.domain_order.index)


def _check_zone(cfg: GeneratorCfg, zone: str, who: str) -> None:
    if zone not in cfg.zones:
        raise ConfigError(f"{who} uses zone '{zone}', which is not in generator.zones")


def _build_specs(cfg: GeneratorCfg, seed: int) -> list[_Spec]:
    specs: list[_Spec] = []
    for cp in cfg.call_places:                                    # shared or not, fixed zone
        _check_zone(cfg, cp.zone, f"call place '{cp.label}'")
        specs.append(_Spec(cp.label, _sorted_domains(cfg, ["emergency", *cp.also_in]), "call_place",
                           cp.zone, shared=bool(cp.also_in)))
    dc = cfg.emergency_roles.get("dispatch_center")
    if dc is None or dc.zone is None:
        raise ConfigError("generator.emergency_roles.dispatch_center needs a zone")
    _check_zone(cfg, dc.zone, "dispatch_center")
    specs.append(_Spec("dispatch_center", ["emergency"], "dispatch_center", dc.zone, shared=False))
    for s in cfg.shared:
        _check_zone(cfg, s.zone, f"shared node '{s.label}'")
        specs.append(_Spec(s.label, _sorted_domains(cfg, s.domains), "standard", s.zone, shared=True))

    emergency_nodes = sum(1 for s in specs if "emergency" in s.domains)
    if emergency_nodes != cfg.domains["emergency"].count:
        raise ConfigError(f"emergency.count is {cfg.domains['emergency'].count} but call_places + "
                          f"dispatch_center make {emergency_nodes}")

    zone_cycle = list(cfg.zones)
    _rng(seed, "zone_cycle").shuffle(zone_cycle)
    for domain in cfg.domain_order:
        if domain == "emergency":
            continue
        dcfg = cfg.domains[domain]
        n_shared = sum(1 for s in specs if domain in s.domains)
        n_private = dcfg.count - n_shared
        if n_private < 0:
            raise ConfigError(f"Domain '{domain}': {n_shared} shared nodes but count is only {dcfg.count}")
        for i in range(n_private):
            specs.append(_Spec(f"{domain}_{i + 1:02d}", [domain], "standard",
                               zone_cycle[i % len(zone_cycle)], shared=False))
    return specs


def _assign_ids(cfg: GeneratorCfg, specs: list[_Spec]) -> None:
    counters: dict[str, int] = {}
    for s in specs:
        s.prefix = SHARED_PREFIX if s.shared else cfg.domains[s.domains[0]].prefix
        counters[s.prefix] = counters.get(s.prefix, 0) + 1
        s.num = counters[s.prefix]
        s.id = make_node_id(s.prefix, s.num)


# ------------------------------------------------------------------ placement
def _place(cfg: GeneratorCfg, specs: list[_Spec], zones: list[Zone], roads: list[Road],
           seed: int) -> dict[str, tuple[float, float]]:
    rng = _rng(seed, "placement")
    W, H = cfg.canvas.width, cfg.canvas.height
    size = cfg.node_size_px
    min_gap = size * cfg.min_spacing_factor
    edge = size
    pad = size * 1.5
    zone_by_id = {z.id: z for z in zones}
    segments = []                                     # (x1, y1, x2, y2, length) of every road piece
    for road in roads:
        for (x1, y1), (x2, y2) in zip(road.points, road.points[1:]):
            segments.append((x1, y1, x2, y2, math.hypot(x2 - x1, y2 - y1)))
    placed: dict[str, tuple[float, float]] = {}

    def free(x: float, y: float) -> bool:
        if not (edge <= x <= W - edge and edge <= y <= H - edge):
            return False
        return all(math.hypot(x - px, y - py) >= min_gap for px, py in placed.values())

    for s in specs:
        z = zone_by_id[s.zone]
        on_road = "traffic" in s.domains
        done = False
        for _ in range(2000):
            if on_road:
                x1, y1, x2, y2, _len = rng.choices(segments, weights=[sg[4] for sg in segments])[0]
                t = rng.random()
                x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                half = cfg.road_gap_px / 2
                if not (z.x - half <= x <= z.x + z.w + half and z.y - half <= y <= z.y + z.h + half):
                    continue
            else:
                x = rng.uniform(z.x + pad, z.x + z.w - pad)
                y = rng.uniform(z.y + pad, z.y + z.h - pad)
            x, y = round(x, 1), round(y, 1)
            if free(x, y):
                placed[s.id] = (x, y)
                done = True
                break
        if not done:
            raise ConfigError(f"Could not place node '{s.label}' in zone '{s.zone}' with spacing "
                              f"{min_gap:.0f}px. Use fewer nodes, a bigger canvas or a smaller spacing factor.")
    return placed


# ------------------------------------------------------------------ assembly
def generate(config: TwinConfig, seed: int | None = None) -> tuple[Topology, Layout]:
    cfg = config.generator
    seed = config.seed if seed is None else seed
    zones = _build_zones(cfg)
    roads = _build_roads(cfg, zones, seed)
    specs = _build_specs(cfg, seed)
    _assign_ids(cfg, specs)
    pos = _place(cfg, specs, zones, roads, seed)

    nodes: dict[str, Node] = {}
    for s in specs:
        sensor_names: list[str] = []
        for d in s.domains:
            names = cfg.emergency_roles[s.role].sensors if d == "emergency" else cfg.domains[d].sensors
            sensor_names += [n for n in names if n not in sensor_names]
        for n in sensor_names:
            if n not in config.sensors:
                raise ConfigError(f"Sensor '{n}' is used but not listed under sensors:")
        nodes[s.id] = Node(node_id=s.id, label=s.label, domains=s.domains, role=s.role, zone=s.zone or "",
                           x=pos[s.id][0], y=pos[s.id][1],
                           sensors=[SensorInfo(name=n, unit=config.sensors[n].unit) for n in sensor_names],
                           actuators=[], neighbours=[])

    rng = _rng(seed, "actuators")                     # which nodes carry an actuator
    for domain in cfg.domain_order:
        dcfg = cfg.domains[domain]
        if not dcfg.actuator:
            continue
        if dcfg.actuator not in config.actuators:
            raise ConfigError(f"Actuator '{dcfg.actuator}' is not listed under actuators:")
        members = sorted(n.node_id for n in nodes.values() if domain in n.domains)
        if dcfg.actuator_role:
            chosen = [i for i in members if nodes[i].role == dcfg.actuator_role]
        else:
            if dcfg.actuator_nodes > len(members):
                raise ConfigError(f"Domain '{domain}': actuator_nodes {dcfg.actuator_nodes} "
                                  f"is more than its {len(members)} nodes")
            chosen = sorted(rng.sample(members, dcfg.actuator_nodes))
        for i in chosen:
            nodes[i].actuators.append(dcfg.actuator)

    def dist(a: Node, b: Node) -> tuple[float, str]:
        return (math.hypot(a.x - b.x, a.y - b.y), b.node_id)

    for node in nodes.values():                       # neighbour lists
        found: list[str] = []
        for d in node.domains:
            others = sorted((n for n in nodes.values() if d in n.domains and n.node_id != node.node_id),
                            key=lambda o: dist(node, o))
            found += [o.node_id for o in others[: cfg.neighbours.same_domain]]
        for cross in cfg.neighbours.cross:
            if cross.from_domain in node.domains and cross.from_role in (None, node.role):
                others = sorted((n for n in nodes.values() if cross.to_domain in n.domains and n.node_id != node.node_id),
                                key=lambda o: dist(node, o))
                found += [o.node_id for o in others[: cross.count]]
        node.neighbours = list(dict.fromkeys(found))

    edges = sorted({tuple(sorted((n.node_id, nb))) for n in nodes.values() for nb in n.neighbours})
    ordered = [nodes[i] for i in sorted(nodes)]
    canvas = Canvas(width=cfg.canvas.width, height=cfg.canvas.height)
    topology = Topology(seed=seed, canvas=canvas, node_size_px=cfg.node_size_px, nodes=ordered, edges=edges)
    layout = Layout(seed=seed, canvas=canvas, zones=zones, roads=roads)
    return topology, layout


def fingerprint(topology: Topology) -> str:
    """Short hash of the whole city. Same seed + config must always give the same value."""
    return hashlib.sha256(topology.model_dump_json().encode()).hexdigest()[:12]


def write_outputs(topology: Topology, layout: Layout, out_dir: Path | str) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t_path, l_path = out / "topology.json", out / "layout.json"
    t_path.write_text(topology.model_dump_json(indent=2), encoding="utf-8")
    l_path.write_text(layout.model_dump_json(indent=2), encoding="utf-8")
    return t_path, l_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the Twin city (layout.json + topology.json).")
    ap.add_argument("--seed", type=int, help="override the seed from the config")
    ap.add_argument("--out", default="generated", help="output folder (default: generated)")
    ap.add_argument("--config", help="path to a config file (default: config/twin.yaml)")
    args = ap.parse_args(argv)
    try:
        config = load_config(args.config)
        topology, layout = generate(config, args.seed)
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 1
    t_path, l_path = write_outputs(topology, layout, args.out)
    per_domain: dict[str, int] = {}
    for n in topology.nodes:
        for d in n.domains:
            per_domain[d] = per_domain.get(d, 0) + 1
    shared = sum(1 for n in topology.nodes if len(n.domains) > 1)
    print(f"seed {topology.seed}  fingerprint {fingerprint(topology)}")
    print(f"{len(topology.nodes)} nodes, {sum(per_domain.values())} domain memberships, {shared} shared, "
          f"{len(topology.edges)} links")
    print("per domain:", ", ".join(f"{d} {c}" for d, c in per_domain.items()))
    print("caps:", compute_caps(config.generator, config.caps))
    print(f"wrote {t_path}\nwrote {l_path}  (zones and roads only, no nodes: send this one to Grok)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

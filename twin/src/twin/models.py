"""Data shapes the Twin hands out. Pydantic checks them and the MCP SDK turns them into schemas."""
from pydantic import BaseModel


class SensorInfo(BaseModel):
    name: str
    unit: str
    device_id: str              # one device per sensor per node, e.g. WAT-03.water_level
    channels: list[str] = []    # empty for normal sensors; e.g. accident, fire, flood, medical for emergency calls


class Node(BaseModel):
    """One sensor or actuator point in the city. A shared node has more than one domain."""
    node_id: str
    label: str
    domains: list[str]          # more than one for shared nodes
    role: str                   # "standard", "call_place" or "dispatch_center"
    zone: str
    x: float                    # position on the 1920x1080 map
    y: float
    sensors: list[SensorInfo]
    actuators: list[str]
    neighbours: list[str]       # nearest nodes, for retries and cross-checks


class Canvas(BaseModel):
    width: int
    height: int


class Topology(BaseModel):
    schema_version: int = 1
    seed: int
    canvas: Canvas
    node_size_px: int
    nodes: list[Node]
    edges: list[tuple[str, str]]    # neighbour links, each pair once


class Zone(BaseModel):
    id: str
    name: str
    x: float
    y: float
    w: float
    h: float


class Road(BaseModel):
    id: str
    kind: str                   # "ring", "main" or "secondary"
    points: list[tuple[float, float]]


class Layout(BaseModel):
    """Zones and roads only. No nodes. This is what the Grok base-map job gets."""
    schema_version: int = 1
    seed: int
    canvas: Canvas
    zones: list[Zone]
    roads: list[Road]


class Reading(BaseModel):
    """One sensor report: which device, when, and the value it reported."""
    # INTERNAL NOTE (a comment on purpose: docstrings are published in the tool schema, comments are not):
    # `value` is the OBSERVED value only. There is deliberately no field for the true value.
    run_id: str
    reading_id: str
    tick: int
    timestamp: str              # simulated UTC, RFC 3339 with Z. Wobbles a few ms around the tick time
    node_id: str
    device_id: str
    sensor: str
    channel: str | None         # only for sensors that split by type
    value: float | None         # null = no value (never zero)
    unit: str


class ReadingsBatch(BaseModel):
    """All readings of one tick, or the filtered part of them."""
    run_id: str
    tick: int
    time: str                   # simulated time of the tick itself
    tick_seconds: float         # simulated length of one tick
    count: int
    readings: list[Reading]


class ClockInfo(BaseModel):
    run_id: str
    tick: int
    time: str
    tick_seconds: float
    speed: float                # simulated seconds per real second (1.0 = real speed)
    running: bool

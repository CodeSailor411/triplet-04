"""Data shapes the Twin hands out. Pydantic checks them and the MCP SDK turns them into schemas."""
from pydantic import BaseModel


class SensorInfo(BaseModel):
    name: str
    unit: str


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

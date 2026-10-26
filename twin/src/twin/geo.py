"""Map position to GPS, and distances between GPS points.

The Twin city is invented. Every node has a map position (x, y) on the 1920x1080 canvas. To give each node a
GPS position we pick ONE arbitrary anchor point (the canvas centre) and one scale (metres per map unit).

Flat-earth maths is good enough here: the city is a few kilometres wide, and the error of this simple method
over 10 km is far below the 1 m that 5 decimals can show. Two facts it uses:
  * 1 degree of latitude is about 111,195 m everywhere.
  * 1 degree of longitude is 111,195 m x cos(latitude), because the meridians get closer towards the poles.
Map y grows downwards, north is up, so a bigger y means further SOUTH (smaller latitude).
"""
import math

EARTH_RADIUS_M = 6_371_000.0      # mean earth radius, used by the distance formula below
# Length of 1 degree of latitude on that sphere (about 111,195 m). Derived from the SAME radius the distance
# formula uses, so GPS distances and map distances agree. (A first try with 111,320 m was off by 0.1 %, 11 m over 9 km.)
METRES_PER_DEGREE = EARTH_RADIUS_M * math.pi / 180
DECIMALS = 5                      # 5 decimals = about 1.1 m of latitude


def to_latlon(x: float, y: float, *, canvas_w: float, canvas_h: float, anchor_lat: float, anchor_lon: float,
              metres_per_unit: float) -> tuple[float, float]:
    """Map position -> (latitude, longitude). The canvas centre is the anchor point."""
    north_m = (canvas_h / 2 - y) * metres_per_unit      # y down on the map, so flip the sign
    east_m = (x - canvas_w / 2) * metres_per_unit
    lat = anchor_lat + north_m / METRES_PER_DEGREE
    lon = anchor_lon + east_m / (METRES_PER_DEGREE * math.cos(math.radians(anchor_lat)))
    return round(lat, DECIMALS), round(lon, DECIMALS)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in metres between two GPS points (haversine formula).

    Haversine = the standard way to get the distance over a sphere's surface from two latitude/longitude pairs.
    This is the number the units-and-distance section of the sensor table refers to.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass direction you face when you walk in a straight line from point 1 to point 2.
    0 = north, 90 = east, 180 = south, 270 = west (clockwise, like a compass). Uses the standard "initial bearing" formula."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360

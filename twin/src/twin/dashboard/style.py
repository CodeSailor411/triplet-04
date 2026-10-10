"""Colours and names used by the dashboard. One place, so the look can be changed without touching the drawing code.

Colours and shapes follow `node-style-spec.md` (3 Oct 2026): dark map, domain colours, hexagon nodes with four trust states
(Trusted, Degraded, Untrusted, Isolated). The node drawing itself lives in `nodes.py`, the generated map in `basemap.py`.
"""

# theme (node style spec, section 6)
BG = "#0A0E17"            # page background (node style spec)
MAP_BG = "#04060B"        # the city map itself: darker than the page, also the fill inside every node on the map
EDGE = "#E6ECF5"          # the white of the wireframe roads
PANEL = "#121826"
PANEL_2 = "#0F1522"       # the second band colour in the timeline
LINE = "#1E2A3F"          # hairlines, borders
TEXT = "#F0F4FF"
DIM = "#7A8BA3"
LAND = "#A8B8C8"          # connection lines

DOMAIN_COLORS = {"traffic": "#FF9F1A", "water": "#00D4FF", "power": "#FFD700", "emergency": "#FF2058", "air_quality": "#00E676",
                 "waste": "#8D6E63", "telecom": "#BB86FC"}
DOMAIN_NAMES = {"traffic": "Traffic", "water": "Water", "power": "Power", "air_quality": "Air quality", "emergency": "Emergency",
                "waste": "Waste", "telecom": "Telecom"}
SHARED_CORE = "#DCDCE6"   # core dot of a shared node
SWITCHED_OFF = "#3A4558"  # outline and core of a node whose layer is switched off (spec 5: "dim grey", value picked in the UI test)

# trust of a device. Used for the dots in the side panel. On the map the trust is the SHAPE of the node, not a colour.
# "unknown" = Guardian has not given a verdict yet (drawn like Trusted, but dimmer).
TRUST_COLORS = {"unknown": "#7A8BA3", "trusted": "#34D399", "degraded": "#FBBF24", "untrusted": "#FF5A5F"}
TRUST_NAMES = {"unknown": "No verdict yet", "trusted": "Trusted", "degraded": "Degraded", "untrusted": "Untrusted"}
TRUST_ORDER = {"unknown": 0, "trusted": 1, "degraded": 2, "untrusted": 3}      # higher = worse
ISOLATED_COLOR = "#F0F4FF"
QUARANTINE_COLOR = "#F0F4FF"
ATTACK_COLOR = "#FF4D4D"

# the four lanes of the timeline, in the order of the challenge's R3: reading, verdict, decision, action
LANES = [
    {"key": "reading", "title": "Reading", "who": "Twin", "color": "#38BDF8"},
    {"key": "verdict", "title": "Verdict", "who": "Guardian", "color": "#A78BFA"},
    {"key": "decision", "title": "Decision", "who": "Brain", "color": "#FBBF24"},
    {"key": "action", "title": "Action", "who": "Twin", "color": "#34D399"},
]
LANE_OF_TYPE = {"reading": 0, "verdict": 1, "decision": 2, "escalation": 2, "action": 3, "containment": 3}
RUN_STRIP_TYPES = {"scenario", "partner_failure"}      # shown on a thin strip above the lanes

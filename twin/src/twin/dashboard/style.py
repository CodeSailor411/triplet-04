"""Colours and names used by the dashboard. One place, so the look can be changed without touching the drawing code.

Colours and shapes follow `node-style-spec.md` (3 Oct 2026): dark map, domain colours, hexagon nodes with four trust states
(Trusted, Degraded, Untrusted, Isolated). The node drawing itself lives in `nodes.py`, the generated map in `basemap.py`.
"""

# the one font of the whole page (files are in dashboard/fonts, served by the dashboard itself, so no internet is needed)
FONT = "Lato, 'Open Sans', Arial, sans-serif"
FONT_FILES = {400: "lato-latin-400-normal.woff2", 700: "lato-latin-700-normal.woff2"}

# theme (node style spec, section 6, then made black / white / grey only on 11 Oct: no blue anywhere)
BG = "#050505"            # page background. Neutral black. Darker than node-style-spec (#0A0E17) on purpose (Dali, 10-11 Oct)
HEADER_BG = "#000000"     # the top bar: the darkest part of the page
MAP_BG = "#020202"        # the city map itself: darker than the panels, also the fill inside every node on the map
EDGE = "#EDEDED"          # the white of the wireframe roads
PANEL = "#0C0C0C"         # cards. Neutral dark grey. Darker than node-style-spec (#121826)
PANEL_2 = "#080808"       # the second band colour in the timeline, input fields, pills
LINE = "#222222"          # hairlines, borders
TEXT = "#F4F4F4"
DIM = "#8C8C8C"
LAND = "#B8B8B8"          # connection lines

DOMAIN_COLORS = {"traffic": "#FF9F1A", "water": "#00D4FF", "power": "#FFD700", "emergency": "#FF2058", "air_quality": "#00E676",
                 "waste": "#8D6E63", "telecom": "#BB86FC"}
DOMAIN_NAMES = {"traffic": "Traffic", "water": "Water", "power": "Power", "air_quality": "Air quality", "emergency": "Emergency",
                "waste": "Waste", "telecom": "Telecom"}
SHARED_CORE = "#E0E0E0"   # core dot of a shared node
SWITCHED_OFF = "#4A4A4A"  # outline and core of a node whose layer is switched off (spec 5: "dim grey", value picked in the UI test)

# trust of a device. Used for the dots in the side panel. On the map the trust is the SHAPE of the node, not a colour.
# "unknown" = Guardian has not given a verdict yet (drawn like Trusted, but dimmer).
TRUST_COLORS = {"unknown": "#8C8C8C", "trusted": "#34D399", "degraded": "#FBBF24", "untrusted": "#FF5A5F"}
TRUST_NAMES = {"unknown": "No verdict yet", "trusted": "Trusted", "degraded": "Degraded", "untrusted": "Untrusted"}
TRUST_ORDER = {"unknown": 0, "trusted": 1, "degraded": 2, "untrusted": 3}      # higher = worse
ISOLATED_COLOR = "#F4F4F4"
QUARANTINE_COLOR = "#F4F4F4"
ATTACK_COLOR = "#FF4D4D"

# the four lanes of the timeline, in the order of the challenge's R3: reading, verdict, decision, action.
# Lanes are shades of grey (white to dark grey), so they never look like a domain colour. The SHAPE and the name tell them apart.
LANES = [
    {"key": "reading", "title": "Reading", "who": "Twin", "color": "#F4F4F4"},
    {"key": "verdict", "title": "Verdict", "who": "Guardian", "color": "#D0D0D0"},
    {"key": "decision", "title": "Decision", "who": "Brain", "color": "#A8A8A8"},
    {"key": "action", "title": "Action", "who": "Twin", "color": "#808080"},
]
LANE_OF_TYPE = {"reading": 0, "verdict": 1, "decision": 2, "escalation": 2, "action": 3, "containment": 3}
RUN_STRIP_TYPES = {"scenario", "partner_failure"}      # shown on a thin strip above the lanes

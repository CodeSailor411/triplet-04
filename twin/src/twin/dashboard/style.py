"""Colours and names used by the dashboard. One place, so the look can be changed (or the node style spec applied) without
touching the drawing code.

NOTE: the node style spec (`node-style-spec.md`, Grok's `nodes.svg`) was not available when this was written. The shapes
and colours below are a simple stand-in. The four trust states are 9antra's: Trusted, Degraded, Untrusted, Isolated.
"""

DOMAIN_COLORS = {"traffic": "#F97316", "water": "#2563EB", "power": "#FACC15", "air_quality": "#14B8A6", "emergency": "#DB2777"}
DOMAIN_NAMES = {"traffic": "Traffic", "water": "Water", "power": "Power", "air_quality": "Air quality", "emergency": "Emergency"}

# trust of a device (ring colour). "unknown" = Guardian has not given a verdict yet.
TRUST_COLORS = {"unknown": "#CBD5E1", "trusted": "#16A34A", "degraded": "#F59E0B", "untrusted": "#DC2626"}
TRUST_NAMES = {"unknown": "No verdict yet", "trusted": "Trusted", "degraded": "Degraded", "untrusted": "Untrusted"}
TRUST_ORDER = {"unknown": 0, "trusted": 1, "degraded": 2, "untrusted": 3}      # higher = worse
ISOLATED_COLOR = "#475569"
QUARANTINE_COLOR = "#7C3AED"
ATTACK_COLOR = "#B91C1C"

# the four lanes of the timeline, in the order of the challenge's R3: reading, verdict, decision, action
LANES = [
    {"key": "reading", "title": "Reading", "who": "Twin", "color": "#0EA5E9"},
    {"key": "verdict", "title": "Verdict", "who": "Guardian", "color": "#8B5CF6"},
    {"key": "decision", "title": "Decision", "who": "Brain", "color": "#F59E0B"},
    {"key": "action", "title": "Action", "who": "Twin", "color": "#16A34A"},
]
LANE_OF_TYPE = {"reading": 0, "verdict": 1, "decision": 2, "escalation": 2, "action": 3, "containment": 3}
RUN_STRIP_TYPES = {"scenario", "partner_failure"}      # shown on a thin strip above the lanes

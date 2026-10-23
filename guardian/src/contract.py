"""Stable Guardian-to-Brain MCP contract names.

# CONFIRM with CIVIS: approve these public tool names before partner rollout.
"""

MCP_TOOL_GET_TRUST_VERDICT = "get_trust_verdict"
MCP_TOOL_AUTHORIZE_ACTION = "authorize_action"
MCP_TOOL_VERIFY_ACTION_TOKEN = "verify_action_token"
MCP_TOOL_DESCRIBE_CAPABILITIES = "describe_capabilities"
MCP_TOOL_EVALUATE_READING_ADVISORY = "evaluate_reading_advisory"

MCP_TOOL_NAMES = (
    MCP_TOOL_DESCRIBE_CAPABILITIES,
    MCP_TOOL_EVALUATE_READING_ADVISORY,
    MCP_TOOL_GET_TRUST_VERDICT,
    MCP_TOOL_AUTHORIZE_ACTION,
    MCP_TOOL_VERIFY_ACTION_TOKEN,
)
MCP_PUBLIC_TOOL_NAMES = tuple(name for name in MCP_TOOL_NAMES if name != MCP_TOOL_VERIFY_ACTION_TOKEN)

TRUST_STATE_MAP = {
    "trusted": "Trusted",
    "suspect": "Degraded",
    "compromised": "Untrusted",
}

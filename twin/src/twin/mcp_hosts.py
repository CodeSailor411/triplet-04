"""Which Host names the Twin's MCP endpoint accepts.

The MCP SDK refuses a request whose Host header is not on its allowed list (a defence against DNS
rebinding, an attack where a web page tricks a browser into calling a server on your own machine).
By default only localhost names are allowed. Inside Docker the other layers call the Twin as
`twin:8000`, so they get HTTP 421. Set TWIN_MCP_ALLOWED_HOSTS=twin:* to allow that name too.
A pattern ending in `:*` means any port.
"""
import os
from collections.abc import Mapping

from mcp.server.transport_security import TransportSecuritySettings

ENV_NAME = "TWIN_MCP_ALLOWED_HOSTS"
LOCAL_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOCAL_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def extra_hosts(env: Mapping[str, str] | None = None) -> list[str]:
    """The comma separated names from the environment, without spaces and empty entries."""
    raw = (os.environ if env is None else env).get(ENV_NAME, "")
    return [name.strip() for name in raw.split(",") if name.strip()]


def transport_security(env: Mapping[str, str] | None = None) -> TransportSecuritySettings | None:
    """None when the variable is unset: the SDK keeps its own default, so nothing changes.
    Otherwise the check stays ON and allows the local names plus the extra ones."""
    extra = extra_hosts(env)
    if not extra:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=LOCAL_HOSTS + extra,
        allowed_origins=LOCAL_ORIGINS,
    )

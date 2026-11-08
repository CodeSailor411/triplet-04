"""The Docker fix: the Twin accepts the Host `twin:8000` only when TWIN_MCP_ALLOWED_HOSTS allows it."""
import asyncio

from mcp.server.transport_security import TransportSecurityMiddleware
from starlette.requests import Request

from twin.mcp_hosts import extra_hosts, transport_security


def _status(settings, host: str):
    """Run the SDK's own request check with this Host header. None means accepted, else the HTTP status."""
    scope = {"type": "http", "method": "POST",
             "headers": [(b"host", host.encode()), (b"content-type", b"application/json")]}
    answer = asyncio.run(TransportSecurityMiddleware(settings).validate_request(Request(scope), is_post=True))
    return None if answer is None else answer.status_code


def test_unset_changes_nothing():
    assert transport_security({}) is None
    assert transport_security({"TWIN_MCP_ALLOWED_HOSTS": " , ,"}) is None


def test_names_are_split_and_trimmed():
    assert extra_hosts({"TWIN_MCP_ALLOWED_HOSTS": " twin:* , brain:*,, "}) == ["twin:*", "brain:*"]


def test_docker_name_is_accepted_when_allowed():
    settings = transport_security({"TWIN_MCP_ALLOWED_HOSTS": "twin:*"})
    assert _status(settings, "twin:8000") is None


def test_local_names_still_work_when_allowed():
    settings = transport_security({"TWIN_MCP_ALLOWED_HOSTS": "twin:*"})
    assert _status(settings, "localhost:8000") is None
    assert _status(settings, "127.0.0.1:8000") is None


def test_other_names_are_still_refused():
    settings = transport_security({"TWIN_MCP_ALLOWED_HOSTS": "twin:*"})
    assert _status(settings, "evil.example:8000") == 421
    assert _status(settings, "twin.evil.example:8000") == 421   # not a match for the twin: pattern


def test_check_stays_on():
    assert transport_security({"TWIN_MCP_ALLOWED_HOSTS": "twin:*"}).enable_dns_rebinding_protection is True

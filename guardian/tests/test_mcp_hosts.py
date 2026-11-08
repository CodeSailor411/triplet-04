"""The Docker fix: the Guardian's MCP endpoint accepts the Host `guardian:5000` only when
GUARDIAN_MCP_ALLOWED_HOSTS allows it. The last two tests send real HTTP requests to a real MCP app."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))   # the Guardian's modules are flat files in src/

from mcp.server import MCPServer
from starlette.testclient import TestClient

from mcp_hosts import extra_hosts, transport_security

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}}
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _post(env: dict, host: str) -> int:
    """Build the MCP app the way unified_api.py does, then call it as if from this Host."""
    app = MCPServer("t").streamable_http_app(streamable_http_path="/mcp", json_response=True,
                                             stateless_http=True, host="127.0.0.1",
                                             transport_security=transport_security(env))
    with TestClient(app, base_url=f"http://{host}") as client:
        return client.post("/mcp", json=INIT, headers=HEADERS).status_code


def test_unset_changes_nothing():
    assert transport_security({}) is None
    assert transport_security({"GUARDIAN_MCP_ALLOWED_HOSTS": " , ,"}) is None


def test_names_are_split_and_trimmed():
    assert extra_hosts({"GUARDIAN_MCP_ALLOWED_HOSTS": " guardian:* , x:*,, "}) == ["guardian:*", "x:*"]


def test_check_stays_on():
    assert transport_security({"GUARDIAN_MCP_ALLOWED_HOSTS": "guardian:*"}).enable_dns_rebinding_protection is True


def test_the_bug_docker_name_is_refused_by_default():
    assert _post({}, "guardian:5000") == 421


def test_docker_name_is_accepted_when_allowed():
    assert _post({"GUARDIAN_MCP_ALLOWED_HOSTS": "guardian:*"}, "guardian:5000") == 200


def test_local_and_other_names():
    env = {"GUARDIAN_MCP_ALLOWED_HOSTS": "guardian:*"}
    assert _post(env, "localhost:5000") == 200
    assert _post(env, "evil.example:5000") == 421

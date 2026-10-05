"""Who is calling? One secret per caller, checked on every request.

The caller sends   Authorization: Bearer <secret>   and the Twin maps the secret to an identity.
A secret that matches nothing is treated as "not logged in".
"""
import hmac
from collections.abc import Mapping
from enum import StrEnum

from .settings import Secrets


class Identity(StrEnum):
    CITY_BRAIN = "city_brain"
    GUARDIAN = "guardian"
    SCENARIO = "scenario"       # whoever runs scenarios (scripts, the demo button). Not a layer.


class KeyRing:
    def __init__(self, keys: Mapping[Identity, str]):
        self._keys = {ident: key.encode() for ident, key in keys.items()}

    @classmethod
    def from_secrets(cls, secrets: Secrets) -> "KeyRing":
        return cls({
            Identity.CITY_BRAIN: secrets.city_brain.get_secret_value(),
            Identity.GUARDIAN: secrets.guardian.get_secret_value(),
            Identity.SCENARIO: secrets.scenario.get_secret_value(),
        })

    def identify(self, token: str | None) -> Identity | None:
        """Constant-time comparison against every key, so timing does not reveal which one was close."""
        if not token:
            return None
        candidate = token.encode()
        found: Identity | None = None
        for ident, key in self._keys.items():
            if hmac.compare_digest(candidate, key):
                found = ident
        return found


def token_from_headers(headers: Mapping[str, str]) -> str | None:
    value = headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


# Who may call what. Tools in HIDDEN_TOOLS do not even appear in the tool list for anyone else,
# and calling them without access gives the same "Unknown tool" error as a tool that does not exist.
LAYERS = frozenset({Identity.CITY_BRAIN, Identity.GUARDIAN})
TOOL_ACCESS: dict[str, frozenset[Identity] | None] = {     # None = anyone, even without a key
    "get_capabilities": None,
    "list_nodes": LAYERS,
    "run_scenario": frozenset({Identity.SCENARIO}),
}
HIDDEN_TOOLS = frozenset({"run_scenario"})

"""CIVIS joint acceptance (23 Oct): five invalid signed tokens still committed on Twin mock 2.
Each one must now be refused with TOKEN_INVALID, in signed mode and in unsigned mode, in our own format.
(The same five for Guardian's g1 format are in test_token_g1.py.)"""
import base64
import math

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from twin.actions import ActionBook
from twin.auth import Identity
from twin.generator import generate
from twin.settings import TokensCfg, load_config
from twin.sim import Simulation
from twin.tokens import make_token

KEY = Ed25519PrivateKey.generate()
PUB = base64.b64encode(KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def world(mode):
    cfg = load_config()
    cfg.tokens = TokensCfg(mode="signed", guardian_public_key=PUB) if mode == "signed" else TokensCfg(mode="unsigned")
    topo, _ = generate(cfg)
    sim = Simulation(topo, cfg)
    return sim, ActionBook(topo, cfg, sim)


def claims(sim, **over):
    c = {"iss": "guardian", "aud": "twin", "jti": "j-ok", "run_id": sim.run_id, "iat": sim.clock.iso_of(sim.tick),
         "exp": sim.clock.iso_of(sim.tick + 30), "action": "set_signal_plan", "targets": ["TRF-01"],
         "params": {"plan": "normal"}, "score": 0.9}
    c.update(over)
    return c


def send(sim, book, mode, c, idem):
    return book.actuate(Identity.CITY_BRAIN, "set_signal_plan", ["TRF-01"], {"plan": "normal"},
                        make_token(c, KEY if mode == "signed" else None), idem)


@pytest.mark.parametrize("mode", ["signed", "unsigned"])
def test_control_a_valid_token_still_commits(mode):
    sim, book = world(mode)
    assert send(sim, book, mode, claims(sim), "ok").status == "committed"


@pytest.mark.parametrize("mode", ["signed", "unsigned"])
@pytest.mark.parametrize("name,over", [
    ("future issued-at", lambda s: {"iat": s.clock.iso_of(s.tick + 3600), "exp": s.clock.iso_of(s.tick + 3630)}),
    ("lifetime above 60 s", lambda s: {"exp": s.clock.iso_of(s.tick + 120)}),
    ("lifetime exactly 61 s", lambda s: {"exp": s.clock.iso_of(s.tick + 61)}),
    ("score above 1", lambda s: {"score": 1.5}),
    ("score far above 1 (a percent)", lambda s: {"score": 90}),
    ("NaN score", lambda s: {"score": math.nan}),
    ("infinite score", lambda s: {"score": math.inf}),
    ("negative score", lambda s: {"score": -0.2}),
    ("empty token id", lambda s: {"jti": ""}),
    ("blank token id", lambda s: {"jti": "   "}),
])
def test_the_five_cases_from_civis_are_refused(mode, name, over):
    sim, book = world(mode)
    r = send(sim, book, mode, claims(sim, **over(sim)), "k-" + name)
    assert r.status == "rejected" and r.code == "TOKEN_INVALID", (name, r.status, r.code)
    assert book.seq == 0, "a refused token must not change anything"


def test_exactly_60_seconds_is_allowed():
    sim, book = world("signed")
    assert send(sim, book, "signed", claims(sim, exp=sim.clock.iso_of(sim.tick + 60)), "k60").status == "committed"

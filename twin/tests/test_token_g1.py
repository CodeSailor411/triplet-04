"""Guardian's own token format ("g1", 9antra's docs/TOKEN.md), accepted by the Twin since 23 Oct.

The helper below signs a g1 token the same way Guardian does (canonical JSON, signature over "g1.<payload>").
It is copied into this test on purpose: the Twin's tests must run without Guardian's code (rule R1).
The real thing, Guardian's own signer talking to the real Twin, was run by hand in the integration check.
"""
import base64
import json
import math

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from twin.actions import ActionBook
from twin.auth import Identity
from twin.generator import generate
from twin.keys import load_public_key
from twin.settings import TokensCfg, load_config
from twin.sim import Simulation
from twin.tokens import TokenError, read_token

BRAIN = Identity.CITY_BRAIN
SIGNAL = "set_signal_plan"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def g1_token(key: Ed25519PrivateKey, claims: dict) -> str:
    payload = b64(json.dumps(claims, sort_keys=True, separators=(",", ":"), allow_nan=True).encode())
    return f"g1.{payload}." + b64(key.sign(f"g1.{payload}".encode()))


def world(tokens: TokensCfg):
    cfg = load_config()
    cfg.tokens = tokens
    topo, _ = generate(cfg)
    sim = Simulation(topo, cfg)
    return sim, ActionBook(topo, cfg, sim)


def raw_pub(key) -> str:
    return base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def claims(sim, **over):
    now = sim.clock.time_of(sim.tick).timestamp()
    c = {"v": 1, "kid": "k1", "token_id": f"t-{id(over)}-{len(over)}", "run_id": sim.run_id, "action": SIGNAL,
         "targets": ["TRF-01"], "params": {"plan": "normal"}, "idempotency_key": "idem-1", "reading_ids": ["r1"],
         "preview_id": None, "iss": "guardian", "aud": "twin", "iat": now, "exp": now + 60,
         "trust_score": 0.9, "risk_level": "R1"}
    c.update(over)
    return c


@pytest.fixture
def setup():
    key = Ed25519PrivateKey.generate()
    sim, book = world(TokensCfg(mode="signed", guardian_public_key=raw_pub(key)))
    return key, sim, book


def go(book, token, idem="idem-1"):
    return book.actuate(BRAIN, SIGNAL, ["TRF-01"], {"plan": "normal"}, token, idem)


def test_a_real_looking_g1_token_commits(setup):
    key, sim, book = setup
    r = go(book, g1_token(key, claims(sim, token_id="a1")))
    assert r.status == "committed" and r.token_id == "a1"


def test_the_same_token_cannot_be_used_twice(setup):
    key, sim, book = setup
    t = g1_token(key, claims(sim, token_id="once"))
    assert go(book, t, "idem-1").status == "committed"
    r = go(book, t, "idem-1b")
    assert r.status == "rejected" and r.code in {"TOKEN_REUSED", "TOKEN_MISMATCH"}


@pytest.mark.parametrize("how", ["raw", "pem_text", "pem_file"])
def test_the_public_key_may_be_raw_base64_pem_text_or_a_pem_file(how, tmp_path):
    key = Ed25519PrivateKey.generate()
    pem = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    p = tmp_path / "g-pub.pem"
    p.write_bytes(pem)
    value = {"raw": raw_pub(key), "pem_text": pem.decode(), "pem_file": str(p)}[how]
    sim, book = world(TokensCfg(mode="signed", guardian_public_key=value))
    assert go(book, g1_token(key, claims(sim, token_id=f"k-{how}"))).status == "committed"


def test_bad_keys_are_refused_at_startup_with_a_plain_message(tmp_path):
    bad = tmp_path / "private.pem"
    bad.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                               serialization.NoEncryption()))
    for value in ("", "not base64 !!", "bm9wZQ==", str(bad), "-----BEGIN PUBLIC KEY-----\nxx\n-----END PUBLIC KEY-----"):
        with pytest.raises(ValueError):
            TokensCfg(mode="signed", guardian_public_key=value)
    with pytest.raises(ValueError):
        load_public_key(None)


def test_g1_needs_signed_mode_and_the_mode_still_comes_from_config_only():
    key = Ed25519PrivateKey.generate()
    sim, book = world(TokensCfg(mode="unsigned"))
    r = go(book, g1_token(key, claims(sim, token_id="u1")))
    assert r.status == "rejected" and r.code == "TOKEN_INVALID"


def test_wrong_signer_and_a_changed_payload_are_refused(setup):
    key, sim, book = setup
    stranger = g1_token(Ed25519PrivateKey.generate(), claims(sim, token_id="s1"))
    good = g1_token(key, claims(sim, token_id="s2")).split(".")
    swapped = ".".join([good[0], g1_token(key, claims(sim, token_id="s3", params={"plan": "all_red"})).split(".")[1], good[2]])
    for t in (stranger, swapped, "g1.@@@.@@@", "g1.e30.AAAA"):
        r = go(book, t, f"i-{id(t)}")
        assert r.status == "rejected" and r.code == "TOKEN_INVALID", t


def test_token_made_for_another_request_is_a_mismatch(setup):
    key, sim, book = setup
    assert go(book, g1_token(key, claims(sim, token_id="m1", params={"plan": "all_red"}))).code == "TOKEN_MISMATCH"
    assert go(book, g1_token(key, claims(sim, token_id="m2", targets=["TRF-04"]))).code == "TOKEN_MISMATCH"


def test_token_is_bound_to_the_idempotency_key_it_was_issued_for(setup):
    key, sim, book = setup
    r = go(book, g1_token(key, claims(sim, token_id="b1", idempotency_key="the-key-guardian-saw")), "another-key")
    assert r.status == "rejected" and r.code == "TOKEN_MISMATCH" and "idempotency_key" in r.message
    # an empty key in the token means "not bound", which the older format always did
    assert go(book, g1_token(key, claims(sim, token_id="b2", idempotency_key="")), "any-key").status == "committed"


@pytest.mark.parametrize("over", [
    {"token_id": ""}, {"token_id": "   "},                         # empty id
    {"trust_score": 1.5}, {"trust_score": -0.1}, {"trust_score": math.nan}, {"trust_score": True},
    {"exp_delta": 120}, {"exp_delta": 0}, {"exp_delta": -5},        # lifetime must be 1..60 s
    {"iat_delta": 30},                                             # dated in the future
    {"v": 2},                                                      # unknown version
    {"iss": "someone"}, {"aud": "brain"},
])
def test_sanity_checks_from_civis_list(setup, over):
    key, sim, book = setup
    over = dict(over)
    now = sim.clock.time_of(sim.tick).timestamp()
    if "exp_delta" in over:
        over["exp"] = now + over.pop("exp_delta")
    if "iat_delta" in over:
        d = over.pop("iat_delta")
        over["iat"], over["exp"] = now + d, now + d + 60
    over.setdefault("token_id", f"san-{abs(hash(str(over)))}")
    r = go(book, g1_token(key, claims(sim, **over)))
    assert r.status == "rejected" and r.code == "TOKEN_INVALID", (over, r.code, r.message)
    assert book.seq == 0                                           # nothing was committed


def test_expired_g1_token_is_refused_by_the_simulated_clock(setup):
    key, sim, book = setup
    sim.tick = 100
    now = sim.clock.time_of(sim.tick).timestamp()
    r = go(book, g1_token(key, claims(sim, token_id="e1", iat=now - 61, exp=now - 1)))
    assert r.status == "rejected" and r.code == "TOKEN_EXPIRED"


def test_read_token_gives_the_same_claims_names_as_our_own_format(setup):
    key, sim, _ = setup
    c = read_token(g1_token(key, claims(sim, token_id="r1", trust_score=0.77)), TokensCfg(
        mode="signed", guardian_public_key=raw_pub(key)))
    assert (c.jti, c.score, c.action, c.targets, c.params, c.idempotency_key) == (
        "r1", 0.77, SIGNAL, ["TRF-01"], {"plan": "normal"}, "idem-1")
    assert c.iat.endswith("Z") and c.exp.endswith("Z")


def test_old_format_still_works_next_to_g1(setup):
    from twin.tokens import make_token
    key, sim, book = setup
    c = {"iss": "guardian", "aud": "twin", "jti": "old-1", "run_id": sim.run_id, "iat": sim.clock.iso_of(sim.tick),
         "exp": sim.clock.iso_of(sim.tick + 30), "action": SIGNAL, "targets": ["TRF-01"], "params": {"plan": "normal"},
         "score": 0.9}
    assert go(book, make_token(c, key)).status == "committed"


def test_a_json_true_score_in_our_own_format_is_refused_too(setup):
    from twin.tokens import make_token
    key, sim, book = setup
    c = {"iss": "guardian", "aud": "twin", "jti": "bool-1", "run_id": sim.run_id, "iat": sim.clock.iso_of(sim.tick),
         "exp": sim.clock.iso_of(sim.tick + 30), "action": SIGNAL, "targets": ["TRF-01"], "params": {"plan": "normal"},
         "score": True}
    r = go(book, make_token(c, key))
    assert r.status == "rejected" and r.code == "TOKEN_INVALID"

"""Fixes from the code review of 4 Nov (F1, F2, F3, F9). One file, so the review and its tests stay together.

F1  the token mode can be set from the environment, the Twin refuses signed mode without a key, /health shows the mode
F2  a Twin that runs on the public example keys says so loudly
F3  token times without a timezone, or numbers too big for a date, are refused with TOKEN_INVALID (they used to crash)
F9  the unused `partners` setting is gone, and an old copy of the config that still has it keeps working
"""
import base64
import json
import logging
from pathlib import Path

import httpx2
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from twin.actions import ActionBook
from twin.app import create_app
from twin.auth import Identity
from twin.generator import generate
from twin.settings import (DEFAULT_CONFIG, EXAMPLE_KEYS, ConfigError, Secrets, Settings, TokensCfg, TWIN_ROOT,
                           example_keys_in_use, load_config)
from twin.sim import Simulation
from twin.tokens import TokenError, make_token, read_token

KEY = Ed25519PrivateKey.generate()
PUB = base64.b64encode(KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
SIGNAL = "set_signal_plan"


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def g1(claims: dict) -> str:
    payload = b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    return f"g1.{payload}." + b64(KEY.sign(f"g1.{payload}".encode()))


def book(tokens: TokensCfg):
    cfg = load_config()
    cfg.tokens = tokens
    topo, _ = generate(cfg)
    sim = Simulation(topo, cfg)
    return sim, ActionBook(topo, cfg, sim)


def jws_claims(sim, **over):
    c = {"iss": "guardian", "aud": "twin", "jti": "j-1", "run_id": sim.run_id, "iat": sim.clock.iso_of(sim.tick),
         "exp": sim.clock.iso_of(sim.tick + 30), "action": SIGNAL, "targets": ["TRF-01"],
         "params": {"plan": "normal"}, "score": 0.9}
    c.update(over)
    return c


def send(sim, book_, token, idem):
    return book_.actuate(Identity.CITY_BRAIN, SIGNAL, ["TRF-01"], {"plan": "normal"}, token, idem)


# ------------------------------------------------------------------ F3
@pytest.mark.parametrize("mode", ["unsigned", "signed"])
@pytest.mark.parametrize("name,over", [
    ("both times without timezone", {"iat": "2026-10-05T08:00:00", "exp": "2026-10-05T08:00:30"}),
    ("only iat without timezone", {"iat": "2026-10-05T08:00:00"}),
    ("only exp without timezone", {"exp": "2026-10-05T08:00:30"}),
    ("a time that is not a date", {"exp": "soon"}),
])
def test_f3_times_without_timezone_are_refused_not_crashed(mode, name, over):
    tokens = TokensCfg(mode="signed", guardian_public_key=PUB) if mode == "signed" else TokensCfg(mode="unsigned")
    sim, b = book(tokens)
    token = make_token(jws_claims(sim, **over), KEY if mode == "signed" else None)
    res = send(sim, b, token, f"f3-{name}")               # used to raise TypeError for the first three
    assert res.status == "rejected" and res.code == "TOKEN_INVALID", name
    assert res.message and "Token" in res.message


def test_f3_the_message_names_the_missing_timezone():
    sim, b = book(TokensCfg(mode="unsigned"))
    res = send(sim, b, make_token(jws_claims(sim, iat="2026-10-05T08:00:00", exp="2026-10-05T08:00:30")), "f3-msg")
    assert "timezone" in res.message


@pytest.mark.parametrize("bad_time", [1e20, 1e300, -1e20])
def test_f3_g1_time_numbers_too_big_for_a_date_are_refused(bad_time):
    """_epoch_to_iso raised OverflowError for these and only ValueError was caught."""
    cfg = TokensCfg(mode="signed", guardian_public_key=PUB)
    sim, _ = book(cfg)
    now = sim.clock.time_of(sim.tick).timestamp()
    claims = {"v": 1, "token_id": "t-big", "run_id": sim.run_id, "action": SIGNAL, "targets": ["TRF-01"],
              "params": {"plan": "normal"}, "idempotency_key": "k", "iss": "guardian", "aud": "twin",
              "iat": now, "exp": now + 60, "trust_score": 0.9}
    for field in ("iat", "exp"):
        with pytest.raises(TokenError) as e:
            read_token(g1({**claims, field: bad_time}), cfg)
        assert e.value.code == "TOKEN_INVALID"


def test_f3_a_good_token_still_commits():
    sim, b = book(TokensCfg(mode="unsigned"))
    assert send(sim, b, make_token(jws_claims(sim)), "f3-ok").status == "committed"


# ------------------------------------------------------------------ F1
def test_f1_default_config_is_still_unsigned(monkeypatch):
    monkeypatch.delenv("TWIN_TOKEN_MODE", raising=False)
    monkeypatch.delenv("TWIN_GUARDIAN_PUBLIC_KEY", raising=False)
    assert load_config().tokens.mode == "unsigned"


def test_f1_environment_switches_to_signed(monkeypatch):
    monkeypatch.setenv("TWIN_TOKEN_MODE", "signed")
    monkeypatch.setenv("TWIN_GUARDIAN_PUBLIC_KEY", PUB)
    cfg = load_config()
    assert cfg.tokens.mode == "signed" and cfg.tokens.guardian_public_key == PUB


def test_f1_signed_without_a_key_does_not_start(monkeypatch):
    monkeypatch.setenv("TWIN_TOKEN_MODE", "signed")
    monkeypatch.delenv("TWIN_GUARDIAN_PUBLIC_KEY", raising=False)
    with pytest.raises(ConfigError, match="guardian_public_key"):
        load_config()


def test_f1_a_wrong_mode_word_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("TWIN_TOKEN_MODE", "sign")
    with pytest.raises(ConfigError, match="TWIN_TOKEN_MODE"):
        load_config()


def test_f1_a_key_alone_does_not_change_the_mode(monkeypatch):
    monkeypatch.delenv("TWIN_TOKEN_MODE", raising=False)
    monkeypatch.setenv("TWIN_GUARDIAN_PUBLIC_KEY", PUB)
    cfg = load_config()
    assert cfg.tokens.mode == "unsigned" and cfg.tokens.guardian_public_key == PUB


def test_f1_signed_from_the_environment_really_refuses_an_unsigned_token(monkeypatch):
    monkeypatch.setenv("TWIN_TOKEN_MODE", "signed")
    monkeypatch.setenv("TWIN_GUARDIAN_PUBLIC_KEY", PUB)
    cfg = load_config()
    sim, b = book(cfg.tokens)
    res = send(sim, b, make_token(jws_claims(sim, jti="j-forged", score=0.01)), "f1-forged")   # the review's attack
    assert res.status == "rejected" and res.code == "TOKEN_INVALID"
    assert send(sim, b, make_token(jws_claims(sim, jti="j-real"), KEY), "f1-real").status == "committed"


def test_f1_the_warning_in_unsigned_mode_says_what_to_do(config, caplog):
    cfg = config.model_copy(deep=True)
    cfg.tokens = TokensCfg(mode="unsigned")
    with caplog.at_level(logging.WARNING, logger="twin"):
        create_app(Settings(config=cfg, secrets=Secrets(city_brain="brain-test-key", guardian="guardian-test-key",
                                                          scenario="scenario-test-key")))
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "TOKENS ARE UNSIGNED" in text and "TWIN_TOKEN_MODE=signed" in text and "TWIN_GUARDIAN_PUBLIC_KEY" in text


def test_f1_no_unsigned_warning_in_signed_mode(config, caplog):
    cfg = config.model_copy(deep=True)
    cfg.tokens = TokensCfg(mode="signed", guardian_public_key=PUB)
    with caplog.at_level(logging.WARNING, logger="twin"):
        create_app(Settings(config=cfg, secrets=Secrets(city_brain="brain-test-key", guardian="guardian-test-key",
                                                          scenario="scenario-test-key")))
    assert "TOKENS ARE UNSIGNED" not in " ".join(r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_f1_health_shows_the_token_mode(base_url):
    async with httpx2.AsyncClient() as h:
        body = (await h.get(base_url + "/health")).json()
    assert body["token_mode"] in ("unsigned", "signed")


# ------------------------------------------------------------------ F2
def test_f2_the_table_in_the_code_equals_env_example():
    pairs = {}
    for line in (TWIN_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            pairs[k.strip()] = v.strip()
    assert {k: pairs[k] for k in EXAMPLE_KEYS} == EXAMPLE_KEYS


def test_f2_own_keys_give_no_warning():
    s = Secrets(city_brain="brain-test-key", guardian="guardian-test-key", scenario="scenario-test-key")
    assert example_keys_in_use(s) == []


def test_f2_each_example_key_is_found():
    s = Secrets(city_brain=EXAMPLE_KEYS["TWIN_KEY_CITY_BRAIN"], guardian="guardian-test-key",
                scenario=EXAMPLE_KEYS["TWIN_KEY_SCENARIO"])
    assert example_keys_in_use(s) == ["TWIN_KEY_CITY_BRAIN", "TWIN_KEY_SCENARIO"]


def test_f2_the_startup_warning_names_the_keys_and_never_prints_a_value(config, caplog):
    s = Secrets(city_brain="brain-test-key", guardian=EXAMPLE_KEYS["TWIN_KEY_GUARDIAN"],
                scenario=EXAMPLE_KEYS["TWIN_KEY_SCENARIO"])
    with caplog.at_level(logging.WARNING, logger="twin"):
        create_app(Settings(config=config, secrets=s))
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "TWIN_KEY_GUARDIAN" in text and "TWIN_KEY_SCENARIO" in text and "start attacks" in text
    assert "TWIN_KEY_CITY_BRAIN" not in text
    assert not any(v in text for v in EXAMPLE_KEYS.values())


def test_f2_no_example_warning_with_own_keys(config, caplog):
    with caplog.at_level(logging.WARNING, logger="twin"):
        create_app(Settings(config=config, secrets=Secrets(city_brain="brain-test-key", guardian="guardian-test-key",
                                                          scenario="scenario-test-key")))
    assert "PUBLIC EXAMPLE VALUE" not in " ".join(r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------ F9
def test_f9_the_shipped_config_has_no_partners_section():
    raw = yaml.safe_load(Path(DEFAULT_CONFIG).read_text(encoding="utf-8"))
    assert "partners" not in raw


def test_f9_an_old_copy_of_the_config_still_loads_and_says_it_ignores_the_section(tmp_path, caplog):
    raw = yaml.safe_load(Path(DEFAULT_CONFIG).read_text(encoding="utf-8"))
    raw["partners"] = {"city_brain": {"url": "http://127.0.0.1:8001/mcp"}, "guardian": {"url": "http://127.0.0.1:8002/mcp"}}
    old = tmp_path / "old-twin.yaml"
    old.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="twin"):
        cfg = load_config(old)
    assert cfg.seed == 42 and not hasattr(cfg, "partners")
    assert any("partners" in r.getMessage() and "ignored" in r.getMessage() for r in caplog.records)

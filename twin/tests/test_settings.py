"""Config and secrets loading."""
import pytest

from twin.settings import ConfigError, load_config, load_settings


def test_config_loads():
    cfg = load_config()
    assert cfg.seed == 42 and cfg.server.port == 8000


def test_seed_override_from_environment(monkeypatch):
    monkeypatch.setenv("TWIN_SEED", "7")
    assert load_config().seed == 7


def test_bad_seed_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("TWIN_SEED", "abc")
    with pytest.raises(ConfigError, match="TWIN_SEED"):
        load_config()


def test_missing_secrets_named_in_error(monkeypatch, tmp_path):
    for k in ("TWIN_KEY_CITY_BRAIN", "TWIN_KEY_GUARDIAN", "TWIN_KEY_SCENARIO"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("twin.settings.TWIN_ROOT", tmp_path)      # no .env here
    from twin import settings as s
    monkeypatch.setitem(s.Secrets.model_config, "env_file", tmp_path / ".env")
    with pytest.raises(ConfigError, match="TWIN_KEY_CITY_BRAIN"):
        load_settings()


def test_duplicate_keys_rejected(monkeypatch, tmp_path):
    from twin import settings as s
    monkeypatch.setitem(s.Secrets.model_config, "env_file", tmp_path / ".env")
    for k in ("TWIN_KEY_CITY_BRAIN", "TWIN_KEY_GUARDIAN", "TWIN_KEY_SCENARIO"):
        monkeypatch.setenv(k, "same-key-value")
    with pytest.raises(ConfigError, match="different"):
        load_settings()


def test_typo_in_yaml_is_an_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("server: {host: x, prot: 1}\n")
    with pytest.raises(ConfigError):
        load_config(bad)

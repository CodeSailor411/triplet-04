"""Loads and checks the Twin's configuration.

Two sources, kept apart on purpose:
  * config/twin.yaml  - normal settings, safe to commit
  * environment / .env - the secrets (one key per caller), never committed
"""
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TWIN_ROOT = Path(__file__).resolve().parents[2]      # the twin/ folder
DEFAULT_CONFIG = TWIN_ROOT / "config" / "twin.yaml"


class ConfigError(Exception):
    """The configuration is missing or wrong. The message says what to fix."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")        # a typo in the YAML is an error, not silently ignored


# ----------------------------------------------------------------- yaml sections
class ServerCfg(_Strict):
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)


class SseCfg(_Strict):
    heartbeat_seconds: float = Field(15, gt=0)


class PartnerCfg(_Strict):
    url: str


class SensorCfg(_Strict):
    unit: str


class ActuatorCfg(_Strict):
    domain: str
    values: list[str] | str
    risk: str | None = None


class CapsCfg(_Strict):
    action_pct: int = Field(ge=1, le=100)
    isolation_pct: int = Field(ge=1, le=100)
    min_nodes: int = Field(ge=1)
    isolation_pct_overrides: dict[str, int] = {}


class CanvasCfg(_Strict):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ZoneGridCfg(_Strict):
    cols: int = Field(ge=1)
    rows: int = Field(ge=1)


class DomainCfg(_Strict):
    prefix: str
    count: int = Field(ge=1)
    sensors: list[str] = []
    actuator: str | None = None
    actuator_nodes: int = Field(0, ge=0)
    actuator_role: str | None = None


class RoleCfg(_Strict):
    sensors: list[str]
    zone: str | None = None


class CallPlaceCfg(_Strict):
    label: str
    zone: str
    also_in: list[str] = []


class SharedCfg(_Strict):
    label: str
    domains: list[str] = Field(min_length=2, max_length=2)
    zone: str


class CrossCfg(_Strict):
    from_domain: str
    from_role: str | None = None
    to_domain: str
    count: int = Field(ge=1)


class NeighbourCfg(_Strict):
    same_domain: int = Field(ge=0)
    cross: list[CrossCfg] = []


class GeneratorCfg(_Strict):
    canvas: CanvasCfg
    node_size_px: int = Field(gt=0)
    min_spacing_factor: float = Field(gt=0)
    canvas_margin_px: int = Field(ge=0)
    road_gap_px: int = Field(ge=0)
    zone_grid: ZoneGridCfg
    zones: list[str]
    domain_order: list[str]
    domains: dict[str, DomainCfg]
    emergency_roles: dict[str, RoleCfg]
    call_places: list[CallPlaceCfg]
    shared: list[SharedCfg]
    neighbours: NeighbourCfg

    @model_validator(mode="after")
    def _check(self):
        if len(self.zones) != self.zone_grid.cols * self.zone_grid.rows:
            raise ValueError("generator.zones must list exactly cols x rows zone names")
        for d in self.domain_order:
            if d not in self.domains:
                raise ValueError(f"generator.domain_order names unknown domain '{d}'")
        return self


class TwinConfig(_Strict):
    server: ServerCfg
    seed: int
    sse: SseCfg
    partners: dict[str, PartnerCfg]
    sensors: dict[str, SensorCfg]
    actuators: dict[str, ActuatorCfg]
    caps: CapsCfg
    generator: GeneratorCfg


# ----------------------------------------------------------------- secrets
class Secrets(BaseSettings):
    """One secret per caller. Read from the environment or from twin/.env."""
    model_config = SettingsConfigDict(
        env_prefix="TWIN_KEY_", env_file=TWIN_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    city_brain: SecretStr = Field(min_length=8)
    guardian: SecretStr = Field(min_length=8)
    scenario: SecretStr = Field(min_length=8)


class Settings(BaseModel):
    config: TwinConfig
    secrets: Secrets
    model_config = ConfigDict(arbitrary_types_allowed=True)


def load_config(config_path: Path | str | None = None) -> TwinConfig:
    """Read config/twin.yaml (no secrets needed), apply the TWIN_SEED override, fail with a clear message."""
    path = Path(config_path or os.environ.get("TWIN_CONFIG") or DEFAULT_CONFIG)
    if not path.is_absolute():
        path = TWIN_ROOT / path
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file is not valid YAML ({path}): {exc}") from None
    if "TWIN_SEED" in os.environ:
        try:
            raw["seed"] = int(os.environ["TWIN_SEED"])
        except ValueError:
            raise ConfigError("TWIN_SEED must be a whole number, for example TWIN_SEED=42") from None
    try:
        return TwinConfig.model_validate(raw)
    except ValidationError as exc:
        lines = [f"  {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise ConfigError(f"Config file {path} has problems:\n" + "\n".join(lines)) from None


def load_settings(config_path: Path | str | None = None) -> Settings:
    """Config plus the secrets. Fails with a message that says what to fix."""
    config = load_config(config_path)
    try:
        secrets = Secrets()
    except ValidationError as exc:
        missing = sorted({f"TWIN_KEY_{str(e['loc'][0]).upper()}" for e in exc.errors()})
        raise ConfigError(
            "Missing or too short secrets: " + ", ".join(missing) + ". "
            "Copy .env.example to .env (keys need at least 8 characters)."
        ) from None
    values = [secrets.city_brain.get_secret_value(), secrets.guardian.get_secret_value(),
              secrets.scenario.get_secret_value()]
    if len(set(values)) != 3:
        raise ConfigError("The three keys must be different from each other.")
    return Settings(config=config, secrets=secrets)

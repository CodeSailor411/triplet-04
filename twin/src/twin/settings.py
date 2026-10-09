"""Loads and checks the Twin's configuration.

Two sources, kept apart on purpose:
  * config/twin.yaml  - normal settings, safe to commit
  * environment / .env - the secrets (one key per caller), never committed
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Literal

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


class ClockCfg(_Strict):
    start: str = "2026-10-05T08:00:00.000Z"
    tick_seconds: float = Field(1.0, gt=0)
    speed: float = Field(1.0, gt=0)
    autorun: bool = True

    @model_validator(mode="after")
    def _check(self):
        if not self.start.endswith("Z"):
            raise ValueError("clock.start must be UTC with a Z, for example 2026-10-05T08:00:00.000Z")
        try:
            datetime.fromisoformat(self.start)
        except ValueError:
            raise ValueError("clock.start is not a valid RFC 3339 time") from None
        return self


class FollowsCfg(_Strict):
    sensor: str
    gain: float


class ProfileCfg(_Strict):
    base: float
    wave_amp: float = Field(0, ge=0)
    wave_period_ticks: int = Field(600, ge=2)
    wander_amp: float = Field(0, ge=0)
    wander_ticks: int = Field(90, ge=2)
    noise_sd: float = Field(0, ge=0)
    bias_sd: float = Field(0, ge=0)
    min_value: float | None = None
    max_value: float | None = None
    decimals: int = Field(1, ge=0, le=6)
    spread: float | None = Field(None, ge=0, le=0.5)      # overrides device_spread for this sensor
    follows: FollowsCfg | None = None
    channels: dict[str, float] = {}


class SensorModelCfg(_Strict):
    device_spread: float = Field(0.12, ge=0, le=0.5)
    timing_wobble_ms: float = Field(40, ge=0)
    profiles: dict[str, ProfileCfg]


class PartnerCfg(_Strict):
    url: str


class SensorCfg(_Strict):
    unit: str


class ParamCfg(_Strict):
    """One input of an action. type: choice (one of `choices`), number, integer, or node (an existing node id)."""
    type: Literal["choice", "number", "integer", "node"]
    choices: list[str] = []
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.type == "choice" and not self.choices:
            raise ValueError("a choice parameter needs a non-empty choices list")
        return self


class ActuatorCfg(_Strict):
    domain: str
    risk: Literal["R1", "R2", "R3"] | None = None      # picked by CIVIS on 4 Oct
    preview_required: bool = False                      # our own flag, not a risk tier
    params: dict[str, ParamCfg]


class TokensCfg(_Strict):
    mode: Literal["unsigned", "signed"] = "unsigned"
    guardian_public_key: str | None = None              # base64 of the raw 32-byte Ed25519 public key
    min_score: dict[str, float] = {}                    # risk level -> minimum score. Empty = not enforced (no number agreed)

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "signed":
            import base64
            try:
                raw = base64.b64decode(self.guardian_public_key or "", validate=True)
            except Exception:
                raw = b""
            if len(raw) != 32:
                raise ValueError("tokens.mode is 'signed', so tokens.guardian_public_key must be the base64 of a "
                                 "raw 32-byte Ed25519 public key")
        bad = set(self.min_score) - {"R1", "R2", "R3"}
        if bad:
            raise ValueError(f"tokens.min_score has unknown risk levels: {sorted(bad)}")
        return self


class ActionsCfg(_Strict):
    preview_enforced: bool = False      # becomes true when the preview tool exists (15 Oct)


class CapsCfg(_Strict):
    action_pct: int = Field(ge=1, le=100)
    isolation_pct: int = Field(ge=1, le=100)
    min_nodes: int = Field(ge=1)
    isolation_pct_overrides: dict[str, int] = {}


class ContainmentCfg(_Strict):
    rollback_lookback_ticks: int = Field(default=60, ge=1)    # how far back rollback searches for a trusted value
    held_commands_kept: int = Field(default=50, ge=1)         # how many held commands the quarantine lane remembers


class LoggingCfg(_Strict):
    enabled: bool = True
    parts_dir: str = "run-logs"       # the Twin's own part files (not committed)
    merged_dir: str = "../logs"       # the shared folder in the repo: one merged file per run


class DashboardCfg(_Strict):
    host: str = "127.0.0.1"
    port: int = 8080
    # Folders (or files) with run logs. Part files and merged files may both be listed: the same event is only shown once.
    # The last two are GUESSES at where CIVIS and 9antra keep their part files. A folder that does not exist is ignored.
    sources: list[str] = ["run-logs", "../logs", "../brain/run-logs", "../guardian/run-logs"]
    refresh_seconds: float = Field(default=1.0, ge=0.2)
    window_ticks: int = Field(default=60, ge=0)          # 0 = the whole run
    # PLACEHOLDERS. Guardian will publish its own cut-offs (decision report: a verdict is a score only, no label).
    trusted_from: float = Field(default=0.8, ge=0, le=1)
    degraded_from: float = Field(default=0.5, ge=0, le=1)


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
    clock: ClockCfg
    tokens: TokensCfg
    actions: ActionsCfg
    sensor_model: SensorModelCfg
    partners: dict[str, PartnerCfg]
    sensors: dict[str, SensorCfg]
    actuators: dict[str, ActuatorCfg]
    caps: CapsCfg
    containment: ContainmentCfg = ContainmentCfg()
    logging: LoggingCfg = LoggingCfg()
    dashboard: DashboardCfg = DashboardCfg()
    generator: GeneratorCfg

    @model_validator(mode="after")
    def _check_sensor_model(self):
        listed, modelled = set(self.sensors), set(self.sensor_model.profiles)
        if listed != modelled:
            raise ValueError("sensor_model.profiles must match the sensors list exactly. Missing a profile: "
                             f"{sorted(listed - modelled)}. Profile without a sensor: {sorted(modelled - listed)}")
        for name, prof in self.sensor_model.profiles.items():
            if prof.follows and prof.follows.sensor not in modelled:
                raise ValueError(f"sensor_model.profiles.{name}.follows names unknown sensor '{prof.follows.sensor}'")
        wobble_ms = self.sensor_model.timing_wobble_ms
        if wobble_ms * 4 > self.clock.tick_seconds * 1000 * 0.25 and wobble_ms > 0:
            raise ValueError("sensor_model.timing_wobble_ms is too large for clock.tick_seconds "
                             "(readings of one device could arrive out of order)")
        return self


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

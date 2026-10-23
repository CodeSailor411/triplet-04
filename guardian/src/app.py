"""Guardian's local advisory MCP server and offline playground host."""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Literal

import joblib
import pandas as pd
from cryptography.hazmat.primitives import serialization
from mcp.server import MCPServer
from pydantic import BaseModel, ConfigDict
from guardian_policy import load_trust_policy
from action_policy import ActionPolicy
from token_service import ActionTokenService
from contract import (TRUST_STATE_MAP, MCP_TOOL_DESCRIBE_CAPABILITIES,
                      MCP_TOOL_EVALUATE_READING_ADVISORY, MCP_PUBLIC_TOOL_NAMES,
                      MCP_TOOL_VERIFY_ACTION_TOKEN)
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
WEB_DIST = ROOT / "web" / "dist"
MODEL_PATH = MODELS_DIR / "guardian_random_forest.joblib"
METADATA = json.loads((MODELS_DIR / "model_metadata.json").read_text(encoding="utf-8"))
SENSOR_CONFIG = json.loads((MODELS_DIR / "sensor_config.json").read_text(encoding="utf-8"))
REFERENCE_RULES = json.loads((Path(__file__).resolve().parent / "reference_rules_config.json").read_text(encoding="utf-8"))
DECISION_THRESHOLD = float(METADATA["decision_threshold"]["value"])
UNCERTAINTY_BAND = float(METADATA["decision_threshold"]["uncertainty_band"])
DOMAINS = SENSOR_CONFIG["domains"]

# The serialized pipeline imports guardian_rf_features by module name. Put the
# model bundle first so its co-located feature module and sensor config are used.
sys.path.insert(0, str(MODELS_DIR))
import guardian_rf_features as feature_module  # noqa: E402

server = MCPServer(
    "guardian-model-lab",
    version="1.0.0",
    instructions=(
        "This service returns an advisory Random Forest anomaly signal. It does not return "
        "Guardian trust scores, verdicts, or action tokens. Deterministic Guardian rules decide."
    ),
)

_model = None
_model_error: str | None = None


class ModelProbabilities(BaseModel):
    trusted: float
    suspicious: float


class AdvisoryOutput(BaseModel):
    ml_label: Literal["Trusted", "Uncertain", "Suspicious", "Unavailable"]
    ml_probabilities: ModelProbabilities | None
    decision_threshold: float
    uncertain: bool
    signals: list[str]
    advisory_only: Literal[True]
    model_version: str
    model_available: bool


class DomainCapability(BaseModel):
    quantity: str
    unit: str
    lo: float
    hi: float
    max_rate: float


class TrustCutoffs(BaseModel):
    trusted_min: float
    degraded_min: float
    confirmation: str


class ReferenceRuleConfig(BaseModel):
    out_of_bounds: float
    rate_of_change_exceeded: float
    statistical_drift_outlier: float
    no_correlated_evidence: float
    weak_correlated_evidence: float
    weak_correlation_min: float
    correlation_satisfied_min: float
    prior_flag_per_count: float
    prior_flag_cap: float


class CapabilitiesOutput(BaseModel):
    protocol_version: str
    model_version: str
    model_available: bool
    decision_threshold: float
    uncertainty_band: float
    domains: dict[str, DomainCapability]
    trust_cutoffs: TrustCutoffs
    reference_rules: ReferenceRuleConfig
    guardian_verdict_policy: dict
    supported_tools: list[str]
    supported_actions: list[str]
    action_aliases: dict[str, str]
    action_token: dict
    advisory_only: Literal[True]


def load_model():
    """Load only the model artifact stored in this repository; cache failures too."""
    global _model, _model_error
    if _model is None and _model_error is None:
        try:
            _model = joblib.load(MODEL_PATH)
            # The checked-in forest's n_jobs=-1 uses Windows worker pipes,
            # which are denied in restricted desktop test environments. A
            # single worker gives identical probabilities and keeps the
            # serialized artifact untouched.
            steps = getattr(_model, "steps", [])
            if steps and hasattr(steps[-1][1], "n_jobs"):
                steps[-1][1].n_jobs = 1
        except Exception as exc:  # Keep MCP/capabilities available when inference is unavailable.
            _model_error = f"{type(exc).__name__}: {exc}"
    return _model


def validate_reading(record: dict) -> dict:
    """Validate a root-level CIVIS feature object and ignore unknown fields."""
    required = feature_module.RAW_INPUT_COLUMNS
    missing = [field for field in required if field not in record]
    if missing:
        raise ValueError(f"Reading is missing required fields: {', '.join(missing)}")
    domain = record["domain"]
    if not isinstance(domain, str) or domain not in DOMAINS:
        raise ValueError(f"Unknown domain {domain!r}; expected one of {', '.join(sorted(DOMAINS))}")
    cleaned = {field: record[field] for field in required}
    if cleaned["value"] is not None:
        for field in required:
            if field == "domain":
                continue
            value = cleaned[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Field {field!r} must be a finite number")
        if not 0 <= cleaned["correlation_strength"] <= 1:
            raise ValueError("Field 'correlation_strength' must be between 0 and 1")
    return cleaned


def explain_signals(record: dict) -> list[str]:
    """Notebook-compatible rule-of-thumb flags, not model attribution."""
    domain = DOMAINS[record["domain"]]
    signals = []
    if record["out_of_bounds"]:
        signals.append(f"value {record['value']:.1f} {domain['unit']} is outside the configured range {domain['lo']}-{domain['hi']}")
    if abs(record["z_score"]) > 3:
        signals.append(f"large deviation from recent history (|z|={abs(record['z_score']):.1f})")
    if record["rate_of_change"] > domain["max_rate"]:
        signals.append("change per tick exceeds the configured maximum rate for this domain")
    if abs(record["baseline_dev_norm"]) > 0.25:
        signals.append(f"{record['baseline_dev_norm']:+.0%} of the configured range away from its baseline")
    if record["flat_run_len"] >= 3:
        signals.append(f"identical to the previous {int(record['flat_run_len'])} readings (possible stuck sensor)")
    if record["incident_claimed"] and record["correlation_strength"] < 0.5:
        signals.append(f"incident claimed but weak neighbour corroboration ({record['correlation_strength']:.2f})")
    if record["decayed_flags"] >= 1:
        signals.append(f"device carries {record['decayed_flags']:.1f} decayed reputation flag(s)")
    return signals or ["no individual warning signals in the inputs"]


def predict_reading(record: dict) -> AdvisoryOutput:
    """Evaluate a reading using the same feature pipeline as the saved notebook."""
    cleaned = validate_reading(record)
    model = load_model()
    version = str(METADATA.get("model_version", "unknown"))
    if cleaned["value"] is None:
        return AdvisoryOutput(
            ml_label="Unavailable", ml_probabilities=None, decision_threshold=DECISION_THRESHOLD,
            uncertain=True, signals=["value is missing (JSON null); the model abstains and Guardian rules decide"],
            advisory_only=True, model_version=version, model_available=model is not None,
        )
    if model is None:
        return AdvisoryOutput(
            ml_label="Unavailable", ml_probabilities=None, decision_threshold=DECISION_THRESHOLD,
            uncertain=True, signals=["Model unavailable — Guardian rules decide"],
            advisory_only=True, model_version=version, model_available=False,
        )
    model_input = pd.DataFrame([cleaned], columns=feature_module.RAW_INPUT_COLUMNS)
    probabilities = model.predict_proba(model_input)[0]
    classes = list(model.classes_)
    suspicious_index = next((i for i, label in enumerate(classes) if str(label).lower() in {"1", "suspicious", "compromised", "suspect"}), None)
    if suspicious_index is None:
        raise RuntimeError(f"The saved model has no suspicious class; classes were {classes!r}")
    suspicious = float(probabilities[suspicious_index])
    trusted = float(1.0 - suspicious)
    lower = DECISION_THRESHOLD - UNCERTAINTY_BAND
    upper = DECISION_THRESHOLD + UNCERTAINTY_BAND
    if suspicious < lower:
        label: Literal["Trusted", "Uncertain", "Suspicious", "Unavailable"] = "Trusted"
    elif suspicious >= upper:
        label = "Suspicious"
    else:
        label = "Uncertain"
    return AdvisoryOutput(
        ml_label=label,
        ml_probabilities=ModelProbabilities(trusted=trusted, suspicious=suspicious),
        decision_threshold=DECISION_THRESHOLD,
        uncertain=label == "Uncertain",
        signals=explain_signals(cleaned),
        advisory_only=True,
        model_version=version,
        model_available=True,
    )


@server.tool(
    name=MCP_TOOL_EVALUATE_READING_ADVISORY,
    title="Evaluate reading advisory",
    description=(
        "Return an advisory Random Forest suspicious probability for one sensor reading. "
        "This is not a Guardian trust score or actuator authorization."
    ),
    structured_output=True,
)
def evaluate_reading_advisory(
    domain: str,
    value: float | None,
    z_score: float,
    rate_of_change: float,
    out_of_bounds: float,
    correlation_strength: float,
    incident_claimed: float,
    decayed_flags: float,
    baseline_dev_norm: float,
    flat_run_len: float,
) -> AdvisoryOutput:
    """Evaluate a sensor feature vector. Must be called only after Layer A passes."""
    return predict_reading({
        "domain": domain, "value": value, "z_score": z_score, "rate_of_change": rate_of_change,
        "out_of_bounds": out_of_bounds, "correlation_strength": correlation_strength,
        "incident_claimed": incident_claimed, "decayed_flags": decayed_flags,
        "baseline_dev_norm": baseline_dev_norm, "flat_run_len": flat_run_len,
    })


@server.tool(name=MCP_TOOL_DESCRIBE_CAPABILITIES, title="Describe Guardian playground capabilities", structured_output=True)
def describe_capabilities() -> CapabilitiesOutput:
    """List model and configuration capabilities so clients can configure the playground."""
    model_available = load_model() is not None
    trust_policy = load_trust_policy()
    action_policy = ActionPolicy()
    token_service = ActionTokenService.from_env()
    public_key = token_service.public_key
    return CapabilitiesOutput(
        protocol_version="2026-07-28",
        model_version=str(METADATA.get("model_version", "unknown")),
        model_available=model_available,
        decision_threshold=DECISION_THRESHOLD,
        uncertainty_band=UNCERTAINTY_BAND,
        domains={key: DomainCapability(**value) for key, value in DOMAINS.items()},
        trust_cutoffs=TrustCutoffs(**REFERENCE_RULES["trust_cutoffs"]),
        reference_rules=ReferenceRuleConfig(**REFERENCE_RULES["penalties"]),
        guardian_verdict_policy={
            "states": TRUST_STATE_MAP,
            "trusted_min_inclusive": trust_policy.trusted_min,
            "degraded_min_exclusive": trust_policy.suspect_min,
            "risk_minimums": trust_policy.risk_minimums,
        },
        supported_tools=[*MCP_PUBLIC_TOOL_NAMES, *(
            [MCP_TOOL_VERIFY_ACTION_TOKEN]
            if os.environ.get("GUARDIAN_ENABLE_TEST_TOKEN_VERIFY", "false").casefold() in {"1", "true", "yes"}
            else [])],
        supported_actions=sorted(action_policy.allowlist),
        action_aliases=dict(action_policy.aliases),
        action_token={
            "version": 1,
            "kid": token_service.kid,
            "public_key_pem": (public_key.public_bytes(serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii") if public_key else None),
        },
        advisory_only=True,
    )


@server.custom_route("/debug/predict", methods=["POST"], include_in_schema=False)
async def local_debug_predict(request: Request) -> Response:
    """Local debugging only. Inter-layer evaluation must use the MCP tool."""
    if os.environ.get("DEMO_MODE", "false").casefold() not in {"1", "true", "yes"}:
        return JSONResponse({"error": "not_found"}, status_code=404)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object")
        result = predict_reading(body)
        return JSONResponse(result.model_dump(mode="json"))
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc), "local_debug_only": True}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Model evaluation failed: {type(exc).__name__}: {exc}", "local_debug_only": True}, status_code=503)


@server.custom_route("/", methods=["GET"], include_in_schema=False)
async def playground_index(request: Request) -> Response:
    index = WEB_DIST / "index.html"
    if not index.is_file():
        return JSONResponse({"error": "React bundle is missing; build guardian/web first."}, status_code=503)
    return FileResponse(index)


@server.custom_route("/{asset_path:path}", methods=["GET"], include_in_schema=False)
async def playground_assets(request: Request) -> Response:
    candidate = (WEB_DIST / request.path_params["asset_path"]).resolve()
    if candidate != WEB_DIST.resolve() and WEB_DIST.resolve() not in candidate.parents:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if candidate.is_file():
        return FileResponse(candidate)
    index = WEB_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse({"error": "React bundle is missing; build guardian/web first."}, status_code=503)


if __name__ == "__main__":
    server.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=int(__import__("os").environ.get("PORT", "5000")),
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
    )

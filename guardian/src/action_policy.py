"""Centralized action normalization, trust checks, and deterministic caps."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from guardian_policy import TrustPolicy, load_trust_policy


class ActionPolicyError(ValueError):
    pass


class ActionPolicy:
    def __init__(self, config_path: str | Path | None = None, trust_policy: TrustPolicy | None = None):
        config = json.loads(Path(config_path or Path(__file__).with_name("guardian_policy.json")).read_text(encoding="utf-8"))
        self.aliases = config["actions"]["aliases"]
        self.allowlist = set(config["actions"]["allowlist"])
        self.action_risks = config["actions"].get("action_risk_levels", {})
        self.action_domains = {k: v.casefold() for k, v in config["actions"].get("action_domains", {}).items()}
        self.power_cap = int(config["actions"]["power_action_cap"])
        self.power_action_scope = config["actions"].get("power_action_scope")
        if self.power_cap < 1 or self.power_action_scope != "per_run":
            raise ValueError("Power action cap must be positive and explicitly scoped per_run")
        self.pool_sizes = {k.lower(): int(v) for k, v in config["actions"]["rollback_pool_sizes"].items()}
        if any(size < 1 for size in self.pool_sizes.values()):
            raise ValueError("rollback pool sizes must be positive")
        self.trust = trust_policy or load_trust_policy(str(config_path) if config_path else None)
        self._lock = threading.RLock()
        self._power_actions: dict[str, int] = {}
        self._occupied_pools: dict[str, set[str]] = {k: set() for k in self.pool_sizes}

    def normalize(self, name: str) -> str:
        canonical = self.aliases.get(name, name)
        if canonical not in self.allowlist:
            raise ActionPolicyError("action_not_allowlisted")
        return canonical

    def authorize(self, *, run_id: str, action: str, parameters: dict[str, Any],
                  trust_score: float, risk_level: str, domain: str | None = None) -> tuple[str, str | None]:
        normalized = self.normalize(action)
        if not isinstance(parameters, dict):
            raise ActionPolicyError("parameters_must_be_object")
        classification = self.trust.classify(trust_score)
        minimum = self.trust.risk_minimums.get(risk_level)
        if risk_level != "NONE" and minimum is None:
            raise ActionPolicyError("unknown_risk_level")
        required_risk = self.action_risks.get(normalized)
        if normalized in self.action_risks and required_risk is None:
            raise ActionPolicyError("action_risk_level_unconfirmed")
        if required_risk and risk_level != required_risk:
            raise ActionPolicyError("action_risk_level_mismatch")
        required_domain = self.action_domains.get(normalized)
        if required_domain is None or (domain or "").casefold() != required_domain:
            raise ActionPolicyError("action_domain_mismatch")
        if risk_level == "NONE" and classification != "trusted":
            raise ActionPolicyError("untiered_action_requires_trusted_verdict")
        exact_fields = {
            "set_priority_mode": {"mode"},
            "send_collection_truck": {"destination", "trucks"},
            "set_signal_plan": {"plan"},
            "set_valve_position": {"position"},
            "set_grid_switch": {"state"},
            "dispatch": {"unit_type", "destination", "units"},
        }[normalized]
        if set(parameters) != exact_fields:
            raise ActionPolicyError("action_parameters_must_match_contract")
        if normalized == "set_signal_plan" and parameters["plan"] not in {"normal", "favor_main_road", "all_red"}:
            raise ActionPolicyError("invalid_signal_plan")
        if normalized == "set_valve_position":
            position = parameters["position"]
            if isinstance(position, bool) or not isinstance(position, (int, float)) or not 0 <= position <= 100:
                raise ActionPolicyError("valve_position_out_of_range")
        if normalized == "set_grid_switch" and parameters["state"] not in {"closed", "open"}:
            raise ActionPolicyError("invalid_grid_switch_state")
        if normalized == "dispatch":
            if parameters["unit_type"] not in {"police", "ambulance", "fire"}:
                raise ActionPolicyError("invalid_dispatch_unit_type")
            units = parameters["units"]
            if isinstance(units, bool) or not isinstance(units, int) or units < 1:
                raise ActionPolicyError("invalid_dispatch_units")
        if minimum is not None and trust_score < minimum:
            raise ActionPolicyError("risk_minimum_score_not_met")
        if normalized == "send_collection_truck":
            trucks = parameters.get("trucks", 1)
            if isinstance(trucks, bool) or not isinstance(trucks, int) or not 1 <= trucks <= 3:
                raise ActionPolicyError("trucks_out_of_range")
        if normalized == "set_priority_mode" and parameters.get("mode") not in {"normal", "emergency_first"}:
            raise ActionPolicyError("invalid_priority_mode")
        if normalized == "send_collection_truck":
            if not isinstance(parameters.get("destination"), str) or not parameters["destination"].strip():
                raise ActionPolicyError("invalid_collection_destination")
        if normalized == "dispatch":
            if not isinstance(parameters.get("destination"), str) or not parameters["destination"].strip():
                raise ActionPolicyError("invalid_dispatch_destination")
        if (domain or "").lower() == "power":
            with self._lock:
                used = self._power_actions.get(run_id, 0)
                if used >= self.power_cap:
                    raise ActionPolicyError("power_action_cap_exceeded")
                self._power_actions[run_id] = used + 1
        return normalized, None

    def reserve_rollback(self, domain: str, node_id: str) -> int:
        pool = domain.lower()
        if pool not in self.pool_sizes:
            raise ActionPolicyError("rollback_pool_not_configured")
        with self._lock:
            slots = self._occupied_pools[pool]
            if node_id in slots:
                return len(slots)
            if len(slots) >= self.pool_sizes[pool]:
                raise ActionPolicyError("rollback_pool_exhausted")
            slots.add(node_id)
            return len(slots)

    def release_rollback(self, domain: str, node_id: str) -> int:
        pool = domain.lower()
        with self._lock:
            if pool not in self._occupied_pools:
                raise ActionPolicyError("rollback_pool_not_configured")
            self._occupied_pools[pool].discard(node_id)
            return len(self._occupied_pools[pool])

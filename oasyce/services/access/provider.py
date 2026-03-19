"""
DataAccessProvider — Tiered Data Access with Bond-Based Authorization

Provides four access methods (query / sample / compute / deliver) that
enforce access-level checks, bond calculation, and exposure tracking.

Bond formula:
  Bond = TWAP(Value) × Multiplier(Level) × RiskFactor × (1 - R/100) × ExposureFactor

Each method delegates to the ReputationEngine and ExposureRegistry for
discount and exposure-factor lookups.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from oasyce.services.access import (
    AccessLevel,
    access_level_index,
    parse_max_access_level,
)
from oasyce.services.access.config import AccessControlConfig
from oasyce.services.reputation import ReputationEngine
from oasyce.services.exposure.registry import ExposureRegistry
from oasyce.services.leakage import LeakageBudget


# ─── Result types ─────────────────────────────────────────────────


@dataclass
class AccessResult:
    """Outcome of a data-access request."""

    success: bool
    data: Optional[Any] = None
    bond_required: float = 0.0
    access_level: str = ""
    error: Optional[str] = None
    warning: Optional[str] = None


# ─── DataAccessProvider ──────────────────────────────────────────


class DataAccessProvider:
    """Enforces tiered access control and computes bond requirements.

    Holds a registry of asset values (TWAP proxy) and risk levels so it
    can compute bonds.  Actual data retrieval is stubbed — callers must
    supply concrete data backends.
    """

    def __init__(
        self,
        config: Optional[AccessControlConfig] = None,
        reputation: Optional[ReputationEngine] = None,
        exposure: Optional[ExposureRegistry] = None,
        leakage: Optional[LeakageBudget] = None,
    ) -> None:
        self.config = config or AccessControlConfig()
        self.reputation = reputation or ReputationEngine(config=self.config)
        self.exposure = exposure or ExposureRegistry(config=self.config)
        self.leakage = leakage or LeakageBudget()
        # asset_id → {value, risk_level, max_access_level}
        self._assets: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ─── Asset registration ───────────────────────────────────────

    def register_asset(
        self,
        asset_id: str,
        value: float,
        risk_level: str = "public",
        max_access_level: str = "L3",
    ) -> None:
        """Register an asset with its TWAP value and risk metadata.

        Raises:
            ValueError: if value <= 0 or risk_level/max_access_level are invalid.
        """
        if value <= 0:
            raise ValueError(f"Asset value must be positive, got {value}")
        self._assets[asset_id] = {
            "value": value,
            "risk_level": risk_level,
            "max_access_level": max_access_level,
        }

    # ─── Access methods ───────────────────────────────────────────

    def query(self, agent_id: str, asset_id: str, query_string: str = "") -> AccessResult:
        """L0 — aggregated statistics only, data never leaves enclave."""
        return self._access(agent_id, asset_id, AccessLevel.L0_QUERY, query_string)

    def sample(self, agent_id: str, asset_id: str, sample_size: int = 10) -> AccessResult:
        """L1 — redacted + watermarked sample fragments."""
        return self._access(agent_id, asset_id, AccessLevel.L1_SAMPLE, f"sample:{sample_size}")

    def compute(
        self, agent_id: str, asset_id: str, code: str = "", params: Optional[Dict] = None
    ) -> AccessResult:
        """L2 — execute code inside TEE, only outputs leave."""
        return self._access(agent_id, asset_id, AccessLevel.L2_COMPUTE, code)

    def deliver(self, agent_id: str, asset_id: str) -> AccessResult:
        """L3 — full data delivery, maximum bond required."""
        return self._access(agent_id, asset_id, AccessLevel.L3_DELIVER, "full_delivery")

    # ─── Core logic ───────────────────────────────────────────────

    def _access(
        self,
        agent_id: str,
        asset_id: str,
        required_level: AccessLevel,
        payload: str,
    ) -> AccessResult:
        """Unified access path: check level → compute bond → record exposure."""
        with self._lock:
            if asset_id not in self._assets:
                return AccessResult(success=False, error=f"Unknown asset: {asset_id}")

            if not self._check_access_level(agent_id, asset_id, required_level):
                return AccessResult(
                    success=False,
                    access_level=required_level.value,
                    error=f"Access denied: level {required_level.value} exceeds asset max or agent is sandboxed",
                )

            bond = self._calculate_bond(agent_id, asset_id, required_level)
            asset_value = self._assets[asset_id]["value"]

            # Leakage budget check (if initialized for this pair)
            leakage_remaining = self.leakage.get_remaining(agent_id, asset_id)
            if leakage_remaining["total_size"] > 0:
                gain = self.leakage.estimate_information_gain(
                    query_result_size=0,
                    dataset_size=leakage_remaining["total_size"],
                    access_level=required_level.value,
                )
                consume_result = self.leakage.consume(agent_id, asset_id, gain)
                if not consume_result["allowed"]:
                    return AccessResult(
                        success=False,
                        access_level=required_level.value,
                        error=f"Leakage budget exceeded: {consume_result['warning']}",
                    )

            self.exposure.track_access(
                agent_id,
                asset_id,
                asset_value,
                required_level.value,
            )

            # Fragmentation detection: upgrade bond if attack pattern detected
            warning = None
            if self.exposure.check_fragmentation_attack(agent_id, asset_id):
                bond = round(bond * self.config.fragmentation_penalty, 6)
                warning = "Fragmentation attack detected: bond upgraded"

            # Append leakage warning if budget is low
            if leakage_remaining["total_size"] > 0:
                updated = self.leakage.get_remaining(agent_id, asset_id)
                if updated["remaining"] < updated["budget"] * 0.2 and updated["budget"] > 0:
                    lw = f"Leakage budget low: {updated['remaining']:.2f} remaining"
                    warning = f"{warning}; {lw}" if warning else lw

            return AccessResult(
                success=True,
                data=f"{required_level.value}:{payload}",
                bond_required=bond,
                access_level=required_level.value,
                warning=warning,
            )

    def _check_access_level(
        self, agent_id: str, asset_id: str, required_level: AccessLevel
    ) -> bool:
        """Verify agent may access at the requested level.

        Three-tier reputation gating:
        1. R < sandbox_threshold (20): sandbox — L0 only
        2. sandbox_threshold <= R < limited_threshold (50): limited — L0, L1
        3. R >= limited_threshold (50): full access — L0, L1, L2, L3

        Also checks: required_level ≤ asset's max_access_level.
        """
        asset = self._assets[asset_id]
        max_level = parse_max_access_level(asset["max_access_level"])

        if access_level_index(required_level) > access_level_index(max_level):
            return False

        rep = self.reputation.get_reputation(agent_id)

        # Tier 1: sandbox — L0 only
        if rep < self.config.sandbox_threshold:
            if required_level != AccessLevel.L0_QUERY:
                return False

        # Tier 2: limited — L0, L1 only
        elif rep < self.config.limited_threshold:
            if access_level_index(required_level) > access_level_index(AccessLevel.L1_SAMPLE):
                return False

        # Tier 3: full access — all levels allowed (no extra check)

        return True

    def _calculate_bond(self, agent_id: str, asset_id: str, access_level: AccessLevel) -> float:
        """Compute bond amount.

        Bond = TWAP(Value) × Multiplier(Level) × RiskFactor × (1 - R/100) × ExposureFactor
        """
        asset = self._assets[asset_id]
        value = asset["value"]
        multiplier = self.config.multiplier_for(access_level.value)
        risk_factor = self.config.risk_factor_for(asset["risk_level"])
        rep_discount = self.reputation.get_bond_discount(agent_id)
        exposure_factor = self.exposure.get_exposure_factor(agent_id, asset_id)

        bond = value * multiplier * risk_factor * rep_discount * exposure_factor
        return round(bond, 6)

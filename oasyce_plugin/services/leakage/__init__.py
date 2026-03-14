"""
Leakage Budget — Information Leakage Control for Tiered Data Access

Limits cumulative information an agent can extract through repeated queries,
preventing dataset reconstruction via many small requests.

Information gain per access level:
  L0 (Query)   → ~0.1% per query  (aggregated statistics only)
  L1 (Sample)  → sample_size / dataset_size  (proportional to sample)
  L2 (Compute) → ~0.5% per query  (only computed output leaves TEE)
  L3 (Deliver) → 100%             (full dataset delivery)

Budget enforcement:
  If used + gain > budget → access BLOCKED until cooldown or reset.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


# ─── Configuration ──────────────────────────────────────────────

@dataclass(frozen=True)
class LeakageBudgetConfig:
    """Leakage budget parameters."""
    default_budget_ratio: float = 0.05      # 5% of dataset information
    estimation_method: str = "token_count"  # "token_count" | "byte_ratio"
    cooldown_seconds: int = 3600            # 1 hour cooldown after budget exhausted


# ─── Information gain estimators ────────────────────────────────

# Fractional information gain per access level (fixed-rate levels)
_FIXED_GAIN_RATES: Dict[str, float] = {
    "L0": 0.001,   # 0.1% per query
    "L2": 0.005,   # 0.5% per compute
    "L3": 1.0,     # 100% (full delivery)
}


# ─── LeakageBudget ──────────────────────────────────────────────

class LeakageBudget:
    """Information leakage budget — limits agent's cumulative information gain.

    Each (agent_id, asset_id) pair has an independent budget.
    """

    def __init__(self, config: Optional[LeakageBudgetConfig] = None) -> None:
        self.config = config or LeakageBudgetConfig()
        # key: (agent_id, asset_id) → {total_size, budget, used, queries, cooldown_until}
        self._budgets: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ── Key helper ─────────────────────────────────────────────

    @staticmethod
    def _key(agent_id: str, asset_id: str) -> str:
        return f"{agent_id}:{asset_id}"

    # ── Public API ─────────────────────────────────────────────

    def initialize_budget(
        self,
        agent_id: str,
        asset_id: str,
        dataset_size: int,
        budget_ratio: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Initialize leakage budget for an (agent, asset) pair.

        Args:
            agent_id: Agent identity.
            asset_id: Asset identity.
            dataset_size: Total dataset size (bytes or token count).
            budget_ratio: Override default budget ratio (0-1).

        Returns:
            Budget state dict.

        Raises:
            ValueError: if dataset_size <= 0 or budget_ratio out of range.
        """
        if dataset_size <= 0:
            raise ValueError(f"dataset_size must be positive, got {dataset_size}")
        ratio = budget_ratio if budget_ratio is not None else self.config.default_budget_ratio
        if not (0 < ratio <= 1):
            raise ValueError(f"budget_ratio must be in (0, 1], got {ratio}")

        key = self._key(agent_id, asset_id)
        budget = dataset_size * ratio

        with self._lock:
            self._budgets[key] = {
                "total_size": dataset_size,
                "budget": budget,
                "used": 0.0,
                "queries": 0,
                "cooldown_until": 0,
            }
            return dict(self._budgets[key])

    def estimate_information_gain(
        self,
        query_result_size: int,
        dataset_size: int,
        access_level: str,
    ) -> float:
        """Estimate information gain for a single query.

        Args:
            query_result_size: Size of the query result (bytes/tokens).
            dataset_size: Total dataset size.
            access_level: Access level string (L0/L1/L2/L3).

        Returns:
            Estimated information gain as absolute value (same unit as dataset_size).
        """
        if dataset_size <= 0:
            return 0.0

        if access_level == "L1":
            # L1 (Sample): proportional to sample size vs dataset
            fraction = min(query_result_size / dataset_size, 1.0)
            return fraction * dataset_size

        # Fixed-rate levels
        rate = _FIXED_GAIN_RATES.get(access_level, 0.001)
        return rate * dataset_size

    def consume(
        self,
        agent_id: str,
        asset_id: str,
        information_gain: float,
    ) -> Dict[str, Any]:
        """Consume information budget.

        Args:
            agent_id: Agent identity.
            asset_id: Asset identity.
            information_gain: Amount of information to consume.

        Returns:
            {"allowed": bool, "remaining_budget": float, "warning": str | None}
        """
        key = self._key(agent_id, asset_id)

        with self._lock:
            if key not in self._budgets:
                return {
                    "allowed": False,
                    "remaining_budget": 0.0,
                    "warning": "Budget not initialized for this (agent, asset) pair",
                }

            entry = self._budgets[key]

            # Check cooldown
            now = time.time()
            if entry["cooldown_until"] > now:
                remaining_cd = int(entry["cooldown_until"] - now)
                return {
                    "allowed": False,
                    "remaining_budget": entry["budget"] - entry["used"],
                    "warning": f"Budget exhausted; cooldown {remaining_cd}s remaining",
                }

            remaining = entry["budget"] - entry["used"]

            # Check if gain would exceed budget
            if entry["used"] + information_gain > entry["budget"]:
                entry["cooldown_until"] = now + self.config.cooldown_seconds
                return {
                    "allowed": False,
                    "remaining_budget": remaining,
                    "warning": f"Information gain {information_gain:.2f} exceeds remaining budget {remaining:.2f}",
                }

            # Consume
            entry["used"] += information_gain
            entry["queries"] += 1
            new_remaining = entry["budget"] - entry["used"]

            # Warn if >80% consumed
            warning = None
            if new_remaining < entry["budget"] * 0.2:
                warning = f"Budget nearly exhausted: {new_remaining:.2f} remaining ({new_remaining / entry['budget'] * 100:.1f}%)"

            return {
                "allowed": True,
                "remaining_budget": new_remaining,
                "warning": warning,
            }

    def get_remaining(self, agent_id: str, asset_id: str) -> Dict[str, Any]:
        """Get remaining budget for an (agent, asset) pair.

        Returns:
            {"total_size", "budget", "used", "remaining", "queries", "exhausted"}
        """
        key = self._key(agent_id, asset_id)

        with self._lock:
            if key not in self._budgets:
                return {
                    "total_size": 0,
                    "budget": 0.0,
                    "used": 0.0,
                    "remaining": 0.0,
                    "queries": 0,
                    "exhausted": True,
                }

            entry = self._budgets[key]
            remaining = entry["budget"] - entry["used"]
            now = time.time()
            return {
                "total_size": entry["total_size"],
                "budget": entry["budget"],
                "used": entry["used"],
                "remaining": remaining,
                "queries": entry["queries"],
                "exhausted": remaining <= 0 or entry["cooldown_until"] > now,
            }

    def reset_budget(self, agent_id: str, asset_id: str) -> Dict[str, Any]:
        """Reset budget for an (agent, asset) pair.

        Returns:
            New budget state.
        """
        key = self._key(agent_id, asset_id)

        with self._lock:
            if key not in self._budgets:
                return {"error": "Budget not initialized"}

            entry = self._budgets[key]
            entry["used"] = 0.0
            entry["queries"] = 0
            entry["cooldown_until"] = 0
            return dict(entry)


__all__ = [
    "LeakageBudgetConfig",
    "LeakageBudget",
]

"""
Configurable protocol parameters — the single source of truth.

All economic constants flow from here. Supports three-layer loading:
  1. Chain query (mainnet: governance-controlled)
  2. Environment variables (OASYCE_PARAM_*)
  3. Hardcoded defaults (this file)

Every parameter has hard min/max bounds to prevent governance attacks.
Rate parameters (creator + validator + burn + treasury) must sum to 1.0.

Usage:
    from oasyce.core.protocol_params import get_protocol_params
    params = get_protocol_params()
    params.reserve_ratio   # 0.50
    params.creator_rate    # 0.93
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from typing import Any, Dict, Optional, Tuple


# ── Bounds: hard limits that governance cannot exceed ──────────────
PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "reserve_ratio": (0.10, 1.00),
    "creator_rate": (0.50, 0.95),
    "validator_rate": (0.01, 0.25),
    "burn_rate": (0.00, 0.15),
    "treasury_rate": (0.00, 0.10),
}


class ParamValidationError(ValueError):
    """Raised when protocol parameters fail validation."""


@dataclass(frozen=True)
class ProtocolParams:
    """Immutable snapshot of protocol economic parameters.

    Frozen to prevent accidental mutation — create a new instance to change.
    """

    # Bonding curve
    reserve_ratio: float = 0.50  # Bancor CW — sqrt curve

    # Fee split (must sum to 1.0)
    creator_rate: float = 0.93  # → reserve pool
    validator_rate: float = 0.03  # → block validators
    burn_rate: float = 0.02  # → burned (deflationary)
    treasury_rate: float = 0.02  # → protocol treasury

    # Price bootstrap
    initial_price: float = 1.0  # OAS per token at genesis
    min_initial_reserve: float = 100.0  # Minimum funded pool reserve

    # Solvency
    reserve_solvency_cap: float = 0.95  # Max % of reserve payable on sell

    def validate(self) -> None:
        """Check bounds and rate sum. Raises ParamValidationError."""
        # Check individual bounds
        for name, (lo, hi) in PARAM_BOUNDS.items():
            val = getattr(self, name)
            if not (lo <= val <= hi):
                raise ParamValidationError(f"{name}={val} out of bounds [{lo}, {hi}]")

        # Rate sum must be 1.0
        rate_sum = self.creator_rate + self.validator_rate + self.burn_rate + self.treasury_rate
        if abs(rate_sum - 1.0) > 1e-9:
            raise ParamValidationError(
                f"Fee rates sum to {rate_sum}, must be 1.0 "
                f"(creator={self.creator_rate} + validator={self.validator_rate} "
                f"+ burn={self.burn_rate} + treasury={self.treasury_rate})"
            )

        # Solvency cap
        if not (0.5 <= self.reserve_solvency_cap <= 1.0):
            raise ParamValidationError(
                f"reserve_solvency_cap={self.reserve_solvency_cap} " f"out of bounds [0.5, 1.0]"
            )

    def to_dict(self) -> Dict[str, float]:
        """Serialize for JSON/API/chain sync."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProtocolParams":
        """Deserialize, accepting only known fields."""
        known = {f.name for f in fields(cls)}
        filtered = {k: float(v) for k, v in d.items() if k in known}
        params = cls(**filtered)
        params.validate()
        return params


# ── Environment variable loading ──────────────────────────────────

_ENV_PREFIX = "OASYCE_PARAM_"


def _load_from_env() -> Dict[str, float]:
    """Read OASYCE_PARAM_* env vars. Returns only those that are set."""
    overrides: Dict[str, float] = {}
    mapping = {
        "RESERVE_RATIO": "reserve_ratio",
        "CREATOR_RATE": "creator_rate",
        "VALIDATOR_RATE": "validator_rate",
        "BURN_RATE": "burn_rate",
        "TREASURY_RATE": "treasury_rate",
        "INITIAL_PRICE": "initial_price",
        "MIN_INITIAL_RESERVE": "min_initial_reserve",
        "RESERVE_SOLVENCY_CAP": "reserve_solvency_cap",
    }
    for env_suffix, param_name in mapping.items():
        val = os.environ.get(f"{_ENV_PREFIX}{env_suffix}")
        if val is not None:
            try:
                overrides[param_name] = float(val)
            except ValueError:
                pass  # Ignore malformed env vars
    return overrides


# ── Chain query (stub — real implementation calls oasyced) ────────


def _load_from_chain() -> Optional[Dict[str, float]]:
    """Query chain for current governance parameters.

    Returns None if chain is unavailable or not in chain-linked mode.
    Real implementation will call:
        oasyced query settlement params --output json
    """
    # TODO Phase 5: implement chain parameter query via OasyceClient
    return None


# ── Singleton with lazy init ──────────────────────────────────────

_cached_params: Optional[ProtocolParams] = None


def get_protocol_params(force_reload: bool = False) -> ProtocolParams:
    """Load protocol parameters with priority: chain > env > defaults.

    Cached after first load. Use force_reload=True after governance update.
    """
    global _cached_params
    if _cached_params is not None and not force_reload:
        return _cached_params

    # Start with defaults
    kwargs: Dict[str, float] = {}

    # Layer 1: env vars
    env_overrides = _load_from_env()
    kwargs.update(env_overrides)

    # Layer 2: chain query (highest priority)
    chain_params = _load_from_chain()
    if chain_params is not None:
        kwargs.update(chain_params)

    params = ProtocolParams(**kwargs)
    params.validate()
    _cached_params = params
    return params


def reset_params_cache() -> None:
    """Clear cached params. Used in tests and after governance updates."""
    global _cached_params
    _cached_params = None

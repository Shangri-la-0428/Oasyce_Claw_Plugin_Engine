"""
Data Access Control — Tiered Access Levels & Bond-Based Authorization

Implements four progressive access levels for data assets:

  L0 (Query)   → Aggregated stats only, data never leaves enclave
  L1 (Sample)  → Redacted + watermarked sample fragments
  L2 (Compute) → Code executes inside TEE, only outputs leave
  L3 (Deliver) → Full data delivery, maximum bond required

Bond formula per access request:

  Bond = TWAP(Value) × Multiplier(Level) × RiskFactor × (1 - R/100) × ExposureFactor

  Multiplier:  L0=1×  L1=2×  L2=3×  L3=15×
  RiskFactor:  public=1.0  low=1.2  medium=1.5  high=2.0  critical=3.0
"""

from __future__ import annotations

from enum import Enum


class AccessLevel(str, Enum):
    """Progressive data access tiers — higher levels require larger bonds."""

    L0_QUERY = "L0"
    L1_SAMPLE = "L1"
    L2_COMPUTE = "L2"
    L3_DELIVER = "L3"


# Ordered list for comparison
ACCESS_LEVEL_ORDER = [
    AccessLevel.L0_QUERY,
    AccessLevel.L1_SAMPLE,
    AccessLevel.L2_COMPUTE,
    AccessLevel.L3_DELIVER,
]


def access_level_index(level: AccessLevel) -> int:
    """Return numeric index (0-3) for access level comparison."""
    return ACCESS_LEVEL_ORDER.index(level)


def parse_max_access_level(level_str: str) -> AccessLevel:
    """Parse a max_access_level string ('L0'/'L1'/'L2'/'L3') to AccessLevel."""
    for lvl in AccessLevel:
        if lvl.value == level_str:
            return lvl
    raise ValueError(f"Unknown access level: {level_str}")


# Re-export main provider class
from .provider import DataAccessProvider

__all__ = ["AccessLevel", "access_level_index", "parse_max_access_level", "DataAccessProvider"]

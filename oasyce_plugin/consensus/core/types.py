"""
Protocol-level types and units for Oasyce consensus.

All monetary values are stored as integer units (1 OAS = 10^8 units).
No float is ever used for monetary amounts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ── Unit system ──────────────────────────────────────────────────────

OAS_DECIMALS: int = 10 ** 8  # 1 OAS = 100,000,000 units


def to_units(oas: float) -> int:
    """Convert a human-readable OAS amount to integer units.

    >>> to_units(1.0)
    100000000
    >>> to_units(0.5)
    50000000
    """
    return int(round(oas * OAS_DECIMALS))


def from_units(units: int) -> float:
    """Convert integer units to human-readable OAS for display only.

    >>> from_units(100000000)
    1.0
    >>> from_units(50000000)
    0.5
    """
    return units / OAS_DECIMALS


# ── Operation types ──────────────────────────────────────────────────

class OperationType(str, Enum):
    REGISTER = "register"
    DELEGATE = "delegate"
    UNDELEGATE = "undelegate"
    SLASH = "slash"
    REWARD = "reward"
    EXIT = "exit"
    UNJAIL = "unjail"


# ── Operation (frozen, immutable) ────────────────────────────────────

@dataclass(frozen=True)
class Operation:
    """A single consensus operation — the atomic unit of state change.

    Once created, an Operation is immutable (frozen dataclass).
    All amounts are in integer units (1 OAS = 10^8 units).
    """
    op_type: OperationType
    validator_id: str
    amount: int = 0              # units
    asset_type: str = "OAS"      # reserved for multi-asset (phase 2)
    from_addr: str = ""
    to_addr: str = ""
    reason: str = ""
    commission_rate: int = 1000  # basis points (1000 = 10.00%)
    signature: str = ""
    chain_id: str = ""
    sender: str = ""             # public key of the operation sender
    timestamp: int = 0           # unix timestamp (anti-replay)

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Operation amount cannot be negative: {self.amount}")


# ── Slash rates in basis points ──────────────────────────────────────

OFFLINE_SLASH_BPS: int = 100       # 1% = 100 basis points
DOUBLE_SIGN_SLASH_BPS: int = 500   # 5% = 500 basis points
LOW_QUALITY_SLASH_BPS: int = 50    # 0.5% = 50 basis points

MAX_COMMISSION_BPS: int = 5000     # 50% max commission


def apply_rate_bps(amount: int, rate_bps: int) -> int:
    """Apply a basis-point rate to an amount. Returns integer units.

    >>> apply_rate_bps(10000, 100)  # 1% of 10000
    100
    >>> apply_rate_bps(10000, 500)  # 5% of 10000
    500
    """
    return (amount * rate_bps) // 10000

"""
Layer 0 — Pure functions for Oasyce protocol math.

These functions have NO side effects, NO state, NO I/O.
They are the irreducible mathematical primitives of the protocol.
Every formula is independently testable with zero mocking.
"""

from __future__ import annotations

import hashlib
import math
from typing import Optional, Tuple

# ── Protocol Constants ──────────────────────────────────────────────
RESERVE_RATIO = 0.5          # Bancor connector weight (CW)
PROTOCOL_FEE_RATE = 0.05     # 5% protocol fee
BURN_RATE = 0.02             # 2% burn
INITIAL_PRICE = 1.0          # OAS per token — fair bootstrap price
MIN_INITIAL_RESERVE = 100.0  # Minimum funded pool reserve
RESERVE_SOLVENCY_CAP = 0.95  # Max fraction of reserve payable on sell

# ── Access Constants ────────────────────────────────────────────────
EQUITY_ACCESS_THRESHOLDS = [
    (0.10, "L3"),   # >= 10% → Deliver
    (0.05, "L2"),   # >= 5%  → Compute
    (0.01, "L1"),   # >= 1%  → Sample
    (0.001, "L0"),  # >= 0.1% → Query
]

REPUTATION_SANDBOX = 20   # R < 20 → L0 only
REPUTATION_LIMITED = 50   # R 20-49 → L0+L1; R ≥ 50 → all

LEVEL_INDEX = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


# ── Bonding Curve ───────────────────────────────────────────────────

def calculate_fees(amount: float) -> Tuple[float, float, float]:
    """Return (fee, burn, net_amount) for a given gross payment."""
    fee = amount * PROTOCOL_FEE_RATE
    burn = amount * BURN_RATE
    return fee, burn, amount - fee - burn


def spot_price(supply: float, reserve: float) -> float:
    """Spot price = reserve / (supply × CW). Returns 0 if supply <= 0."""
    if supply <= 0:
        return 0.0
    return reserve / (supply * RESERVE_RATIO)


def bonding_curve_buy(supply: float, reserve: float, net_payment: float) -> float:
    """Bancor buy: tokens minted for a net payment (after fees).

    Formula: tokens = supply × ((1 + payment/reserve)^CW − 1)
    Bootstrap: tokens = payment / INITIAL_PRICE when reserve == 0.
    """
    if reserve > 0 and supply > 0:
        return supply * ((1 + net_payment / reserve) ** RESERVE_RATIO - 1)
    return net_payment / INITIAL_PRICE


def bonding_curve_sell(supply: float, reserve: float, tokens: float) -> float:
    """Inverse Bancor: gross payout for selling tokens back.

    Formula: payout = reserve × (1 − (1 − tokens/supply)^(1/CW))
    Capped at RESERVE_SOLVENCY_CAP × reserve to keep pool solvent.
    """
    ratio = 1 - tokens / supply
    gross = reserve * (1 - ratio ** (1 / RESERVE_RATIO))
    return min(gross, reserve * RESERVE_SOLVENCY_CAP)


def price_impact(price_before: float, price_after: float) -> float:
    """Price impact as percentage. Returns 0 if price_before <= 0."""
    if price_before <= 0:
        return 0.0
    return (price_after - price_before) / price_before * 100


# ── Equity → Access ─────────────────────────────────────────────────

def equity_to_access_level(equity_pct: float, reputation: float) -> Optional[str]:
    """Determine access level from equity % and reputation score.

    Returns "L0"-"L3" or None if insufficient equity.
    Reputation caps the maximum level:
      R < 20  → L0 only
      R < 50  → L0 + L1
      R >= 50 → all levels
    """
    # Find highest qualifying level from equity
    equity_level: Optional[str] = None
    for threshold, level in EQUITY_ACCESS_THRESHOLDS:
        if equity_pct >= threshold:
            equity_level = level
            break

    if equity_level is None:
        return None

    # Cap by reputation
    if reputation < REPUTATION_SANDBOX:
        max_idx = 0
    elif reputation < REPUTATION_LIMITED:
        max_idx = 1
    else:
        max_idx = 3

    equity_idx = LEVEL_INDEX[equity_level]
    return f"L{min(equity_idx, max_idx)}"


# ── Jury Selection ──────────────────────────────────────────────────

def jury_score(dispute_id: str, node_id: str, reputation: float) -> float:
    """Weighted jury selection score: random × log(1 + reputation).

    Deterministic given (dispute_id, node_id) — fair selection with
    diminishing returns on reputation advantage.
    """
    seed = hashlib.sha256((dispute_id + node_id).encode()).hexdigest()
    hash_val = int(seed[:16], 16)
    random_val = hash_val / (2**64)
    return random_val * math.log1p(reputation)

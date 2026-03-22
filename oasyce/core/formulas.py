"""
Layer 0 — Pure functions for Oasyce protocol math.

DEPRECATED: Local fallback only. The canonical bonding curve, fee split,
and access level calculations live in the Go chain (x/settlement,
x/datarights). These Python implementations are only active when
OASYCE_ALLOW_LOCAL_FALLBACK=true. Constants here should stay in sync
with Go chain constants in x/settlement/types/types.go.

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

# ── Rights Type Multipliers ────────────────────────────────────────
RIGHTS_MULTIPLIERS = {
    "original": 1.0,        # Full value
    "co_creation": 0.9,     # 90% — shared creation
    "licensed": 0.7,        # 70% — licensed content
    "collection": 0.3,      # 30% — aggregated data
}


def rights_multiplier(rights_type: str) -> float:
    """Return pricing multiplier for a rights type. Defaults to 'collection' (0.3x)."""
    return RIGHTS_MULTIPLIERS.get(rights_type, RIGHTS_MULTIPLIERS["collection"])


# ── Share Diminishing Returns ──────────────────────────────────────
DIMINISHING_RATES = [
    (0, 1.0),        # First buyer: 100% share rate
    (1, 0.8),        # Second: 80%
    (2, 0.6),        # Third: 60%
    (3, 0.4),        # Fourth+: 40%
]


def share_rate(buyer_index: int) -> float:
    """Return the share earning rate for the Nth buyer (0-indexed).

    Early buyers get more shares per OAS: 100% → 80% → 60% → 40%.
    This rewards early participation without unfairly exploiting it
    (INITIAL_PRICE prevents the first buyer from getting 10x value).
    """
    for max_idx, rate in reversed(DIMINISHING_RATES):
        if buyer_index >= max_idx:
            return rate
    return 0.4  # fallback


# ── Reputation Decay ───────────────────────────────────────────────
REPUTATION_DECAY_HALF_LIFE_DAYS = 30  # Score halves every 30 days
REPUTATION_FLOOR = 0.0
REPUTATION_CAP = 100.0


def reputation_decay(score: float, elapsed_days: float) -> float:
    """Apply exponential time decay to a reputation score.

    Formula: score × exp(-0.693 × elapsed_days / half_life)
    Half-life of 30 days: score halves every month of inactivity.
    Clamped to [REPUTATION_FLOOR, REPUTATION_CAP].
    """
    if elapsed_days <= 0 or score <= REPUTATION_FLOOR:
        return max(score, REPUTATION_FLOOR)
    decay_factor = math.exp(-0.693 * elapsed_days / REPUTATION_DECAY_HALF_LIFE_DAYS)
    result = score * decay_factor
    return max(min(result, REPUTATION_CAP), REPUTATION_FLOOR)


# ── Dispute Economics ──────────────────────────────────────────────
DISPUTE_FEE = 5.0              # OAS required to file dispute
JUROR_REWARD = 2.0             # OAS per juror for correct vote
MAJORITY_THRESHOLD = 2 / 3     # 2/3 majority required
REP_PENALTY_PROVIDER_LOSS = -10.0  # Provider loses dispute
REP_PENALTY_CONSUMER_LOSS = -5.0   # Consumer loses dispute
REP_REWARD_MAJORITY_JUROR = 1.0    # Correct jury vote
REP_PENALTY_MINORITY_JUROR = -2.0  # Incorrect jury vote

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
    if net_payment <= 0:
        return 0.0
    if reserve > 0 and supply > 0:
        return supply * ((1 + net_payment / reserve) ** RESERVE_RATIO - 1)
    return net_payment / INITIAL_PRICE


def bonding_curve_sell(supply: float, reserve: float, tokens: float) -> float:
    """Inverse Bancor: gross payout for selling tokens back.

    Formula: payout = reserve × (1 − (1 − tokens/supply)^(1/CW))
    Capped at RESERVE_SOLVENCY_CAP × reserve to keep pool solvent.
    """
    if tokens <= 0 or supply <= 0 or reserve <= 0:
        return 0.0
    if tokens >= supply:
        return reserve * RESERVE_SOLVENCY_CAP  # Can't sell entire supply; cap at max
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
    if reputation < 0:
        reputation = 0.0  # Floor at zero
    seed = hashlib.sha256((dispute_id + node_id).encode()).hexdigest()
    hash_val = int(seed[:16], 16)
    random_val = hash_val / (2**64)
    return random_val * math.log1p(reputation)

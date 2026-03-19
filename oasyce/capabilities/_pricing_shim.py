"""Lightweight local stubs for BancorCurve and FeeSplitter.

The real pricing and settlement logic now lives on the Go chain
(x/settlement, x/capability modules). These stubs provide just enough
math for the capability module to work locally — quote estimation,
share ledger bookkeeping, and fee-split breakdowns. Actual on-chain
settlement goes through chain_client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


class BancorCurve:
    """Minimal Bancor bonding-curve stub.

    Formulas (same as the original oasyce.bancor.curve):
        spot_price   = reserve / (supply * reserve_ratio)
        purchase_return = supply * ((1 + deposit/reserve)^reserve_ratio - 1)
    """

    def calculate_price(
        self,
        reserve: float,
        supply: float,
        reserve_ratio: float,
    ) -> float:
        """Return the current spot price."""
        if supply <= 0 or reserve_ratio <= 0:
            return 0.0
        return reserve / (supply * reserve_ratio)

    def calculate_purchase_return(
        self,
        reserve: float,
        supply: float,
        reserve_ratio: float,
        deposit: float,
    ) -> float:
        """Return shares minted for a given OAS deposit."""
        if reserve <= 0 or supply <= 0 or reserve_ratio <= 0 or deposit <= 0:
            return 0.0
        return supply * ((1 + deposit / reserve) ** reserve_ratio - 1)


@dataclass
class DiminishingTier:
    """Earnings tier — creator rate drops as cumulative earnings rise."""

    threshold: float
    multiplier: float


DEFAULT_TIERS = [
    DiminishingTier(threshold=0, multiplier=1.0),
    DiminishingTier(threshold=100, multiplier=0.80),
    DiminishingTier(threshold=500, multiplier=0.60),
    DiminishingTier(threshold=2000, multiplier=0.40),
]


@dataclass
class FeeSplitResult:
    """Breakdown of how the fee is split."""

    creator: float
    validator: float
    burn: float
    treasury: float
    effective_creator_rate: float
    tier_level: int


class FeeSplitter:
    """Stub fee splitter with tiered diminishing returns.

    On-chain settlement uses x/settlement.MsgReleaseEscrow which
    applies the real splits. This stub is only for local estimation.
    """

    def __init__(
        self,
        creator_pct: float = 0.60,
        validator_pct: float = 0.20,
        burn_pct: float = 0.15,
        treasury_pct: float = 0.05,
        tiers: Optional[List[DiminishingTier]] = None,
    ) -> None:
        self.creator_pct = creator_pct
        self.validator_pct = validator_pct
        self.burn_pct = burn_pct
        self.treasury_pct = treasury_pct
        self.tiers = sorted(
            tiers if tiers is not None else list(DEFAULT_TIERS),
            key=lambda t: t.threshold,
        )
        self._earnings: Dict[str, float] = {}

    def _tier_for(self, creator_id: str) -> tuple:
        cumulative = self._earnings.get(creator_id, 0.0)
        tier_level = 0
        multiplier = 1.0
        for i, tier in enumerate(self.tiers):
            if cumulative >= tier.threshold:
                tier_level = i
                multiplier = tier.multiplier
        return tier_level, multiplier

    def split(self, total_fee: float, creator_id: str) -> FeeSplitResult:
        """Compute the fee split and update cumulative earnings."""
        tier_level, multiplier = self._tier_for(creator_id)
        effective_rate = self.creator_pct * multiplier

        creator_amount = total_fee * effective_rate
        validator_amount = total_fee * self.validator_pct
        burn_amount = total_fee * self.burn_pct

        base_treasury = total_fee * self.treasury_pct
        creator_surplus = total_fee * self.creator_pct - creator_amount
        treasury_amount = base_treasury + creator_surplus

        self._earnings[creator_id] = self._earnings.get(creator_id, 0.0) + creator_amount

        return FeeSplitResult(
            creator=round(creator_amount, 10),
            validator=round(validator_amount, 10),
            burn=round(burn_amount, 10),
            treasury=round(treasury_amount, 10),
            effective_creator_rate=round(effective_rate, 10),
            tier_level=tier_level,
        )

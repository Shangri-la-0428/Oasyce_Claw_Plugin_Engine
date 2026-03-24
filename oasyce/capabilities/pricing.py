"""Capability Pricing — wraps Bonding Curve with protocol fee and diminishing returns.

Price flow:
    gross_price = curve.calculate_price(...)
    protocol_fee = gross × 3% (1.5% burn + 1.5% verifier)
    net_to_curve = gross × 97%

The quote() method returns the total price a consumer will pay, the estimated
shares they will receive (after diminishing returns), and the current tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from oasyce.capabilities._pricing_shim import BancorCurve

_PROTOCOL_FEE_PCT = 0.03  # 3% protocol fee

# Diminishing returns — same tiers as shares.py
_DIMINISHING = [1.0, 0.8, 0.6]
_DIMINISHING_FLOOR = 0.4


@dataclass
class QuoteResult:
    """Result of a capability price quote."""

    capability_id: str
    consumer_id: str
    spot_price: float  # current spot price per unit
    protocol_fee: float  # 3% protocol fee
    net_to_curve: float  # 97% entering curve pool
    shares_estimate: float  # estimated shares after diminishing returns
    diminishing_tier: int  # 0-based call index (capped at 3)
    diminishing_multiplier: float


class CapabilityPricing:
    """Pricing engine for capability invocations.

    Wraps BancorCurve with protocol fee deduction and diminishing returns
    tracking per (consumer, capability) pair.

    Parameters
    ----------
    initial_reserve : float
        OAS seeded into each new capability pool.
    initial_supply : float
        Initial share supply.
    reserve_ratio : float
        Bancor connector weight.
    protocol_fee_pct : float
        Protocol fee percentage (default 5%).
    """

    def __init__(
        self,
        initial_reserve: float = 100.0,
        initial_supply: float = 100.0,
        reserve_ratio: float = 0.35,
        protocol_fee_pct: float = _PROTOCOL_FEE_PCT,
    ) -> None:
        self._curve = BancorCurve()
        self._initial_reserve = initial_reserve
        self._initial_supply = initial_supply
        self._reserve_ratio = reserve_ratio
        self._protocol_fee_pct = protocol_fee_pct

        # Per-capability pool state: capability_id → (reserve, supply)
        self._pools: Dict[str, Tuple[float, float]] = {}
        # Call count tracking: (consumer_id, capability_id) → count
        self._call_counts: Dict[Tuple[str, str], int] = {}

    def _get_pool(self, capability_id: str) -> Tuple[float, float]:
        if capability_id not in self._pools:
            self._pools[capability_id] = (
                self._initial_reserve,
                self._initial_supply,
            )
        return self._pools[capability_id]

    def quote(self, capability_id: str, consumer_id: str) -> QuoteResult:
        """Return a price quote for invoking a capability.

        The quote includes:
        - Current spot price (from Bonding Curve)
        - Protocol fee breakdown
        - Estimated shares after diminishing returns
        """
        reserve, supply = self._get_pool(capability_id)
        spot_price = self._curve.calculate_price(
            reserve,
            supply,
            self._reserve_ratio,
        )

        protocol_fee = spot_price * self._protocol_fee_pct
        net_to_curve = spot_price - protocol_fee

        # Diminishing returns
        key = (consumer_id, capability_id)
        call_idx = self._call_counts.get(key, 0)
        if call_idx < len(_DIMINISHING):
            multiplier = _DIMINISHING[call_idx]
        else:
            multiplier = _DIMINISHING_FLOOR
        tier = min(call_idx, 3)

        # Estimate shares for net_to_curve deposit
        raw_shares = self._curve.calculate_purchase_return(
            reserve,
            supply,
            self._reserve_ratio,
            net_to_curve,
        )
        shares_estimate = raw_shares * multiplier

        return QuoteResult(
            capability_id=capability_id,
            consumer_id=consumer_id,
            spot_price=spot_price,
            protocol_fee=protocol_fee,
            net_to_curve=net_to_curve,
            shares_estimate=shares_estimate,
            diminishing_tier=tier,
            diminishing_multiplier=multiplier,
        )

    def get_call_count(self, consumer_id: str, capability_id: str) -> int:
        """Return the call count for a (consumer, capability) pair."""
        return self._call_counts.get((consumer_id, capability_id), 0)

    def increment_call_count(self, consumer_id: str, capability_id: str) -> int:
        """Increment and return the new call count."""
        key = (consumer_id, capability_id)
        count = self._call_counts.get(key, 0) + 1
        self._call_counts[key] = count
        return count

    def sync_pool(self, capability_id: str, reserve: float, supply: float) -> None:
        """Sync pool state from an external source (e.g. ShareLedger)."""
        self._pools[capability_id] = (reserve, supply)

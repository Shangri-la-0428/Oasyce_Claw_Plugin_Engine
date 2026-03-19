"""Share Ledger for capability assets.

Each capability has an independent Bonding Curve pool.  Consumers who
invoke a capability receive shares minted along the curve.  Shares can
be burned (sold back) along the same curve.

Diminishing Returns prevent monopolisation:
    1st call: 100% of shares
    2nd call:  80%
    3rd call:  60%
    4th+ call: 40%
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from oasyce.capabilities._pricing_shim import BancorCurve

# Diminishing returns multipliers indexed by call ordinal (0-based).
_DIMINISHING = [1.0, 0.8, 0.6]  # 4th+ defaults to 0.4
_DIMINISHING_FLOOR = 0.4


@dataclass
class MintResult:
    """Result of a share mint operation."""

    capability_id: str
    consumer_id: str
    shares_minted: float
    diminishing_tier: int  # 0-based call index (capped at 3)
    diminishing_multiplier: float
    pool_reserve_after: float
    pool_supply_after: float


@dataclass
class BurnResult:
    """Result of a share burn (sell) operation."""

    capability_id: str
    holder_id: str
    shares_burned: float
    oas_returned: float
    pool_reserve_after: float
    pool_supply_after: float


class ShareLedgerError(Exception):
    """Raised on invalid share operations."""


class ShareLedger:
    """In-memory share ledger backed by Bonding Curve pools.

    Parameters
    ----------
    initial_reserve : float
        OAS seeded into each new capability pool.
    initial_supply : float
        Initial share supply for each new capability pool.
    reserve_ratio : float
        Bancor connector weight (F).
    """

    def __init__(
        self,
        initial_reserve: float = 100.0,
        initial_supply: float = 100.0,
        reserve_ratio: float = 0.35,
    ) -> None:
        self._curve = BancorCurve()
        self._initial_reserve = initial_reserve
        self._initial_supply = initial_supply
        self._reserve_ratio = reserve_ratio

        # Per-capability pool state: capability_id → (reserve, supply)
        self._pools: Dict[str, Tuple[float, float]] = {}
        # Share balances: (capability_id, holder_id) → shares
        self._balances: Dict[Tuple[str, str], float] = {}
        # Call count for diminishing returns: (consumer_id, capability_id) → count
        self._call_counts: Dict[Tuple[str, str], int] = {}

    # ── Pool helpers ──────────────────────────────────────────────────

    def _get_pool(self, capability_id: str) -> Tuple[float, float]:
        """Return (reserve, supply), initialising the pool if needed."""
        if capability_id not in self._pools:
            self._pools[capability_id] = (
                self._initial_reserve,
                self._initial_supply,
            )
        return self._pools[capability_id]

    # ── Public API ────────────────────────────────────────────────────

    def mint(
        self,
        capability_id: str,
        consumer_id: str,
        amount_oas: float,
    ) -> MintResult:
        """Mint shares for a consumer by depositing OAS into the curve pool.

        Applies diminishing returns based on the consumer's call count for
        this capability.

        Returns:
            MintResult with the number of shares actually minted.
        """
        if amount_oas <= 0:
            raise ShareLedgerError("amount_oas must be positive")

        reserve, supply = self._get_pool(capability_id)

        # Calculate raw shares from curve
        raw_shares = self._curve.calculate_purchase_return(
            reserve,
            supply,
            self._reserve_ratio,
            amount_oas,
        )

        # Diminishing returns
        key = (consumer_id, capability_id)
        call_idx = self._call_counts.get(key, 0)
        if call_idx < len(_DIMINISHING):
            multiplier = _DIMINISHING[call_idx]
        else:
            multiplier = _DIMINISHING_FLOOR
        tier = min(call_idx, 3)

        shares_minted = raw_shares * multiplier
        self._call_counts[key] = call_idx + 1

        # Update pool: full OAS goes into reserve (shares are reduced, not OAS)
        new_reserve = reserve + amount_oas
        new_supply = supply + shares_minted
        self._pools[capability_id] = (new_reserve, new_supply)

        # Credit holder
        bal_key = (capability_id, consumer_id)
        self._balances[bal_key] = self._balances.get(bal_key, 0.0) + shares_minted

        return MintResult(
            capability_id=capability_id,
            consumer_id=consumer_id,
            shares_minted=shares_minted,
            diminishing_tier=tier,
            diminishing_multiplier=multiplier,
            pool_reserve_after=new_reserve,
            pool_supply_after=new_supply,
        )

    def burn(
        self,
        capability_id: str,
        holder_id: str,
        shares: float,
    ) -> BurnResult:
        """Burn (sell) shares back along the curve.

        Sell formula: ΔR = R × (1 - (1 - ΔS/S)^(1/F))

        Returns:
            BurnResult with the OAS returned.
        """
        if shares <= 0:
            raise ShareLedgerError("shares must be positive")

        bal_key = (capability_id, holder_id)
        held = self._balances.get(bal_key, 0.0)
        if held < shares:
            raise ShareLedgerError(f"insufficient shares: {held:.4f} < {shares:.4f}")

        reserve, supply = self._get_pool(capability_id)
        if shares > supply:
            raise ShareLedgerError("cannot burn more shares than total supply")

        # Sell formula: ΔR = R × (1 - (1 - ΔS/S)^(1/F))
        oas_returned = reserve * (1 - (1 - shares / supply) ** (1 / self._reserve_ratio))

        new_reserve = reserve - oas_returned
        new_supply = supply - shares
        self._pools[capability_id] = (new_reserve, new_supply)
        self._balances[bal_key] = held - shares

        return BurnResult(
            capability_id=capability_id,
            holder_id=holder_id,
            shares_burned=shares,
            oas_returned=oas_returned,
            pool_reserve_after=new_reserve,
            pool_supply_after=new_supply,
        )

    def balance(self, capability_id: str, holder_id: str) -> float:
        """Return shares held by a holder for a capability."""
        return self._balances.get((capability_id, holder_id), 0.0)

    def total_supply(self, capability_id: str) -> float:
        """Return total share supply for a capability."""
        _, supply = self._get_pool(capability_id)
        return supply

    def pool_reserve(self, capability_id: str) -> float:
        """Return OAS in the reserve pool for a capability."""
        reserve, _ = self._get_pool(capability_id)
        return reserve

    def call_count(self, consumer_id: str, capability_id: str) -> int:
        """Return the call count for diminishing returns tracking."""
        return self._call_counts.get((consumer_id, capability_id), 0)

"""Share ownership tracking for Oasyce assets.

When someone buys on the bonding curve, they receive shares proportional
to their payment.  This module tracks who owns how many shares of each asset.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShareHolding:
    """A single ownership record: one owner's position in one asset."""

    owner: str
    asset_id: str
    shares: float
    acquired_price: float  # average price per share at acquisition


class ShareRegistry:
    """Tracks share ownership across all assets.

    Thread-safety note: this is a synchronous in-memory store. Wrap with
    a lock if used from async contexts with concurrent mutations.
    """

    def __init__(self) -> None:
        # (owner, asset_id) -> ShareHolding
        self._holdings: dict[tuple[str, str], ShareHolding] = {}

    def record_purchase(
        self, owner: str, asset_id: str, shares: float, price_per_share: float
    ) -> ShareHolding:
        """Record a share purchase, averaging into any existing position.

        Args:
            owner: Buyer identifier.
            asset_id: Asset being purchased.
            shares: Number of new shares acquired.
            price_per_share: Price paid per share.

        Returns:
            Updated ShareHolding.
        """
        key = (owner, asset_id)
        existing = self._holdings.get(key)
        if existing is None:
            holding = ShareHolding(
                owner=owner,
                asset_id=asset_id,
                shares=shares,
                acquired_price=price_per_share,
            )
            self._holdings[key] = holding
            return holding

        # Weighted average price
        total_cost = existing.shares * existing.acquired_price + shares * price_per_share
        new_total = existing.shares + shares
        existing.shares = new_total
        existing.acquired_price = total_cost / new_total if new_total > 0 else 0.0
        return existing

    def get_holding(self, owner: str, asset_id: str) -> ShareHolding | None:
        """Get a specific owner's holding for an asset."""
        return self._holdings.get((owner, asset_id))

    def get_holdings_by_owner(self, owner: str) -> list[ShareHolding]:
        """Get all holdings for a given owner."""
        return [h for (o, _), h in self._holdings.items() if o == owner]

    def get_holders(self, asset_id: str) -> list[ShareHolding]:
        """Get all holders of a given asset."""
        return [h for (_, a), h in self._holdings.items() if a == asset_id]

    def total_shares(self, asset_id: str) -> float:
        """Total shares outstanding for an asset."""
        return sum(h.shares for (_, a), h in self._holdings.items() if a == asset_id)

from __future__ import annotations

from oasyce.interfaces.pricing import IPricing, QuoteResult

# Linear bonding curve: price = BASE + SLOPE * supply
_BASE_PRICE = 1.0
_SLOPE = 0.1


class MockPricing(IPricing):
    def quote(self, asset_id: str, supply: int) -> QuoteResult:
        price = _BASE_PRICE + _SLOPE * supply
        return QuoteResult(asset_id=asset_id, price_oas=price, supply=supply)

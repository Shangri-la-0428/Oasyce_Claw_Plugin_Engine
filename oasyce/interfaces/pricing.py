from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class QuoteResult:
    asset_id: str
    price_oas: float
    supply: int


class IPricing(ABC):
    @abstractmethod
    def quote(self, asset_id: str, supply: int) -> QuoteResult:
        """Return a price quote using a linear bonding curve."""
        ...

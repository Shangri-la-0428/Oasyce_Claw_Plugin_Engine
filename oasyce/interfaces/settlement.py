from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from oasyce.models.transaction import Transaction, SettleSplit


@dataclass(frozen=True)
class SettleResult:
    success: bool
    tx_id: str
    split: Optional[SettleSplit] = None
    reason: Optional[str] = None


class ISettlement(ABC):
    @abstractmethod
    def settle(self, tx: Transaction) -> SettleResult: ...

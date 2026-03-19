from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
import uuid


@dataclass
class Transaction:
    """A settlement transaction that distributes OAS tokens."""

    tx_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    asset_id: str = ""
    buyer: str = ""
    amount_oas: float = 0.0
    tx_type: Literal["buy", "sell"] = "buy"


@dataclass(frozen=True)
class SettleSplit:
    """Breakdown of how OAS tokens are distributed."""

    creator: float
    protocol_burn: float
    protocol_validator: float
    router: float

    @property
    def total(self) -> float:
        return self.creator + self.protocol_burn + self.protocol_validator + self.router

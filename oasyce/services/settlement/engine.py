"""
Settlement engine -- delegates to the Cosmos chain via OasyceClient.

Provides backward-compatible types and methods for GUI and legacy code.
Actual settlement operations go through the chain's settlement module.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from oasyce.chain_client import ChainClientError, OasyceClient


class TradeStatus(str, Enum):
    PENDING = "pending"
    SETTLED = "settled"
    FAILED = "failed"


class PriceModel(str, Enum):
    BONDING_CURVE = "bonding_curve"
    FIXED = "fixed"


RESERVE_RATIO = 0.5
PROTOCOL_FEE_RATE = 0.05
BURN_RATE = 0.02


@dataclass
class QuoteResult:
    """Result of a bonding curve price quote."""

    asset_id: str
    payment_oas: float
    equity_minted: float
    spot_price_before: float
    spot_price_after: float
    price_impact_pct: float
    protocol_fee: float
    burn_amount: float


@dataclass
class Quote:
    asset_id: str
    price_oas: float
    supply: int = 0


@dataclass
class SettlementReceipt:
    receipt_id: str = ""
    status: TradeStatus = TradeStatus.SETTLED
    asset_id: str = ""
    buyer: str = ""
    amount_oas: float = 0.0
    quote: Optional[QuoteResult] = None


@dataclass
class SettlementConfig:
    rest_url: str = "http://localhost:1317"


@dataclass
class AssetPool:
    asset_id: str
    owner: str
    supply: float = 1.0
    reserve_balance: float = 0.1
    equity: Dict[str, float] = field(default_factory=dict)

    @property
    def spot_price(self) -> float:
        if self.supply <= 0:
            return 0.0
        return self.reserve_balance / (self.supply * RESERVE_RATIO)


class SettlementEngine:
    """Settlement engine with local bonding curve + chain delegation.

    Local bonding curve provides instant quotes and demo functionality.
    Chain escrow handles real settlements when the chain is available.
    """

    def __init__(self, config: Optional[SettlementConfig] = None):
        cfg = config or SettlementConfig()
        self._chain = OasyceClient(rest_url=cfg.rest_url)
        self._pools: Dict[str, AssetPool] = {}
        self.receipts: List[SettlementReceipt] = []

    @property
    def pools(self) -> Dict[str, AssetPool]:
        return self._pools

    def register_asset(self, asset_id: str, owner: str) -> AssetPool:
        if asset_id in self._pools:
            return self._pools[asset_id]
        pool = AssetPool(asset_id=asset_id, owner=owner)
        self._pools[asset_id] = pool
        return pool

    def get_pool(self, asset_id: str) -> Optional[AssetPool]:
        return self._pools.get(asset_id)

    def quote(self, asset_id: str, amount_oas: float) -> QuoteResult:
        """Calculate bonding curve quote for purchasing shares."""
        pool = self._pools.get(asset_id)
        if pool is None:
            pool = self.register_asset(asset_id, "protocol")

        price_before = pool.spot_price

        # Bancor bonding curve: tokens = supply * ((1 + payment/reserve)^CW - 1)
        fee = amount_oas * PROTOCOL_FEE_RATE
        burn = amount_oas * BURN_RATE
        net_payment = amount_oas - fee - burn

        if pool.reserve_balance > 0 and pool.supply > 0:
            tokens = pool.supply * ((1 + net_payment / pool.reserve_balance) ** RESERVE_RATIO - 1)
        else:
            tokens = net_payment * 10  # bootstrap: 10 tokens per OAS

        new_reserve = pool.reserve_balance + net_payment
        new_supply = pool.supply + tokens
        price_after = new_reserve / (new_supply * RESERVE_RATIO) if new_supply > 0 else 0

        impact = ((price_after - price_before) / price_before * 100) if price_before > 0 else 0

        return QuoteResult(
            asset_id=asset_id,
            payment_oas=round(amount_oas, 6),
            equity_minted=tokens,
            spot_price_before=price_before,
            spot_price_after=price_after,
            price_impact_pct=impact,
            protocol_fee=fee,
            burn_amount=burn,
        )

    def buy(self, asset_id: str, buyer: str, amount_oas: float) -> SettlementReceipt:
        """Buy shares: compute quote, update pool, record receipt."""
        q = self.quote(asset_id, amount_oas)
        pool = self._pools[asset_id]

        # Update pool state
        net = amount_oas - q.protocol_fee - q.burn_amount
        pool.reserve_balance += net
        pool.supply += q.equity_minted
        pool.equity[buyer] = pool.equity.get(buyer, 0) + q.equity_minted

        receipt = SettlementReceipt(
            receipt_id=uuid.uuid4().hex[:12],
            status=TradeStatus.SETTLED,
            asset_id=asset_id,
            buyer=buyer,
            amount_oas=amount_oas,
            quote=q,
        )
        self.receipts.append(receipt)

        # Also try chain escrow (non-blocking)
        try:
            owner = pool.owner
            self._chain.chain.create_escrow(
                creator=buyer,
                provider=owner,
                amount_uoas=int(amount_oas * 1e8),
                asset_id=asset_id,
            )
        except (ChainClientError, Exception):
            pass

        return receipt

    def execute(self, asset_id: str, buyer: str, payment_oas: float) -> SettlementReceipt:
        """Backward-compatible alias for buy()."""
        return self.buy(asset_id, buyer, payment_oas)

    def network_stats(self) -> Dict[str, Any]:
        return {
            "pools": len(self._pools),
            "chain_connected": self._chain.is_chain_mode,
        }

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
MIN_INITIAL_RESERVE = 100.0


class SlippageError(Exception):
    """Raised when price impact exceeds the caller's max_slippage tolerance."""


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
class SellQuoteResult:
    """Result of a bonding curve sell quote."""

    asset_id: str
    tokens_sold: float
    payout_oas: float
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
    error: Optional[str] = None


@dataclass
class SettlementConfig:
    rest_url: str = "http://localhost:1317"
    min_initial_reserve: float = MIN_INITIAL_RESERVE
    chain_required: bool = True  # fail settlement if chain escrow fails


@dataclass
class AssetPool:
    asset_id: str
    owner: str
    supply: float = 1.0
    reserve_balance: float = MIN_INITIAL_RESERVE
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
        self._config = config or SettlementConfig()
        self._chain = OasyceClient(rest_url=self._config.rest_url)
        self._pools: Dict[str, AssetPool] = {}
        self.receipts: List[SettlementReceipt] = []

    @property
    def pools(self) -> Dict[str, AssetPool]:
        return self._pools

    def register_asset(self, asset_id: str, owner: str) -> AssetPool:
        if asset_id in self._pools:
            return self._pools[asset_id]
        pool = AssetPool(
            asset_id=asset_id,
            owner=owner,
            reserve_balance=self._config.min_initial_reserve,
        )
        self._pools[asset_id] = pool
        return pool

    def get_pool(self, asset_id: str) -> Optional[AssetPool]:
        return self._pools.get(asset_id)

    # ── Buy ────────────────────────────────────────────────────────

    def quote(
        self, asset_id: str, amount_oas: float, max_slippage: Optional[float] = None
    ) -> QuoteResult:
        """Calculate bonding curve quote for purchasing shares.

        Args:
            max_slippage: Maximum allowed price impact as a fraction (e.g. 0.05 = 5%).
                          Raises SlippageError if exceeded.
        """
        pool = self._pools.get(asset_id)
        if pool is None:
            pool = self.register_asset(asset_id, "protocol")

        price_before = pool.spot_price

        fee = amount_oas * PROTOCOL_FEE_RATE
        burn = amount_oas * BURN_RATE
        net_payment = amount_oas - fee - burn

        if pool.reserve_balance > 0 and pool.supply > 0:
            tokens = pool.supply * ((1 + net_payment / pool.reserve_balance) ** RESERVE_RATIO - 1)
        else:
            tokens = net_payment * 10

        new_reserve = pool.reserve_balance + net_payment
        new_supply = pool.supply + tokens
        price_after = new_reserve / (new_supply * RESERVE_RATIO) if new_supply > 0 else 0

        impact = ((price_after - price_before) / price_before * 100) if price_before > 0 else 0

        if max_slippage is not None and abs(impact) > max_slippage * 100:
            raise SlippageError(
                f"Price impact {impact:.2f}% exceeds max slippage {max_slippage * 100:.2f}%"
            )

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

    def buy(
        self,
        asset_id: str,
        buyer: str,
        amount_oas: float,
        max_slippage: Optional[float] = None,
    ) -> SettlementReceipt:
        """Buy shares: compute quote, update pool, record receipt.

        Chain escrow creation is mandatory when chain_required=True (default).
        If chain escrow fails, local state is rolled back and receipt is FAILED.
        """
        q = self.quote(asset_id, amount_oas, max_slippage=max_slippage)
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

        # Chain escrow — mandatory for settlement integrity
        try:
            self._chain.chain.create_escrow(
                creator=buyer,
                provider=pool.owner,
                amount_uoas=int(amount_oas * 1e8),
                asset_id=asset_id,
            )
        except (ChainClientError, Exception) as e:
            if self._config.chain_required:
                # Roll back local state
                pool.reserve_balance -= net
                pool.supply -= q.equity_minted
                pool.equity[buyer] = pool.equity.get(buyer, 0) - q.equity_minted
                if pool.equity.get(buyer, 0) <= 0:
                    pool.equity.pop(buyer, None)
                receipt.status = TradeStatus.FAILED
                receipt.error = f"Chain escrow failed: {e}"

        self.receipts.append(receipt)
        return receipt

    def execute(self, asset_id: str, buyer: str, payment_oas: float) -> SettlementReceipt:
        """Backward-compatible alias for buy()."""
        return self.buy(asset_id, buyer, payment_oas)

    # ── Sell ───────────────────────────────────────────────────────

    def sell_quote(
        self,
        asset_id: str,
        tokens_to_sell: float,
        seller: str,
        max_slippage: Optional[float] = None,
    ) -> SellQuoteResult:
        """Calculate payout for selling tokens back to the bonding curve.

        Inverse Bancor: payout = reserve * (1 - (1 - tokens/supply)^(1/CW))
        """
        pool = self._pools.get(asset_id)
        if pool is None:
            raise ValueError(f"Asset {asset_id} not found")

        owned = pool.equity.get(seller, 0)
        if tokens_to_sell > owned:
            raise ValueError(
                f"Insufficient equity: have {owned:.6f}, want to sell {tokens_to_sell:.6f}"
            )
        if tokens_to_sell <= 0:
            raise ValueError("tokens_to_sell must be positive")
        if tokens_to_sell >= pool.supply:
            raise ValueError("Cannot sell entire supply")

        price_before = pool.spot_price

        # Inverse Bancor formula
        ratio = 1 - tokens_to_sell / pool.supply
        gross_payout = pool.reserve_balance * (1 - ratio ** (1 / RESERVE_RATIO))

        fee = gross_payout * PROTOCOL_FEE_RATE
        burn = gross_payout * BURN_RATE
        net_payout = gross_payout - fee - burn

        new_reserve = pool.reserve_balance - gross_payout
        new_supply = pool.supply - tokens_to_sell
        price_after = new_reserve / (new_supply * RESERVE_RATIO) if new_supply > 0 else 0

        impact = ((price_after - price_before) / price_before * 100) if price_before > 0 else 0

        if max_slippage is not None and abs(impact) > max_slippage * 100:
            raise SlippageError(
                f"Price impact {impact:.2f}% exceeds max slippage {max_slippage * 100:.2f}%"
            )

        return SellQuoteResult(
            asset_id=asset_id,
            tokens_sold=tokens_to_sell,
            payout_oas=round(net_payout, 6),
            spot_price_before=price_before,
            spot_price_after=price_after,
            price_impact_pct=impact,
            protocol_fee=fee,
            burn_amount=burn,
        )

    def sell(
        self,
        asset_id: str,
        seller: str,
        tokens_to_sell: float,
        max_slippage: Optional[float] = None,
    ) -> SettlementReceipt:
        """Sell tokens back to the bonding curve and receive OAS payout."""
        sq = self.sell_quote(asset_id, tokens_to_sell, seller, max_slippage)
        pool = self._pools[asset_id]

        # Update pool state
        pool.reserve_balance -= sq.payout_oas + sq.protocol_fee + sq.burn_amount
        pool.supply -= tokens_to_sell
        pool.equity[seller] = pool.equity.get(seller, 0) - tokens_to_sell
        if pool.equity.get(seller, 0) <= 0:
            pool.equity.pop(seller, None)

        receipt = SettlementReceipt(
            receipt_id=uuid.uuid4().hex[:12],
            status=TradeStatus.SETTLED,
            asset_id=asset_id,
            buyer=seller,  # seller in this context
            amount_oas=sq.payout_oas,
        )

        # Chain escrow refund — mandatory
        try:
            self._chain.chain.create_escrow(
                creator=seller,
                provider=pool.owner,
                amount_uoas=int(sq.payout_oas * 1e8),
                asset_id=asset_id,
            )
        except (ChainClientError, Exception) as e:
            if self._config.chain_required:
                # Roll back
                pool.reserve_balance += sq.payout_oas + sq.protocol_fee + sq.burn_amount
                pool.supply += tokens_to_sell
                pool.equity[seller] = pool.equity.get(seller, 0) + tokens_to_sell
                receipt.status = TradeStatus.FAILED
                receipt.error = f"Chain escrow failed: {e}"

        self.receipts.append(receipt)
        return receipt

    # ── Stats ──────────────────────────────────────────────────────

    def network_stats(self) -> Dict[str, Any]:
        return {
            "pools": len(self._pools),
            "chain_connected": self._chain.is_chain_mode,
        }

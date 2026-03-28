"""
Settlement engine -- delegates to the Cosmos chain via OasyceClient.

DEPRECATED: The bonding curve implementation in this module duplicates
the Go chain (x/settlement, x/datarights). In strict chain mode
(allow_local_fallback=False, the default), the facade bypasses local
pool operations and delegates to chain RPC. This module is scheduled
for simplification to a pure chain RPC wrapper.

Provides backward-compatible types and methods for GUI and legacy code.
Actual settlement operations go through the chain's settlement module.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TradeStatus(str, Enum):
    PENDING = "pending"
    SETTLED = "settled"
    FAILED = "failed"


class AssetStatus(str, Enum):
    """Asset lifecycle states: ACTIVE → SHUTDOWN_PENDING → TERMINATED."""

    ACTIVE = "active"
    SHUTDOWN_PENDING = "shutdown_pending"
    TERMINATED = "terminated"


class PriceModel(str, Enum):
    BONDING_CURVE = "bonding_curve"
    FIXED = "fixed"


from oasyce.core.formulas import (
    RESERVE_RATIO,
    CREATOR_RATE,
    PROTOCOL_FEE_RATE,
    BURN_RATE,
    TREASURY_RATE,
    INITIAL_PRICE,
    MIN_INITIAL_RESERVE,
    RESERVE_SOLVENCY_CAP,
    bonding_curve_buy,
    bonding_curve_sell,
    calculate_fees,
    price_impact,
    spot_price as _spot_price,
)


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
    treasury_amount: float = 0.0


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
    treasury_amount: float = 0.0


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
    rpc_url: str = "http://localhost:26657"
    min_initial_reserve: float = MIN_INITIAL_RESERVE
    chain_required: bool = True  # fail settlement if chain escrow fails
    allow_local_fallback: Optional[bool] = None


@dataclass
class AssetPool:
    asset_id: str
    owner: str
    supply: float = 1.0
    reserve_balance: float = 0.0
    equity: Dict[str, float] = field(default_factory=dict)
    # Lifecycle fields
    status: AssetStatus = AssetStatus.ACTIVE
    shutdown_start_time: float = 0.0
    shutdown_end_time: float = 0.0
    # Snapshot at TERMINATED — used for pro-rata claim
    snapshot_reserve: float = 0.0
    snapshot_total_shares: float = 0.0
    claimed: Dict[str, bool] = field(default_factory=dict)

    @property
    def spot_price(self) -> float:
        return _spot_price(self.supply, self.reserve_balance)


class SettlementEngine:
    """Settlement engine with local bonding curve + chain delegation.

    Local bonding curve provides instant quotes and demo functionality.
    Chain escrow handles real settlements when the chain is available.
    """

    def __init__(self, config: Optional[SettlementConfig] = None):
        from oasyce.chain_client import ChainClientError, OasyceClient

        self._config = config or SettlementConfig()
        allow_local_fallback = self._config.allow_local_fallback
        if allow_local_fallback is None:
            allow_local_fallback = not self._config.chain_required
        self._chain_error_type = ChainClientError
        self._chain = OasyceClient(
            rest_url=self._config.rest_url,
            rpc_url=self._config.rpc_url,
            allow_local_fallback=allow_local_fallback,
        )
        self._pools: Dict[str, AssetPool] = {}
        self.receipts: List[SettlementReceipt] = []
        self._protocol_fees_collected: float = 0.0
        self._total_burned: float = 0.0
        self._treasury_collected: float = 0.0
        self._lock = threading.Lock()

    @property
    def pools(self) -> Dict[str, AssetPool]:
        return dict(self._pools)

    def register_asset(self, asset_id: str, owner: str, initial_reserve: float = 0.0) -> AssetPool:
        if asset_id in self._pools:
            return self._pools[asset_id]
        if initial_reserve > 0 and initial_reserve < MIN_INITIAL_RESERVE:
            raise ValueError(
                f"Initial reserve must be >= {MIN_INITIAL_RESERVE} OAS or 0 (unfunded)"
            )
        pool = AssetPool(
            asset_id=asset_id,
            owner=owner,
            reserve_balance=initial_reserve,
        )
        self._pools[asset_id] = pool
        return pool

    def get_pool(self, asset_id: str) -> Optional[AssetPool]:
        """Return the pool object. Internal use — prefer get_equity/get_supply for read access."""
        return self._pools.get(asset_id)

    def get_equity(self, asset_id: str, agent_id: str) -> float:
        """Return the equity held by *agent_id* in *asset_id* without exposing the pool."""
        pool = self._pools.get(asset_id)
        if pool is None:
            return 0.0
        return pool.equity.get(agent_id, 0.0)

    def get_supply(self, asset_id: str) -> float:
        """Return the current token supply for *asset_id*."""
        pool = self._pools.get(asset_id)
        if pool is None:
            return 0.0
        return pool.supply

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
            pool = AssetPool(asset_id=asset_id, owner="protocol")

        price_before = pool.spot_price
        fee, burn, treasury, net_payment = calculate_fees(amount_oas)
        tokens = bonding_curve_buy(pool.supply, pool.reserve_balance, net_payment)

        new_reserve = pool.reserve_balance + net_payment
        new_supply = pool.supply + tokens
        price_after = _spot_price(new_supply, new_reserve)
        impact = price_impact(price_before, price_after)

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
            treasury_amount=treasury,
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
        with self._lock:
            pool = self._pools.get(asset_id)
            if pool is not None and pool.status != AssetStatus.ACTIVE:
                raise ValueError(
                    f"Cannot buy: asset is {pool.status.value} "
                    f"(only ACTIVE assets accept purchases)"
                )
            if pool is None:
                pool = self.register_asset(asset_id, "protocol")
            q = self.quote(asset_id, amount_oas, max_slippage=max_slippage)
            pool = self._pools[asset_id]

            # Update pool state (atomic — roll back on any failure)
            net = amount_oas - q.protocol_fee - q.burn_amount - q.treasury_amount
            old_reserve = pool.reserve_balance
            old_supply = pool.supply
            old_equity = pool.equity.get(buyer, 0)
            try:
                pool.reserve_balance = old_reserve + net
                pool.supply = old_supply + q.equity_minted
                pool.equity[buyer] = old_equity + q.equity_minted
            except Exception:
                pool.reserve_balance = old_reserve
                pool.supply = old_supply
                pool.equity[buyer] = old_equity
                raise

            # Track fee accounting
            self._protocol_fees_collected += q.protocol_fee
            self._total_burned += q.burn_amount
            self._treasury_collected += q.treasury_amount

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
            except (self._chain_error_type, Exception) as e:
                if self._config.chain_required:
                    # Roll back to saved state
                    pool.reserve_balance = old_reserve
                    pool.supply = old_supply
                    if old_equity <= 0:
                        pool.equity.pop(buyer, None)
                    else:
                        pool.equity[buyer] = old_equity
                    # Roll back fee accounting
                    self._protocol_fees_collected -= q.protocol_fee
                    self._total_burned -= q.burn_amount
                    self._treasury_collected -= q.treasury_amount
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
        gross_payout = bonding_curve_sell(pool.supply, pool.reserve_balance, tokens_to_sell)
        fee = gross_payout * PROTOCOL_FEE_RATE
        burn_amt = gross_payout * BURN_RATE
        treasury_amt = gross_payout * TREASURY_RATE
        net_payout = gross_payout - fee - burn_amt - treasury_amt

        new_reserve = pool.reserve_balance - gross_payout
        new_supply = pool.supply - tokens_to_sell
        price_after = _spot_price(new_supply, new_reserve)
        impact = price_impact(price_before, price_after)

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
            burn_amount=burn_amt,
            treasury_amount=treasury_amt,
        )

    def sell(
        self,
        asset_id: str,
        seller: str,
        tokens_to_sell: float,
        max_slippage: Optional[float] = None,
    ) -> SettlementReceipt:
        """Sell tokens back to the bonding curve and receive OAS payout.

        Access-sell safety: equity-based access (get_equity_access_level) is
        computed live from current holdings on every request — never cached.
        Selling tokens immediately reduces equity %, so access level drops
        the moment this sell settles.  No lock-period or session tracking is
        needed because the facade re-checks equity on every access attempt.
        """
        with self._lock:
            pool = self._pools.get(asset_id)
            if pool is not None and pool.status == AssetStatus.TERMINATED:
                raise ValueError("Cannot sell: asset is terminated. Use claim to retrieve funds.")
            sq = self.sell_quote(asset_id, tokens_to_sell, seller, max_slippage)
            pool = self._pools[asset_id]

            # Validate reserve sufficiency
            total_debit = sq.payout_oas + sq.protocol_fee + sq.burn_amount + sq.treasury_amount
            if total_debit > pool.reserve_balance:
                raise ValueError("Insufficient reserve for sell operation")

            # Update pool state (atomic — roll back on any failure)
            old_reserve = pool.reserve_balance
            old_supply = pool.supply
            old_equity = pool.equity.get(seller, 0)
            try:
                pool.reserve_balance = old_reserve - total_debit
                pool.supply = old_supply - tokens_to_sell
                new_equity = old_equity - tokens_to_sell
                if new_equity <= 0:
                    pool.equity.pop(seller, None)
                else:
                    pool.equity[seller] = new_equity
            except Exception:
                pool.reserve_balance = old_reserve
                pool.supply = old_supply
                pool.equity[seller] = old_equity
                raise

            # Track fee accounting
            self._protocol_fees_collected += sq.protocol_fee
            self._total_burned += sq.burn_amount
            self._treasury_collected += sq.treasury_amount

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
            except (self._chain_error_type, Exception) as e:
                if self._config.chain_required:
                    # Roll back to saved state
                    pool.reserve_balance = old_reserve
                    pool.supply = old_supply
                    pool.equity[seller] = old_equity
                    # Roll back fee accounting
                    self._protocol_fees_collected -= sq.protocol_fee
                    self._total_burned -= sq.burn_amount
                    self._treasury_collected -= sq.treasury_amount
                    receipt.status = TradeStatus.FAILED
                    receipt.error = f"Chain escrow failed: {e}"

            self.receipts.append(receipt)
            return receipt

    # ── Lifecycle ──────────────────────────────────────────────────

    SHUTDOWN_COOLDOWN_SECONDS: float = 7 * 24 * 3600  # 7 days

    def initiate_shutdown(self, asset_id: str, owner: str) -> None:
        """Owner initiates graceful shutdown. ACTIVE → SHUTDOWN_PENDING.

        During SHUTDOWN_PENDING:
          - Buy is disabled
          - New access is disabled
          - Sell remains enabled (market exit window)
          - Disputes remain enabled
        """
        with self._lock:
            pool = self._pools.get(asset_id)
            if pool is None:
                raise ValueError(f"Asset {asset_id} not found")
            if pool.owner != owner:
                raise PermissionError("Only the asset owner can initiate shutdown")
            if pool.status != AssetStatus.ACTIVE:
                raise ValueError(f"Cannot shutdown: asset is {pool.status.value} (must be ACTIVE)")
            pool.status = AssetStatus.SHUTDOWN_PENDING
            pool.shutdown_start_time = time.time()
            pool.shutdown_end_time = pool.shutdown_start_time + self.SHUTDOWN_COOLDOWN_SECONDS

    def finalize_termination(self, asset_id: str) -> None:
        """Anyone can finalize after cooldown expires. SHUTDOWN_PENDING → TERMINATED.

        Snapshots reserve and total_shares for pro-rata claim.
        No funds move here — holders pull via claim_termination().
        """
        with self._lock:
            pool = self._pools.get(asset_id)
            if pool is None:
                raise ValueError(f"Asset {asset_id} not found")
            if pool.status != AssetStatus.SHUTDOWN_PENDING:
                raise ValueError(
                    f"Cannot finalize: asset is {pool.status.value} (must be SHUTDOWN_PENDING)"
                )
            if time.time() < pool.shutdown_end_time:
                remaining = pool.shutdown_end_time - time.time()
                raise ValueError(f"Cooldown not finished: {remaining:.0f}s remaining")
            # Snapshot for pro-rata distribution
            pool.snapshot_reserve = pool.reserve_balance
            pool.snapshot_total_shares = pool.supply
            pool.status = AssetStatus.TERMINATED

    def claim_termination(self, asset_id: str, holder: str) -> float:
        """Holder claims their pro-rata share of reserve after termination.

        payout = (holder_shares / snapshot_total_shares) * snapshot_reserve

        Returns the payout amount in OAS.
        """
        with self._lock:
            pool = self._pools.get(asset_id)
            if pool is None:
                raise ValueError(f"Asset {asset_id} not found")
            if pool.status != AssetStatus.TERMINATED:
                raise ValueError(f"Cannot claim: asset is {pool.status.value} (must be TERMINATED)")
            if pool.claimed.get(holder):
                raise ValueError(f"Already claimed: {holder}")

            shares = pool.equity.get(holder, 0.0)
            if shares <= 0:
                raise ValueError(f"No shares to claim for {holder}")

            if pool.snapshot_total_shares <= 0:
                raise ValueError("No shares existed at termination")

            payout = (shares / pool.snapshot_total_shares) * pool.snapshot_reserve

            # Mark claimed, clear equity
            pool.claimed[holder] = True
            pool.equity.pop(holder, None)
            pool.reserve_balance -= payout

            return round(payout, 6)

    def get_shutdown_info(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """Return lifecycle status info for an asset."""
        pool = self._pools.get(asset_id)
        if pool is None:
            return None
        info: Dict[str, Any] = {
            "asset_id": asset_id,
            "status": pool.status.value,
        }
        if pool.status == AssetStatus.SHUTDOWN_PENDING:
            remaining = max(0, pool.shutdown_end_time - time.time())
            info["shutdown_end_time"] = pool.shutdown_end_time
            info["remaining_seconds"] = remaining
        elif pool.status == AssetStatus.TERMINATED:
            info["snapshot_reserve"] = pool.snapshot_reserve
            info["snapshot_total_shares"] = pool.snapshot_total_shares
            unclaimed = {k: v for k, v in pool.equity.items() if v > 0 and not pool.claimed.get(k)}
            info["unclaimed_holders"] = len(unclaimed)
        return info

    # ── Stats ──────────────────────────────────────────────────────

    def protocol_stats(self) -> Dict[str, Any]:
        return {
            "protocol_fees_collected": round(self._protocol_fees_collected, 6),
            "total_burned": round(self._total_burned, 6),
            "treasury_collected": round(self._treasury_collected, 6),
            "pools": len(self._pools),
            "chain_connected": self._chain.is_chain_mode,
        }

    def network_stats(self) -> Dict[str, Any]:
        stats = self.protocol_stats()
        return stats

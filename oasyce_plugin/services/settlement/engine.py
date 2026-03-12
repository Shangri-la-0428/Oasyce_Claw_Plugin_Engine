"""
Settlement Engine — The Revenue Split & Deflationary Core

Implements the Oasyce clearinghouse logic:
  Quote  → Calculate price via Bancor curve for a data access request
  Execute → Atomic split: protocol fee → burn + verifier | net → reserve
  Settle → Record the trade, update asset state, return receipt

Economic model per trade (100 OAS example):
  ┌─ Protocol Fee 5% → 5 OAS
  │   ├─ Burn 50% → 2.5 OAS (dead address, absolute deflation)
  │   └─ Verifier Reward 50% → 2.5 OAS
  └─ Net Deposit 95% → 95 OAS → enters bonding curve, pushes price up
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ─── Configuration ────────────────────────────────────────

@dataclass(frozen=True)
class SettlementConfig:
    """Settlement engine parameters."""
    protocol_fee_rate: float = 0.05      # 5% protocol tax
    burn_rate: float = 0.50              # 50% of fee burned
    reserve_ratio: float = 0.20          # Bancor F parameter (20%)
    min_payment: float = 0.001           # Minimum payment in OAS
    max_slippage: float = 0.50           # 50% max slippage tolerance (wide for early-stage pools)
    burn_address: str = "0x000000000000000000000000000000000000dEaD"


# ─── Data Models ──────────────────────────────────────────

class TradeStatus(str, Enum):
    QUOTED = "QUOTED"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


@dataclass
class AssetPool:
    """Per-asset bonding curve state."""
    asset_id: str
    owner: str
    supply: float = 1000.0         # Initial supply tokens
    reserve_balance: float = 100.0  # Initial reserve in OAS
    total_trades: int = 0
    total_burned: float = 0.0
    total_verifier_rewards: float = 0.0
    created_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def spot_price(self) -> float:
        """P = R / (S × F) where F = reserve_ratio."""
        if self.supply <= 0 or self.reserve_balance <= 0:
            return 0.0
        return self.reserve_balance / (self.supply * 0.20)  # F=0.20


@dataclass
class Quote:
    """Price quote for a data access purchase."""
    asset_id: str
    payment_oas: float
    protocol_fee: float
    burn_amount: float
    verifier_reward: float
    net_deposit: float
    equity_minted: float
    spot_price_before: float
    spot_price_after: float
    price_impact_pct: float
    quoted_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: int = 0

    def __post_init__(self):
        if self.expires_at == 0:
            self.expires_at = self.quoted_at + 60  # 60s validity


@dataclass
class SettlementReceipt:
    """Immutable record of a completed trade."""
    receipt_id: str
    asset_id: str
    buyer: str
    status: TradeStatus
    quote: Quote
    equity_balance: float       # Buyer's total equity after trade
    settled_at: int = field(default_factory=lambda: int(time.time()))
    error: Optional[str] = None


# ─── Settlement Engine ────────────────────────────────────

class SettlementEngine:
    """Stateful settlement engine managing per-asset bonding curves."""

    def __init__(self, config: Optional[SettlementConfig] = None):
        self.config = config or SettlementConfig()
        self.pools: Dict[str, AssetPool] = {}
        self.receipts: List[SettlementReceipt] = []
        self.balances: Dict[str, Dict[str, float]] = {}  # {asset_id: {buyer: equity}}
        self.total_burned: float = 0.0
        self.total_trades: int = 0

    # ─── Pool Management ──────────────────────────────────

    def register_asset(
        self,
        asset_id: str,
        owner: str,
        initial_supply: float = 1000.0,
        initial_reserve: float = 100.0,
    ) -> AssetPool:
        """Register a newly verified asset into the settlement network."""
        if asset_id in self.pools:
            raise ValueError(f"Asset {asset_id} already registered")
        pool = AssetPool(
            asset_id=asset_id,
            owner=owner,
            supply=initial_supply,
            reserve_balance=initial_reserve,
        )
        self.pools[asset_id] = pool
        self.balances[asset_id] = {owner: initial_supply}
        return pool

    def get_pool(self, asset_id: str) -> Optional[AssetPool]:
        return self.pools.get(asset_id)

    # ─── Quote ────────────────────────────────────────────

    def quote(self, asset_id: str, payment_oas: float) -> Quote:
        """Calculate a price quote for buying data access equity.
        
        Formula: ΔTokens = S × ((1 + ΔR/R)^F − 1)
        where ΔR = payment after fee deduction
        """
        pool = self.pools.get(asset_id)
        if not pool:
            raise ValueError(f"Asset {asset_id} not found")
        if payment_oas < self.config.min_payment:
            raise ValueError(f"Payment below minimum ({self.config.min_payment} OAS)")

        # Fee calculation
        fee = payment_oas * self.config.protocol_fee_rate
        burn = fee * self.config.burn_rate
        verifier = fee - burn
        net = payment_oas - fee

        # Bancor purchase return: ΔTokens = S × ((1 + net/R)^F − 1)
        F = self.config.reserve_ratio
        ratio = 1 + net / pool.reserve_balance
        equity_minted = pool.supply * (math.pow(ratio, F) - 1)

        # Price impact
        spot_before = pool.spot_price
        new_supply = pool.supply + equity_minted
        new_reserve = pool.reserve_balance + net
        spot_after = new_reserve / (new_supply * F) if new_supply > 0 else 0
        impact = ((spot_after - spot_before) / spot_before * 100) if spot_before > 0 else 0

        return Quote(
            asset_id=asset_id,
            payment_oas=payment_oas,
            protocol_fee=round(fee, 6),
            burn_amount=round(burn, 6),
            verifier_reward=round(verifier, 6),
            net_deposit=round(net, 6),
            equity_minted=round(equity_minted, 6),
            spot_price_before=round(spot_before, 6),
            spot_price_after=round(spot_after, 6),
            price_impact_pct=round(impact, 4),
        )

    # ─── Execute & Settle ─────────────────────────────────

    def execute(
        self,
        asset_id: str,
        buyer: str,
        payment_oas: float,
        max_slippage_pct: Optional[float] = None,
    ) -> SettlementReceipt:
        """Execute a full trade: quote → validate → update state → receipt.
        
        This is the atomic settlement — all state changes happen together
        or not at all (simulating an on-chain atomic transaction).
        
        Args:
            max_slippage_pct: Optional caller-specified slippage limit (percentage).
                              If None, no slippage check is performed.
        """
        try:
            # 1. Generate fresh quote
            q = self.quote(asset_id, payment_oas)

            # 2. Validate slippage (only if caller specifies a limit)
            if max_slippage_pct is not None and q.price_impact_pct > max_slippage_pct:
                return self._fail_receipt(asset_id, buyer, q, "Slippage exceeds tolerance")

            # 3. Validate quote freshness
            if int(time.time()) > q.expires_at:
                return self._fail_receipt(asset_id, buyer, q, "Quote expired")

            pool = self.pools[asset_id]

            # 4. Atomic state update
            pool.supply += q.equity_minted
            pool.reserve_balance += q.net_deposit
            pool.total_trades += 1
            pool.total_burned += q.burn_amount
            pool.total_verifier_rewards += q.verifier_reward

            # 5. Update buyer balance
            if asset_id not in self.balances:
                self.balances[asset_id] = {}
            self.balances[asset_id][buyer] = self.balances[asset_id].get(buyer, 0) + q.equity_minted

            # 6. Global stats
            self.total_burned += q.burn_amount
            self.total_trades += 1

            # 7. Generate receipt
            receipt_id = self._generate_receipt_id(asset_id, buyer, q)
            receipt = SettlementReceipt(
                receipt_id=receipt_id,
                asset_id=asset_id,
                buyer=buyer,
                status=TradeStatus.SETTLED,
                quote=q,
                equity_balance=self.balances[asset_id][buyer],
            )
            self.receipts.append(receipt)
            return receipt

        except Exception as e:
            return SettlementReceipt(
                receipt_id="FAILED",
                asset_id=asset_id,
                buyer=buyer,
                status=TradeStatus.FAILED,
                quote=Quote(
                    asset_id=asset_id, payment_oas=payment_oas,
                    protocol_fee=0, burn_amount=0, verifier_reward=0,
                    net_deposit=0, equity_minted=0, spot_price_before=0,
                    spot_price_after=0, price_impact_pct=0,
                ),
                equity_balance=0,
                error=str(e),
            )

    # ─── Analytics ────────────────────────────────────────

    def network_stats(self) -> Dict[str, Any]:
        """Global settlement network statistics."""
        return {
            "total_assets": len(self.pools),
            "total_trades": self.total_trades,
            "total_burned_oas": round(self.total_burned, 6),
            "total_reserve_oas": round(sum(p.reserve_balance for p in self.pools.values()), 6),
            "total_supply_tokens": round(sum(p.supply for p in self.pools.values()), 6),
            "avg_spot_price": round(
                sum(p.spot_price for p in self.pools.values()) / len(self.pools), 6
            ) if self.pools else 0,
        }

    def asset_stats(self, asset_id: str) -> Dict[str, Any]:
        """Per-asset statistics."""
        pool = self.pools.get(asset_id)
        if not pool:
            raise ValueError(f"Asset {asset_id} not found")
        holders = self.balances.get(asset_id, {})
        return {
            "asset_id": asset_id,
            "owner": pool.owner,
            "spot_price_oas": round(pool.spot_price, 6),
            "supply": round(pool.supply, 6),
            "reserve_oas": round(pool.reserve_balance, 6),
            "total_trades": pool.total_trades,
            "total_burned": round(pool.total_burned, 6),
            "total_verifier_rewards": round(pool.total_verifier_rewards, 6),
            "holder_count": len(holders),
            "top_holders": sorted(holders.items(), key=lambda x: x[1], reverse=True)[:5],
        }

    # ─── Helpers ──────────────────────────────────────────

    def _generate_receipt_id(self, asset_id: str, buyer: str, quote: Quote) -> str:
        raw = f"{asset_id}:{buyer}:{quote.quoted_at}:{quote.payment_oas}".encode()
        return f"RCP_{hashlib.sha256(raw).hexdigest()[:12].upper()}"

    def _fail_receipt(
        self, asset_id: str, buyer: str, quote: Quote, error: str
    ) -> SettlementReceipt:
        return SettlementReceipt(
            receipt_id="FAILED",
            asset_id=asset_id,
            buyer=buyer,
            status=TradeStatus.FAILED,
            quote=quote,
            equity_balance=self.balances.get(asset_id, {}).get(buyer, 0),
            error=error,
        )

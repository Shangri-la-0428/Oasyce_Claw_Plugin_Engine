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
    reserve_ratio: float = 0.35          # Bancor F parameter (35%)
    min_payment: float = 0.001           # Minimum payment in OAS
    max_slippage: float = 0.50           # 50% max slippage tolerance (wide for early-stage pools)
    burn_address: str = "0x000000000000000000000000000000000000dEaD"
    buyer_collateral_ratio: float = 0.10 # 10% collateral on share purchase
    dispute_stake: float = 1000.0        # OAS required to file a dispute


# ─── Data Models ──────────────────────────────────────────

class TradeStatus(str, Enum):
    QUOTED = "QUOTED"
    EXECUTED = "EXECUTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    SLASHED = "SLASHED"
    DISPUTED = "DISPUTED"


class PriceModel(str, Enum):
    BONDING_CURVE = "bonding_curve"
    FREE = "free"


@dataclass
class AssetPool:
    """Per-asset bonding curve state."""
    asset_id: str
    owner: str
    supply: float = 10000.0        # Initial supply tokens
    reserve_balance: float = 1000.0 # Initial reserve in OAS
    reserve_ratio: float = 0.35    # Bancor F parameter (connector weight)
    total_trades: int = 0
    total_burned: float = 0.0
    total_verifier_rewards: float = 0.0
    price_model: str = "bonding_curve"  # "bonding_curve" or "free"
    created_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def spot_price(self) -> float:
        """P = R / (S × F) where F = reserve_ratio."""
        if self.supply <= 0 or self.reserve_balance <= 0:
            return 0.0
        return self.reserve_balance / (self.supply * self.reserve_ratio)


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
        self.collaterals: Dict[str, Dict[str, float]] = {}  # {asset_id: {buyer: collateral_oas}}
        self.frozen: Dict[str, set] = {}  # {asset_id: {frozen_buyers}}
        self.disputes: List[Dict[str, Any]] = []
        self.banned: set = set()  # banned buyer/owner IDs
        self.total_burned: float = 0.0
        self.total_trades: int = 0

    # ─── Pool Management ──────────────────────────────────

    def register_asset(
        self,
        asset_id: str,
        owner: str,
        initial_supply: float = 10000.0,
        initial_reserve: float = 1000.0,
        price_model: str = "bonding_curve",
    ) -> AssetPool:
        """Register a newly verified asset into the settlement network.
        
        Args:
            price_model: "bonding_curve" (default) or "free".
                         Free assets record attribution only — no curve, no shares.
        """
        if asset_id in self.pools:
            raise ValueError(f"Asset {asset_id} already registered")
        if owner in self.banned:
            raise ValueError(f"Owner {owner} is banned from the network")

        if price_model == "free":
            pool = AssetPool(
                asset_id=asset_id,
                owner=owner,
                supply=0,
                reserve_balance=0,
                reserve_ratio=0,
                price_model="free",
            )
        else:
            pool = AssetPool(
                asset_id=asset_id,
                owner=owner,
                supply=initial_supply,
                reserve_balance=initial_reserve,
                reserve_ratio=self.config.reserve_ratio,
                price_model="bonding_curve",
            )
            self.balances[asset_id] = {owner: initial_supply}

        self.pools[asset_id] = pool
        return pool

    def get_pool(self, asset_id: str) -> Optional[AssetPool]:
        return self.pools.get(asset_id)

    # ─── Quote ────────────────────────────────────────────

    def quote(self, asset_id: str, payment_oas: float) -> Quote:
        """Calculate a price quote for buying data access equity.
        
        Formula: ΔTokens = S × ((1 + ΔR/R)^F − 1)
        where ΔR = payment after fee deduction, F = 0.35
        """
        pool = self.pools.get(asset_id)
        if not pool:
            raise ValueError(f"Asset {asset_id} not found")
        if pool.price_model == "free":
            raise ValueError(f"Asset {asset_id} is free — no purchase required")
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
            # 0. Check if buyer is banned
            if buyer in self.banned:
                return self._fail_receipt(
                    asset_id, buyer,
                    Quote(asset_id=asset_id, payment_oas=payment_oas,
                          protocol_fee=0, burn_amount=0, verifier_reward=0,
                          net_deposit=0, equity_minted=0, spot_price_before=0,
                          spot_price_after=0, price_impact_pct=0),
                    "Buyer is banned from the network")

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

            # 5b. Lock buyer collateral
            collateral = payment_oas * self.config.buyer_collateral_ratio
            if asset_id not in self.collaterals:
                self.collaterals[asset_id] = {}
            self.collaterals[asset_id][buyer] = self.collaterals[asset_id].get(buyer, 0) + collateral

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

    # ─── Buyer Slashing ────────────────────────────────────

    def slash_buyer(
        self,
        asset_id: str,
        buyer: str,
        reason: str = "data_leak",
        slash_pct: float = 1.0,
    ) -> Dict[str, Any]:
        """Slash a buyer's collateral and freeze their shares.
        
        Args:
            slash_pct: Fraction of collateral to burn (1.0 = 100%, 0.5 = 50%).
            reason: "data_leak" (100% slash + freeze) or "license_violation" (50% slash).
        """
        collateral = self.collaterals.get(asset_id, {}).get(buyer, 0)
        if collateral <= 0:
            raise ValueError(f"Buyer {buyer} has no collateral for asset {asset_id}")

        burn_amount = collateral * slash_pct
        remaining = collateral - burn_amount

        # Burn collateral
        self.collaterals[asset_id][buyer] = remaining
        self.total_burned += burn_amount

        # Freeze shares
        if asset_id not in self.frozen:
            self.frozen[asset_id] = set()
        self.frozen[asset_id].add(buyer)

        # Ban on full slash
        if slash_pct >= 1.0:
            self.banned.add(buyer)

        return {
            "asset_id": asset_id,
            "buyer": buyer,
            "reason": reason,
            "collateral_burned": round(burn_amount, 6),
            "collateral_remaining": round(remaining, 6),
            "shares_frozen": True,
            "banned": buyer in self.banned,
        }

    # ─── Dispute Resolution ───────────────────────────────

    def file_dispute(
        self,
        asset_id: str,
        challenger: str,
        evidence_type: str,
        evidence_hash: str,
    ) -> Dict[str, Any]:
        """File a dispute against an asset registration.
        
        Args:
            evidence_type: "git_commit", "popc_certificate", "prior_registration", "publication"
            evidence_hash: SHA-256 hash of the evidence document
        """
        pool = self.pools.get(asset_id)
        if not pool:
            raise ValueError(f"Asset {asset_id} not found")
        if challenger in self.banned:
            raise ValueError(f"Challenger {challenger} is banned")

        dispute = {
            "dispute_id": self._generate_receipt_id(asset_id, challenger,
                Quote(asset_id=asset_id, payment_oas=0, protocol_fee=0,
                      burn_amount=0, verifier_reward=0, net_deposit=0,
                      equity_minted=0, spot_price_before=0,
                      spot_price_after=0, price_impact_pct=0)),
            "asset_id": asset_id,
            "challenger": challenger,
            "current_owner": pool.owner,
            "evidence_type": evidence_type,
            "evidence_hash": evidence_hash,
            "stake_oas": self.config.dispute_stake,
            "status": "pending",
            "filed_at": int(time.time()),
        }
        self.disputes.append(dispute)
        return dispute

    def resolve_dispute(
        self,
        dispute_id: str,
        upheld: bool,
    ) -> Dict[str, Any]:
        """Resolve a dispute. Called after validator committee vote.
        
        Args:
            upheld: True = challenger wins, False = original owner wins.
        """
        dispute = None
        for d in self.disputes:
            if d["dispute_id"] == dispute_id:
                dispute = d
                break
        if not dispute:
            raise ValueError(f"Dispute {dispute_id} not found")
        if dispute["status"] != "pending":
            raise ValueError(f"Dispute {dispute_id} already resolved")

        if upheld:
            # Challenger wins: transfer registration, slash original owner
            asset_id = dispute["asset_id"]
            pool = self.pools[asset_id]
            old_owner = pool.owner
            pool.owner = dispute["challenger"]

            # Burn original owner's collateral if any
            old_collateral = self.collaterals.get(asset_id, {}).get(old_owner, 0)
            if old_collateral > 0:
                self.total_burned += old_collateral
                self.collaterals[asset_id][old_owner] = 0

            # Ban malicious registrant
            self.banned.add(old_owner)

            # Transfer initial shares to challenger
            if asset_id in self.balances:
                old_shares = self.balances[asset_id].pop(old_owner, 0)
                self.balances[asset_id][dispute["challenger"]] = \
                    self.balances[asset_id].get(dispute["challenger"], 0) + old_shares

            dispute["status"] = "upheld"
            dispute["resolved_at"] = int(time.time())
            return {
                "dispute_id": dispute_id,
                "result": "upheld",
                "new_owner": dispute["challenger"],
                "old_owner_banned": True,
                "collateral_burned": round(old_collateral, 6),
            }
        else:
            # Original owner wins: burn challenger's stake
            self.total_burned += dispute["stake_oas"]
            dispute["status"] = "rejected"
            dispute["resolved_at"] = int(time.time())
            return {
                "dispute_id": dispute_id,
                "result": "rejected",
                "challenger_stake_burned": dispute["stake_oas"],
            }

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

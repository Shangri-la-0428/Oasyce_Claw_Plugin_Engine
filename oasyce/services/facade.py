"""
Oasyce Service Facade — unified entry point for all business operations.

Both CLI and GUI MUST route through this facade to ensure consistent
pricing, access control, settlement, and notifications.

Architecture:
    CLI (cli.py)  ──┐
                    ├──▶ OasyceServiceFacade ──▶ Services (settlement, access, reputation, ...)
    GUI (app.py)  ──┘

This eliminates the prior divergence where CLI used bridge_buy() while GUI
used SettlementEngine directly, producing different prices for the same asset.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result envelope — every facade method returns this.
# ---------------------------------------------------------------------------
@dataclass
class ServiceResult:
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Access level constants
# ---------------------------------------------------------------------------
from oasyce.core.formulas import (
    EQUITY_ACCESS_THRESHOLDS,
    LEVEL_INDEX as _LEVEL_INDEX,
    REPUTATION_SANDBOX,
    REPUTATION_LIMITED,
    equity_to_access_level,
)

ACCESS_LEVELS = {
    "L0": {"name": "Query", "multiplier": 1.0, "lock_days": 1},
    "L1": {"name": "Sample", "multiplier": 2.0, "lock_days": 3},
    "L2": {"name": "Compute", "multiplier": 3.0, "lock_days": 7},
    "L3": {"name": "Deliver", "multiplier": 15.0, "lock_days": 30},
}

REPUTATION_THRESHOLDS = {
    "sandbox": REPUTATION_SANDBOX,
    "limited": REPUTATION_LIMITED,
}


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------
class OasyceServiceFacade:
    """Single entry point for quote, buy, access-control, and registration."""

    def __init__(self, config=None, ledger=None, verify_identity: bool = False):
        self._config = config
        self._ledger = ledger
        self._verify_identity = verify_identity
        self._init_lock = threading.Lock()

        # Lazy-initialised service instances
        self._settlement = None
        self._access_provider = None
        self._reputation = None
        self._skills = None
        self._dispute_manager = None

    # -- lazy accessors -----------------------------------------------------

    def _get_settlement(self):
        if self._settlement is None:
            with self._init_lock:
                if self._settlement is None:  # double-check
                    from oasyce.services.settlement.engine import SettlementEngine

                    self._settlement = SettlementEngine()
        return self._settlement

    def _get_reputation(self):
        if self._reputation is None:
            with self._init_lock:
                if self._reputation is None:  # double-check
                    from oasyce.services.reputation import ReputationEngine

                    self._reputation = ReputationEngine()
        return self._reputation

    def _get_access_provider(self):
        if self._access_provider is None:
            with self._init_lock:
                if self._access_provider is None:  # double-check
                    from oasyce.services.access.provider import DataAccessProvider

                    self._access_provider = DataAccessProvider(
                        reputation=self._get_reputation(),
                    )
        return self._access_provider

    def _get_dispute_manager(self):
        if self._dispute_manager is None:
            with self._init_lock:
                if self._dispute_manager is None:  # double-check
                    from oasyce.capabilities.dispute import DisputeManager

                    # Wire callbacks using other facade services
                    def _get_invocation(invocation_id: str):
                        """Look up an invocation record from the ledger."""
                        if self._ledger is None:
                            return None
                        try:
                            asset = self._ledger.get_asset(invocation_id)
                            if asset is None:
                                return None
                            # get_asset() merges parsed metadata into the dict,
                            # so top-level keys include both columns and metadata fields.
                            import types

                            inv = types.SimpleNamespace(
                                consumer_id=asset.get("consumer_id", ""),
                                provider_id=asset.get("provider_id", asset.get("owner", "")),
                                capability_id=asset.get("capability_id", ""),
                                state=types.SimpleNamespace(value=asset.get("state", "completed")),
                                settled_at=asset.get("settled_at", 0),
                                escrow_id=asset.get("escrow_id", ""),
                                price=asset.get("price", 0.0),
                            )
                            return inv
                        except Exception as e:
                            logger.warning("Failed to lookup invocation %s: %s", invocation_id, e)
                            return None

                    def _get_reputation(agent_id: str) -> float:
                        try:
                            rep_engine = self._get_reputation()
                            return rep_engine.get_reputation(agent_id)
                        except Exception as e:
                            logger.warning("Failed to get reputation for %s: %s", agent_id, e)
                            return 0.0

                    def _get_stake(agent_id: str) -> float:
                        # Default stub — returns enough to qualify as juror
                        return 100.0

                    def _escrow_refund(escrow_id: str):
                        pass  # No-op stub for local mode

                    def _escrow_release(escrow_id: str):
                        pass  # No-op stub for local mode

                    def _reputation_update(agent_id: str, delta: float, reason: str) -> None:
                        """Apply a reputation delta via the ReputationEngine."""
                        try:
                            rep_engine = self._get_reputation()
                            if delta > 0:
                                rep_engine.update(agent_id, success=True)
                            else:
                                rep_engine.update(agent_id, success=False)
                        except Exception as e:
                            logger.warning("Failed to update reputation for %s: %s", agent_id, e)

                    self._dispute_manager = DisputeManager(
                        get_invocation=_get_invocation,
                        get_reputation=_get_reputation,
                        get_stake=_get_stake,
                        escrow_refund=_escrow_refund,
                        escrow_release=_escrow_release,
                        reputation_update_fn=_reputation_update,
                    )
        return self._dispute_manager

    def _get_skills(self):
        if self._skills is None:
            with self._init_lock:
                if self._skills is None:  # double-check
                    from oasyce.skills.agent_skills import OasyceSkills

                    self._skills = OasyceSkills(config=self._config, ledger=self._ledger)
        return self._skills

    # -----------------------------------------------------------------------
    # Identity verification
    # -----------------------------------------------------------------------
    def _verify_agent(self, agent_id: str, signature: Optional[str] = None) -> bool:
        """Verify agent identity via Ed25519 signature.

        When verify_identity is False (default, local mode), all agents are trusted.
        When True (network mode), signature must be valid for agent_id.
        """
        if not self._verify_identity:
            return True
        if signature is None:
            return False
        # Verify Ed25519 signature
        try:
            from oasyce.crypto.keys import verify_signature

            return verify_signature(agent_id, signature)
        except ImportError:
            # Crypto module not available — fall back to trust
            return True
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # Equity → Access mapping
    # -----------------------------------------------------------------------
    def get_equity_access_level(self, asset_id: str, agent_id: str) -> Optional[str]:
        """Determine access level granted by equity holdings.

        Equity % of pool → access level:
          >= 0.1% → L0 (Query)
          >= 1%   → L1 (Sample)
          >= 5%   → L2 (Compute)
          >= 10%  → L3 (Deliver)

        Reputation constraints still apply: the granted level is capped
        by the agent's reputation tier.

        **DESIGN NOTE -- live check, no caching.**  This method reads
        equity and supply directly from the settlement engine on every
        call.  If a user sells tokens, their equity % drops immediately
        and subsequent access checks reflect the reduced level.  This
        prevents the "buy access, sell tokens, keep access" race
        condition without requiring session tracking or lock periods.

        Returns the level string ("L0"-"L3") or None if no equity or
        insufficient holdings.
        """
        se = self._get_settlement()
        supply = se.get_supply(asset_id)
        if supply <= 0:
            return None
        holdings = se.get_equity(asset_id, agent_id)
        if holdings <= 0:
            return None
        pct = holdings / supply
        rep = self._get_reputation()
        score = rep.get_reputation(agent_id)
        return equity_to_access_level(pct, score)

    # -----------------------------------------------------------------------
    # Quote
    # -----------------------------------------------------------------------
    def quote(self, asset_id: str, amount_oas: float = 10.0) -> ServiceResult:
        """Get bonding-curve price quote for an asset."""
        try:
            se = self._get_settlement()
            pool = se.get_pool(asset_id)
            if pool is None:
                # Try chain bridge as fallback
                try:
                    from oasyce.bridge.core_bridge import bridge_quote

                    chain_quote = bridge_quote(asset_id)
                    if "error" not in chain_quote:
                        return ServiceResult(success=True, data=chain_quote)
                except Exception:
                    pass
                return ServiceResult(
                    success=False,
                    error=f"Asset {asset_id} not found in any pool",
                )

            qr = se.quote(asset_id, amount_oas)
            return ServiceResult(
                success=True,
                data={
                    "asset_id": qr.asset_id,
                    "payment_oas": qr.payment_oas,
                    "equity_minted": qr.equity_minted,
                    "spot_price_before": qr.spot_price_before,
                    "spot_price_after": qr.spot_price_after,
                    "price_impact_pct": qr.price_impact_pct,
                    "protocol_fee": qr.protocol_fee,
                    "burn_amount": qr.burn_amount,
                },
            )
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Buy
    # -----------------------------------------------------------------------
    def buy(self, asset_id: str, buyer: str, amount_oas: float = 10.0,
            signature: Optional[str] = None) -> ServiceResult:
        """Execute a share purchase through the settlement engine."""
        if not self._verify_agent(buyer, signature):
            return ServiceResult(success=False, error="Identity verification failed: invalid or missing signature")
        try:
            se = self._get_settlement()
            pool = se.get_pool(asset_id)

            if pool is None:
                # Fallback to chain bridge
                try:
                    from oasyce.bridge.core_bridge import bridge_buy

                    result = bridge_buy(asset_id, buyer, amount_oas, ledger=self._ledger)
                    if "error" not in result:
                        return ServiceResult(success=True, data=result)
                    return ServiceResult(success=False, error=result["error"])
                except Exception as e:
                    return ServiceResult(success=False, error=str(e))

            receipt = se.execute(asset_id, buyer, amount_oas)
            if receipt.status.value == "failed":
                return ServiceResult(success=False, error=receipt.error or "Settlement failed")
            data = {
                "receipt_id": receipt.receipt_id,
                "asset_id": receipt.asset_id,
                "buyer": receipt.buyer,
                "amount_oas": receipt.amount_oas,
                "settled": True,
                "quote": (
                    {
                        "equity_minted": receipt.quote.equity_minted,
                        "spot_price_after": receipt.quote.spot_price_after,
                        "protocol_fee": receipt.quote.protocol_fee,
                    }
                    if receipt.quote
                    else None
                ),
            }
            # Equity → access: show what level the buyer now has
            data["access_granted"] = self.get_equity_access_level(asset_id, buyer)
            return ServiceResult(success=True, data=data)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Sell
    # -----------------------------------------------------------------------
    def sell(
        self,
        asset_id: str,
        seller: str,
        tokens_to_sell: float,
        max_slippage: Optional[float] = None,
        signature: Optional[str] = None,
    ) -> ServiceResult:
        """Sell tokens back to the bonding curve for OAS payout."""
        if not self._verify_agent(seller, signature):
            return ServiceResult(success=False, error="Identity verification failed: invalid or missing signature")
        # Default slippage protection: 10% max
        if max_slippage is None:
            max_slippage = 0.10
        try:
            se = self._get_settlement()
            receipt = se.sell(asset_id, seller, tokens_to_sell, max_slippage)
            if receipt.status.value == "failed":
                return ServiceResult(success=False, error=receipt.error or "Sell failed")
            return ServiceResult(
                success=True,
                data={
                    "receipt_id": receipt.receipt_id,
                    "asset_id": receipt.asset_id,
                    "seller": seller,
                    "payout_oas": receipt.amount_oas,
                    "settled": True,
                },
            )
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Access Control — L0-L3 tiered access
    # -----------------------------------------------------------------------
    def access_quote(self, asset_id: str, buyer: str) -> ServiceResult:
        """Return bond quotes for all accessible levels (L0-L3)."""
        try:
            rep = self._get_reputation()
            score = rep.get_reputation(buyer)
            discount = rep.get_bond_discount(buyer)

            # Determine max allowed level based on reputation
            if score < REPUTATION_THRESHOLDS["sandbox"]:
                max_level = 0  # L0 only
            elif score < REPUTATION_THRESHOLDS["limited"]:
                max_level = 1  # L0 + L1
            else:
                max_level = 3  # all levels

            # Get base price (TWAP proxy: use spot price from settlement)
            se = self._get_settlement()
            pool = se.get_pool(asset_id)
            base_price = pool.spot_price if pool else 1.0

            levels = []
            for i, (level_key, info) in enumerate(ACCESS_LEVELS.items()):
                bond = base_price * info["multiplier"] * discount
                levels.append(
                    {
                        "level": level_key,
                        "name": info["name"],
                        "bond_oas": round(bond, 6),
                        "lock_days": info["lock_days"],
                        "available": i <= max_level,
                        "reason": (
                            None
                            if i <= max_level
                            else f"Reputation {score:.0f} < {REPUTATION_THRESHOLDS['limited'] if i <= 1 else 50}"
                        ),
                    }
                )

            # Check what equity already grants
            equity_level = self.get_equity_access_level(asset_id, buyer)
            equity_idx = _LEVEL_INDEX.get(equity_level, -1) if equity_level else -1

            # Mark levels covered by equity
            for lv in levels:
                lv_idx = _LEVEL_INDEX[lv["level"]]
                if lv_idx <= equity_idx:
                    lv["covered_by_equity"] = True
                    lv["bond_oas"] = 0
                else:
                    lv["covered_by_equity"] = False

            return ServiceResult(
                success=True,
                data={
                    "asset_id": asset_id,
                    "buyer": buyer,
                    "reputation": round(score, 2),
                    "equity_level": equity_level,
                    "levels": levels,
                },
            )
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def access_buy(self, asset_id: str, buyer: str, level: str) -> ServiceResult:
        """Execute a tiered access purchase."""
        if level not in ACCESS_LEVELS:
            return ServiceResult(
                success=False,
                error=f"Invalid level: {level}. Must be one of {list(ACCESS_LEVELS.keys())}",
            )

        # First check if buyer can access this level
        quote_result = self.access_quote(asset_id, buyer)
        if not quote_result.success:
            return quote_result

        level_data = None
        for lv in quote_result.data["levels"]:
            if lv["level"] == level:
                level_data = lv
                break

        if level_data is None:
            return ServiceResult(success=False, error=f"Level {level} not found")

        if not level_data["available"]:
            return ServiceResult(
                success=False,
                error=f"Access denied: {level_data['reason']}",
            )

        # If equity already covers this level, skip bond purchase
        if level_data.get("covered_by_equity"):
            return ServiceResult(
                success=True,
                data={
                    "asset_id": asset_id,
                    "buyer": buyer,
                    "level": level,
                    "bond_oas": 0,
                    "lock_days": 0,
                    "via_equity": True,
                    "receipt": None,
                },
            )

        # Execute the bond purchase
        bond_oas = level_data["bond_oas"]
        buy_result = self.buy(asset_id, buyer, bond_oas)
        if not buy_result.success:
            return buy_result

        return ServiceResult(
            success=True,
            data={
                "asset_id": asset_id,
                "buyer": buyer,
                "level": level,
                "bond_oas": bond_oas,
                "lock_days": level_data["lock_days"],
                "via_equity": False,
                "receipt": buy_result.data,
            },
        )

    # -----------------------------------------------------------------------
    # Register — delegates to OasyceSkills (already shared)
    # -----------------------------------------------------------------------
    def register(
        self,
        file_path: str,
        owner: str,
        tags: List[str],
        rights_type: str = "original",
        co_creators: Optional[List[Dict[str, Any]]] = None,
        price_model: str = "auto",
        manual_price: Optional[float] = None,
        storage_backend: Optional[str] = None,
    ) -> ServiceResult:
        """Register a data asset through the unified skill pipeline."""
        # Validate price model
        if price_model in ("fixed", "floor"):
            if manual_price is None or manual_price <= 0:
                return ServiceResult(
                    success=False,
                    error=f"price_model={price_model} requires a positive manual_price",
                )

        try:
            skills = self._get_skills()

            # Scan → Classify → Metadata → Certificate → Register
            file_info = skills.scan_data_skill(file_path)
            classification = skills.classify_data_skill(file_info)
            metadata = skills.generate_metadata_skill(
                file_info,
                tags,
                owner=owner,
                classification=classification,
                rights_type=rights_type,
                co_creators=co_creators,
            )

            # Attach price model
            metadata["price_model"] = price_model
            if manual_price is not None:
                metadata["manual_price"] = manual_price

            result = skills.register_data_asset_skill(
                metadata,
                file_path=file_path,
                storage_backend=storage_backend,
            )

            return ServiceResult(success=True, data=result)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Dispute
    # -----------------------------------------------------------------------
    def dispute(
        self,
        asset_id: str,
        consumer_id: str,
        reason: str,
        invocation_id: Optional[str] = None,
        signature: Optional[str] = None,
    ) -> ServiceResult:
        """Open a dispute for an asset or invocation.

        If *invocation_id* is provided, the full DisputeManager jury flow is
        used.  Otherwise the dispute is stored as a simple metadata flag on
        the asset in the ledger (backward-compatible path).
        """
        if not self._verify_agent(consumer_id, signature):
            return ServiceResult(success=False, error="Identity verification failed: invalid or missing signature")
        try:
            # ── Full jury-based dispute (invocation_id provided) ──────
            if invocation_id is not None:
                dm = self._get_dispute_manager()
                record = dm.open_dispute(invocation_id, consumer_id, reason)
                return ServiceResult(
                    success=True,
                    data={
                        "ok": True,
                        "dispute_id": record.dispute_id,
                        "invocation_id": record.invocation_id,
                        "state": record.state.value,
                        "consumer_id": record.consumer_id,
                        "provider_id": record.provider_id,
                    },
                )

            # ── Legacy asset-level dispute (no invocation_id) ─────────
            if self._ledger is None:
                return ServiceResult(success=False, error="Ledger not available")

            meta = self._ledger.get_asset_metadata(asset_id)
            if meta is None:
                return ServiceResult(success=False, error=f"Asset not found: {asset_id}")

            meta["disputed"] = True
            meta["dispute_reason"] = reason
            meta["dispute_time"] = int(time.time())
            meta["dispute_status"] = "open"

            # Best-effort arbitrator discovery
            arbitrators: List[Dict[str, Any]] = []
            try:
                from oasyce.services.discovery import SkillDiscoveryEngine

                discovery = SkillDiscoveryEngine(get_capabilities=lambda: [])
                candidates = discovery.discover_arbitrators(
                    dispute_tags=meta.get("tags", []),
                    limit=3,
                )
                arbitrators = [
                    {
                        "capability_id": c.capability_id,
                        "name": c.name,
                        "score": c.final_score,
                    }
                    for c in candidates
                ]
                meta["arbitrator_candidates"] = arbitrators
            except Exception:
                pass

            self._ledger.set_asset_metadata(asset_id, meta)

            return ServiceResult(
                success=True,
                data={
                    "ok": True,
                    "asset_id": asset_id,
                    "disputed": True,
                    "arbitrators": arbitrators,
                },
            )
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Resolve dispute
    # -----------------------------------------------------------------------
    def resolve_dispute(
        self,
        dispute_id: str = "",
        asset_id: str = "",
        remedy: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> ServiceResult:
        """Resolve a dispute.

        Two paths:
        * If *dispute_id* is given — use DisputeManager.resolve() (jury tally).
        * If *asset_id* + *remedy* are given — apply a simple remedy to the
          ledger record (backward-compatible path).
        """
        try:
            # ── Jury-based resolution (dispute_id provided) ───────────
            if dispute_id:
                dm = self._get_dispute_manager()
                resolution = dm.resolve(dispute_id)
                return ServiceResult(
                    success=True,
                    data={
                        "ok": True,
                        "dispute_id": resolution.dispute_id,
                        "outcome": resolution.outcome.value,
                        "consumer_refunded": resolution.consumer_refunded,
                        "provider_paid": resolution.provider_paid,
                        "slash_amount": resolution.slash_amount,
                        "jury_reward": resolution.jury_reward,
                    },
                )

            # ── Legacy asset-level resolution ─────────────────────────
            if not asset_id:
                return ServiceResult(success=False, error="dispute_id or asset_id required")

            from oasyce.models import VALID_REMEDY_TYPES

            if remedy not in VALID_REMEDY_TYPES:
                return ServiceResult(
                    success=False,
                    error=f"Invalid remedy. Must be one of: {', '.join(VALID_REMEDY_TYPES)}",
                )

            if self._ledger is None:
                return ServiceResult(success=False, error="Ledger not available")

            meta = self._ledger.get_asset_metadata(asset_id)
            if meta is None:
                return ServiceResult(success=False, error=f"Asset not found: {asset_id}")

            if not meta.get("disputed"):
                return ServiceResult(success=False, error="Asset is not disputed")

            if meta.get("dispute_status") == "resolved":
                return ServiceResult(success=False, error="Dispute already resolved")

            details = details or {}
            resolution_rec = {
                "remedy": remedy,
                "details": details,
                "resolved_at": int(time.time()),
            }
            meta["dispute_status"] = "resolved"
            meta["dispute_resolution"] = resolution_rec

            if remedy == "delist":
                meta["delisted"] = True
            elif remedy == "transfer":
                new_owner = details.get("new_owner", "")
                if new_owner:
                    meta["owner"] = new_owner
                    self._ledger.update_asset_owner(asset_id, new_owner)
            elif remedy == "rights_correction":
                from oasyce.models import VALID_RIGHTS_TYPES

                new_rights = details.get("new_rights_type", "collection")
                if new_rights in VALID_RIGHTS_TYPES:
                    meta["rights_type"] = new_rights
            elif remedy == "share_adjustment":
                new_co_creators = details.get("co_creators")
                if new_co_creators:
                    # Validate shares sum to 100
                    total_share = sum(c.get("share", 0) for c in new_co_creators)
                    if abs(total_share - 100) > 0.01:
                        return ServiceResult(
                            success=False,
                            error=f"Co-creator shares must sum to 100 (got {total_share})",
                        )
                    # Validate all addresses are non-empty
                    for c in new_co_creators:
                        if not c.get("address"):
                            return ServiceResult(
                                success=False,
                                error="Each co-creator must have a non-empty address",
                            )
                    meta["co_creators"] = new_co_creators

            self._ledger.set_asset_metadata(asset_id, meta)

            return ServiceResult(
                success=True,
                data={
                    "ok": True,
                    "asset_id": asset_id,
                    "remedy": remedy,
                    "resolution": resolution_rec,
                },
            )
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Protocol Stats
    # -----------------------------------------------------------------------
    def protocol_stats(self) -> ServiceResult:
        """Return protocol-level statistics (fees collected, tokens burned)."""
        try:
            se = self._get_settlement()
            stats = se.protocol_stats()
            return ServiceResult(success=True, data=stats)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Reputation Decay (proactive)
    # -----------------------------------------------------------------------
    def decay_all_reputations(self) -> ServiceResult:
        """Apply time-based reputation decay to all agents.

        Should be called periodically (e.g., daily via cron or background task).
        """
        try:
            rep = self._get_reputation()
            changed = rep.decay_all()
            return ServiceResult(success=True, data={"agents_decayed": changed})
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Sell Quote (preview without executing)
    # -----------------------------------------------------------------------
    def sell_quote(self, asset_id: str, seller: str, tokens: float) -> ServiceResult:
        """Get a quote for selling tokens back to the bonding curve."""
        try:
            se = self._get_settlement()
            sq = se.sell_quote(asset_id, tokens, seller)
            return ServiceResult(
                success=True,
                data={
                    "asset_id": sq.asset_id,
                    "tokens_sold": sq.tokens_sold,
                    "payout_oas": sq.payout_oas,
                    "protocol_fee": sq.protocol_fee,
                    "burn_amount": sq.burn_amount,
                    "price_impact_pct": sq.price_impact_pct,
                },
            )
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Pool Info (read-only)
    # -----------------------------------------------------------------------
    def get_pool_info(self, asset_id: str) -> ServiceResult:
        """Return read-only pool information for an asset."""
        try:
            se = self._get_settlement()
            pool = se.get_pool(asset_id)
            if pool is None:
                return ServiceResult(success=False, error=f"Pool not found: {asset_id}")
            return ServiceResult(
                success=True,
                data={
                    "asset_id": pool.asset_id,
                    "owner": pool.owner,
                    "supply": pool.supply,
                    "reserve_balance": pool.reserve_balance,
                    "spot_price": pool.spot_price,
                    "equity": dict(pool.equity),  # copy
                    "total_buys": pool.total_buys,
                    "total_sells": pool.total_sells,
                },
            )
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # List Pools
    # -----------------------------------------------------------------------
    def list_pools(self) -> ServiceResult:
        """List summary of all settlement pools."""
        try:
            se = self._get_settlement()
            pools = []
            for aid, pool in se.pools.items():
                pools.append({
                    "asset_id": pool.asset_id,
                    "owner": pool.owner,
                    "supply": pool.supply,
                    "reserve_balance": pool.reserve_balance,
                    "spot_price": pool.spot_price,
                })
            return ServiceResult(success=True, data={"pools": pools})
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Portfolio
    # -----------------------------------------------------------------------
    def get_portfolio(self, agent_id: str) -> ServiceResult:
        """Get an agent's equity holdings across all pools."""
        try:
            se = self._get_settlement()
            holdings = []
            for aid, pool in se.pools.items():
                equity = pool.equity.get(agent_id, 0)
                if equity > 0:
                    pct = equity / pool.supply if pool.supply > 0 else 0
                    holdings.append({
                        "asset_id": aid,
                        "tokens": equity,
                        "pct": round(pct * 100, 4),
                        "value_oas": round(equity * pool.spot_price, 6),
                        "access_level": None,  # filled below
                    })
            # Fill access levels
            for h in holdings:
                h["access_level"] = self.get_equity_access_level(h["asset_id"], agent_id)
            return ServiceResult(success=True, data={"agent_id": agent_id, "holdings": holdings})
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Asset Mutation — update / delete / get
    # -----------------------------------------------------------------------
    def update_asset_metadata(
        self, asset_id: str, updates: Dict[str, Any],
        owner: str = "",
        signature: Optional[str] = None,
    ) -> ServiceResult:
        """Update asset metadata fields (tags, version, etc.).

        Only specified keys are merged; existing keys are preserved.
        *owner* is the caller requesting the update — verified against the
        asset's actual owner.
        """
        if not self._verify_agent(owner or asset_id, signature):
            return ServiceResult(success=False, error="Identity verification failed: invalid or missing signature")
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")
        try:
            # Verify caller is the asset owner
            if owner:
                meta = self._ledger.get_asset_metadata(asset_id)
                if meta is None:
                    return ServiceResult(success=False, error=f"Asset not found: {asset_id}")
                if meta.get("owner") != owner:
                    return ServiceResult(success=False, error="Only the asset owner can update metadata")
            if not self._ledger.update_asset_metadata(asset_id, updates):
                return ServiceResult(success=False, error=f"Asset not found: {asset_id}")
            return ServiceResult(success=True, data={"asset_id": asset_id, "updated_keys": list(updates.keys())})
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def delist_asset(self, asset_id: str, owner: str, signature: Optional[str] = None) -> ServiceResult:
        """Owner voluntarily delists their asset (sets delisted=True, keeps records)."""
        if not self._verify_agent(owner, signature):
            return ServiceResult(success=False, error="Identity verification failed")
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")
        meta = self._ledger.get_asset_metadata(asset_id)
        if meta is None:
            return ServiceResult(success=False, error=f"Asset not found: {asset_id}")
        if meta.get("owner") != owner:
            return ServiceResult(success=False, error="Only the asset owner can delist")
        if meta.get("delisted"):
            return ServiceResult(success=False, error="Asset is already delisted")
        self._ledger.update_asset_metadata(asset_id, {"delisted": True})
        return ServiceResult(success=True, data={"asset_id": asset_id, "delisted": True, "owner": owner})

    def delete_asset(self, asset_id: str, signature: Optional[str] = None) -> ServiceResult:
        """Delete an asset and its associated records.

        Removes from ledger, fingerprint records, and settlement pool.
        """
        if not self._verify_agent(asset_id, signature):
            return ServiceResult(success=False, error="Identity verification failed: invalid or missing signature")
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")

        # Prevent deletion if anyone holds equity
        se = self._get_settlement()
        pool = se.get_pool(asset_id)
        if pool is not None:
            holders = {k: v for k, v in pool.equity.items() if v > 0}
            if holders:
                return ServiceResult(
                    success=False,
                    error=f"Cannot delete: {len(holders)} equity holder(s) have active positions. "
                    f"All holders must sell before deletion.",
                )

        try:
            if not self._ledger.delete_asset(asset_id):
                return ServiceResult(success=False, error=f"Asset not found: {asset_id}")
            return ServiceResult(success=True, data={"asset_id": asset_id, "deleted": True})
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def jury_vote(
        self,
        dispute_id: str,
        juror_id: str,
        verdict: str,
        reason: str = "",
        signature: Optional[str] = None,
    ) -> ServiceResult:
        """Submit a juror's vote on a dispute.

        *verdict* must be ``'consumer'`` or ``'provider'``.
        """
        if not self._verify_agent(juror_id, signature):
            return ServiceResult(success=False, error="Identity verification failed: invalid or missing signature")
        try:
            dm = self._get_dispute_manager()
            vote = dm.submit_vote(dispute_id, juror_id, verdict, reason)
            return ServiceResult(
                success=True,
                data={
                    "dispute_id": dispute_id,
                    "juror_id": vote.juror_id,
                    "verdict": vote.verdict.value,
                    "reason": vote.reason,
                },
            )
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def submit_evidence(
        self,
        dispute_id: str,
        submitter: str,
        evidence_hash: str,
        evidence_type: str = "fingerprint_match",
        weight: float = 1.0,
        description: str = "",
        signature: Optional[str] = None,
    ) -> ServiceResult:
        """Submit evidence for a dispute."""
        if not self._verify_agent(submitter, signature):
            return ServiceResult(success=False, error="Identity verification failed")
        try:
            from oasyce.core.evidence import Evidence, EvidenceType

            evidence = Evidence(
                evidence_hash=evidence_hash,
                evidence_type=EvidenceType(evidence_type),
                weight=weight,
                source=submitter,
            )
            dm = self._get_dispute_manager()
            dm.submit_evidence(
                dispute_id=dispute_id,
                party_id=submitter,
                evidence_hash=evidence_hash,
                description=description,
            )
            return ServiceResult(
                success=True,
                data={
                    "dispute_id": dispute_id,
                    "evidence_hash": evidence_hash,
                    "evidence_type": evidence_type,
                    "weight": weight,
                },
            )
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def get_asset(self, asset_id: str) -> ServiceResult:
        """Get asset information by ID."""
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")
        try:
            asset = self._ledger.get_asset(asset_id)
            if asset is None:
                return ServiceResult(success=False, error=f"Asset not found: {asset_id}")
            return ServiceResult(success=True, data=asset)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

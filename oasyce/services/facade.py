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

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
ACCESS_LEVELS = {
    "L0": {"name": "Query", "multiplier": 1.0, "lock_days": 1},
    "L1": {"name": "Sample", "multiplier": 2.0, "lock_days": 3},
    "L2": {"name": "Compute", "multiplier": 3.0, "lock_days": 7},
    "L3": {"name": "Deliver", "multiplier": 15.0, "lock_days": 30},
}

REPUTATION_THRESHOLDS = {
    "sandbox": 20,  # R < 20 → L0 only
    "limited": 50,  # R 20-49 → L0 + L1
    # R ≥ 50 → all levels
}

# Equity % thresholds → access level granted
EQUITY_ACCESS_THRESHOLDS = [
    (0.10, "L3"),   # >= 10% → L3 (Deliver)
    (0.05, "L2"),   # >= 5%  → L2 (Compute)
    (0.01, "L1"),   # >= 1%  → L1 (Sample)
    (0.001, "L0"),  # >= 0.1% → L0 (Query)
]

# Map level string to numeric index for comparisons
_LEVEL_INDEX = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------
class OasyceServiceFacade:
    """Single entry point for quote, buy, access-control, and registration."""

    def __init__(self, config=None, ledger=None):
        self._config = config
        self._ledger = ledger

        # Lazy-initialised service instances
        self._settlement = None
        self._access_provider = None
        self._reputation = None
        self._skills = None
        self._dispute_manager = None

    # -- lazy accessors -----------------------------------------------------

    def _get_settlement(self):
        if self._settlement is None:
            from oasyce.services.settlement.engine import SettlementEngine

            self._settlement = SettlementEngine()
        return self._settlement

    def _get_reputation(self):
        if self._reputation is None:
            from oasyce.services.reputation import ReputationEngine

            self._reputation = ReputationEngine()
        return self._reputation

    def _get_access_provider(self):
        if self._access_provider is None:
            from oasyce.services.access.provider import DataAccessProvider

            self._access_provider = DataAccessProvider(
                reputation=self._get_reputation(),
            )
        return self._access_provider

    def _get_dispute_manager(self):
        if self._dispute_manager is None:
            from oasyce.capabilities.dispute import DisputeManager

            # Wire callbacks using other facade services
            def _get_invocation(invocation_id: str):
                """Look up an invocation record from the ledger."""
                if self._ledger is None:
                    return None
                try:
                    row = self._ledger._conn.execute(
                        "SELECT * FROM assets WHERE asset_id = ?", (invocation_id,)
                    ).fetchone()
                    if row is None:
                        return None
                    # Return a simple namespace object with expected attributes
                    import types
                    import json as _json

                    meta = _json.loads(row["metadata"]) if row.get("metadata") else {}
                    inv = types.SimpleNamespace(
                        consumer_id=meta.get("consumer_id", ""),
                        provider_id=meta.get("provider_id", row.get("owner", "")),
                        capability_id=meta.get("capability_id", ""),
                        state=types.SimpleNamespace(value=meta.get("state", "completed")),
                        settled_at=meta.get("settled_at", 0),
                        escrow_id=meta.get("escrow_id", ""),
                        price=meta.get("price", 0.0),
                    )
                    return inv
                except Exception:
                    return None

            def _get_reputation(agent_id: str) -> float:
                try:
                    rep_engine = self._get_reputation()
                    return rep_engine.get_reputation(agent_id)
                except Exception:
                    return 0.0

            def _get_stake(agent_id: str) -> float:
                # Default stub — returns enough to qualify as juror
                return 100.0

            def _escrow_refund(escrow_id: str):
                pass  # No-op stub for local mode

            def _escrow_release(escrow_id: str):
                pass  # No-op stub for local mode

            self._dispute_manager = DisputeManager(
                get_invocation=_get_invocation,
                get_reputation=_get_reputation,
                get_stake=_get_stake,
                escrow_refund=_escrow_refund,
                escrow_release=_escrow_release,
            )
        return self._dispute_manager

    def _get_skills(self):
        if self._skills is None:
            from oasyce.skills.agent_skills import OasyceSkills

            self._skills = OasyceSkills(config=self._config, ledger=self._ledger)
        return self._skills

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

        Returns the level string ("L0"-"L3") or None if no equity or
        insufficient holdings.
        """
        se = self._get_settlement()
        pool = se.get_pool(asset_id)
        if pool is None or pool.supply <= 0:
            return None

        holdings = pool.equity.get(agent_id, 0)
        if holdings <= 0:
            return None

        pct = holdings / pool.supply

        # Find highest qualifying level from equity
        equity_level: Optional[str] = None
        for threshold, level in EQUITY_ACCESS_THRESHOLDS:
            if pct >= threshold:
                equity_level = level
                break

        if equity_level is None:
            return None

        # Cap by reputation
        rep = self._get_reputation()
        score = rep.get_reputation(agent_id)
        if score < REPUTATION_THRESHOLDS["sandbox"]:
            max_idx = 0  # L0 only
        elif score < REPUTATION_THRESHOLDS["limited"]:
            max_idx = 1  # L0 + L1
        else:
            max_idx = 3  # all levels

        equity_idx = _LEVEL_INDEX[equity_level]
        capped_idx = min(equity_idx, max_idx)
        return f"L{capped_idx}"

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
    def buy(self, asset_id: str, buyer: str, amount_oas: float = 10.0) -> ServiceResult:
        """Execute a share purchase through the settlement engine."""
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
    ) -> ServiceResult:
        """Sell tokens back to the bonding curve for OAS payout."""
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
    ) -> ServiceResult:
        """Open a dispute for an asset or invocation.

        If *invocation_id* is provided, the full DisputeManager jury flow is
        used.  Otherwise the dispute is stored as a simple metadata flag on
        the asset in the ledger (backward-compatible path).
        """
        import json as _json

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

            row = self._ledger._conn.execute(
                "SELECT metadata FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if not row:
                return ServiceResult(success=False, error=f"Asset not found: {asset_id}")

            meta = _json.loads(row["metadata"]) if row["metadata"] else {}
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

            self._ledger._conn.execute(
                "UPDATE assets SET metadata = ? WHERE asset_id = ?",
                (_json.dumps(meta), asset_id),
            )
            self._ledger._conn.commit()

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
        import json as _json

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

            row = self._ledger._conn.execute(
                "SELECT metadata FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if not row:
                return ServiceResult(success=False, error=f"Asset not found: {asset_id}")

            meta = _json.loads(row["metadata"]) if row["metadata"] else {}
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
                    self._ledger._conn.execute(
                        "UPDATE assets SET owner = ? WHERE asset_id = ?",
                        (new_owner, asset_id),
                    )
            elif remedy == "rights_correction":
                from oasyce.models import VALID_RIGHTS_TYPES

                new_rights = details.get("new_rights_type", "collection")
                if new_rights in VALID_RIGHTS_TYPES:
                    meta["rights_type"] = new_rights
            elif remedy == "share_adjustment":
                new_co_creators = details.get("co_creators")
                if new_co_creators:
                    meta["co_creators"] = new_co_creators

            self._ledger._conn.execute(
                "UPDATE assets SET metadata = ? WHERE asset_id = ?",
                (_json.dumps(meta), asset_id),
            )
            self._ledger._conn.commit()

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

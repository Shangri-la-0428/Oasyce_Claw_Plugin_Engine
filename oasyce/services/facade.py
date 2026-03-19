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
    "L3": {"name": "Deliver", "multiplier": 5.0, "lock_days": 30},
}

REPUTATION_THRESHOLDS = {
    "sandbox": 20,  # R < 20 → L0 only
    "limited": 50,  # R 20-49 → L0 + L1
    # R ≥ 50 → all levels
}


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

    def _get_skills(self):
        if self._skills is None:
            from oasyce.skills.agent_skills import OasyceSkills

            self._skills = OasyceSkills(config=self._config, ledger=self._ledger)
        return self._skills

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
            return ServiceResult(
                success=True,
                data={
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

            return ServiceResult(
                success=True,
                data={
                    "asset_id": asset_id,
                    "buyer": buyer,
                    "reputation": round(score, 2),
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

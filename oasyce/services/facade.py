"""
Oasyce Service Facade — unified entry point for all business operations.

Both CLI and GUI MUST route through this facade to ensure consistent
pricing, access control, settlement, and notifications.

Architecture:
    CLI (cli.py)  ──┐
                    ├──▶ OasyceServiceFacade ──▶ Services (settlement, access, reputation, ...)
    GUI (app.py)  ──┘

Layer separation:
    OasyceQuery   — read-only view; safe to hand to any GET handler
    OasyceServiceFacade — full facade including write operations (buy, sell, register, ...)

GUI GET handlers use OasyceQuery (cannot mutate state).
GUI POST handlers and CLI commands use OasyceServiceFacade.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from oasyce.chain_client import OasyceClient
from oasyce.services.settlement.engine import AssetStatus, QuoteResult, SettlementConfig

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
    INITIAL_PRICE,
    LEVEL_INDEX as _LEVEL_INDEX,
    REPUTATION_SANDBOX,
    REPUTATION_LIMITED,
    bonding_curve_buy,
    calculate_fees,
    equity_to_access_level,
    price_impact,
    spot_price as _spot_price,
)

ACCESS_LEVELS = {
    "L0": {"name": "Query", "multiplier": 1.0, "lock_days": 1},
    "L1": {"name": "Sample", "multiplier": 2.0, "lock_days": 3},
    "L2": {"name": "Compute", "multiplier": 3.0, "lock_days": 7},
    "L3": {"name": "Deliver", "multiplier": 5.0, "lock_days": 30},
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

    def __init__(
        self,
        config=None,
        ledger=None,
        verify_identity: bool = False,
        allow_local_fallback: Optional[bool] = None,
    ):
        from oasyce.config import get_network_mode, get_security

        self._config = config
        self._ledger = ledger
        self._network_mode = get_network_mode()
        _security = get_security(self._network_mode)

        # verify_identity: explicit True overrides; otherwise derive from mode
        self._verify_identity = verify_identity or _security["verify_identity"]

        # allow_local_fallback: explicit param > OASYCE_STRICT_CHAIN env > mode default
        if allow_local_fallback is not None:
            self._allow_local_fallback = allow_local_fallback
        elif _env_flag("OASYCE_STRICT_CHAIN"):
            self._allow_local_fallback = False
        else:
            self._allow_local_fallback = _security["allow_local_fallback"]
        self._init_lock = threading.Lock()

        # Lazy-initialised service instances
        self._settlement = None
        self._access_provider = None
        self._reputation = None
        self._skills = None
        self._dispute_manager = None
        self._chain_client = None

    # -- lazy accessors -----------------------------------------------------

    def _get_settlement(self):
        if self._settlement is None:
            with self._init_lock:
                if self._settlement is None:  # double-check
                    from oasyce.services.settlement.engine import SettlementEngine

                    self._settlement = SettlementEngine(
                        config=SettlementConfig(
                            chain_required=not self._allow_local_fallback,
                            allow_local_fallback=self._allow_local_fallback,
                        )
                    )
        return self._settlement

    def _get_chain_client(self):
        if self._chain_client is None:
            with self._init_lock:
                if self._chain_client is None:  # double-check
                    rest_url = getattr(self._config, "rest_url", "http://localhost:1317")
                    self._chain_client = OasyceClient(
                        rest_url=rest_url,
                        allow_local_fallback=self._allow_local_fallback,
                    )
        return self._chain_client

    def _strict_chain_mode(self) -> bool:
        return not self._allow_local_fallback

    @staticmethod
    def _parse_number(value: Any, scale: float = 1.0) -> float:
        if isinstance(value, dict):
            value = value.get("amount", 0)
        try:
            return float(value) / scale
        except (TypeError, ValueError):
            return 0.0

    def _get_chain_market_state(self, asset_id: str) -> Dict[str, float]:
        data = self._get_chain_client().get_bonding_curve_price(asset_id)
        supply = self._parse_number(data.get("supply", 0))
        reserve = self._parse_number(data.get("reserve", {}), scale=1e8)
        quoted_price = self._parse_number(data.get("price", {}), scale=1e8)
        if quoted_price > 0:
            spot_price = quoted_price
        elif supply <= 0 and reserve <= 0:
            spot_price = INITIAL_PRICE
        else:
            spot_price = _spot_price(supply, reserve)
        return {
            "supply": supply,
            "reserve": reserve,
            "spot_price": spot_price,
        }

    def _quote_from_chain_state(
        self,
        asset_id: str,
        amount_oas: float,
        max_slippage: Optional[float] = None,
    ) -> QuoteResult:
        state = self._get_chain_market_state(asset_id)
        price_before = state["spot_price"]
        fee, burn, treasury, net_payment = calculate_fees(amount_oas)
        tokens = bonding_curve_buy(state["supply"], state["reserve"], net_payment)
        new_reserve = state["reserve"] + net_payment
        new_supply = state["supply"] + tokens
        price_after = _spot_price(new_supply, new_reserve)
        impact = price_impact(price_before, price_after)
        if max_slippage is not None and abs(impact) > max_slippage * 100:
            raise ValueError(
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

    def _get_onchain_holdings(self, asset_id: str, agent_id: str) -> tuple[float, float]:
        market = self._get_chain_market_state(asset_id)
        if market["supply"] <= 0:
            return 0.0, 0.0

        holdings = 0.0
        shareholders = self._get_chain_client().get_shareholders(asset_id)
        for holder in shareholders:
            address = (
                holder.get("address")
                or holder.get("owner")
                or holder.get("shareholder")
                or holder.get("holder")
                or ""
            )
            if address == agent_id:
                holdings = self._parse_number(holder.get("shares", holder.get("amount", 0)))
                break
        return holdings, market["supply"]

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
        if self._strict_chain_mode():
            holdings, supply = self._get_onchain_holdings(asset_id, agent_id)
        else:
            se = self._get_settlement()
            supply = se.get_supply(asset_id)
            holdings = se.get_equity(asset_id, agent_id)
        if supply <= 0:
            return None
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
            if self._strict_chain_mode():
                qr = self._quote_from_chain_state(asset_id, amount_oas)
            else:
                se = self._get_settlement()
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
            if self._strict_chain_mode():
                from oasyce.bridge.core_bridge import bridge_buy

                qr = self._quote_from_chain_state(asset_id, amount_oas)
                result = bridge_buy(asset_id, buyer, amount_oas, ledger=self._ledger)
                if "error" in result:
                    return ServiceResult(success=False, error=result["error"])

                access_granted = None
                try:
                    access_granted = self.get_equity_access_level(asset_id, buyer)
                except Exception:
                    pass

                return ServiceResult(
                    success=True,
                    data={
                        "tx_id": result.get("tx_id"),
                        "receipt_id": result.get("tx_id"),
                        "asset_id": asset_id,
                        "buyer": buyer,
                        "amount_oas": amount_oas,
                        "settled": True,
                        "quote": {
                            "equity_minted": qr.equity_minted,
                            "spot_price_after": qr.spot_price_after,
                            "protocol_fee": qr.protocol_fee,
                        },
                        "access_granted": access_granted,
                    },
                )

            se = self._get_settlement()
            pool = se.get_pool(asset_id)

            if pool is None:
                # Check if asset exists in local ledger — auto-register pool
                local_asset = self._ledger.get_asset(asset_id) if self._ledger else None
                if local_asset:
                    owner = local_asset.get("owner", "protocol")
                    se.register_asset(asset_id, owner)
                else:
                    # Truly unknown — fallback to chain bridge
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
            if self._strict_chain_mode():
                # Route through on-chain MsgSellShares
                chain = self._get_chain_client()
                shares_int = int(tokens_to_sell * 1e8)
                min_payout = int(shares_int * (1.0 - max_slippage)) if max_slippage < 1.0 else None
                result = chain.sell_shares(
                    seller=seller,
                    asset_id=asset_id,
                    shares=shares_int,
                    min_payout_uoas=min_payout,
                )
                payout_uoas = int(result.get("payout", result.get("tx_response", {}).get("payout", 0)))
                return ServiceResult(
                    success=True,
                    data={
                        "receipt_id": result.get("tx_response", {}).get("txhash", ""),
                        "asset_id": asset_id,
                        "seller": seller,
                        "payout_oas": payout_uoas / 1e8,
                        "settled": True,
                        "chain_tx": True,
                    },
                )
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

            # Determine max allowed level based on reputation
            if score < REPUTATION_THRESHOLDS["sandbox"]:
                max_level = 0  # L0 only
            elif score < REPUTATION_THRESHOLDS["limited"]:
                max_level = 1  # L0 + L1
            else:
                max_level = 3  # all levels

            if self._strict_chain_mode():
                base_price = self._get_chain_market_state(asset_id)["spot_price"]
            else:
                se = self._get_settlement()
                pool = se.get_pool(asset_id)
                base_price = pool.spot_price if pool else INITIAL_PRICE

            # Determine risk level from asset metadata (default: public)
            risk_level = "public"
            if self._ledger is not None:
                meta = self._ledger.get_asset_metadata(asset_id)
                if meta is not None:
                    risk_level = meta.get("risk_level", "public")

            # Use DataAccessProvider.bond_for for the full bond formula
            # (includes RiskFactor and ExposureFactor)
            provider = self._get_access_provider()

            levels = []
            for i, (level_key, info) in enumerate(ACCESS_LEVELS.items()):
                bond = provider.bond_for(buyer, base_price, level_key, risk_level=risk_level)
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

            # Mark levels covered by equity (keep original bond visible)
            for lv in levels:
                lv_idx = _LEVEL_INDEX[lv["level"]]
                lv["covered_by_equity"] = lv_idx <= equity_idx

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

    def access_buy(
        self,
        asset_id: str,
        buyer: str,
        level: str,
        pre_quoted_bond: Optional[float] = None,
    ) -> ServiceResult:
        """Execute a tiered access purchase.

        Args:
            pre_quoted_bond: If the caller already obtained a quote, pass the
                bond value here to avoid a second quote (which could drift).
        """
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

        # Use pre-quoted bond if caller already did a quote, else use fresh quote
        bond_oas = pre_quoted_bond if pre_quoted_bond is not None else level_data["bond_oas"]
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

            if consumer_id == meta.get("owner"):
                return ServiceResult(success=False, error="Cannot dispute your own asset")

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

    # -----------------------------------------------------------------------
    # Asset Versioning
    # -----------------------------------------------------------------------
    def add_asset_version(
        self, asset_id: str, file_hash: str, owner: str,
        metadata: Optional[Dict[str, Any]] = None,
        signature: Optional[str] = None,
    ) -> ServiceResult:
        """Register a new version of an existing asset. Only the owner can add versions."""
        if not self._verify_agent(owner, signature):
            return ServiceResult(success=False, error="Identity verification failed")
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")
        asset_meta = self._ledger.get_asset_metadata(asset_id)
        if asset_meta is None:
            return ServiceResult(success=False, error=f"Asset not found: {asset_id}")
        if asset_meta.get("owner") != owner:
            return ServiceResult(success=False, error="Only the asset owner can add versions")
        prev_hash = asset_meta.get("file_hash", "")
        version = self._ledger.add_version(asset_id, file_hash, prev_hash, metadata or {})
        return ServiceResult(success=True, data={
            "asset_id": asset_id, "version": version,
            "file_hash": file_hash, "prev_hash": prev_hash,
        })

    def get_asset_versions(self, asset_id: str) -> ServiceResult:
        """Get full version history for an asset."""
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")
        versions = self._ledger.get_versions(asset_id)
        return ServiceResult(success=True, data={
            "asset_id": asset_id, "versions": versions, "count": len(versions),
        })

    # -----------------------------------------------------------------------
    # Asset Lifecycle — Graceful Exit
    # -----------------------------------------------------------------------
    def initiate_shutdown(
        self, asset_id: str, owner: str, signature: Optional[str] = None
    ) -> ServiceResult:
        """Owner initiates graceful shutdown. ACTIVE → SHUTDOWN_PENDING (7d cooldown).

        During SHUTDOWN_PENDING: buy disabled, new access disabled, sell allowed.
        """
        if not self._verify_agent(owner, signature):
            return ServiceResult(success=False, error="Identity verification failed")
        try:
            se = self._get_settlement()
            se.initiate_shutdown(asset_id, owner)
            info = se.get_shutdown_info(asset_id)
            # Notify all equity holders
            pool = se.get_pool(asset_id)
            if pool is not None:
                notif = self._get_notifications()
                for holder in pool.equity:
                    if holder != owner:
                        notif.notify(
                            holder,
                            "SHUTDOWN_INITIATED",
                            f"Asset {asset_id} is shutting down. You have 7 days to sell your shares.",
                            {"asset_id": asset_id, "owner": owner},
                        )
            return ServiceResult(success=True, data=info or {})
        except (ValueError, PermissionError) as e:
            return ServiceResult(success=False, error=str(e))

    def finalize_termination(
        self, asset_id: str, sender: str = "", signature: Optional[str] = None
    ) -> ServiceResult:
        """Anyone can finalize after cooldown. SHUTDOWN_PENDING → TERMINATED.

        Snapshots reserve and total_shares for pro-rata claim.
        """
        if sender and not self._verify_agent(sender, signature):
            return ServiceResult(success=False, error="Identity verification failed")
        try:
            se = self._get_settlement()
            se.finalize_termination(asset_id)
            info = se.get_shutdown_info(asset_id)
            # Notify all holders that they can claim
            pool = se.get_pool(asset_id)
            if pool is not None:
                notif = self._get_notifications()
                for holder in pool.equity:
                    notif.notify(
                        holder,
                        "ASSET_TERMINATED",
                        f"Asset {asset_id} is terminated. Claim your funds.",
                        {"asset_id": asset_id, "snapshot_reserve": pool.snapshot_reserve},
                    )
            return ServiceResult(success=True, data=info or {})
        except ValueError as e:
            return ServiceResult(success=False, error=str(e))

    def claim_termination(
        self, asset_id: str, holder: str, signature: Optional[str] = None
    ) -> ServiceResult:
        """Holder claims pro-rata share of reserve after termination.

        payout = (holder_shares / snapshot_total_shares) * snapshot_reserve
        """
        if not self._verify_agent(holder, signature):
            return ServiceResult(success=False, error="Identity verification failed")
        try:
            se = self._get_settlement()
            payout = se.claim_termination(asset_id, holder)
            notif = self._get_notifications()
            notif.notify(
                holder,
                "TERMINATION_CLAIMED",
                f"Claimed {payout:.6f} OAS from terminated asset {asset_id}.",
                {"asset_id": asset_id, "payout_oas": payout},
            )
            return ServiceResult(
                success=True,
                data={"asset_id": asset_id, "holder": holder, "payout_oas": payout},
            )
        except (ValueError, PermissionError) as e:
            return ServiceResult(success=False, error=str(e))

    def asset_lifecycle_info(self, asset_id: str) -> ServiceResult:
        """Return lifecycle status info for an asset."""
        se = self._get_settlement()
        info = se.get_shutdown_info(asset_id)
        if info is None:
            return ServiceResult(success=False, error=f"Asset {asset_id} not found in settlement")
        return ServiceResult(success=True, data=info)

    def delete_asset(self, asset_id: str, owner: str = "", signature: Optional[str] = None) -> ServiceResult:
        """Delete an asset and its associated records.

        Only allowed after TERMINATED state and all holders have claimed.
        Use initiate_shutdown → finalize_termination → claim for graceful exit.
        """
        if not self._verify_agent(owner, signature):
            return ServiceResult(success=False, error="Identity verification failed: invalid or missing signature")
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")

        # Verify caller is the asset owner
        meta = self._ledger.get_asset_metadata(asset_id)
        if meta is None:
            return ServiceResult(success=False, error=f"Asset not found: {asset_id}")
        if owner and meta.get("owner") != owner:
            return ServiceResult(success=False, error="Caller is not the asset owner")

        # Check lifecycle state — must be TERMINATED or have no pool
        se = self._get_settlement()
        pool = se.get_pool(asset_id)
        if pool is not None:
            if pool.status != AssetStatus.TERMINATED:
                return ServiceResult(
                    success=False,
                    error=f"Cannot delete: asset is {pool.status.value}. "
                    f"Use initiate_shutdown first.",
                )
            unclaimed = {k: v for k, v in pool.equity.items() if v > 0 and not pool.claimed.get(k)}
            if unclaimed:
                return ServiceResult(
                    success=False,
                    error=f"Cannot delete: {len(unclaimed)} holder(s) have unclaimed funds.",
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

    # -----------------------------------------------------------------------
    # Query Layer — read-only, no business logic
    # -----------------------------------------------------------------------

    def query_chain_status(self) -> ServiceResult:
        """Chain status: height, asset count, burn stats."""
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")
        try:
            height = self._ledger.get_chain_height()
            total_assets = self._ledger.count_assets()
            total_distributions = self._ledger.count_fingerprints()
            burn_stats: dict = {}
            try:
                se = self._get_settlement()
                ps = se.protocol_stats()
                burn_stats = {
                    "total_burned": round(ps.get("total_burned", 0), 6),
                    "protocol_fees_collected": round(ps.get("protocol_fees_collected", 0), 6),
                    "burn_rate_pct": 2.0,
                    "protocol_fee_pct": 3.0,
                }
            except Exception:
                pass
            return ServiceResult(success=True, data={
                "chain_height": height,
                "total_assets": total_assets,
                "total_distributions": total_distributions,
                **burn_stats,
            })
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def query_assets(self) -> ServiceResult:
        """List all assets with pool prices and metadata."""
        if self._ledger is None:
            return ServiceResult(success=True, data=[])
        try:
            import hashlib as _hl
            rows = self._ledger.list_assets()
            se = self._get_settlement()
            results = []
            for r in rows:
                import json as _j
                meta = _j.loads(r["metadata"]) if r.get("metadata") else {}
                entry: dict = {
                    "asset_id": r["asset_id"],
                    "owner": r["owner"],
                    "tags": meta.get("tags", []),
                    "created_at": r["created_at"],
                    "file_path": meta.get("file_path"),
                    "file_hash": meta.get("file_hash"),
                    "rights_type": meta.get("rights_type", "original"),
                    "co_creators": meta.get("co_creators"),
                    "disputed": meta.get("disputed", False),
                    "dispute_reason": meta.get("dispute_reason"),
                    "dispute_time": meta.get("dispute_time"),
                    "dispute_status": meta.get("dispute_status"),
                    "dispute_resolution": meta.get("dispute_resolution"),
                    "delisted": meta.get("delisted", False),
                    "spot_price": None,
                }
                aid = r["asset_id"]
                if aid in se.pools:
                    pool = se.pools[aid]
                    if pool.supply > 0:
                        entry["spot_price"] = round(pool.spot_price, 6)
                # Hash integrity check
                fp = meta.get("file_path")
                fh = meta.get("file_hash")
                if fp and fh:
                    try:
                        h = _hl.sha256()
                        with open(fp, "rb") as f:
                            for chunk in iter(lambda: f.read(8192), b""):
                                h.update(chunk)
                        entry["hash_status"] = "ok" if h.hexdigest() == fh else "changed"
                    except FileNotFoundError:
                        entry["hash_status"] = "missing"
                else:
                    entry["hash_status"] = "ok"
                # Version info
                full_meta = self._ledger.get_asset_metadata(aid) or {}
                versions = full_meta.get("versions", [])
                entry["version"] = versions[-1]["version"] if versions else 1
                entry["versions_count"] = len(versions) if versions else 1
                results.append(entry)
            return ServiceResult(success=True, data=results)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def query_blocks(self, limit: int = 20) -> ServiceResult:
        """List recent blocks."""
        if self._ledger is None:
            return ServiceResult(success=True, data=[])
        try:
            rows = self._ledger.list_blocks(limit=limit)
            blocks = [{
                "block_number": r["block_number"],
                "block_hash": r["block_hash"],
                "prev_hash": r["prev_hash"],
                "merkle_root": r["merkle_root"],
                "timestamp": r["timestamp"],
            } for r in rows]
            return ServiceResult(success=True, data=blocks)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def query_block(self, block_number: int) -> ServiceResult:
        """Get a single block with transactions."""
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")
        try:
            block = self._ledger.get_block(block_number, include_tx=True)
            if block is None:
                return ServiceResult(success=False, error=f"Block not found: {block_number}")
            return ServiceResult(success=True, data=block)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def query_stakes(self) -> ServiceResult:
        """List validator stakes summary."""
        if self._ledger is None:
            return ServiceResult(success=True, data=[])
        try:
            rows = self._ledger.get_stakes_summary()
            return ServiceResult(success=True, data=[
                {"validator_id": r["validator_id"], "total": r["total"]}
                for r in rows
            ])
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def query_transactions(self, limit: int = 50) -> ServiceResult:
        """List recent settlement receipts."""
        try:
            se = self._get_settlement()
            txs = []
            if hasattr(se, "receipts"):
                for r in se.receipts[-limit:]:
                    txs.append({
                        "receipt_id": r.receipt_id,
                        "asset_id": r.asset_id,
                        "buyer": r.buyer,
                        "amount": r.quote.payment_oas if r.quote else r.amount_oas,
                        "tokens": round(r.quote.equity_minted, 4) if r.quote else 0,
                        "status": r.status.value,
                        "timestamp": getattr(r, "timestamp", 0),
                    })
            return ServiceResult(success=True, data=txs)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def query_fingerprints(self, asset_id: str) -> ServiceResult:
        """Get fingerprint distributions for an asset."""
        if self._ledger is None:
            return ServiceResult(success=True, data=[])
        try:
            from oasyce.fingerprint.registry import FingerprintRegistry
            registry = FingerprintRegistry(self._ledger)
            return ServiceResult(success=True, data=registry.get_distributions(asset_id))
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def query_trace(self, fingerprint: str) -> ServiceResult:
        """Trace a fingerprint back to its source."""
        if self._ledger is None:
            return ServiceResult(success=False, error="Ledger not available")
        try:
            from oasyce.fingerprint.registry import FingerprintRegistry
            registry = FingerprintRegistry(self._ledger)
            result = registry.trace_fingerprint(fingerprint)
            if result is None:
                return ServiceResult(success=False, error="Fingerprint not found")
            return ServiceResult(success=True, data=result)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -- dispute queries (inline DB access to avoid circular import) --------

    _dispute_db_conn = None

    def _get_dispute_db(self):
        """Lazy-init dispute SQLite database (mirrors oasyce.gui.app logic)."""
        if OasyceServiceFacade._dispute_db_conn is None:
            import sqlite3
            data_dir = (
                self._config.data_dir
                if self._config and hasattr(self._config, "data_dir")
                else os.path.join(os.path.expanduser("~"), ".oasyce")
            )
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "disputes.db")
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS disputes (
                    dispute_id TEXT PRIMARY KEY,
                    asset_id TEXT NOT NULL,
                    buyer TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_text TEXT DEFAULT '',
                    status TEXT DEFAULT 'open',
                    created_at REAL NOT NULL,
                    resolved_at REAL,
                    resolution TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_disputes_buyer
                ON disputes (buyer, created_at DESC)
                """
            )
            OasyceServiceFacade._dispute_db_conn = conn
        return OasyceServiceFacade._dispute_db_conn

    def query_disputes(self, buyer: str = "", dispute_id: str = "") -> ServiceResult:
        """Query disputes. If dispute_id given, return single. If buyer given, list by buyer."""
        try:
            db = self._get_dispute_db()
            if dispute_id:
                r = db.execute(
                    "SELECT * FROM disputes WHERE dispute_id = ?",
                    (dispute_id,),
                ).fetchone()
                if not r:
                    return ServiceResult(success=False, error="Dispute not found")
                return ServiceResult(success=True, data={
                    "dispute_id": r["dispute_id"],
                    "asset_id": r["asset_id"],
                    "buyer": r["buyer"],
                    "reason": r["reason"],
                    "evidence_text": r["evidence_text"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "resolved_at": r["resolved_at"],
                    "resolution": r["resolution"],
                })
            if buyer:
                rows = db.execute(
                    "SELECT * FROM disputes WHERE buyer = ? ORDER BY created_at DESC",
                    (buyer,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM disputes ORDER BY created_at DESC",
                ).fetchall()
            disputes = [{
                "dispute_id": r["dispute_id"],
                "asset_id": r["asset_id"],
                "buyer": r["buyer"],
                "reason": r["reason"],
                "evidence_text": r["evidence_text"],
                "status": r["status"],
                "created_at": r["created_at"],
                "resolved_at": r["resolved_at"],
                "resolution": r["resolution"],
            } for r in rows]
            return ServiceResult(success=True, data=disputes)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # -----------------------------------------------------------------------
    # Task Market — AHRP bounty system
    # -----------------------------------------------------------------------

    def _get_task_market(self):
        if not hasattr(self, "_task_market"):
            from oasyce.ahrp.task_market import TaskMarket
            self._task_market = TaskMarket()
        return self._task_market

    def post_task(self, requester_id: str, description: str, budget: float,
                  deadline_seconds: int = 3600, required_capabilities: list = None,
                  selection_strategy: str = "weighted_score",
                  min_reputation: float = 0.0) -> ServiceResult:
        """Post a new bounty task."""
        try:
            from oasyce.ahrp.task_market import SelectionStrategy
            strategy_map = {s.value: s for s in SelectionStrategy}
            strategy = strategy_map.get(selection_strategy, SelectionStrategy.WEIGHTED_SCORE)
            tm = self._get_task_market()
            task = tm.post_task(
                requester_id=requester_id,
                description=description,
                budget=budget,
                deadline_seconds=deadline_seconds,
                required_capabilities=required_capabilities or [],
                selection_strategy=strategy,
                min_reputation=min_reputation,
            )
            return ServiceResult(success=True, data=self._task_to_dict(task))
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def submit_task_bid(self, task_id: str, agent_id: str, price: float,
                        estimated_seconds: int = 0, capability_proof: dict = None,
                        reputation_score: float = 0.0) -> ServiceResult:
        """Submit a bid on a task."""
        try:
            tm = self._get_task_market()
            bid = tm.submit_bid(
                task_id=task_id,
                agent_id=agent_id,
                price=price,
                estimated_seconds=estimated_seconds,
                capability_proof=capability_proof or {},
                reputation_score=reputation_score,
            )
            return ServiceResult(success=True, data=self._bid_to_dict(bid))
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def select_task_winner(self, task_id: str, agent_id: str = "") -> ServiceResult:
        """Select winning bid for a task."""
        try:
            tm = self._get_task_market()
            bid = tm.select_winner(task_id, agent_id=agent_id or None)
            return ServiceResult(success=True, data=self._bid_to_dict(bid))
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def complete_task(self, task_id: str) -> ServiceResult:
        """Mark task as completed."""
        try:
            tm = self._get_task_market()
            task = tm.complete_task(task_id)
            return ServiceResult(success=True, data=self._task_to_dict(task))
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def cancel_task(self, task_id: str) -> ServiceResult:
        """Cancel a task."""
        try:
            tm = self._get_task_market()
            task = tm.cancel_task(task_id)
            return ServiceResult(success=True, data=self._task_to_dict(task))
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def query_tasks(self, capabilities: list = None) -> ServiceResult:
        """List open tasks, optionally filtered by capabilities."""
        try:
            tm = self._get_task_market()
            tasks = tm.get_open_tasks(capabilities=capabilities)
            return ServiceResult(success=True, data=[self._task_to_dict(t) for t in tasks])
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def query_task(self, task_id: str) -> ServiceResult:
        """Get a specific task by ID."""
        try:
            tm = self._get_task_market()
            task = tm.get_task(task_id)
            if task is None:
                return ServiceResult(success=False, error="Task not found")
            return ServiceResult(success=True, data=self._task_to_dict(task))
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    @staticmethod
    def _task_to_dict(task) -> dict:
        """Convert Task dataclass to dict."""
        return {
            "task_id": task.task_id,
            "requester_id": task.requester_id,
            "description": task.description,
            "budget": task.budget,
            "deadline": task.deadline,
            "required_capabilities": task.required_capabilities,
            "selection_strategy": task.selection_strategy.value,
            "status": task.status.value,
            "bids": [OasyceServiceFacade._bid_to_dict(b) for b in (task.bids or [])],
            "assigned_agent": task.assigned_agent,
            "created_at": task.created_at,
            "min_reputation": task.min_reputation,
        }

    @staticmethod
    def _bid_to_dict(bid) -> dict:
        """Convert TaskBid dataclass to dict."""
        return {
            "bid_id": bid.bid_id,
            "agent_id": bid.agent_id,
            "price": bid.price,
            "estimated_seconds": bid.estimated_seconds,
            "capability_proof": bid.capability_proof,
            "reputation_score": bid.reputation_score,
            "timestamp": bid.timestamp,
        }

    # ── Contribution subsystem ────────────────────────────────────

    def query_contribution(self, file_path: str, creator_key: str, source_type: str = "manual") -> ServiceResult:
        """Generate and return a contribution proof for a file."""
        try:
            from oasyce.services.contribution import ContributionEngine
            engine = ContributionEngine()
            cert = engine.generate_proof(file_path, creator_key, source_type=source_type)
            return ServiceResult(success=True, data={
                "content_hash": cert.content_hash,
                "semantic_fingerprint": cert.semantic_fingerprint,
                "source_type": cert.source_type,
                "source_evidence": cert.source_evidence,
                "creator_key": cert.creator_key,
                "timestamp": cert.timestamp,
            })
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def verify_contribution(self, certificate_dict: dict, file_path: str) -> ServiceResult:
        """Verify a contribution certificate against a file."""
        try:
            from oasyce.services.contribution import ContributionEngine, ContributionCertificate
            engine = ContributionEngine()
            cert = ContributionCertificate.from_dict(certificate_dict)
            result = engine.verify_proof(cert, file_path)
            return ServiceResult(success=True, data=result)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # ── Leakage subsystem ─────────────────────────────────────────

    def query_leakage(self, agent_id: str, asset_id: str) -> ServiceResult:
        """Check leakage budget remaining for an agent-asset pair."""
        try:
            from oasyce.services.leakage import LeakageBudget
            lb = LeakageBudget()
            info = lb.get_remaining(agent_id, asset_id)
            return ServiceResult(success=True, data=info)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def reset_leakage(self, agent_id: str, asset_id: str) -> ServiceResult:
        """Reset leakage budget for an agent-asset pair."""
        try:
            from oasyce.services.leakage import LeakageBudget
            lb = LeakageBudget()
            result = lb.reset_budget(agent_id, asset_id)
            return ServiceResult(success=True, data=result)
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    # ── Cache subsystem ───────────────────────────────────────────

    def query_cache_stats(self) -> ServiceResult:
        """Get provider cache statistics."""
        try:
            from oasyce.offline.provider_cache import ProviderCache
            cache = ProviderCache()
            return ServiceResult(success=True, data=cache.stats())
        except Exception as e:
            return ServiceResult(success=False, error=str(e))

    def purge_cache(self) -> ServiceResult:
        """Purge expired entries from provider cache."""
        try:
            from oasyce.offline.provider_cache import ProviderCache
            cache = ProviderCache()
            removed = cache.purge_expired()
            return ServiceResult(success=True, data={"removed": removed})
        except Exception as e:
            return ServiceResult(success=False, error=str(e))


# ---------------------------------------------------------------------------
# OasyceQuery — read-only view of the service facade
# ---------------------------------------------------------------------------

class OasyceQuery:
    """Read-only projection of OasyceServiceFacade.

    GUI GET handlers and any code that should not mutate state use this.
    Attempting to call a write method (buy, sell, register, ...) raises
    AttributeError at runtime.

    Usage:
        facade = OasyceServiceFacade(...)
        query  = OasyceQuery(facade)
        result = query.query_assets()        # OK
        result = query.buy(...)              # AttributeError
    """

    _ALLOWED = frozenset({
        # query_* — pure read forwarding
        "query_chain_status",
        "query_assets",
        "query_blocks",
        "query_block",
        "query_stakes",
        "query_transactions",
        "query_fingerprints",
        "query_trace",
        "query_disputes",
        "query_tasks",
        "query_task",
        "query_contribution",
        "verify_contribution",
        "query_leakage",
        "query_cache_stats",
        # get_* — read-only lookups
        "get_equity_access_level",
        "get_pool_info",
        "get_portfolio",
        "get_asset_versions",
        "get_asset",
        # quotes — read-only price estimation
        "quote",
        "access_quote",
        "sell_quote",
    })

    def __init__(self, facade: OasyceServiceFacade):
        object.__setattr__(self, "_facade", facade)

    def __getattr__(self, name: str):
        if name in self._ALLOWED:
            return getattr(self._facade, name)
        raise AttributeError(
            f"OasyceQuery has no attribute '{name}'. "
            f"Write operations require OasyceServiceFacade."
        )

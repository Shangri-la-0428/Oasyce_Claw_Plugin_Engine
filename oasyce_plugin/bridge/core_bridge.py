"""
Bridge between oasyce_plugin CLI and oasyce_core protocol.

Converts plugin-side signed metadata into CapturePack for oasyce_core,
and exposes quote/buy/stake via OasyceProtocol.

If oasyce_core is not installed, all bridge functions raise RuntimeError
with a clear message.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional


def _check_core():
    """Verify oasyce_core is importable. Raise RuntimeError if not."""
    try:
        import oasyce_core  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "oasyce-core is not installed. "
            "Install with: pip install oasyce-core\n"
            "Without it, local features (register, search, dashboard) still work.\n"
            "Core bridge features (quote via Bancor, buy, stake) require oasyce-core."
        )


def _get_protocol():
    """Return a singleton-like OasyceProtocol (local/mock mode, no P2P node)."""
    _check_core()
    from oasyce_core.protocol import OasyceProtocol

    if not hasattr(_get_protocol, "_instance"):
        _get_protocol._instance = OasyceProtocol()
    return _get_protocol._instance


def reset_protocol() -> None:
    """Reset the cached protocol instance (useful for tests)."""
    if hasattr(_get_protocol, "_instance"):
        del _get_protocol._instance


# Backwards-compatible alias used by existing tests and CLI code.
reset_engine = reset_protocol


def metadata_to_capture_pack(signed_metadata: dict):
    """Convert plugin signed metadata dict into a CapturePack for oasyce_core."""
    _check_core()
    from oasyce_core.models.capture_pack import CapturePack

    file_hash = signed_metadata.get("file_hash", "0" * 64)
    signature = signed_metadata.get("popc_signature", "deadbeef")

    # Use existing timestamp or generate one
    ts = signed_metadata.get("timestamp")
    if isinstance(ts, (int, float)):
        iso_ts = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    else:
        iso_ts = datetime.now(timezone.utc).isoformat()

    return CapturePack(
        timestamp=iso_ts,
        gps_hash="a" * 64,  # placeholder — plugin has no GPS yet
        device_signature=signature,
        media_hash=file_hash,
        source="camera",
    )


# ---------------------------------------------------------------------------
# Async helpers (bridge runs locally; P2P node not required)
# ---------------------------------------------------------------------------

async def _async_register(pack, creator: str) -> dict:
    """Verify and register a CapturePack through the protocol (local path)."""
    protocol = _get_protocol()

    result = protocol._verifier.verify(pack)
    if not result.valid:
        return {"valid": False, "reason": result.reason, "core_asset_id": None}

    asset_id = protocol._register_asset(pack.media_hash, creator, uuid.uuid4().hex)
    return {"valid": True, "reason": result.reason, "core_asset_id": asset_id}


# ---------------------------------------------------------------------------
# Public bridge API
# ---------------------------------------------------------------------------

def bridge_register(signed_metadata: dict, creator: Optional[str] = None) -> dict:
    """Submit signed metadata through the oasyce_core verify+register pipeline.

    Returns a dict with ``valid``, ``reason``, and ``core_asset_id``.
    Async internally; safe to call from synchronous CLI or test code.
    """
    pack = metadata_to_capture_pack(signed_metadata)
    creator = creator or signed_metadata.get("owner", "anonymous")
    return asyncio.run(_async_register(pack, creator))


def bridge_quote(asset_id: str) -> dict:
    """Get Bancor-based price quote from the oasyce_core protocol."""
    protocol = _get_protocol()
    asset = protocol.get_asset(asset_id)
    if asset is None:
        return {"error": f"Asset {asset_id} not found in core registry"}

    quote = protocol._pricing.quote(asset_id, asset.supply)
    reserve, _cur_supply = protocol._pricing._get_state(asset_id)
    return {
        "asset_id": quote.asset_id,
        "price_oas": quote.price_oas,
        "supply": quote.supply,
        "reserve": reserve,
        "cw": protocol._pricing._reserve_ratio,
    }


def bridge_buy(asset_id: str, buyer: str, amount: float = 10.0, ledger: "Any" = None) -> dict:
    """Execute a buy via the oasyce_core protocol (Bancor curve + deflationary settlement).

    Args:
        asset_id: Asset to purchase.
        buyer: Buyer address.
        amount: OAS to spend (default 10.0).
        ledger: Optional Ledger instance for persisting transaction + shares.

    Returns:
        Dict with trade details, or ``{"error": ...}`` if the asset is not found.
    """
    protocol = _get_protocol()
    buy_result = protocol.buy_asset(asset_id, buyer=buyer, amount=amount)

    if buy_result is None:
        return {"error": f"Asset {asset_id} not found or not tradeable in core registry"}

    tokens = buy_result.tokens_received
    price_oas = amount / tokens if tokens > 0 else amount

    asset = protocol.get_asset(asset_id)
    tx_id = uuid.uuid4().hex
    result: dict = {
        "asset_id": asset_id,
        "buyer": buyer,
        "price_oas": price_oas,
        "tokens_received": tokens,
        "supply": asset.supply if asset else None,
        "settled": True,
        "tx_id": tx_id,
    }

    if buy_result.split:
        result["split"] = {
            "creator": buy_result.split.creator,
            "protocol_burn": buy_result.split.protocol_burn,
            "protocol_validator": buy_result.split.protocol_validator,
            "router": buy_result.split.router,
        }

    # Persist to SQLite ledger
    if ledger is not None:
        ledger.record_tx(
            tx_type="buy",
            asset_id=asset_id,
            from_addr=buyer,
            amount=amount,
            metadata=result,
        )
        ledger.update_shares(buyer, asset_id, tokens)

    return result


def bridge_stake(validator_id: str, amount: float, ledger: "Any" = None, staker: str = "default") -> float:
    """Stake OAS for a validator via the protocol.

    Args:
        validator_id: Validator to stake for.
        amount: OAS amount to stake.
        ledger: Optional Ledger instance for persisting stake.
        staker: Staker address (default "default").

    Returns:
        New total staked amount for the validator.
    """
    protocol = _get_protocol()
    total = protocol.stake(validator_id, amount)

    if ledger is not None:
        ledger.record_tx(
            tx_type="stake",
            from_addr=staker,
            to_addr=validator_id,
            amount=amount,
        )
        ledger.update_stake(validator_id, staker, amount)

    return total


def bridge_get_shares(owner: str, ledger: "Any" = None) -> list:
    """Return all share holdings for *owner* via the protocol.

    When a ledger is provided, the protocol result is authoritative but
    ledger records are available for audit.
    """
    protocol = _get_protocol()
    return protocol.get_shares(owner)

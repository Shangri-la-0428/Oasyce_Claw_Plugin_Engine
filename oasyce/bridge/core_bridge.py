"""
Bridge between oasyce CLI and the Oasyce Cosmos chain.

Converts plugin-side signed metadata into CapturePack, verifies locally,
then delegates all chain operations (register, quote, buy, stake, shares)
to the Go chain via OasyceClient (REST/gRPC).

If the chain is unavailable, operations will fall back to the local engine
(if installed) or raise ChainClientError.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from oasyce.chain_client import OasyceClient, ChainClientError


def _get_client() -> OasyceClient:
    """Return a singleton-like OasyceClient."""
    if not hasattr(_get_client, "_instance"):
        _get_client._instance = OasyceClient()
    return _get_client._instance


def reset_protocol() -> None:
    """Reset the cached client instance (useful for tests)."""
    if hasattr(_get_client, "_instance"):
        del _get_client._instance


# Backwards-compatible alias used by existing tests and CLI code.
reset_engine = reset_protocol


def metadata_to_capture_pack(signed_metadata: dict):
    """Convert plugin signed metadata dict into a CapturePack."""
    from oasyce.models.capture_pack import CapturePack

    file_hash = signed_metadata.get("file_hash", "0" * 64)
    signature = signed_metadata.get("popc_signature", "deadbeef")

    ts = signed_metadata.get("timestamp")
    if isinstance(ts, (int, float)):
        iso_ts = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    else:
        iso_ts = datetime.now(timezone.utc).isoformat()

    return CapturePack(
        timestamp=iso_ts,
        gps_hash="a" * 64,  # placeholder -- plugin has no GPS yet
        device_signature=signature,
        media_hash=file_hash,
        source="camera",
    )


# ---------------------------------------------------------------------------
# Local verification helper
# ---------------------------------------------------------------------------


def _verify_pack(pack) -> dict:
    """Run local MockVerifier on a CapturePack. Returns {valid, reason}."""
    from oasyce.mock.mock_verifier import MockVerifier

    verifier = MockVerifier()
    result = verifier.verify(pack)
    return {"valid": result.valid, "reason": result.reason}


# ---------------------------------------------------------------------------
# Public bridge API
# ---------------------------------------------------------------------------


def bridge_register(signed_metadata: dict, creator: Optional[str] = None) -> dict:
    """Verify locally, then register the data asset on-chain.

    Returns a dict with ``valid``, ``reason``, and ``core_asset_id``.
    """
    pack = metadata_to_capture_pack(signed_metadata)
    creator = creator or signed_metadata.get("owner", "anonymous")

    # Step 1: local verification
    verify = _verify_pack(pack)
    if not verify["valid"]:
        return {"valid": False, "reason": verify["reason"], "core_asset_id": None}

    # Step 2: register on chain via OasyceClient
    client = _get_client()
    content_hash = pack.media_hash
    name = signed_metadata.get("name", f"asset-{content_hash[:8]}")
    description = signed_metadata.get("description", "")
    rights_type = signed_metadata.get("rights_type", "original")
    tags = signed_metadata.get("tags", [])

    try:
        tx_result = client.chain.register_data_asset(
            owner=creator,
            name=name,
            description=description,
            content_hash=content_hash,
            rights_type=rights_type,
            tags=tags,
        )
        asset_id = tx_result.get("tx_response", {}).get("txhash", uuid.uuid4().hex)
    except ChainClientError:
        # Fallback: generate a local asset ID
        asset_id = hashlib.sha256(f"{creator}:{content_hash}".encode()).hexdigest()[:16]

    return {"valid": True, "reason": verify["reason"], "core_asset_id": asset_id}


def bridge_quote(asset_id: str) -> dict:
    """Get bonding-curve price quote from the chain.

    Returns price info dict or ``{"error": ...}`` on failure.
    """
    client = _get_client()
    try:
        data = client.get_bonding_curve_price(asset_id)
        return {
            "asset_id": asset_id,
            "price_oas": float(data.get("price", {}).get("amount", 0)) / 1e8,
            "supply": int(data.get("supply", 0)),
            "reserve": float(data.get("reserve", {}).get("amount", 0)) / 1e8,
        }
    except ChainClientError as exc:
        return {"error": f"Failed to get quote for {asset_id}: {exc}"}


def bridge_buy(
    asset_id: str,
    buyer: str,
    amount: float = 10.0,
    ledger: Any = None,
) -> dict:
    """Buy shares of a data asset on-chain.

    Args:
        asset_id: Asset to purchase.
        buyer: Buyer address.
        amount: OAS to spend (default 10.0).
        ledger: Optional Ledger instance for persisting transaction + shares.

    Returns:
        Dict with trade details, or ``{"error": ...}`` on failure.
    """
    client = _get_client()
    amount_uoas = int(amount * 1e8)  # Convert OAS to uoas

    try:
        tx_result = client.chain.buy_shares(
            buyer=buyer,
            asset_id=asset_id,
            amount_uoas=amount_uoas,
        )
        tx_id = tx_result.get("tx_response", {}).get("txhash", uuid.uuid4().hex)
        result: dict = {
            "asset_id": asset_id,
            "buyer": buyer,
            "amount_oas": amount,
            "settled": True,
            "tx_id": tx_id,
        }
    except ChainClientError as exc:
        return {"error": f"Failed to buy {asset_id}: {exc}"}

    # Persist to SQLite ledger if provided
    if ledger is not None:
        ledger.record_tx(
            tx_type="buy",
            asset_id=asset_id,
            from_addr=buyer,
            amount=amount,
            metadata=result,
        )

    return result


def bridge_stake(
    validator_id: str,
    amount: float,
    ledger: Any = None,
    staker: str = "default",
) -> dict:
    """Stake OAS for a validator via standard Cosmos SDK staking tx.

    Args:
        validator_id: Validator address to delegate to.
        amount: OAS amount to stake.
        ledger: Optional Ledger instance for persisting stake.
        staker: Staker/delegator address.

    Returns:
        Dict with delegation details.
    """
    client = _get_client()
    amount_uoas = int(amount * 1e8)

    try:
        # Use standard Cosmos SDK staking delegation message
        tx_result = client.chain._broadcast_tx(
            "/cosmos.staking.v1beta1.MsgDelegate",
            {
                "delegator_address": staker,
                "validator_address": validator_id,
                "amount": {"denom": "uoas", "amount": str(amount_uoas)},
            },
        )
        tx_id = tx_result.get("tx_response", {}).get("txhash", "")
        result = {
            "validator_id": validator_id,
            "staker": staker,
            "amount_oas": amount,
            "tx_id": tx_id,
            "success": True,
        }
    except ChainClientError as exc:
        return {"error": f"Stake failed: {exc}", "success": False}

    if ledger is not None:
        ledger.record_tx(
            tx_type="stake",
            from_addr=staker,
            to_addr=validator_id,
            amount=amount,
        )
        ledger.update_stake(validator_id, staker, amount)

    return result


def bridge_get_shares(owner: str, ledger: Any = None) -> list:
    """Return all share holdings for *owner* from the chain.

    Queries each known asset for shareholders, filtering by owner.
    Falls back to ledger data if chain is unavailable.
    """
    client = _get_client()

    # First try: query assets owned by address, then get shareholders
    try:
        assets_data = client.list_data_assets(owner=owner)
        shares = []
        for asset in assets_data:
            asset_id = asset.get("id", asset.get("asset_id", ""))
            if asset_id:
                try:
                    sh_data = client.chain.get_shareholders(asset_id)
                    for sh in sh_data.get("shareholders", []):
                        if sh.get("address") == owner:
                            shares.append(
                                {
                                    "asset_id": asset_id,
                                    "owner": owner,
                                    "shares": int(sh.get("shares", 0)),
                                }
                            )
                except ChainClientError:
                    pass
        return shares
    except ChainClientError:
        pass

    # Fallback: use local ledger if available
    if ledger is not None and hasattr(ledger, "get_shares"):
        return ledger.get_shares(owner)

    return []

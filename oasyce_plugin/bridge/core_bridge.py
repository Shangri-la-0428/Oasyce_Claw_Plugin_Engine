"""
Bridge between oasyce_plugin CLI and oasyce_core engine.

Converts plugin-side signed metadata into CapturePack for oasyce_core,
and exposes quote/buy via OasyceEngine.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add oasyce_core to sys.path
_CORE_PATH = str(Path.home() / "Desktop" / "Oasyce_Project" / "oasyce_core")
if _CORE_PATH not in sys.path:
    sys.path.insert(0, str(Path(_CORE_PATH).parent))

from oasyce_core.engine import OasyceEngine
from oasyce_core.models.capture_pack import CapturePack


def _get_engine() -> OasyceEngine:
    """Return a singleton-like OasyceEngine (mock mode)."""
    if not hasattr(_get_engine, "_instance"):
        _get_engine._instance = OasyceEngine()
    return _get_engine._instance


def reset_engine() -> None:
    """Reset the cached engine (useful for tests)."""
    if hasattr(_get_engine, "_instance"):
        del _get_engine._instance


def metadata_to_capture_pack(signed_metadata: dict) -> CapturePack:
    """Convert plugin signed metadata dict into a CapturePack for oasyce_core."""
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


def bridge_register(signed_metadata: dict, creator: Optional[str] = None) -> dict:
    """Submit signed metadata through oasyce_core verify+register pipeline.

    Returns dict with verify_result and asset_id from oasyce_core.
    """
    engine = _get_engine()
    pack = metadata_to_capture_pack(signed_metadata)
    creator = creator or signed_metadata.get("owner", "anonymous")

    verify_result, asset_id = engine.submit(pack, creator=creator)
    return {
        "valid": verify_result.valid,
        "reason": verify_result.reason,
        "core_asset_id": asset_id,
    }


def bridge_quote(asset_id: str) -> dict:
    """Get price quote from oasyce_core pricing engine."""
    engine = _get_engine()
    asset = engine.cfg.registry.get(asset_id)
    if asset is None:
        return {"error": f"Asset {asset_id} not found in core registry"}

    quote = engine.cfg.pricing.quote(asset_id, asset.supply)
    return {
        "asset_id": quote.asset_id,
        "price_oas": quote.price_oas,
        "supply": quote.supply,
    }


def bridge_buy(asset_id: str, buyer: str) -> dict:
    """Execute buy via oasyce_core engine."""
    engine = _get_engine()
    quote, settle = engine.buy(asset_id, buyer=buyer)

    if quote is None:
        return {"error": f"Asset {asset_id} not found in core registry"}

    result = {
        "asset_id": asset_id,
        "buyer": buyer,
        "price_oas": quote.price_oas,
        "supply": quote.supply,
        "settled": settle.success if settle else False,
        "tx_id": settle.tx_id if settle else None,
    }
    if settle and settle.split:
        result["split"] = {
            "creator": settle.split.creator,
            "protocol_burn": settle.split.protocol_burn,
            "protocol_validator": settle.split.protocol_validator,
            "router": settle.split.router,
        }
    return result

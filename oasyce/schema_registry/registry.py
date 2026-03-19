"""Unified registration entry point."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from ..engines.result import Result, err, ok
from .types import AssetType
from .validation import validate


def register(
    asset_type: Union[str, AssetType],
    payload: Dict[str, Any],
    version: int = 1,
) -> Result[Dict]:
    """Validate and stamp a payload with its asset_type.

    Returns the payload with `asset_type` field set on success.
    """
    result = validate(asset_type, payload, version)
    if not result.ok:
        return err(result.error or "Validation failed", code=result.code)

    # Coerce to enum for stamping
    if isinstance(asset_type, str):
        asset_type = AssetType(asset_type)

    stamped = dict(payload)
    stamped["asset_type"] = asset_type.value
    return ok(stamped)

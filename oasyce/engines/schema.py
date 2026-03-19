"""Metadata validation — delegates to schema_registry.

.. deprecated::
    Use ``oasyce.schema_registry.validate("data", payload)`` directly.
    This module is kept for backward compatibility.
"""

from __future__ import annotations

import re
import warnings
from typing import Any, Dict, List

from .result import Result, err, ok

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SIG_RE = re.compile(r"^[0-9a-f]{128}$")
ASSET_RE = re.compile(r"^OAS_[0-9A-F]{8}$")


def validate_metadata(metadata: Dict[str, Any], require_signature: bool = False) -> Result[bool]:
    """Validate data-asset metadata.

    .. deprecated:: Use schema_registry.validate("data", metadata) instead.
    """
    from oasyce.schema_registry import validate as sr_validate

    result = sr_validate("data", metadata)
    if not result.ok:
        # Map schema_registry error codes to legacy codes for compatibility
        legacy_code = result.code
        error_msg = result.error or ""
        if "Missing required field" in error_msg:
            legacy_code = "MISSING_FIELD"
        elif "UNKNOWN_ASSET_TYPE" in (result.code or ""):
            legacy_code = "INVALID_METADATA"
        elif "INVALID_PAYLOAD" in (result.code or ""):
            legacy_code = "INVALID_METADATA"
        else:
            legacy_code = "INVALID_FIELD"
        return err(error_msg, code=legacy_code)

    # Signature check (not part of schema_registry basic validation)
    if require_signature:
        if "popc_signature" not in metadata:
            return err("Missing popc_signature", code="MISSING_SIGNATURE")
        sig = metadata.get("popc_signature")
        if not isinstance(sig, str) or not SIG_RE.match(sig):
            return err("popc_signature format invalid", code="INVALID_FIELD")

    return ok(True)

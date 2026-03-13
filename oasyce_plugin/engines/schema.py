from __future__ import annotations

import re
from typing import Any, Dict, List

from .result import Result, err, ok

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
SIG_RE = re.compile(r"^[0-9a-f]{128}$")
ASSET_RE = re.compile(r"^OAS_[0-9A-F]{8}$")


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def validate_metadata(metadata: Dict[str, Any], require_signature: bool = False) -> Result[bool]:
    if not isinstance(metadata, dict):
        return err("Metadata must be a dict", code="INVALID_METADATA")

    required_keys = [
        "schema_version",
        "engine_version",
        "asset_id",
        "filename",
        "owner",
        "tags",
        "timestamp",
        "file_size_bytes",
        "file_hash",
        "hash_algo",
    ]

    for key in required_keys:
        if key not in metadata:
            return err(f"Missing field: {key}", code="MISSING_FIELD")

    if not isinstance(metadata["schema_version"], int):
        return err("schema_version must be int", code="INVALID_FIELD")
    if not isinstance(metadata["engine_version"], str):
        return err("engine_version must be str", code="INVALID_FIELD")
    if not isinstance(metadata["asset_id"], str) or not ASSET_RE.match(metadata["asset_id"]):
        return err("asset_id format invalid", code="INVALID_FIELD")
    if not isinstance(metadata["filename"], str) or not metadata["filename"]:
        return err("filename must be non-empty str", code="INVALID_FIELD")
    if not isinstance(metadata["owner"], str) or not metadata["owner"]:
        return err("owner must be non-empty str", code="INVALID_FIELD")
    if not _is_str_list(metadata["tags"]):
        return err("tags must be list[str]", code="INVALID_FIELD")
    if not isinstance(metadata["timestamp"], int):
        return err("timestamp must be int", code="INVALID_FIELD")
    if not isinstance(metadata["file_size_bytes"], int):
        return err("file_size_bytes must be int", code="INVALID_FIELD")
    if not isinstance(metadata["file_hash"], str) or not HASH_RE.match(metadata["file_hash"]):
        return err("file_hash must be 64-char hex", code="INVALID_FIELD")
    if metadata.get("hash_algo") != "sha256":
        return err("hash_algo must be sha256", code="INVALID_FIELD")

    if require_signature:
        if "popc_signature" not in metadata:
            return err("Missing popc_signature", code="MISSING_SIGNATURE")
        if not isinstance(metadata.get("popc_signature"), str) or not SIG_RE.match(metadata["popc_signature"]):
            return err("popc_signature format invalid", code="INVALID_FIELD")

    return ok(True)

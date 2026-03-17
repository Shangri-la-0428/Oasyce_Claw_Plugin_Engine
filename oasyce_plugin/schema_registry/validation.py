"""Schema validation logic."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from ..engines.result import Result, err, ok
from .schemas import get_schema
from .types import AssetType, SchemaVersion


def validate(
    asset_type: Union[str, AssetType],
    payload: Dict[str, Any],
    version: int = 1,
) -> Result[bool]:
    """Validate a payload against a registered schema.

    Collects all errors and returns them at once.
    """
    if not isinstance(payload, dict):
        return err("Payload must be a dict", code="INVALID_PAYLOAD")

    # Coerce string to AssetType
    if isinstance(asset_type, str):
        try:
            asset_type = AssetType(asset_type)
        except ValueError:
            return err(
                f"Unknown asset type: {asset_type}",
                code="UNKNOWN_ASSET_TYPE",
            )

    schema = get_schema(asset_type, version)
    if schema is None:
        return err(
            f"No schema for {asset_type.value}/v{version}",
            code="SCHEMA_NOT_FOUND",
        )

    errors: List[str] = []
    field_map = schema.field_map()

    # Check required fields
    for spec in schema.fields:
        if spec.required and spec.name not in payload:
            errors.append(f"Missing required field: {spec.name}")

    # Validate present fields
    for key, value in payload.items():
        spec = field_map.get(key)
        if spec is None:
            continue  # extra fields are allowed
        if value is None and not spec.required:
            continue
        field_errors = spec.validate_value(value)
        errors.extend(field_errors)

    if errors:
        return err("; ".join(errors), code="VALIDATION_FAILED")

    return ok(True)

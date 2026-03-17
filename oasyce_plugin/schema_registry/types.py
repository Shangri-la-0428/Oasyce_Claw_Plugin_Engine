"""Schema registry core types."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Type


class AssetType(str, Enum):
    DATA = "data"
    CAPABILITY = "capability"
    ORACLE = "oracle"
    IDENTITY = "identity"


@dataclass(frozen=True)
class FieldSpec:
    """Specification for a single field in a schema."""
    name: str
    type: Type
    required: bool = True
    default: Any = None
    regex: Optional[str] = None
    item_type: Optional[Type] = None  # for list fields

    def validate_value(self, value: Any) -> List[str]:
        """Validate a single value against this spec. Returns list of errors."""
        errors: List[str] = []

        if self.type is list:
            if not isinstance(value, list):
                errors.append(f"{self.name}: expected list, got {type(value).__name__}")
            elif self.item_type:
                for i, item in enumerate(value):
                    if not isinstance(item, self.item_type):
                        errors.append(
                            f"{self.name}[{i}]: expected {self.item_type.__name__}, "
                            f"got {type(item).__name__}"
                        )
        elif not isinstance(value, self.type):
            errors.append(
                f"{self.name}: expected {self.type.__name__}, got {type(value).__name__}"
            )

        if self.regex and isinstance(value, str):
            if not re.match(self.regex, value):
                errors.append(f"{self.name}: does not match pattern {self.regex}")

        return errors


@dataclass(frozen=True)
class SchemaVersion:
    """A versioned schema definition."""
    asset_type: AssetType
    version: int
    fields: tuple  # tuple of FieldSpec (frozen-compatible)

    def field_map(self) -> dict:
        return {f.name: f for f in self.fields}

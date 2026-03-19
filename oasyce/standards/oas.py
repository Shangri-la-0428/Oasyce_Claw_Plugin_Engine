"""
OAS: Oasyce Asset Standard (Unified)

Extends OAS-DAS with asset_type discriminator to support multiple
asset types under one standard.

  asset_type = 'data'       → OasDasAsset (Phase 1)
  asset_type = 'capability' → OasAsset with CapabilityInterfaceLayer (Phase 2)
  asset_type = 'oracle'     → OasAsset with OracleLayer (Phase 2.5)
  asset_type = 'identity'   → OasAsset with IdentityExtLayer (Phase 2.5)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# Re-export everything from OAS-DAS for backward compat
from oasyce.standards.oas_das import (
    OriginType,
    IdentityLayer,
    MetadataLayer,
    AccessPolicyLayer,
    ComputeInterfaceLayer,
    ProvenanceLayer,
    OasDasAsset,
    _VALID_RISK_LEVELS,
    _VALID_ACCESS_LEVELS,
    _VALID_PRICE_MODELS,
    _VALID_LICENSE_TYPES,
    _VALID_ORIGIN_TYPES,
)


class AssetType(str, enum.Enum):
    """Asset type discriminator."""

    DATA = "data"
    CAPABILITY = "capability"
    ORACLE = "oracle"
    IDENTITY = "identity"


@dataclass
class CapabilityInterfaceLayer:
    """Interface definition for capability assets.

    Defines the input/output contract and execution constraints
    for a callable agent service.
    """

    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    execution_limits: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        """Validate schemas. Returns list of error messages."""
        errors: List[str] = []
        for name, schema in [
            ("input_schema", self.input_schema),
            ("output_schema", self.output_schema),
        ]:
            if schema and not isinstance(schema, dict):
                errors.append(f"{name} must be a dict")
            elif schema and "type" not in schema:
                errors.append(f"{name} must have a 'type' key")
        return errors


@dataclass
class OasAsset:
    """Unified Oasyce Asset Standard.

    Wraps OasDasAsset for data assets and adds capability, oracle,
    and identity support. The asset_type field discriminates between them.
    """

    asset_type: str = AssetType.DATA.value
    identity: Optional[IdentityLayer] = None
    metadata: Optional[MetadataLayer] = None
    access_policy: Optional[AccessPolicyLayer] = None
    compute_interface: Optional[ComputeInterfaceLayer] = None
    provenance: Optional[ProvenanceLayer] = None
    capability_interface: Optional[CapabilityInterfaceLayer] = None
    oracle_layer: Optional[Any] = None  # OracleLayer (lazy import to avoid circular)
    identity_ext_layer: Optional[Any] = None  # IdentityExtLayer (lazy import)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result: Dict[str, Any] = {"asset_type": self.asset_type}
        if self.identity:
            result["identity"] = asdict(self.identity)
        if self.metadata:
            result["metadata"] = asdict(self.metadata)
        if self.access_policy:
            result["access_policy"] = asdict(self.access_policy)
        if self.compute_interface:
            result["compute_interface"] = asdict(self.compute_interface)
        if self.provenance:
            result["provenance"] = asdict(self.provenance)
        if self.capability_interface:
            result["capability_interface"] = asdict(self.capability_interface)
        if self.oracle_layer:
            result["oracle_layer"] = asdict(self.oracle_layer)
        if self.identity_ext_layer:
            result["identity_ext_layer"] = asdict(self.identity_ext_layer)
        return result

    @classmethod
    def from_das(cls, das: OasDasAsset) -> OasAsset:
        """Create a unified asset from an existing OasDasAsset."""
        return cls(
            asset_type=AssetType.DATA.value,
            identity=das.identity,
            metadata=das.metadata,
            access_policy=das.access_policy,
            compute_interface=das.compute_interface,
            provenance=das.provenance,
        )

    def to_das(self) -> OasDasAsset:
        """Convert back to OasDasAsset (data assets only)."""
        if self.asset_type != AssetType.DATA.value:
            raise ValueError("Cannot convert capability asset to OasDasAsset")
        return OasDasAsset(
            identity=self.identity or IdentityLayer(asset_id="", creator="", created_at=0),
            metadata=self.metadata or MetadataLayer(title=""),
            access_policy=self.access_policy or AccessPolicyLayer(),
            compute_interface=self.compute_interface or ComputeInterfaceLayer(),
            provenance=self.provenance or ProvenanceLayer(),
        )

    def validate(self) -> List[str]:
        """Validate the asset. Returns list of error messages."""
        errors: List[str] = []

        if self.asset_type not in {e.value for e in AssetType}:
            errors.append(
                f"asset_type '{self.asset_type}' must be one of " f"{[e.value for e in AssetType]}"
            )

        if self.asset_type == AssetType.CAPABILITY.value:
            if self.capability_interface:
                errors.extend(self.capability_interface.validate())
            else:
                errors.append("capability assets require capability_interface")

        if self.asset_type == AssetType.ORACLE.value:
            if self.oracle_layer:
                errors.extend(self.oracle_layer.validate())
            else:
                errors.append("oracle assets require oracle_layer")

        if self.asset_type == AssetType.IDENTITY.value:
            if self.identity_ext_layer:
                errors.extend(self.identity_ext_layer.validate())
            else:
                errors.append("identity assets require identity_ext_layer")

        return errors


__all__ = [
    # From oas_das
    "OriginType",
    "IdentityLayer",
    "MetadataLayer",
    "AccessPolicyLayer",
    "ComputeInterfaceLayer",
    "ProvenanceLayer",
    "OasDasAsset",
    # New unified
    "AssetType",
    "CapabilityInterfaceLayer",
    "OasAsset",
]

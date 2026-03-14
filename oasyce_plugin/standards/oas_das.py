"""
OAS-DAS: Oasyce Data Asset Standard

Five-layer schema that makes data assets machine-readable:
  Layer 1 - Identity: global unique ID, creator, timestamps
  Layer 2 - Metadata: descriptive information (title, tags, file info)
  Layer 3 - Access Policy: risk level, pricing, licensing, restrictions
  Layer 4 - Compute Interface: TEE execution parameters (L2)
  Layer 5 - Provenance: PoPC signatures, lineage, dedup vectors
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class IdentityLayer:
    """Layer 1: Asset Identity"""
    asset_id: str
    creator: str
    created_at: int
    version: str = "1.0"
    namespace: str = "oasyce"


@dataclass
class MetadataLayer:
    """Layer 2: Descriptive Metadata"""
    title: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    file_type: str = ""
    file_size_bytes: int = 0
    checksum_sha256: str = ""
    language: str = ""
    category: str = ""


@dataclass
class AccessPolicyLayer:
    """Layer 3: Access Policy"""
    risk_level: str = "public"
    max_access_level: str = "L3"
    price_model: str = "bonding_curve"
    license_type: str = "proprietary"
    geographic_restrictions: List[str] = field(default_factory=list)
    expiry_timestamp: Optional[int] = None


@dataclass
class ComputeInterfaceLayer:
    """Layer 4: Compute Interface (L2 TEE)"""
    supported_operations: List[str] = field(default_factory=list)
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    runtime: str = "python3"
    max_compute_seconds: int = 300
    memory_limit_mb: int = 1024


@dataclass
class ProvenanceLayer:
    """Layer 5: Provenance & Lineage"""
    popc_signature: Optional[str] = None
    certificate_issuer: Optional[str] = None
    parent_assets: List[str] = field(default_factory=list)
    fingerprint_id: Optional[str] = None
    semantic_vector: Optional[List[float]] = None


# Valid enum values for validation
_VALID_RISK_LEVELS = {"public", "low", "medium", "high", "critical"}
_VALID_ACCESS_LEVELS = {"L0", "L1", "L2", "L3"}
_VALID_PRICE_MODELS = {"bonding_curve", "free"}
_VALID_LICENSE_TYPES = {"proprietary", "cc-by", "cc-by-sa", "mit", "public-domain"}


@dataclass
class OasDasAsset:
    """Complete OAS-DAS Data Asset Standard"""
    identity: IdentityLayer
    metadata: MetadataLayer
    access_policy: AccessPolicyLayer
    compute_interface: ComputeInterfaceLayer = field(default_factory=ComputeInterfaceLayer)
    provenance: ProvenanceLayer = field(default_factory=ProvenanceLayer)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to nested dictionary."""
        return {
            "identity": asdict(self.identity),
            "metadata": asdict(self.metadata),
            "access_policy": asdict(self.access_policy),
            "compute_interface": asdict(self.compute_interface),
            "provenance": asdict(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OasDasAsset:
        """Deserialize from nested dictionary."""
        return cls(
            identity=IdentityLayer(**data["identity"]),
            metadata=MetadataLayer(**data["metadata"]),
            access_policy=AccessPolicyLayer(**data.get("access_policy", {})),
            compute_interface=ComputeInterfaceLayer(**data.get("compute_interface", {})),
            provenance=ProvenanceLayer(**data.get("provenance", {})),
        )

    @classmethod
    def from_asset_metadata(cls, meta: Any) -> OasDasAsset:
        """Convert from existing AssetMetadata dataclass.

        Args:
            meta: An AssetMetadata instance (from oasyce_plugin.models).
        """
        identity = IdentityLayer(
            asset_id=meta.asset_id,
            creator=meta.owner,
            created_at=meta.timestamp,
            version=meta.schema_version,
        )
        metadata = MetadataLayer(
            title=meta.filename,
            tags=list(meta.tags) if meta.tags else [],
            file_size_bytes=meta.file_size_bytes,
        )
        access_policy = AccessPolicyLayer(
            risk_level=meta.risk_level,
            max_access_level=meta.max_access_level,
        )
        compute_interface = ComputeInterfaceLayer()
        if meta.compute_interface:
            compute_interface.supported_operations = [meta.compute_interface]

        provenance = ProvenanceLayer(
            popc_signature=meta.popc_signature,
            certificate_issuer=meta.certificate_issuer,
            semantic_vector=meta.semantic_vector,
        )
        return cls(
            identity=identity,
            metadata=metadata,
            access_policy=access_policy,
            compute_interface=compute_interface,
            provenance=provenance,
        )

    def validate(self) -> List[str]:
        """Validate all required fields. Returns list of error messages (empty = valid)."""
        errors: List[str] = []

        # Identity layer — required fields
        if not self.identity.asset_id:
            errors.append("identity.asset_id is required")
        if not self.identity.creator:
            errors.append("identity.creator is required")
        if not self.identity.created_at:
            errors.append("identity.created_at is required")

        # Metadata layer — title required
        if not self.metadata.title:
            errors.append("metadata.title is required")

        # Access policy — enum validation
        if self.access_policy.risk_level not in _VALID_RISK_LEVELS:
            errors.append(
                f"access_policy.risk_level '{self.access_policy.risk_level}' "
                f"must be one of {sorted(_VALID_RISK_LEVELS)}"
            )
        if self.access_policy.max_access_level not in _VALID_ACCESS_LEVELS:
            errors.append(
                f"access_policy.max_access_level '{self.access_policy.max_access_level}' "
                f"must be one of {sorted(_VALID_ACCESS_LEVELS)}"
            )
        if self.access_policy.price_model not in _VALID_PRICE_MODELS:
            errors.append(
                f"access_policy.price_model '{self.access_policy.price_model}' "
                f"must be one of {sorted(_VALID_PRICE_MODELS)}"
            )
        if self.access_policy.license_type not in _VALID_LICENSE_TYPES:
            errors.append(
                f"access_policy.license_type '{self.access_policy.license_type}' "
                f"must be one of {sorted(_VALID_LICENSE_TYPES)}"
            )

        return errors

    def similarity(self, other: OasDasAsset) -> float:
        """Cosine similarity based on semantic_vector. Returns 0.0 if either vector is missing."""
        a = self.provenance.semantic_vector
        b = other.provenance.semantic_vector
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def is_duplicate(self, other: OasDasAsset, threshold: float = 0.9) -> bool:
        """Returns True if similarity > threshold."""
        return self.similarity(other) > threshold

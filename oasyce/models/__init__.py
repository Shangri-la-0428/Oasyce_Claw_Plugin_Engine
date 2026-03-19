"""Oasyce data models — plugin-side and core models merged."""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

# ─── Rights type constants ────────────────────────────────────
VALID_RIGHTS_TYPES = {"original", "co_creation", "licensed", "collection"}

RIGHTS_TYPE_MULTIPLIER: Dict[str, float] = {
    "original": 1.0,
    "co_creation": 0.9,
    "licensed": 0.7,
    "collection": 0.3,
}

# ─── Dispute resolution constants ────────────────────────────
VALID_REMEDY_TYPES = {"delist", "transfer", "rights_correction", "share_adjustment"}
VALID_DISPUTE_STATUSES = {"open", "resolved", "dismissed"}


@dataclass
class AssetMetadata:
    asset_id: str
    filename: str
    owner: str
    tags: List[str]
    timestamp: int
    file_size_bytes: int
    asset_type: str = "data"
    classification: Optional[Dict[str, Any]] = None
    popc_signature: Optional[str] = None
    certificate_issuer: Optional[str] = None
    schema_version: str = "1.0"
    risk_level: str = "public"
    max_access_level: str = "L3"
    compute_interface: Optional[str] = None
    semantic_vector: Optional[List[float]] = None
    rights_type: str = "original"
    co_creators: Optional[List[Dict[str, Any]]] = None
    disputed: bool = False
    dispute_reason: Optional[str] = None
    dispute_status: Optional[str] = None  # open / resolved / dismissed
    dispute_resolution: Optional[Dict[str, Any]] = None  # {remedy, details, resolved_at}
    delisted: bool = False


@dataclass
class EngineResult:
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


# Re-export core models
from oasyce.models.asset import Asset, AssetStatus  # noqa: E402, F401
from oasyce.models.capture_pack import CapturePack  # noqa: E402, F401
from oasyce.models.shares import ShareHolding, ShareRegistry  # noqa: E402, F401
from oasyce.models.transaction import Transaction  # noqa: E402, F401

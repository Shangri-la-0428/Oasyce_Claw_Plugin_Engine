from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class AssetMetadata:
    asset_id: str
    filename: str
    owner: str
    tags: List[str]
    timestamp: int
    file_size_bytes: int
    classification: Optional[Dict[str, Any]] = None
    popc_signature: Optional[str] = None
    certificate_issuer: Optional[str] = None
    schema_version: str = "1.0"
    risk_level: str = "public"
    max_access_level: str = "L3"
    compute_interface: Optional[str] = None
    semantic_vector: Optional[List[float]] = None

@dataclass
class EngineResult:
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

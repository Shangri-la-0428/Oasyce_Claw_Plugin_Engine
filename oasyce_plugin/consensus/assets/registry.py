"""
Asset definition registry — stores metadata about registered asset types.

The native OAS asset is always pre-registered. Additional assets (USDC,
DATA_CREDIT, CAPABILITY_TOKEN, or custom ones) can be registered at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from oasyce_plugin.consensus.core.types import ASSET_DECIMALS, KNOWN_ASSET_TYPES


@dataclass
class AssetDefinition:
    """Metadata describing a registered asset type."""
    asset_type: str
    name: str
    decimals: int
    issuer: str = ""       # issuer address (empty for native OAS)
    metadata: Dict = field(default_factory=dict)
    is_native: bool = False


class AssetRegistry:
    """In-memory registry of known asset types.

    Thread-safe via the owning ConsensusState's lock.
    """

    def __init__(self) -> None:
        self._assets: Dict[str, AssetDefinition] = {}
        # Pre-register native OAS
        self._assets["OAS"] = AssetDefinition(
            asset_type="OAS",
            name="Oasyce Token",
            decimals=ASSET_DECIMALS.get("OAS", 8),
            issuer="",
            is_native=True,
        )

    def register_asset(self, definition: AssetDefinition) -> Dict:
        """Register a new asset type. Returns result dict."""
        if definition.asset_type in self._assets:
            return {"ok": False, "error": f"asset type '{definition.asset_type}' already registered"}
        if not definition.asset_type:
            return {"ok": False, "error": "asset_type cannot be empty"}
        if definition.decimals < 0 or definition.decimals > 18:
            return {"ok": False, "error": "decimals must be 0-18"}
        self._assets[definition.asset_type] = definition
        return {"ok": True, "asset_type": definition.asset_type}

    def get_asset_info(self, asset_type: str) -> Optional[AssetDefinition]:
        """Look up an asset definition."""
        return self._assets.get(asset_type)

    def is_registered(self, asset_type: str) -> bool:
        return asset_type in self._assets

    def list_assets(self) -> List[AssetDefinition]:
        return list(self._assets.values())

    def to_dict_list(self) -> List[Dict]:
        """Serializable list for CLI / JSON output."""
        result = []
        for a in self._assets.values():
            result.append({
                "asset_type": a.asset_type,
                "name": a.name,
                "decimals": a.decimals,
                "issuer": a.issuer,
                "is_native": a.is_native,
                "metadata": a.metadata,
            })
        return result

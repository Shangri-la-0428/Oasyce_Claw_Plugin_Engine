from __future__ import annotations

from typing import Optional

from oasyce.interfaces.registry import IRegistry
from oasyce.models.asset import Asset


class MockRegistry(IRegistry):
    def __init__(self) -> None:
        self._store: dict[str, Asset] = {}

    def register(self, asset: Asset) -> str:
        self._store[asset.asset_id] = asset
        return asset.asset_id

    def get(self, asset_id: str) -> Optional[Asset]:
        return self._store.get(asset_id)

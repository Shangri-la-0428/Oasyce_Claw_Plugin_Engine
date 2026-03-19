from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from oasyce.models.asset import Asset


class IRegistry(ABC):
    @abstractmethod
    def register(self, asset: Asset) -> str:
        """Register an asset; return its asset_id."""
        ...

    @abstractmethod
    def get(self, asset_id: str) -> Optional[Asset]:
        """Retrieve an asset by id, or None."""
        ...

    def update_supply(self, asset_id: str, new_supply: int) -> None:
        """Persist updated supply count. Default: no-op (in-memory registries don't need it)."""
        pass

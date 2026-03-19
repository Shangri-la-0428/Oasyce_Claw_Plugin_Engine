"""Abstract ledger storage backend for the Oasyce chain database."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class LedgerBackend(ABC):
    """Abstract storage backend for the Oasyce ledger."""

    @abstractmethod
    def initialize(self) -> None:
        """Create tables if they don't exist."""
        ...

    @abstractmethod
    def store_block(self, block: Dict[str, Any]) -> None:
        """Persist a block."""
        ...

    @abstractmethod
    def get_block(self, block_hash: str) -> Optional[Dict[str, Any]]:
        """Retrieve a block by hash."""
        ...

    @abstractmethod
    def get_latest_block(self) -> Optional[Dict[str, Any]]:
        """Get the most recent block."""
        ...

    @abstractmethod
    def get_chain_length(self) -> int:
        """Return the number of blocks."""
        ...

    @abstractmethod
    def store_transaction(self, tx: Dict[str, Any]) -> None:
        """Persist a transaction record."""
        ...

    @abstractmethod
    def get_transactions(
        self, asset_id: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query transactions, optionally filtered by asset_id."""
        ...

    @abstractmethod
    def store_asset(self, asset: Dict[str, Any]) -> None:
        """Register an asset in the ledger."""
        ...

    @abstractmethod
    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve asset by ID."""
        ...

    @abstractmethod
    def search_assets(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search assets by keyword."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Clean up resources."""
        ...

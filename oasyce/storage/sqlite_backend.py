"""SQLite storage backend — thin adapter over the existing Ledger class."""

from typing import Any, Dict, List, Optional

from oasyce.storage.backend import LedgerBackend
from oasyce.storage.ledger import Ledger


class SqliteBackend(LedgerBackend):
    """Wraps the existing Ledger to implement LedgerBackend."""

    def __init__(self, db_path: str = ":memory:"):
        self._db_path = db_path
        self._ledger: Optional[Ledger] = None

    def initialize(self) -> None:
        self._ledger = Ledger(self._db_path)

    @property
    def ledger(self) -> Ledger:
        if self._ledger is None:
            raise RuntimeError("Backend not initialized — call initialize() first")
        return self._ledger

    def store_block(self, block: Dict[str, Any]) -> None:
        conn = self.ledger._conn
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO blocks
                    (block_number, block_hash, prev_hash, merkle_root, timestamp, tx_count, nonce)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    block.get("block_number", block.get("height", 0)),
                    block.get("block_hash"),
                    block.get("prev_hash"),
                    block.get("merkle_root"),
                    block.get("timestamp"),
                    block.get("tx_count", 0),
                    block.get("nonce", 0),
                ),
            )

    def get_block(self, block_hash: str) -> Optional[Dict[str, Any]]:
        row = self.ledger._conn.execute(
            "SELECT * FROM blocks WHERE block_hash = ?", (block_hash,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_latest_block(self) -> Optional[Dict[str, Any]]:
        return self.ledger.get_latest_block()

    def get_chain_length(self) -> int:
        return self.ledger.get_chain_height()

    def store_transaction(self, tx: Dict[str, Any]) -> None:
        self.ledger.record_tx(
            tx_type=tx.get("tx_type", "transfer"),
            asset_id=tx.get("asset_id"),
            from_addr=tx.get("from_addr", tx.get("seller")),
            to_addr=tx.get("to_addr", tx.get("buyer")),
            amount=tx.get("amount"),
            metadata=tx.get("metadata"),
            signature=tx.get("signature"),
        )

    def get_transactions(
        self, asset_id: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        conn = self.ledger._conn
        if asset_id:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE asset_id = ? ORDER BY created_at DESC LIMIT ?",
                (asset_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def store_asset(self, asset: Dict[str, Any]) -> None:
        self.ledger.register_asset(
            asset_id=asset.get("asset_id", ""),
            owner=asset.get("owner", ""),
            file_hash=asset.get("file_hash", ""),
            metadata=asset,
            popc_signature=asset.get("popc_signature", ""),
        )

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        return self.ledger.get_asset(asset_id)

    def search_assets(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        results = self.ledger.search_assets(query)
        return results[:limit]

    def close(self) -> None:
        if self._ledger is not None:
            self._ledger.close()
            self._ledger = None

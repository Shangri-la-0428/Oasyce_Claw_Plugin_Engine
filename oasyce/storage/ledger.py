"""
SQLite Ledger — local client-side storage for assets, transactions, shares.
"""

import hashlib
import json as _json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from oasyce.crypto.keys import sign as _sign_message
from oasyce.crypto.merkle import merkle_root


def _default_db_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".oasyce", "chain.db")


class Ledger:
    """SQLite ledger for local operation — caches chain state client-side."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _default_db_path()
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id        TEXT PRIMARY KEY,
                    owner           TEXT NOT NULL,
                    file_hash       TEXT NOT NULL,
                    metadata        TEXT NOT NULL,
                    popc_signature  TEXT,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    tx_id       TEXT PRIMARY KEY,
                    tx_type     TEXT NOT NULL,
                    asset_id    TEXT,
                    from_addr   TEXT,
                    to_addr     TEXT,
                    amount      REAL,
                    metadata    TEXT,
                    signature   TEXT,
                    block_number INTEGER,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS blocks (
                    block_number        INTEGER PRIMARY KEY,
                    block_hash          TEXT NOT NULL UNIQUE,
                    prev_hash           TEXT NOT NULL,
                    merkle_root         TEXT NOT NULL,
                    timestamp           TIMESTAMP NOT NULL,
                    tx_count            INTEGER NOT NULL,
                    nonce               INTEGER DEFAULT 0,
                    validator_signature TEXT,
                    validator_pubkey    TEXT
                );
                CREATE TABLE IF NOT EXISTS shares (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner       TEXT NOT NULL,
                    asset_id    TEXT NOT NULL,
                    amount      REAL NOT NULL,
                    UNIQUE(owner, asset_id)
                );
                CREATE TABLE IF NOT EXISTS stakes (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    validator_id    TEXT NOT NULL,
                    staker          TEXT NOT NULL,
                    amount          REAL NOT NULL,
                    UNIQUE(validator_id, staker)
                );
                CREATE TABLE IF NOT EXISTS fingerprints (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id    TEXT NOT NULL,
                    caller_id   TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    timestamp   INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fingerprint_records (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id    TEXT NOT NULL,
                    caller_id   TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    timestamp   INTEGER NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS asset_versions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id    TEXT NOT NULL,
                    version     INTEGER NOT NULL DEFAULT 1,
                    file_hash   TEXT NOT NULL,
                    prev_hash   TEXT,
                    metadata    TEXT,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(asset_id, version)
                );
            """
            )

    # ── Assets ─────────────────────────────────────────────────

    def register_asset(
        self, asset_id: str, owner: str, file_hash: str, metadata: dict, popc_signature: str = ""
    ) -> str:
        meta_json = _json.dumps(metadata, ensure_ascii=False)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO assets (asset_id, owner, file_hash, metadata, popc_signature) "
                "VALUES (?, ?, ?, ?, ?)",
                (asset_id, owner, file_hash, meta_json, popc_signature),
            )
        return asset_id

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("metadata"):
            d.update(_json.loads(d["metadata"]))
        return d

    def get_asset_metadata(self, asset_id: str) -> Optional[dict]:
        """Return parsed metadata dict for an asset, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT metadata FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if row is None:
            return None
        return _json.loads(row["metadata"]) if row["metadata"] else {}

    def set_asset_metadata(self, asset_id: str, metadata: dict) -> bool:
        """Replace the metadata JSON blob for an asset. Returns False if asset not found."""
        meta_json = _json.dumps(metadata, ensure_ascii=False)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE assets SET metadata = ? WHERE asset_id = ?",
                (meta_json, asset_id),
            )
        return cursor.rowcount > 0

    def update_asset_metadata(self, asset_id: str, updates: dict) -> bool:
        """Merge *updates* into existing metadata. Returns False if asset not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT metadata FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if row is None:
                return False
            meta = _json.loads(row["metadata"]) if row["metadata"] else {}
            meta.update(updates)
            meta_json = _json.dumps(meta, ensure_ascii=False)
            with self._conn:
                self._conn.execute(
                    "UPDATE assets SET metadata = ? WHERE asset_id = ?",
                    (meta_json, asset_id),
                )
        return True

    def update_asset_owner(self, asset_id: str, new_owner: str) -> bool:
        """Change the owner column for an asset. Returns False if asset not found."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE assets SET owner = ? WHERE asset_id = ?",
                (new_owner, asset_id),
            )
        return cursor.rowcount > 0

    def delete_asset(self, asset_id: str) -> bool:
        """Delete an asset and its fingerprint_records. Returns False if not found."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM assets WHERE asset_id = ?", (asset_id,)
            )
            if cursor.rowcount == 0:
                return False
            try:
                self._conn.execute(
                    "DELETE FROM fingerprint_records WHERE asset_id = ?", (asset_id,)
                )
            except Exception:
                pass  # table may not exist
        return True

    def search_assets(self, query: str) -> List[Dict[str, Any]]:
        with self._lock:
            if query:
                escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                rows = self._conn.execute(
                    "SELECT * FROM assets WHERE metadata LIKE ? ESCAPE '\\' "
                    "OR asset_id LIKE ? ESCAPE '\\' ORDER BY created_at DESC",
                    (f"%{escaped}%", f"%{escaped}%"),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM assets ORDER BY created_at DESC"
                ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("metadata"):
                try:
                    d.update(_json.loads(d["metadata"]))
                except _json.JSONDecodeError:
                    pass
            results.append(d)
        return results

    def count_assets(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM assets").fetchone()
        return row[0] if row else 0

    # ── Transactions ───────────────────────────────────────────

    def record_tx(
        self,
        tx_type: str,
        asset_id: str = "",
        from_addr: str = "",
        to_addr: str = "",
        amount: float = 0.0,
        metadata: dict = None,
        signature: str = "",
    ) -> str:
        tx_id = uuid.uuid4().hex
        meta_json = _json.dumps(metadata or {}, ensure_ascii=False)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO transactions (tx_id, tx_type, asset_id, from_addr, to_addr, amount, metadata, signature) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (tx_id, tx_type, asset_id, from_addr, to_addr, amount, meta_json, signature),
            )
        return tx_id

    def get_pending_transactions(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM transactions WHERE block_number IS NULL ORDER BY created_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_transaction(self, tx_id: str) -> Optional[Dict[str, Any]]:
        """Return a single transaction by ID, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM transactions WHERE tx_id = ?", (tx_id,)
            ).fetchone()
        return dict(row) if row else None

    def count_transactions(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
        return row[0] if row else 0

    # ── Blocks ─────────────────────────────────────────────────

    def create_block(
        self, validator_key: str = None, validator_pubkey: str = None
    ) -> Optional[Dict[str, Any]]:
        pending = self.get_pending_transactions()
        if not pending:
            return None
        height = self.get_chain_height()
        prev = self.get_block(height - 1) if height > 0 else None
        prev_hash = prev["block_hash"] if prev else "0" * 64
        tx_ids = [tx["tx_id"] for tx in pending]
        mr = merkle_root(tx_ids)
        now = datetime.now(timezone.utc).isoformat()
        block_data = f"{height}{prev_hash}{mr}{now}"
        block_hash = hashlib.sha256(block_data.encode()).hexdigest()

        signature = None
        if validator_key:
            signature = _sign_message(block_data.encode(), validator_key)

        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO blocks (block_number, block_hash, prev_hash, merkle_root, "
                "timestamp, tx_count, validator_signature, validator_pubkey) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (height, block_hash, prev_hash, mr, now, len(tx_ids), signature, validator_pubkey),
            )
            for tx_id in tx_ids:
                self._conn.execute(
                    "UPDATE transactions SET block_number = ? WHERE tx_id = ?",
                    (height, tx_id),
                )
        return {
            "block_number": height,
            "block_hash": block_hash,
            "prev_hash": prev_hash,
            "merkle_root": mr,
            "timestamp": now,
            "tx_count": len(tx_ids),
            "validator_signature": signature,
            "validator_pubkey": validator_pubkey,
        }

    def get_block(self, number: int, include_tx: bool = False) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM blocks WHERE block_number = ?", (number,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            if include_tx:
                txs = self._conn.execute(
                    "SELECT * FROM transactions WHERE block_number = ?", (number,)
                ).fetchall()
                d["transactions"] = [dict(t) for t in txs]
        return d

    def get_chain_height(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT MAX(block_number) FROM blocks").fetchone()
        if row is None or row[0] is None:
            return 0
        return row[0] + 1

    def insert_remote_block(self, block_data: dict) -> bool:
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO blocks (block_number, block_hash, prev_hash, merkle_root, "
                    "timestamp, tx_count, validator_signature, validator_pubkey) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        block_data["block_number"],
                        block_data["block_hash"],
                        block_data["prev_hash"],
                        block_data["merkle_root"],
                        block_data["timestamp"],
                        block_data.get("tx_count", 0),
                        block_data.get("validator_signature"),
                        block_data.get("validator_pubkey"),
                    ),
                )
            return True
        except Exception:
            return False

    def get_chain_from(self, start: int) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM blocks WHERE block_number >= ? ORDER BY block_number", (start,)
            ).fetchall()
        return [dict(r) for r in rows]

    def attempt_reorg(self, remote_chain: list) -> bool:
        if not remote_chain:
            return False
        local_height = self.get_chain_height()
        remote_height = len(remote_chain)
        if remote_height <= local_height:
            return False

        sorted_chain = sorted(remote_chain, key=lambda b: b["block_number"])
        for i, block in enumerate(sorted_chain):
            if i == 0:
                if block["block_number"] == 0 and block["prev_hash"] != "0" * 64:
                    return False
            else:
                if block["prev_hash"] != sorted_chain[i - 1]["block_hash"]:
                    return False

        with self._lock, self._conn:
            self._conn.execute("DELETE FROM blocks WHERE block_number >= ?", (0,))
            for block in sorted_chain:
                self._conn.execute(
                    "INSERT OR REPLACE INTO blocks (block_number, block_hash, prev_hash, merkle_root, "
                    "timestamp, tx_count, validator_signature, validator_pubkey) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        block["block_number"],
                        block["block_hash"],
                        block["prev_hash"],
                        block["merkle_root"],
                        block["timestamp"],
                        block.get("tx_count", 0),
                        block.get("validator_signature"),
                        block.get("validator_pubkey"),
                    ),
                )
        return True

    # ── Shares ─────────────────────────────────────────────────

    def update_shares(self, owner: str, asset_id: str, amount: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO shares (owner, asset_id, amount) VALUES (?, ?, ?) "
                "ON CONFLICT(owner, asset_id) DO UPDATE SET amount = amount + ?",
                (owner, asset_id, amount, amount),
            )

    def get_shares(self, owner: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM shares WHERE owner = ?", (owner,)).fetchall()
        return [dict(r) for r in rows]

    # ── Stakes ─────────────────────────────────────────────────

    def update_stake(self, validator_id: str, staker: str, amount: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO stakes (validator_id, staker, amount) VALUES (?, ?, ?) "
                "ON CONFLICT(validator_id, staker) DO UPDATE SET amount = amount + ?",
                (validator_id, staker, amount, amount),
            )

    def get_stakes(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM stakes").fetchall()
        return [dict(r) for r in rows]

    def get_validator_stake(self, validator_id: str) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT SUM(amount) FROM stakes WHERE validator_id = ?", (validator_id,)
            ).fetchone()
        return row[0] if row and row[0] else 0.0

    # ── Fingerprints ───────────────────────────────────────────

    def record_fingerprint(
        self, asset_id: str, caller_id: str, fingerprint: str, timestamp: int
    ) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO fingerprints (asset_id, caller_id, fingerprint, timestamp) "
                "VALUES (?, ?, ?, ?)",
                (asset_id, caller_id, fingerprint, timestamp),
            )
        return cursor.lastrowid

    def get_fingerprints(self, asset_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM fingerprints WHERE asset_id = ?", (asset_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def trace_fingerprint(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM fingerprints WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
        return dict(row) if row else None

    # ── Asset Versions ─────────────────────────────────────────

    def add_version(
        self, asset_id: str, file_hash: str, prev_hash: str = None, metadata: dict = None
    ) -> int:
        meta_json = _json.dumps(metadata or {}, ensure_ascii=False)
        with self._lock:
            current = self._conn.execute(
                "SELECT MAX(version) FROM asset_versions WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            next_ver = (current[0] or 0) + 1
            with self._conn:
                self._conn.execute(
                    "INSERT INTO asset_versions (asset_id, version, file_hash, prev_hash, metadata) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (asset_id, next_ver, file_hash, prev_hash, meta_json),
                )
        return next_ver

    def get_versions(self, asset_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM asset_versions WHERE asset_id = ? ORDER BY version", (asset_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Asset list ─────────────────────────────────────────────

    def list_assets(self, order_by: str = "created_at", desc: bool = True) -> list:
        """List all assets."""
        direction = "DESC" if desc else "ASC"
        # Whitelist column names to prevent SQL injection
        allowed = {"created_at", "asset_id", "owner"}
        col = order_by if order_by in allowed else "created_at"
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM assets ORDER BY {col} {direction}"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Fingerprint queries ───────────────────────────────────

    def count_fingerprints(self) -> int:
        """Count total fingerprint records."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM fingerprint_records").fetchone()
            return row["c"] if row else 0

    # ── Stakes queries ────────────────────────────────────────

    def get_stakes_summary(self) -> list:
        """Get stakes aggregated by validator."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT validator_id, SUM(amount) AS total FROM stakes GROUP BY validator_id"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Block queries ─────────────────────────────────────────

    def list_blocks(self, limit: int = 10, offset: int = 0) -> list:
        """List blocks with pagination, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM blocks ORDER BY block_number DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_asset_owner(self, asset_id: str) -> Optional[str]:
        """Return the owner of an asset, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT owner FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        return row["owner"] if row else None

    def reconnect(self) -> None:
        """Re-open the connection for multi-threaded use."""
        import sqlite3
        self._conn.close()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    # ── Utility ────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()

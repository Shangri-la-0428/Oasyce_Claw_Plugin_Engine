"""
SQLite Ledger — re-exports from oasyce_core if available,
otherwise provides a minimal built-in implementation.
"""

try:
    from oasyce_core.storage.ledger import *  # noqa: F401,F403
    from oasyce_core.storage.ledger import Ledger
except ImportError:
    # Minimal built-in Ledger for local-only operation without oasyce_core.
    import hashlib
    import json as _json
    import os
    import sqlite3
    import uuid
    from datetime import datetime, timezone
    from typing import Any, Dict, List, Optional

    from oasyce_plugin.crypto.merkle import merkle_root

    def _default_db_path() -> str:
        return os.path.join(os.path.expanduser("~"), ".oasyce", "chain.db")

    class Ledger:
        """Minimal SQLite ledger for local operation without oasyce_core."""

        def __init__(self, db_path: Optional[str] = None):
            self.db_path = db_path or _default_db_path()
            if self.db_path != ":memory:":
                os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._create_tables()

        def _create_tables(self) -> None:
            with self._conn:
                self._conn.executescript("""
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
                        block_number    INTEGER PRIMARY KEY,
                        block_hash      TEXT NOT NULL UNIQUE,
                        prev_hash       TEXT NOT NULL,
                        merkle_root     TEXT NOT NULL,
                        timestamp       TIMESTAMP NOT NULL,
                        tx_count        INTEGER NOT NULL,
                        nonce           INTEGER DEFAULT 0
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
                """)

        # ── Assets ─────────────────────────────────────────────────

        def register_asset(self, asset_id: str, owner: str, file_hash: str,
                           metadata: dict, popc_signature: str = "") -> str:
            meta_json = _json.dumps(metadata, ensure_ascii=False)
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO assets (asset_id, owner, file_hash, metadata, popc_signature) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (asset_id, owner, file_hash, meta_json, popc_signature),
                )
            return asset_id

        def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
            row = self._conn.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            if d.get("metadata"):
                d.update(_json.loads(d["metadata"]))
            return d

        def search_assets(self, query: str) -> List[Dict[str, Any]]:
            if query:
                rows = self._conn.execute(
                    "SELECT * FROM assets WHERE metadata LIKE ? OR asset_id LIKE ? ORDER BY created_at DESC",
                    (f"%{query}%", f"%{query}%"),
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
            row = self._conn.execute("SELECT COUNT(*) FROM assets").fetchone()
            return row[0] if row else 0

        # ── Transactions ───────────────────────────────────────────

        def record_tx(self, tx_type: str, asset_id: str = "",
                      from_addr: str = "", to_addr: str = "",
                      amount: float = 0.0, metadata: dict = None,
                      signature: str = "") -> str:
            tx_id = uuid.uuid4().hex
            meta_json = _json.dumps(metadata or {}, ensure_ascii=False)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO transactions (tx_id, tx_type, asset_id, from_addr, to_addr, amount, metadata, signature) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (tx_id, tx_type, asset_id, from_addr, to_addr, amount, meta_json, signature),
                )
            return tx_id

        def get_pending_transactions(self) -> List[Dict[str, Any]]:
            rows = self._conn.execute(
                "SELECT * FROM transactions WHERE block_number IS NULL ORDER BY created_at"
            ).fetchall()
            return [dict(r) for r in rows]

        def count_transactions(self) -> int:
            row = self._conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
            return row[0] if row else 0

        # ── Blocks ─────────────────────────────────────────────────

        def create_block(self) -> Optional[Dict[str, Any]]:
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
            with self._conn:
                self._conn.execute(
                    "INSERT INTO blocks (block_number, block_hash, prev_hash, merkle_root, timestamp, tx_count) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (height, block_hash, prev_hash, mr, now, len(tx_ids)),
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
            }

        def get_block(self, number: int, include_tx: bool = False) -> Optional[Dict[str, Any]]:
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
            row = self._conn.execute("SELECT MAX(block_number) FROM blocks").fetchone()
            if row is None or row[0] is None:
                return 0
            return row[0] + 1

        def insert_remote_block(self, block_data: dict) -> bool:
            try:
                with self._conn:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO blocks (block_number, block_hash, prev_hash, merkle_root, timestamp, tx_count) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (block_data["block_number"], block_data["block_hash"],
                         block_data["prev_hash"], block_data["merkle_root"],
                         block_data["timestamp"], block_data.get("tx_count", 0)),
                    )
                return True
            except Exception:
                return False

        def get_chain_from(self, start: int) -> List[Dict[str, Any]]:
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
            with self._conn:
                self._conn.execute("DELETE FROM blocks WHERE block_number >= ?", (0,))
                for block in remote_chain:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO blocks (block_number, block_hash, prev_hash, merkle_root, timestamp, tx_count) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (block["block_number"], block["block_hash"],
                         block["prev_hash"], block["merkle_root"],
                         block["timestamp"], block.get("tx_count", 0)),
                    )
            return True

        # ── Shares ─────────────────────────────────────────────────

        def update_shares(self, owner: str, asset_id: str, amount: float) -> None:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO shares (owner, asset_id, amount) VALUES (?, ?, ?) "
                    "ON CONFLICT(owner, asset_id) DO UPDATE SET amount = amount + ?",
                    (owner, asset_id, amount, amount),
                )

        def get_shares(self, owner: str) -> List[Dict[str, Any]]:
            rows = self._conn.execute(
                "SELECT * FROM shares WHERE owner = ?", (owner,)
            ).fetchall()
            return [dict(r) for r in rows]

        # ── Stakes ─────────────────────────────────────────────────

        def update_stake(self, validator_id: str, staker: str, amount: float) -> None:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO stakes (validator_id, staker, amount) VALUES (?, ?, ?) "
                    "ON CONFLICT(validator_id, staker) DO UPDATE SET amount = amount + ?",
                    (validator_id, staker, amount, amount),
                )

        def get_stakes(self) -> List[Dict[str, Any]]:
            rows = self._conn.execute("SELECT * FROM stakes").fetchall()
            return [dict(r) for r in rows]

        def get_validator_stake(self, validator_id: str) -> float:
            row = self._conn.execute(
                "SELECT SUM(amount) FROM stakes WHERE validator_id = ?", (validator_id,)
            ).fetchone()
            return row[0] if row and row[0] else 0.0

        # ── Fingerprints ───────────────────────────────────────────

        def record_fingerprint(self, asset_id: str, caller_id: str,
                               fingerprint: str, timestamp: int) -> int:
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO fingerprints (asset_id, caller_id, fingerprint, timestamp) "
                    "VALUES (?, ?, ?, ?)",
                    (asset_id, caller_id, fingerprint, timestamp),
                )
            return cursor.lastrowid

        def get_fingerprints(self, asset_id: str) -> List[Dict[str, Any]]:
            rows = self._conn.execute(
                "SELECT * FROM fingerprints WHERE asset_id = ?", (asset_id,)
            ).fetchall()
            return [dict(r) for r in rows]

        def trace_fingerprint(self, fingerprint: str) -> Optional[Dict[str, Any]]:
            row = self._conn.execute(
                "SELECT * FROM fingerprints WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            return dict(row) if row else None

        # ── Asset Versions ─────────────────────────────────────────

        def add_version(self, asset_id: str, file_hash: str,
                        prev_hash: str = None, metadata: dict = None) -> int:
            current = self._conn.execute(
                "SELECT MAX(version) FROM asset_versions WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            next_ver = (current[0] or 0) + 1
            meta_json = _json.dumps(metadata or {}, ensure_ascii=False)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO asset_versions (asset_id, version, file_hash, prev_hash, metadata) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (asset_id, next_ver, file_hash, prev_hash, meta_json),
                )
            return next_ver

        def get_versions(self, asset_id: str) -> List[Dict[str, Any]]:
            rows = self._conn.execute(
                "SELECT * FROM asset_versions WHERE asset_id = ? ORDER BY version", (asset_id,)
            ).fetchall()
            return [dict(r) for r in rows]

        # ── Utility ────────────────────────────────────────────────

        def close(self) -> None:
            self._conn.close()

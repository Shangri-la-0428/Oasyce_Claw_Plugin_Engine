"""
SQLite persistent ledger — the local chain database for Oasyce nodes.

Stores assets, transactions, shares, and stakes in ~/.oasyce/chain.db.
Replaces scattered JSON files with a single SQLite database, similar to
how Bitcoin uses LevelDB for its local UTXO set.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from oasyce_plugin.crypto.merkle import merkle_root


def _default_db_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".oasyce", "chain.db")


class Ledger:
    """Encapsulates all SQLite operations for the Oasyce local ledger."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _default_db_path()
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._migrate()

    def _create_tables(self) -> None:
        with self._conn:
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

                CREATE TABLE IF NOT EXISTS fingerprint_records (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id    TEXT NOT NULL,
                    caller_id   TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    timestamp   INTEGER NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def _migrate(self) -> None:
        """Add block_number column to transactions if missing (upgrade path)."""
        cols = [
            r[1]
            for r in self._conn.execute("PRAGMA table_info(transactions)").fetchall()
        ]
        if "block_number" not in cols:
            with self._conn:
                self._conn.execute(
                    "ALTER TABLE transactions ADD COLUMN block_number INTEGER"
                )

    # ── Assets ───────────────────────────────────────────────────────────

    def save_asset(self, metadata: Dict[str, Any]) -> None:
        """Write an asset record from its full metadata dict."""
        asset_id = metadata["asset_id"]
        owner = metadata.get("owner", "")
        file_hash = metadata.get("file_hash", "")
        popc_sig = metadata.get("popc_signature")
        meta_json = json.dumps(metadata, ensure_ascii=False)

        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO assets
                    (asset_id, owner, file_hash, metadata, popc_signature)
                VALUES (?, ?, ?, ?, ?)
                """,
                (asset_id, owner, file_hash, meta_json, popc_sig),
            )

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single asset's full metadata, or None."""
        row = self._conn.execute(
            "SELECT metadata FROM assets WHERE asset_id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["metadata"])

    def search_assets(self, tag: str) -> List[Dict[str, Any]]:
        """Search assets whose metadata JSON contains the given tag."""
        rows = self._conn.execute("SELECT metadata FROM assets").fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            meta = json.loads(row["metadata"])
            if tag in meta.get("tags", []):
                results.append(meta)
        return results

    # ── Transactions ─────────────────────────────────────────────────────

    def record_tx(
        self,
        tx_type: str,
        asset_id: Optional[str] = None,
        from_addr: Optional[str] = None,
        to_addr: Optional[str] = None,
        amount: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        signature: Optional[str] = None,
    ) -> str:
        """Record a transaction and return the generated tx_id."""
        tx_id = uuid.uuid4().hex
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO transactions
                    (tx_id, tx_type, asset_id, from_addr, to_addr, amount, metadata, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tx_id, tx_type, asset_id, from_addr, to_addr, amount, meta_json, signature),
            )
        return tx_id

    # ── Shares ───────────────────────────────────────────────────────────

    def update_shares(self, owner: str, asset_id: str, delta: float) -> None:
        """Upsert share holdings — positive delta = buy, negative = sell."""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO shares (owner, asset_id, amount)
                VALUES (?, ?, ?)
                ON CONFLICT(owner, asset_id) DO UPDATE
                    SET amount = amount + excluded.amount
                """,
                (owner, asset_id, delta),
            )

    def get_shares(self, owner: str) -> List[Dict[str, Any]]:
        """Return all share positions for an owner."""
        rows = self._conn.execute(
            "SELECT asset_id, amount FROM shares WHERE owner = ? AND amount > 0",
            (owner,),
        ).fetchall()
        return [{"asset_id": r["asset_id"], "amount": r["amount"]} for r in rows]

    # ── Stakes ───────────────────────────────────────────────────────────

    def update_stake(self, validator_id: str, staker: str, delta: float) -> None:
        """Upsert stake — positive delta = stake, negative = unstake."""
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO stakes (validator_id, staker, amount)
                VALUES (?, ?, ?)
                ON CONFLICT(validator_id, staker) DO UPDATE
                    SET amount = amount + excluded.amount
                """,
                (validator_id, staker, delta),
            )

    def get_stake(self, validator_id: str) -> float:
        """Return total staked amount for a validator (sum of all stakers)."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM stakes WHERE validator_id = ?",
            (validator_id,),
        ).fetchone()
        return float(row["total"])

    # ── Blocks ────────────────────────────────────────────────────────────

    def _block_hash(self, prev_hash: str, mr: str, ts: str, nonce: int) -> str:
        raw = f"{prev_hash}{mr}{ts}{nonce}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def create_block(self) -> Optional[Dict[str, Any]]:
        """Pack all unconfirmed transactions into a new block.

        Returns the block dict, or None if there are no pending transactions.
        """
        rows = self._conn.execute(
            "SELECT tx_id FROM transactions WHERE block_number IS NULL ORDER BY created_at"
        ).fetchall()
        if not rows:
            return None

        tx_ids = [r["tx_id"] for r in rows]
        mr = merkle_root(tx_ids)

        # Determine block number and prev_hash
        prev = self._conn.execute(
            "SELECT block_number, block_hash FROM blocks ORDER BY block_number DESC LIMIT 1"
        ).fetchone()
        if prev:
            block_number = prev["block_number"] + 1
            prev_hash = prev["block_hash"]
        else:
            block_number = 0
            prev_hash = "0" * 64

        ts = datetime.now(timezone.utc).isoformat()
        nonce = 0
        bh = self._block_hash(prev_hash, mr, ts, nonce)

        with self._conn:
            self._conn.execute(
                """
                INSERT INTO blocks (block_number, block_hash, prev_hash, merkle_root, timestamp, tx_count, nonce)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (block_number, bh, prev_hash, mr, ts, len(tx_ids), nonce),
            )
            self._conn.execute(
                "UPDATE transactions SET block_number = ? WHERE block_number IS NULL",
                (block_number,),
            )

        return {
            "block_number": block_number,
            "block_hash": bh,
            "prev_hash": prev_hash,
            "merkle_root": mr,
            "timestamp": ts,
            "tx_count": len(tx_ids),
            "nonce": nonce,
            "tx_ids": tx_ids,
        }

    def get_block(self, block_number: int, include_tx: bool = False) -> Optional[Dict[str, Any]]:
        """Retrieve a block and its associated transaction IDs.

        If *include_tx* is True, return full transaction dicts instead of
        just tx_ids (needed for sync protocol).
        """
        row = self._conn.execute(
            "SELECT * FROM blocks WHERE block_number = ?", (block_number,)
        ).fetchone()
        if row is None:
            return None
        tx_rows = self._conn.execute(
            "SELECT * FROM transactions WHERE block_number = ? ORDER BY created_at",
            (block_number,),
        ).fetchall()
        result: Dict[str, Any] = {
            "block_number": row["block_number"],
            "block_hash": row["block_hash"],
            "prev_hash": row["prev_hash"],
            "merkle_root": row["merkle_root"],
            "timestamp": row["timestamp"],
            "tx_count": row["tx_count"],
            "nonce": row["nonce"],
            "tx_ids": [r["tx_id"] for r in tx_rows],
        }
        if include_tx:
            result["transactions"] = [
                {
                    "tx_id": r["tx_id"],
                    "tx_type": r["tx_type"],
                    "asset_id": r["asset_id"],
                    "from_addr": r["from_addr"],
                    "to_addr": r["to_addr"],
                    "amount": r["amount"],
                    "metadata": r["metadata"],
                    "signature": r["signature"],
                    "block_number": r["block_number"],
                    "created_at": r["created_at"],
                }
                for r in tx_rows
            ]
        return result

    def get_latest_block(self) -> Optional[Dict[str, Any]]:
        """Return the most recent block, or None if the chain is empty."""
        row = self._conn.execute(
            "SELECT block_number FROM blocks ORDER BY block_number DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self.get_block(row["block_number"])

    def get_chain_height(self) -> int:
        """Return the current chain height (number of blocks)."""
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM blocks").fetchone()
        return row["cnt"]

    def verify_chain(self) -> bool:
        """Walk the entire chain and verify hash linkage + merkle roots.

        Returns True if every block is valid, False otherwise.
        """
        blocks = self._conn.execute(
            "SELECT * FROM blocks ORDER BY block_number ASC"
        ).fetchall()
        if not blocks:
            return True

        for i, blk in enumerate(blocks):
            # Verify prev_hash linkage
            if i == 0:
                if blk["prev_hash"] != "0" * 64:
                    return False
            else:
                if blk["prev_hash"] != blocks[i - 1]["block_hash"]:
                    return False

            # Verify merkle root
            tx_rows = self._conn.execute(
                "SELECT tx_id FROM transactions WHERE block_number = ? ORDER BY created_at",
                (blk["block_number"],),
            ).fetchall()
            expected_mr = merkle_root([r["tx_id"] for r in tx_rows])
            if blk["merkle_root"] != expected_mr:
                return False

            # Verify block hash
            expected_bh = self._block_hash(
                blk["prev_hash"], blk["merkle_root"], blk["timestamp"], blk["nonce"]
            )
            if blk["block_hash"] != expected_bh:
                return False

        return True

    # ── Remote block insertion (sync) ────────────────────────────────────

    def insert_remote_block(self, block_data: Dict[str, Any]) -> bool:
        """Validate and insert a block received from a remote peer.

        *block_data* must contain: block_number, block_hash, prev_hash,
        merkle_root, timestamp, tx_count, nonce, and a *transactions*
        list with full tx dicts.

        Returns True on success, False on validation failure.
        Duplicate blocks (same block_number already exists) are silently
        ignored and return True (idempotent).
        """
        bn = block_data.get("block_number")
        bh = block_data.get("block_hash")
        prev_hash = block_data.get("prev_hash")
        mr = block_data.get("merkle_root")
        ts = block_data.get("timestamp")
        nonce = block_data.get("nonce", 0)
        txs = block_data.get("transactions", [])

        # Reject incomplete block data
        if bn is None or bh is None or prev_hash is None or mr is None or ts is None:
            return False

        # Idempotent: if block already stored, skip
        existing = self._conn.execute(
            "SELECT block_hash FROM blocks WHERE block_number = ?", (bn,)
        ).fetchone()
        if existing is not None:
            return True

        # 1. Verify prev_hash linkage
        if bn == 0:
            expected_prev = "0" * 64
        else:
            prev_block = self._conn.execute(
                "SELECT block_hash FROM blocks WHERE block_number = ?", (bn - 1,)
            ).fetchone()
            if prev_block is None:
                return False
            expected_prev = prev_block["block_hash"]
        if prev_hash != expected_prev:
            return False

        # 2. Timestamp validation
        try:
            block_ts = datetime.fromisoformat(ts)
            if block_ts.tzinfo is None:
                block_ts = block_ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return False

        now = datetime.now(timezone.utc)
        if block_ts > now + timedelta(seconds=120):
            return False

        if bn > 0:
            prev_block_row = self._conn.execute(
                "SELECT timestamp FROM blocks WHERE block_number = ?", (bn - 1,)
            ).fetchone()
            if prev_block_row is not None:
                prev_ts = datetime.fromisoformat(prev_block_row["timestamp"])
                if prev_ts.tzinfo is None:
                    prev_ts = prev_ts.replace(tzinfo=timezone.utc)
                if block_ts < prev_ts:
                    return False

        # 3. Verify merkle_root matches transactions
        tx_ids = [tx["tx_id"] for tx in txs]
        expected_mr = merkle_root(tx_ids)
        if mr != expected_mr:
            return False

        # 4. Verify block_hash
        expected_bh = self._block_hash(prev_hash, mr, ts, nonce)
        if bh != expected_bh:
            return False

        # All good — write block and transactions
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO blocks (block_number, block_hash, prev_hash, merkle_root, timestamp, tx_count, nonce)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (bn, bh, prev_hash, mr, ts, len(txs), nonce),
            )
            for tx in txs:
                meta = tx.get("metadata")
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO transactions
                        (tx_id, tx_type, asset_id, from_addr, to_addr, amount, metadata, signature, block_number, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tx["tx_id"], tx.get("tx_type", ""), tx.get("asset_id"),
                        tx.get("from_addr"), tx.get("to_addr"), tx.get("amount"),
                        meta, tx.get("signature"), bn, tx.get("created_at"),
                    ),
                )
        return True

    # ── Chain evaluation & reorg ────────────────────────────────────────

    MAX_REORG_DEPTH = 10

    def evaluate_chain(self, blocks: List[Dict[str, Any]]) -> bool:
        """Validate a complete chain segment: hash linkage, merkle roots, block hashes."""
        if not blocks:
            return True

        for i, blk in enumerate(blocks):
            bn = blk.get("block_number")
            bh = blk.get("block_hash")
            prev_hash = blk.get("prev_hash")
            mr = blk.get("merkle_root")
            ts = blk.get("timestamp")
            nonce = blk.get("nonce", 0)
            txs = blk.get("transactions", [])

            if bn is None or bh is None or prev_hash is None or mr is None or ts is None:
                return False

            # Verify prev_hash linkage
            if i == 0:
                if bn == 0:
                    if prev_hash != "0" * 64:
                        return False
                # For non-genesis first block, linkage checked by caller
            else:
                if prev_hash != blocks[i - 1].get("block_hash"):
                    return False

            # Verify merkle root
            tx_ids = [tx["tx_id"] for tx in txs]
            expected_mr = merkle_root(tx_ids)
            if mr != expected_mr:
                return False

            # Verify block hash
            expected_bh = self._block_hash(prev_hash, mr, ts, nonce)
            if bh != expected_bh:
                return False

        return True

    def attempt_reorg(self, new_chain: List[Dict[str, Any]]) -> bool:
        """Replace current chain with *new_chain* if it is longer and valid.

        Returns True if a reorg happened, False otherwise.
        Constraints:
        - new_chain must be longer than current chain by at least 1 block.
        - Reorg depth (blocks rolled back) must not exceed MAX_REORG_DEPTH.
        - Every block in new_chain must pass full validation.
        """
        if not new_chain:
            return False

        current_height = self.get_chain_height()
        new_height = len(new_chain)

        if new_height <= current_height:
            return False

        if not self.evaluate_chain(new_chain):
            return False

        # Find the fork point: how many existing blocks need to be rolled back
        fork_point = 0
        for blk in new_chain:
            bn = blk["block_number"]
            existing = self._conn.execute(
                "SELECT block_hash FROM blocks WHERE block_number = ?", (bn,)
            ).fetchone()
            if existing is None or existing["block_hash"] != blk["block_hash"]:
                fork_point = bn
                break

        rollback_depth = current_height - fork_point
        if rollback_depth > self.MAX_REORG_DEPTH:
            return False

        # Delete old blocks and their transactions from fork_point onward
        with self._conn:
            self._conn.execute(
                "DELETE FROM transactions WHERE block_number >= ?", (fork_point,)
            )
            self._conn.execute(
                "DELETE FROM blocks WHERE block_number >= ?", (fork_point,)
            )

            # Insert new chain blocks from fork_point onward
            for blk in new_chain:
                if blk["block_number"] < fork_point:
                    continue
                self._conn.execute(
                    """
                    INSERT INTO blocks (block_number, block_hash, prev_hash, merkle_root, timestamp, tx_count, nonce)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        blk["block_number"], blk["block_hash"], blk["prev_hash"],
                        blk["merkle_root"], blk["timestamp"],
                        blk.get("tx_count", len(blk.get("transactions", []))),
                        blk.get("nonce", 0),
                    ),
                )
                for tx in blk.get("transactions", []):
                    self._conn.execute(
                        """
                        INSERT OR IGNORE INTO transactions
                            (tx_id, tx_type, asset_id, from_addr, to_addr, amount, metadata, signature, block_number, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            tx["tx_id"], tx.get("tx_type", ""), tx.get("asset_id"),
                            tx.get("from_addr"), tx.get("to_addr"), tx.get("amount"),
                            tx.get("metadata"), tx.get("signature"),
                            blk["block_number"], tx.get("created_at"),
                        ),
                    )

        return True

    def get_chain_from(self, start: int) -> List[Dict[str, Any]]:
        """Return all blocks from *start* onward, with full transactions."""
        blocks = []
        bn = start
        while True:
            blk = self.get_block(bn, include_tx=True)
            if blk is None:
                break
            blocks.append(blk)
            bn += 1
        return blocks

    # ── Lifecycle ────────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()

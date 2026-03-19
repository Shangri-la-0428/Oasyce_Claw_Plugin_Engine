"""PostgreSQL storage backend for production Oasyce deployments.

Requires: pip install psycopg2-binary
This is an OPTIONAL dependency — SQLite is the default.
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import psycopg2
    import psycopg2.extras

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

from oasyce.storage.backend import LedgerBackend


class PostgresBackend(LedgerBackend):
    def __init__(self, dsn: str):
        if not HAS_PSYCOPG2:
            raise ImportError(
                "psycopg2 is required for PostgreSQL backend. "
                "Install: pip install psycopg2-binary"
            )
        self.dsn = dsn
        self.conn = None

    def initialize(self) -> None:
        self.conn = psycopg2.connect(self.dsn)
        self.conn.autocommit = True
        with self.conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS blocks (
                    block_hash TEXT PRIMARY KEY,
                    prev_hash TEXT,
                    height INTEGER,
                    timestamp DOUBLE PRECISION,
                    merkle_root TEXT,
                    miner TEXT,
                    data JSONB
                )
            """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    tx_id TEXT PRIMARY KEY,
                    asset_id TEXT,
                    buyer TEXT,
                    seller TEXT,
                    amount DOUBLE PRECISION,
                    timestamp DOUBLE PRECISION,
                    block_hash TEXT,
                    data JSONB
                )
            """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    asset_id TEXT PRIMARY KEY,
                    owner TEXT,
                    name TEXT,
                    tags TEXT,
                    price DOUBLE PRECISION,
                    created_at DOUBLE PRECISION,
                    data JSONB
                )
            """
            )
            # Indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_asset ON transactions(asset_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tx_time ON transactions(timestamp DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_blocks_height ON blocks(height DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_assets_owner ON assets(owner)")

    def store_block(self, block: Dict[str, Any]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO blocks (block_hash, prev_hash, height, timestamp, "
                "merkle_root, miner, data) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    block.get("block_hash"),
                    block.get("prev_hash"),
                    block.get("height", 0),
                    block.get("timestamp", 0),
                    block.get("merkle_root"),
                    block.get("miner"),
                    json.dumps(block),
                ),
            )

    def get_block(self, block_hash: str) -> Optional[Dict[str, Any]]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT data FROM blocks WHERE block_hash = %s", (block_hash,))
            row = cur.fetchone()
            return json.loads(row["data"]) if row else None

    def get_latest_block(self) -> Optional[Dict[str, Any]]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT data FROM blocks ORDER BY height DESC LIMIT 1")
            row = cur.fetchone()
            return json.loads(row["data"]) if row else None

    def get_chain_length(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM blocks")
            return cur.fetchone()[0]

    def store_transaction(self, tx: Dict[str, Any]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO transactions (tx_id, asset_id, buyer, seller, amount, "
                "timestamp, block_hash, data) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    tx.get("tx_id"),
                    tx.get("asset_id"),
                    tx.get("buyer"),
                    tx.get("seller"),
                    tx.get("amount", 0),
                    tx.get("timestamp", 0),
                    tx.get("block_hash"),
                    json.dumps(tx),
                ),
            )

    def get_transactions(
        self, asset_id: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if asset_id:
                cur.execute(
                    "SELECT data FROM transactions WHERE asset_id = %s "
                    "ORDER BY timestamp DESC LIMIT %s",
                    (asset_id, limit),
                )
            else:
                cur.execute(
                    "SELECT data FROM transactions ORDER BY timestamp DESC LIMIT %s",
                    (limit,),
                )
            return [json.loads(row["data"]) for row in cur.fetchall()]

    def store_asset(self, asset: Dict[str, Any]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO assets (asset_id, owner, name, tags, price, created_at, "
                "data) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (asset_id) DO UPDATE SET data = EXCLUDED.data",
                (
                    asset.get("asset_id"),
                    asset.get("owner"),
                    asset.get("name", ""),
                    asset.get("tags", ""),
                    asset.get("price", 0),
                    asset.get("created_at", 0),
                    json.dumps(asset),
                ),
            )

    def get_asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT data FROM assets WHERE asset_id = %s", (asset_id,))
            row = cur.fetchone()
            return json.loads(row["data"]) if row else None

    def search_assets(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            like = f"%{query}%"
            cur.execute(
                "SELECT data FROM assets WHERE name ILIKE %s OR tags ILIKE %s "
                "ORDER BY created_at DESC LIMIT %s",
                (like, like, limit),
            )
            return [json.loads(row["data"]) for row in cur.fetchall()]

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

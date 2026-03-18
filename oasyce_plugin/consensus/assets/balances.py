"""
Multi-asset balance management — SQLite-backed balances keyed by (address, asset_type).

All amounts are integer units. The table is created lazily on first use
so that existing databases upgrade transparently.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any, Dict, List, Optional


class MultiAssetBalance:
    """Manages per-address, per-asset-type balances in SQLite."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock
        self._ensure_table()

    def _ensure_table(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS asset_balances (
                    address    TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    amount     INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (address, asset_type)
                );
                CREATE INDEX IF NOT EXISTS idx_asset_balances_addr
                    ON asset_balances(address);
                CREATE INDEX IF NOT EXISTS idx_asset_balances_type
                    ON asset_balances(asset_type);

                CREATE TABLE IF NOT EXISTS asset_transfers (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_addr   TEXT NOT NULL,
                    to_addr     TEXT NOT NULL,
                    asset_type  TEXT NOT NULL,
                    amount      INTEGER NOT NULL,
                    block_height INTEGER NOT NULL DEFAULT 0,
                    timestamp   INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_asset_transfers_from
                    ON asset_transfers(from_addr);
                CREATE INDEX IF NOT EXISTS idx_asset_transfers_to
                    ON asset_transfers(to_addr);
            """)

    # ── Read ────────────────────────────────────────────────────────

    def get_balance(self, address: str, asset_type: str = "OAS") -> int:
        """Get balance for an address and asset type."""
        with self._lock:
            row = self._conn.execute(
                "SELECT amount FROM asset_balances "
                "WHERE address = ? AND asset_type = ?",
                (address, asset_type),
            ).fetchone()
        return row[0] if row else 0

    def get_all_balances(self, address: str) -> Dict[str, int]:
        """Get all asset balances for an address."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT asset_type, amount FROM asset_balances "
                "WHERE address = ? AND amount > 0",
                (address,),
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_total_supply(self, asset_type: str) -> int:
        """Sum of all positive balances for an asset type."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM asset_balances "
                "WHERE asset_type = ? AND amount > 0",
                (asset_type,),
            ).fetchone()
        return row[0] if row else 0

    # ── Write ───────────────────────────────────────────────────────

    def credit(self, address: str, asset_type: str, amount: int) -> int:
        """Add amount to an address's balance. Returns new balance."""
        if amount < 0:
            raise ValueError("credit amount must be non-negative")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO asset_balances (address, asset_type, amount) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(address, asset_type) DO UPDATE SET amount = amount + ?",
                (address, asset_type, amount, amount),
            )
            row = self._conn.execute(
                "SELECT amount FROM asset_balances "
                "WHERE address = ? AND asset_type = ?",
                (address, asset_type),
            ).fetchone()
        return row[0]

    def debit(self, address: str, asset_type: str, amount: int) -> int:
        """Subtract amount from an address's balance. Returns new balance.

        Raises ValueError if insufficient balance.
        """
        if amount < 0:
            raise ValueError("debit amount must be non-negative")
        current = self.get_balance(address, asset_type)
        if current < amount:
            raise ValueError(
                f"insufficient {asset_type} balance: have {current}, need {amount}"
            )
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE asset_balances SET amount = amount - ? "
                "WHERE address = ? AND asset_type = ?",
                (amount, address, asset_type),
            )
            row = self._conn.execute(
                "SELECT amount FROM asset_balances "
                "WHERE address = ? AND asset_type = ?",
                (address, asset_type),
            ).fetchone()
        return row[0]

    def transfer(self, from_addr: str, to_addr: str,
                 asset_type: str, amount: int,
                 block_height: int = 0, timestamp: int = 0) -> Dict[str, Any]:
        """Atomically transfer between two addresses. Returns result dict."""
        if amount <= 0:
            return {"ok": False, "error": "transfer amount must be positive"}
        if from_addr == to_addr:
            return {"ok": False, "error": "cannot transfer to self"}

        current = self.get_balance(from_addr, asset_type)
        if current < amount:
            return {
                "ok": False,
                "error": f"insufficient {asset_type} balance: have {current}, need {amount}",
            }

        # Perform atomic transfer
        with self._lock, self._conn:
            # Debit sender
            self._conn.execute(
                "INSERT INTO asset_balances (address, asset_type, amount) "
                "VALUES (?, ?, 0) "
                "ON CONFLICT(address, asset_type) DO NOTHING",
                (from_addr, asset_type),
            )
            self._conn.execute(
                "UPDATE asset_balances SET amount = amount - ? "
                "WHERE address = ? AND asset_type = ?",
                (amount, from_addr, asset_type),
            )
            # Credit receiver
            self._conn.execute(
                "INSERT INTO asset_balances (address, asset_type, amount) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(address, asset_type) DO UPDATE SET amount = amount + ?",
                (to_addr, asset_type, amount, amount),
            )
            # Record transfer
            self._conn.execute(
                "INSERT INTO asset_transfers "
                "(from_addr, to_addr, asset_type, amount, block_height, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (from_addr, to_addr, asset_type, amount, block_height, timestamp),
            )

        return {
            "ok": True,
            "from": from_addr,
            "to": to_addr,
            "asset_type": asset_type,
            "amount": amount,
        }

    def get_transfer_history(self, address: str,
                             asset_type: Optional[str] = None,
                             limit: int = 50) -> List[Dict[str, Any]]:
        """Get transfer history involving an address."""
        clauses = ["(from_addr = ? OR to_addr = ?)"]
        params: list = [address, address]
        if asset_type:
            clauses.append("asset_type = ?")
            params.append(asset_type)
        where = " AND ".join(clauses)
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM asset_transfers WHERE {where} "
                f"ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(zip(
            ["id", "from_addr", "to_addr", "asset_type", "amount",
             "block_height", "timestamp"],
            r,
        )) for r in rows]

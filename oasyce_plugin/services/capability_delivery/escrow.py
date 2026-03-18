"""
Escrow Ledger — atomic fund locking for capability invocations.

Flow:
  1. Consumer calls lock() → funds move from balance to escrow
  2. On success: release() → funds move from escrow to provider
  3. On failure: refund() → funds return from escrow to consumer
  4. On timeout: auto-refund after TTL expires

All amounts are in OAS integer units (1 OAS = 10^8 units).
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class EscrowStatus(str, Enum):
    LOCKED = "locked"
    RELEASED = "released"
    REFUNDED = "refunded"
    EXPIRED = "expired"


@dataclass
class EscrowEntry:
    """A single escrow lock."""
    escrow_id: str
    consumer_id: str
    provider_id: str
    capability_id: str
    amount: int               # OAS units
    status: str = EscrowStatus.LOCKED
    created_at: int = 0
    resolved_at: int = 0
    ttl: int = 300            # seconds until auto-refund
    invocation_id: str = ""   # linked invocation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "escrow_id": self.escrow_id,
            "consumer_id": self.consumer_id,
            "provider_id": self.provider_id,
            "capability_id": self.capability_id,
            "amount": self.amount,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "ttl": self.ttl,
            "invocation_id": self.invocation_id,
        }


class EscrowLedger:
    """Thread-safe escrow ledger backed by SQLite.

    Tracks locked funds per invocation. Supports lock/release/refund
    and automatic expiry of stale locks.

    If an optional ``balances`` (:class:`MultiAssetBalance`) instance is
    provided, escrow operations will debit/credit real token balances in
    addition to maintaining the accounting ledger.
    """

    # Protocol fee: 5% of settled amount (in basis points)
    PROTOCOL_FEE_BPS: int = 500

    # OAS uses 8 decimal places (1 OAS = 10^8 units).  Amounts stored in
    # the escrow table are already in integer units, so no extra conversion
    # is needed when forwarding to MultiAssetBalance.
    _OAS_ASSET: str = "OAS"
    _PROTOCOL_TREASURY: str = "protocol_treasury"

    _DEFAULT_DB_PATH = os.path.join("~", ".oasyce", "escrow.db")

    def __init__(self, db_path: str = "", balances=None):
        """
        Parameters
        ----------
        db_path : str
            Path to the SQLite database.  Defaults to ``~/.oasyce/escrow.db``.
        balances : MultiAssetBalance | None
            If provided, real token balances are debited/credited during
            lock/release/refund.  When ``None`` (the default), escrow
            operates in ledger-only mode for backward compatibility.
        """
        if not db_path:
            db_path = os.path.expanduser(self._DEFAULT_DB_PATH)
        if db_path != ":memory:":
            db_dir = os.path.dirname(db_path)
            os.makedirs(db_dir, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._balances = balances
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS escrow (
                escrow_id TEXT PRIMARY KEY,
                consumer_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'locked',
                created_at INTEGER NOT NULL,
                resolved_at INTEGER NOT NULL DEFAULT 0,
                ttl INTEGER NOT NULL DEFAULT 300,
                invocation_id TEXT NOT NULL DEFAULT '',
                auth_token TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_escrow_consumer
                ON escrow(consumer_id, status);
            CREATE INDEX IF NOT EXISTS idx_escrow_invocation
                ON escrow(invocation_id);
        """)
        # Migrate: add auth_token column to existing tables that lack it
        try:
            self._conn.execute(
                "ALTER TABLE escrow ADD COLUMN auth_token TEXT NOT NULL DEFAULT ''"
            )
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

    def lock(self, consumer_id: str, provider_id: str,
             capability_id: str, amount: int,
             invocation_id: str = "",
             ttl: int = 300) -> Dict[str, Any]:
        """Lock funds in escrow for a capability invocation.

        Returns {"ok": True, "escrow_id": "..."} or {"ok": False, "error": "..."}.
        """
        if amount <= 0:
            return {"ok": False, "error": "amount must be positive"}
        if not consumer_id:
            return {"ok": False, "error": "consumer_id required"}
        if not provider_id:
            return {"ok": False, "error": "provider_id required"}

        # Debit consumer's real token balance (funds move into escrow).
        if self._balances is not None:
            try:
                self._balances.debit(consumer_id, self._OAS_ASSET, amount)
            except ValueError:
                return {"ok": False, "error": "insufficient balance"}

        escrow_id = f"ESC_{uuid.uuid4().hex[:16].upper()}"
        auth_token = secrets.token_hex(32)

        with self._lock:
            self._conn.execute("""
                INSERT INTO escrow
                    (escrow_id, consumer_id, provider_id, capability_id,
                     amount, status, created_at, ttl, invocation_id, auth_token)
                VALUES (?, ?, ?, ?, ?, 'locked', ?, ?, ?, ?)
            """, (
                escrow_id, consumer_id, provider_id, capability_id,
                amount, int(time.time()), ttl, invocation_id, auth_token,
            ))
            self._conn.commit()

        return {"ok": True, "escrow_id": escrow_id, "auth_token": auth_token}

    def release(self, escrow_id: str, auth_token: str = "") -> Dict[str, Any]:
        """Release escrowed funds to the provider (invocation succeeded).

        Requires the auth_token returned by lock() for authorization.

        Returns the settlement breakdown:
          provider_amount = amount - protocol_fee
          protocol_fee = amount * PROTOCOL_FEE_BPS / 10000
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM escrow WHERE escrow_id = ?",
                (escrow_id,),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "escrow not found"}
            if row["status"] != EscrowStatus.LOCKED:
                return {"ok": False, "error": f"escrow is {row['status']}, cannot release"}
            if not auth_token or auth_token != row["auth_token"]:
                return {"ok": False, "error": "invalid auth_token"}

            amount = row["amount"]
            fee = amount * self.PROTOCOL_FEE_BPS // 10000
            provider_amount = amount - fee

            self._conn.execute(
                "UPDATE escrow SET status = 'released', resolved_at = ? "
                "WHERE escrow_id = ?",
                (int(time.time()), escrow_id),
            )
            self._conn.commit()

        # Credit real token balances (funds leave escrow).
        if self._balances is not None:
            self._balances.credit(
                row["provider_id"], self._OAS_ASSET, provider_amount,
            )
            self._balances.credit(
                self._PROTOCOL_TREASURY, self._OAS_ASSET, fee,
            )

        return {
            "ok": True,
            "escrow_id": escrow_id,
            "amount": amount,
            "provider_amount": provider_amount,
            "protocol_fee": fee,
            "provider_id": row["provider_id"],
            "consumer_id": row["consumer_id"],
        }

    def refund(self, escrow_id: str, auth_token: str = "") -> Dict[str, Any]:
        """Refund escrowed funds to the consumer (invocation failed).

        Requires the auth_token returned by lock() for authorization.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM escrow WHERE escrow_id = ?",
                (escrow_id,),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "escrow not found"}
            if row["status"] != EscrowStatus.LOCKED:
                return {"ok": False, "error": f"escrow is {row['status']}, cannot refund"}
            if not auth_token or auth_token != row["auth_token"]:
                return {"ok": False, "error": "invalid auth_token"}

            self._conn.execute(
                "UPDATE escrow SET status = 'refunded', resolved_at = ? "
                "WHERE escrow_id = ?",
                (int(time.time()), escrow_id),
            )
            self._conn.commit()

        # Credit consumer's real token balance (funds return from escrow).
        if self._balances is not None:
            self._balances.credit(
                row["consumer_id"], self._OAS_ASSET, row["amount"],
            )

        return {
            "ok": True,
            "escrow_id": escrow_id,
            "refunded_amount": row["amount"],
            "consumer_id": row["consumer_id"],
        }

    def expire_stale(self) -> int:
        """Refund all escrows that have exceeded their TTL.

        Returns the number of expired escrows.
        """
        now = int(time.time())
        with self._lock:
            cur = self._conn.execute(
                "UPDATE escrow SET status = 'expired', resolved_at = ? "
                "WHERE status = 'locked' AND (created_at + ttl) < ?",
                (now, now),
            )
            self._conn.commit()
            return cur.rowcount

    def get(self, escrow_id: str) -> Optional[EscrowEntry]:
        """Get an escrow entry by ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM escrow WHERE escrow_id = ?",
                (escrow_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_entry(row)

    def get_by_invocation(self, invocation_id: str) -> Optional[EscrowEntry]:
        """Get the escrow entry for a specific invocation."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM escrow WHERE invocation_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (invocation_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_entry(row)

    def list_locked(self, consumer_id: Optional[str] = None,
                    limit: int = 50) -> List[EscrowEntry]:
        """List currently locked escrows."""
        query = "SELECT * FROM escrow WHERE status = 'locked'"
        params: list = []
        if consumer_id:
            query += " AND consumer_id = ?"
            params.append(consumer_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def total_locked(self, consumer_id: Optional[str] = None) -> int:
        """Total amount currently locked in escrow."""
        query = "SELECT COALESCE(SUM(amount), 0) FROM escrow WHERE status = 'locked'"
        params: list = []
        if consumer_id:
            query += " AND consumer_id = ?"
            params.append(consumer_id)
        with self._lock:
            return self._conn.execute(query, params).fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> EscrowEntry:
        return EscrowEntry(
            escrow_id=row["escrow_id"],
            consumer_id=row["consumer_id"],
            provider_id=row["provider_id"],
            capability_id=row["capability_id"],
            amount=row["amount"],
            status=row["status"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            ttl=row["ttl"],
            invocation_id=row["invocation_id"],
        )

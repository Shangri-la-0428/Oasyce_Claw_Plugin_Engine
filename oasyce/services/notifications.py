"""
Notification Service — SQLite-backed notification system for Oasyce.

Supports event types: PURCHASE, SALE, DISPUTE_FILED, DISPUTE_RESOLVED,
CAPABILITY_INVOKED, EARNINGS_RECEIVED.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    DISPUTE_FILED = "DISPUTE_FILED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    CAPABILITY_INVOKED = "CAPABILITY_INVOKED"
    EARNINGS_RECEIVED = "EARNINGS_RECEIVED"
    SHUTDOWN_INITIATED = "SHUTDOWN_INITIATED"
    ASSET_TERMINATED = "ASSET_TERMINATED"
    TERMINATION_CLAIMED = "TERMINATION_CLAIMED"


class NotificationService:
    """SQLite-backed notification storage and retrieval."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            data_dir = os.path.join(os.path.expanduser("~"), ".oasyce")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "notifications.db")
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                address TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT DEFAULT '{}',
                read INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            )
        """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notif_address
            ON notifications (address, created_at DESC)
        """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notif_unread
            ON notifications (address, read)
        """
        )
        self._conn.commit()

    def notify(
        self,
        address: str,
        event_type: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a notification. Returns the notification_id."""
        nid = f"NOTIF_{uuid.uuid4().hex[:12]}"
        now = time.time()
        self._conn.execute(
            "INSERT INTO notifications (id, address, event_type, message, data, read, created_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?)",
            (nid, address, event_type, message, json.dumps(data or {}), now),
        )
        self._conn.commit()
        return nid

    def get_notifications(
        self,
        address: str,
        unread_only: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List notifications for an address."""
        if unread_only:
            rows = self._conn.execute(
                "SELECT * FROM notifications WHERE address = ? AND read = 0 "
                "ORDER BY created_at DESC LIMIT ?",
                (address, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM notifications WHERE address = ? " "ORDER BY created_at DESC LIMIT ?",
                (address, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def mark_read(self, notification_id: str) -> bool:
        """Mark a single notification as read. Returns True if found."""
        cursor = self._conn.execute(
            "UPDATE notifications SET read = 1 WHERE id = ?",
            (notification_id,),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def mark_all_read(self, address: str) -> int:
        """Mark all notifications for an address as read. Returns count."""
        cursor = self._conn.execute(
            "UPDATE notifications SET read = 1 WHERE address = ? AND read = 0",
            (address,),
        )
        self._conn.commit()
        return cursor.rowcount

    def get_unread_count(self, address: str) -> int:
        """Return the number of unread notifications for badge display."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE address = ? AND read = 0",
            (address,),
        ).fetchone()
        return row["c"] if row else 0

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data_str = row["data"] if row["data"] else "{}"
        try:
            data_parsed = json.loads(data_str)
        except (json.JSONDecodeError, TypeError):
            data_parsed = {}
        return {
            "id": row["id"],
            "address": row["address"],
            "event_type": row["event_type"],
            "message": row["message"],
            "data": data_parsed,
            "read": bool(row["read"]),
            "created_at": row["created_at"],
        }

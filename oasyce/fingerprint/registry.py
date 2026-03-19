"""Fingerprint distribution registry — records who received what."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from oasyce.storage.ledger import Ledger


class FingerprintRegistry:
    """Track fingerprint distributions using the existing Ledger database."""

    def __init__(self, ledger: Ledger) -> None:
        self._conn = ledger._conn

    def record_distribution(
        self,
        asset_id: str,
        caller_id: str,
        fingerprint: str,
        timestamp: int,
    ) -> int:
        """Record a distribution event. Returns the record id."""
        with self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO fingerprint_records (asset_id, caller_id, fingerprint, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (asset_id, caller_id, fingerprint, timestamp),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def trace_fingerprint(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        """Look up a fingerprint to find who received it."""
        row = self._conn.execute(
            "SELECT * FROM fingerprint_records WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "asset_id": row["asset_id"],
            "caller_id": row["caller_id"],
            "fingerprint": row["fingerprint"],
            "timestamp": row["timestamp"],
            "created_at": row["created_at"],
        }

    def get_distributions(self, asset_id: str) -> List[Dict[str, Any]]:
        """Return all distribution records for an asset."""
        rows = self._conn.execute(
            "SELECT * FROM fingerprint_records WHERE asset_id = ? ORDER BY timestamp",
            (asset_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "asset_id": r["asset_id"],
                "caller_id": r["caller_id"],
                "fingerprint": r["fingerprint"],
                "timestamp": r["timestamp"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

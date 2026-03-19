"""
Provider cache for offline mode.

SQLite-backed cache of Provider metadata with TTL support.
Allows browsing providers when the network is unavailable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import threading
from pathlib import Path
from typing import Optional


DEFAULT_TTL = 3600  # 1 hour
DEFAULT_DB_PATH = os.path.join(str(Path.home()), ".oasyce", "provider_cache.db")


class ProviderCache:
    """SQLite cache for Provider metadata with TTL-based expiry."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH, default_ttl: int = DEFAULT_TTL):
        self.db_path = db_path
        self.default_ttl = default_ttl
        self._lock = threading.Lock()

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_cache (
                provider_id TEXT PRIMARY KEY,
                metadata    TEXT NOT NULL,
                cached_at   REAL NOT NULL,
                ttl         INTEGER NOT NULL,
                source      TEXT DEFAULT 'network'
            )
        """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_provider_cached_at
            ON provider_cache(cached_at)
        """
        )
        self._conn.commit()

    def cache_provider(self, provider_id: str, metadata: dict, ttl: Optional[int] = None):
        """Cache or update a provider's metadata."""
        if ttl is None:
            ttl = self.default_ttl
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO provider_cache
                   (provider_id, metadata, cached_at, ttl, source)
                   VALUES (?, ?, ?, ?, ?)""",
                (provider_id, json.dumps(metadata), time.time(), ttl, "network"),
            )
            self._conn.commit()

    def cache_many(self, providers: list[dict], ttl: Optional[int] = None):
        """Batch cache multiple providers. Each dict must have 'provider_id'."""
        if ttl is None:
            ttl = self.default_ttl
        now = time.time()
        with self._lock:
            self._conn.executemany(
                """INSERT OR REPLACE INTO provider_cache
                   (provider_id, metadata, cached_at, ttl, source)
                   VALUES (?, ?, ?, ?, ?)""",
                [(p["provider_id"], json.dumps(p), now, ttl, "network") for p in providers],
            )
            self._conn.commit()

    def get_cached_provider(self, provider_id: str, ignore_ttl: bool = False) -> Optional[dict]:
        """Get a cached provider. Returns None if missing or expired (unless ignore_ttl)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT metadata, cached_at, ttl FROM provider_cache WHERE provider_id = ?",
                (provider_id,),
            ).fetchone()

        if row is None:
            return None

        metadata = json.loads(row["metadata"])
        cached_at = row["cached_at"]
        ttl = row["ttl"]

        if not ignore_ttl and time.time() - cached_at > ttl:
            return None  # expired

        metadata["_cached_at"] = cached_at
        metadata["_expired"] = time.time() - cached_at > ttl
        return metadata

    def get_all_cached(self, include_expired: bool = False) -> list[dict]:
        """Get all cached providers. By default excludes expired entries."""
        now = time.time()
        with self._lock:
            rows = self._conn.execute(
                "SELECT provider_id, metadata, cached_at, ttl FROM provider_cache ORDER BY cached_at DESC"
            ).fetchall()

        results = []
        for row in rows:
            cached_at = row["cached_at"]
            ttl = row["ttl"]
            expired = now - cached_at > ttl

            if not include_expired and expired:
                continue

            metadata = json.loads(row["metadata"])
            metadata["_cached_at"] = cached_at
            metadata["_expired"] = expired
            results.append(metadata)

        return results

    def remove_provider(self, provider_id: str):
        """Remove a single provider from cache."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM provider_cache WHERE provider_id = ?",
                (provider_id,),
            )
            self._conn.commit()

    def clear(self):
        """Clear all cached providers."""
        with self._lock:
            self._conn.execute("DELETE FROM provider_cache")
            self._conn.commit()

    def purge_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        now = time.time()
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM provider_cache WHERE (? - cached_at) > ttl",
                (now,),
            )
            self._conn.commit()
            return cursor.rowcount

    def stats(self) -> dict:
        """Return cache statistics."""
        now = time.time()
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM provider_cache").fetchone()[0]
            expired = self._conn.execute(
                "SELECT COUNT(*) FROM provider_cache WHERE (? - cached_at) > ttl",
                (now,),
            ).fetchone()[0]
        return {
            "total": total,
            "active": total - expired,
            "expired": expired,
            "db_path": self.db_path,
            "default_ttl": self.default_ttl,
        }

    def close(self):
        """Close the database connection."""
        self._conn.close()

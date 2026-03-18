"""
Capability Endpoint Registry — providers register their API endpoints.

Providers supply:
  - endpoint_url: the HTTP endpoint to call
  - api_key: encrypted at rest, never exposed to consumers
  - pricing: per-invocation price in OAS units
  - rate_limit: max calls per minute (provider self-declared)
  - input_schema / output_schema: JSON Schema for validation

Anyone with a spare API key or idle compute can list their capability.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Lazy import to avoid circular dependency — the validation function lives in
# the gateway module.  We import at call-site instead.


logger = logging.getLogger(__name__)


# ── Encryption helpers (AES-GCM via cryptography lib) ────────────

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from passphrase + salt."""
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    return kdf.derive(passphrase.encode())


def _encrypt_api_key(api_key: str, passphrase: str) -> str:
    """Encrypt an API key. Returns hex(salt + nonce + ciphertext + tag)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = os.urandom(16)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, api_key.encode(), None)
    return (salt + nonce + ct).hex()


def _decrypt_api_key(encrypted_hex: str, passphrase: str) -> str:
    """Decrypt an API key from hex(salt + nonce + ciphertext + tag)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = bytes.fromhex(encrypted_hex)
    salt = raw[:16]
    nonce = raw[16:28]
    ct = raw[28:]
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode()


# ── Data model ───────────────────────────────────────────────────


@dataclass
class CapabilityEndpoint:
    """A registered capability endpoint — what a provider puts on the market.

    Attributes:
        capability_id: Unique identifier for this capability listing.
        provider_id:   Public key / address of the provider.
        name:          Human-readable name (e.g. "GPT-4 Translation").
        endpoint_url:  HTTP URL to invoke (POST).
        api_key_enc:   Encrypted API key (never exposed to consumers).
        price_per_call: Price per invocation in OAS integer units.
        rate_limit:    Max calls per minute (0 = unlimited).
        input_schema:  JSON Schema for request validation.
        output_schema: JSON Schema for response validation.
        tags:          Discovery tags.
        description:   Free-text description.
        status:        active / suspended / delisted.
        created_at:    Registration timestamp.
        total_calls:   Lifetime invocation count.
        total_earned:  Lifetime earnings in OAS units.
        avg_latency_ms: Rolling average response time.
        success_rate:  Rolling success rate (0.0–1.0).
    """
    capability_id: str
    provider_id: str
    name: str
    endpoint_url: str
    api_key_enc: str = ""          # encrypted
    price_per_call: int = 0        # OAS units
    rate_limit: int = 60           # calls/minute, 0=unlimited
    input_schema: str = "{}"       # JSON string
    output_schema: str = "{}"      # JSON string
    tags: str = "[]"               # JSON array string
    description: str = ""
    status: str = "active"
    created_at: int = 0
    total_calls: int = 0
    total_earned: int = 0
    avg_latency_ms: float = 0.0
    success_rate: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "name": self.name,
            "endpoint_url": self.endpoint_url,
            "price_per_call": self.price_per_call,
            "rate_limit": self.rate_limit,
            "input_schema": json.loads(self.input_schema),
            "output_schema": json.loads(self.output_schema),
            "tags": json.loads(self.tags),
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "total_calls": self.total_calls,
            "total_earned": self.total_earned,
            "avg_latency_ms": self.avg_latency_ms,
            "success_rate": self.success_rate,
            # Never expose api_key_enc
        }


# Minimum balance a provider must hold to register a capability (Sybil barrier).
# 100 OAS in integer units (1 OAS = 10^8 units).
MIN_PROVIDER_STAKE = 100_00000000


# ── Registry (SQLite-backed) ────────────────────────────────────


class EndpointRegistry:
    """Stores and manages capability endpoints.

    API keys are encrypted with a node-local passphrase before storage.
    The passphrase never leaves the node.
    """

    def __init__(self, db_path: str = ":memory:",
                 encryption_passphrase: Optional[str] = None,
                 allow_private: bool = False,
                 balances=None):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        if db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._passphrase = encryption_passphrase or self._load_or_create_passphrase()
        self._allow_private = allow_private
        self._balances = balances
        self._create_tables()

    def _load_or_create_passphrase(self) -> str:
        """Load persisted passphrase from ~/.oasyce/encryption_key, or create one.

        If no passphrase file exists, generates a random 32-byte hex token,
        writes it to ~/.oasyce/encryption_key with 0600 permissions, and
        logs a warning suggesting the user set one explicitly.
        """
        key_path = Path.home() / ".oasyce" / "encryption_key"
        if key_path.exists():
            return key_path.read_text().strip()

        # Auto-generate
        passphrase = secrets.token_hex(32)
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(passphrase)
        os.chmod(str(key_path), 0o600)
        logger.warning(
            "Auto-generated encryption passphrase stored at %s. "
            "Consider setting an explicit passphrase via the "
            "encryption_passphrase parameter for production use.",
            key_path,
        )
        return passphrase

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS capability_endpoints (
                capability_id TEXT PRIMARY KEY,
                provider_id TEXT NOT NULL,
                name TEXT NOT NULL,
                endpoint_url TEXT NOT NULL,
                api_key_enc TEXT NOT NULL DEFAULT '',
                price_per_call INTEGER NOT NULL DEFAULT 0,
                rate_limit INTEGER NOT NULL DEFAULT 60,
                input_schema TEXT NOT NULL DEFAULT '{}',
                output_schema TEXT NOT NULL DEFAULT '{}',
                tags TEXT NOT NULL DEFAULT '[]',
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL DEFAULT 0,
                total_calls INTEGER NOT NULL DEFAULT 0,
                total_earned INTEGER NOT NULL DEFAULT 0,
                avg_latency_ms REAL NOT NULL DEFAULT 0.0,
                success_rate REAL NOT NULL DEFAULT 1.0
            );
            CREATE INDEX IF NOT EXISTS idx_cap_provider
                ON capability_endpoints(provider_id);
            CREATE INDEX IF NOT EXISTS idx_cap_status
                ON capability_endpoints(status);
        """)

    def register(self, endpoint_url: str, api_key: str,
                 provider_id: str, name: str,
                 price_per_call: int = 0,
                 rate_limit: int = 60,
                 input_schema: Optional[Dict] = None,
                 output_schema: Optional[Dict] = None,
                 tags: Optional[List[str]] = None,
                 description: str = "",
                 capability_id: Optional[str] = None) -> Dict[str, Any]:
        """Register a new capability endpoint.

        The API key is encrypted before storage.

        Returns:
            {"ok": True, "capability_id": "..."} on success.
            {"ok": False, "error": "..."} on failure.
        """
        if not endpoint_url:
            return {"ok": False, "error": "endpoint_url required"}

        # SSRF protection: reject private/internal endpoint URLs at registration time
        if not self._allow_private:
            from oasyce_plugin.services.capability_delivery.gateway import _validate_endpoint_url
            if not _validate_endpoint_url(endpoint_url):
                return {"ok": False, "error": "endpoint URL blocked: private/internal address not allowed"}

        if not provider_id:
            return {"ok": False, "error": "provider_id required"}
        if not name:
            return {"ok": False, "error": "name required"}
        # price_per_call >= 0 is explicitly allowed: free capabilities (price=0)
        # skip escrow in the settlement protocol and are invoked directly.
        if price_per_call < 0:
            return {"ok": False, "error": "price_per_call must be non-negative"}

        # Sybil protection: require minimum stake if balances are available
        if self._balances is not None:
            provider_balance = self._balances.get_balance(provider_id, "OAS")
            if provider_balance < MIN_PROVIDER_STAKE:
                return {
                    "ok": False,
                    "error": "insufficient stake: providers must hold at least 100 OAS",
                }

        # Generate capability_id from content hash if not provided
        if not capability_id:
            raw = f"{provider_id}:{name}:{endpoint_url}:{int(time.time())}"
            capability_id = "CAP_" + hashlib.sha256(raw.encode()).hexdigest()[:16].upper()

        # Encrypt API key
        api_key_enc = ""
        if api_key:
            api_key_enc = _encrypt_api_key(api_key, self._passphrase)

        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM capability_endpoints WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
            if existing:
                return {"ok": False, "error": f"capability_id {capability_id} already exists"}

            self._conn.execute("""
                INSERT INTO capability_endpoints
                    (capability_id, provider_id, name, endpoint_url, api_key_enc,
                     price_per_call, rate_limit, input_schema, output_schema,
                     tags, description, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """, (
                capability_id, provider_id, name, endpoint_url, api_key_enc,
                price_per_call, rate_limit,
                json.dumps(input_schema or {}),
                json.dumps(output_schema or {}),
                json.dumps(tags or []),
                description,
                int(time.time()),
            ))
            self._conn.commit()

        return {"ok": True, "capability_id": capability_id}

    def get(self, capability_id: str) -> Optional[CapabilityEndpoint]:
        """Get a capability endpoint by ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM capability_endpoints WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_endpoint(row)

    def get_api_key(self, capability_id: str) -> Optional[str]:
        """Decrypt and return the API key for a capability. Internal use only."""
        with self._lock:
            row = self._conn.execute(
                "SELECT api_key_enc FROM capability_endpoints WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
        if not row or not row["api_key_enc"]:
            return None
        return _decrypt_api_key(row["api_key_enc"], self._passphrase)

    def list_active(self, provider_id: Optional[str] = None,
                    tag: Optional[str] = None,
                    limit: int = 50) -> List[CapabilityEndpoint]:
        """List active capability endpoints with optional filters."""
        query = "SELECT * FROM capability_endpoints WHERE status = 'active'"
        params: List[Any] = []

        if provider_id:
            query += " AND provider_id = ?"
            params.append(provider_id)

        if tag:
            query += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')

        query += " ORDER BY total_calls DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_endpoint(r) for r in rows]

    def update_stats(self, capability_id: str,
                     latency_ms: float, success: bool,
                     earned: int = 0) -> None:
        """Update invocation statistics for a capability."""
        with self._lock:
            row = self._conn.execute(
                "SELECT total_calls, avg_latency_ms, success_rate, total_earned "
                "FROM capability_endpoints WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
            if not row:
                return

            n = row["total_calls"]
            old_latency = row["avg_latency_ms"]
            old_rate = row["success_rate"]
            old_earned = row["total_earned"]

            new_n = n + 1
            new_latency = (old_latency * n + latency_ms) / new_n
            new_rate = (old_rate * n + (1.0 if success else 0.0)) / new_n

            self._conn.execute("""
                UPDATE capability_endpoints
                SET total_calls = ?, avg_latency_ms = ?, success_rate = ?,
                    total_earned = ?
                WHERE capability_id = ?
            """, (new_n, new_latency, new_rate, old_earned + earned,
                  capability_id))
            self._conn.commit()

    def suspend(self, capability_id: str) -> bool:
        """Suspend a capability (e.g. due to quality issues)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE capability_endpoints SET status = 'suspended' "
                "WHERE capability_id = ? AND status = 'active'",
                (capability_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delist(self, capability_id: str) -> bool:
        """Permanently delist a capability."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE capability_endpoints SET status = 'delisted' "
                "WHERE capability_id = ?",
                (capability_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_endpoint(row: sqlite3.Row) -> CapabilityEndpoint:
        return CapabilityEndpoint(
            capability_id=row["capability_id"],
            provider_id=row["provider_id"],
            name=row["name"],
            endpoint_url=row["endpoint_url"],
            api_key_enc=row["api_key_enc"],
            price_per_call=row["price_per_call"],
            rate_limit=row["rate_limit"],
            input_schema=row["input_schema"],
            output_schema=row["output_schema"],
            tags=row["tags"],
            description=row["description"],
            status=row["status"],
            created_at=row["created_at"],
            total_calls=row["total_calls"],
            total_earned=row["total_earned"],
            avg_latency_ms=row["avg_latency_ms"],
            success_rate=row["success_rate"],
        )

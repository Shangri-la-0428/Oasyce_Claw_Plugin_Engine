"""
Settlement Protocol — ties together escrow, gateway, and registry.

This is the top-level orchestrator for capability invocations:

  1. Consumer requests invocation
  2. Protocol locks escrow (consumer pays upfront)
  3. Gateway calls provider endpoint
  4. On success: release escrow → provider gets paid, stats updated
  5. On failure: refund escrow → consumer gets money back
  6. On timeout: auto-expire escrow → consumer refunded

The settlement protocol is the single entry point for all
capability invocations — no one calls the gateway directly.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from oasyce_plugin.services.capability_delivery.escrow import EscrowLedger
from oasyce_plugin.services.capability_delivery.gateway import (
    InvocationGateway,
    InvocationResult,
)
from oasyce_plugin.services.capability_delivery.registry import EndpointRegistry


class InvocationStatus(str, Enum):
    PENDING = "pending"       # escrow locked, not yet called
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"       # call succeeded, escrow released
    FAILED = "failed"         # call failed, escrow refunded
    TIMEOUT = "timeout"       # TTL expired, escrow auto-refunded
    DISPUTED = "disputed"     # consumer disputes quality


@dataclass
class InvocationRecord:
    """Immutable record of a capability invocation."""
    invocation_id: str
    capability_id: str
    consumer_id: str
    provider_id: str
    amount: int                    # OAS units paid
    status: str
    input_hash: str                # SHA-256 of input (privacy)
    output_hash: str = ""          # SHA-256 of output
    escrow_id: str = ""
    latency_ms: float = 0.0
    provider_earned: int = 0       # after protocol fee
    protocol_fee: int = 0
    created_at: int = 0
    settled_at: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "capability_id": self.capability_id,
            "consumer_id": self.consumer_id,
            "provider_id": self.provider_id,
            "amount": self.amount,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "provider_earned": self.provider_earned,
            "protocol_fee": self.protocol_fee,
            "created_at": self.created_at,
            "settled_at": self.settled_at,
            "error": self.error,
        }


class SettlementProtocol:
    """Orchestrates the full invoke-and-settle lifecycle.

    Usage:
        protocol = SettlementProtocol(registry, escrow, gateway)
        result = protocol.invoke("CAP_ABC", "consumer-addr", {"text": "hi"})
        # result["ok"] == True → invocation succeeded, escrow released
        # result["ok"] == False → invocation failed, escrow refunded
    """

    _DEFAULT_DB_PATH = os.path.join("~", ".oasyce", "settlement.db")

    def __init__(self, registry: EndpointRegistry,
                 escrow: EscrowLedger,
                 gateway: InvocationGateway,
                 db_path: str = ""):
        if not db_path:
            db_path = os.path.expanduser(self._DEFAULT_DB_PATH)
        if db_path != ":memory:":
            db_dir = os.path.dirname(db_path)
            os.makedirs(db_dir, exist_ok=True)
        self._registry = registry
        self._escrow = escrow
        self._gateway = gateway
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS invocations (
                invocation_id TEXT PRIMARY KEY,
                capability_id TEXT NOT NULL,
                consumer_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                output_hash TEXT NOT NULL DEFAULT '',
                escrow_id TEXT NOT NULL DEFAULT '',
                latency_ms REAL NOT NULL DEFAULT 0.0,
                provider_earned INTEGER NOT NULL DEFAULT 0,
                protocol_fee INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                settled_at INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_inv_consumer
                ON invocations(consumer_id);
            CREATE INDEX IF NOT EXISTS idx_inv_capability
                ON invocations(capability_id);
            CREATE INDEX IF NOT EXISTS idx_inv_provider
                ON invocations(provider_id);
        """)

    def invoke(self, capability_id: str, consumer_id: str,
               input_payload: Dict[str, Any],
               escrow_ttl: int = 300) -> Dict[str, Any]:
        """Full invoke-and-settle flow.

        Steps:
          1. Look up capability and price
          2. Lock escrow
          3. Call provider via gateway
          4. On success: release escrow, record settlement
          5. On failure: refund escrow, record failure

        Returns:
            {
                "ok": bool,
                "invocation_id": str,
                "output": dict,           # provider response (on success)
                "latency_ms": float,
                "amount": int,            # total paid
                "provider_earned": int,   # provider's share
                "protocol_fee": int,      # protocol's cut
                "error": str,             # error message (on failure)
            }
        """
        import hashlib
        import json

        # Step 1: Look up capability
        endpoint = self._registry.get(capability_id)
        if not endpoint:
            return {"ok": False, "error": f"capability not found: {capability_id}"}
        if endpoint.status != "active":
            return {"ok": False, "error": f"capability is {endpoint.status}"}

        price = endpoint.price_per_call
        invocation_id = f"INV_{uuid.uuid4().hex[:16].upper()}"
        input_hash = hashlib.sha256(
            json.dumps(input_payload, sort_keys=True).encode()
        ).hexdigest()

        # Step 2: Lock escrow
        escrow_result = self._escrow.lock(
            consumer_id=consumer_id,
            provider_id=endpoint.provider_id,
            capability_id=capability_id,
            amount=price,
            invocation_id=invocation_id,
            ttl=escrow_ttl,
        )
        if not escrow_result["ok"]:
            return {"ok": False, "error": f"escrow lock failed: {escrow_result['error']}"}

        escrow_id = escrow_result["escrow_id"]
        escrow_auth_token = escrow_result["auth_token"]

        # Record pending invocation
        self._record_invocation(InvocationRecord(
            invocation_id=invocation_id,
            capability_id=capability_id,
            consumer_id=consumer_id,
            provider_id=endpoint.provider_id,
            amount=price,
            status=InvocationStatus.IN_PROGRESS,
            input_hash=input_hash,
            escrow_id=escrow_id,
            created_at=int(time.time()),
        ))

        # Step 3: Call provider
        result = self._gateway.invoke(
            capability_id, input_payload, consumer_id,
        )

        # Step 4/5: Settle
        if result.success:
            return self._settle_success(
                invocation_id, escrow_id, result, input_hash,
                escrow_auth_token,
            )
        else:
            return self._settle_failure(
                invocation_id, escrow_id, result,
                escrow_auth_token,
            )

    def _settle_success(self, invocation_id: str, escrow_id: str,
                        result: InvocationResult,
                        input_hash: str,
                        escrow_auth_token: str = "") -> Dict[str, Any]:
        """Release escrow and record successful settlement."""
        import hashlib
        import json

        release = self._escrow.release(escrow_id, auth_token=escrow_auth_token)
        if not release["ok"]:
            # Escrow release failed (shouldn't happen) — treat as failure
            return self._settle_failure(
                invocation_id, escrow_id, result,
                escrow_auth_token,
            )

        output_hash = hashlib.sha256(
            json.dumps(result.output, sort_keys=True).encode()
        ).hexdigest()

        # Update invocation record
        with self._lock:
            self._conn.execute("""
                UPDATE invocations
                SET status = ?, output_hash = ?, latency_ms = ?,
                    provider_earned = ?, protocol_fee = ?, settled_at = ?
                WHERE invocation_id = ?
            """, (
                InvocationStatus.SUCCESS,
                output_hash,
                result.latency_ms,
                release["provider_amount"],
                release["protocol_fee"],
                int(time.time()),
                invocation_id,
            ))
            self._conn.commit()

        # Update registry stats
        self._registry.update_stats(
            release.get("capability_id", ""),
            latency_ms=result.latency_ms,
            success=True,
            earned=release["provider_amount"],
        )
        # Workaround: update_stats needs capability_id
        escrow_entry = self._escrow.get(escrow_id)
        if escrow_entry:
            self._registry.update_stats(
                escrow_entry.capability_id,
                latency_ms=result.latency_ms,
                success=True,
                earned=release["provider_amount"],
            )

        return {
            "ok": True,
            "invocation_id": invocation_id,
            "output": result.output,
            "latency_ms": result.latency_ms,
            "amount": release["amount"],
            "provider_earned": release["provider_amount"],
            "protocol_fee": release["protocol_fee"],
        }

    def _settle_failure(self, invocation_id: str, escrow_id: str,
                        result: InvocationResult,
                        escrow_auth_token: str = "") -> Dict[str, Any]:
        """Refund escrow and record failure."""
        refund = self._escrow.refund(escrow_id, auth_token=escrow_auth_token)

        error_msg = result.error or "invocation failed"
        with self._lock:
            self._conn.execute("""
                UPDATE invocations
                SET status = ?, latency_ms = ?, error = ?, settled_at = ?
                WHERE invocation_id = ?
            """, (
                InvocationStatus.FAILED,
                result.latency_ms,
                error_msg,
                int(time.time()),
                invocation_id,
            ))
            self._conn.commit()

        # Update registry stats (failure)
        escrow_entry = self._escrow.get(escrow_id)
        if escrow_entry:
            self._registry.update_stats(
                escrow_entry.capability_id,
                latency_ms=result.latency_ms,
                success=False,
            )

        return {
            "ok": False,
            "invocation_id": invocation_id,
            "error": error_msg,
            "latency_ms": result.latency_ms,
            "refunded": refund.get("ok", False),
            "refunded_amount": refund.get("refunded_amount", 0),
        }

    def get_invocation(self, invocation_id: str) -> Optional[InvocationRecord]:
        """Get an invocation record by ID."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM invocations WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def list_invocations(self, consumer_id: Optional[str] = None,
                         provider_id: Optional[str] = None,
                         capability_id: Optional[str] = None,
                         status: Optional[str] = None,
                         limit: int = 50) -> List[InvocationRecord]:
        """List invocation records with optional filters."""
        query = "SELECT * FROM invocations WHERE 1=1"
        params: list = []

        if consumer_id:
            query += " AND consumer_id = ?"
            params.append(consumer_id)
        if provider_id:
            query += " AND provider_id = ?"
            params.append(provider_id)
        if capability_id:
            query += " AND capability_id = ?"
            params.append(capability_id)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_record(r) for r in rows]

    def provider_earnings(self, provider_id: str) -> Dict[str, Any]:
        """Get total earnings for a provider."""
        with self._lock:
            row = self._conn.execute("""
                SELECT COUNT(*) as total_calls,
                       COALESCE(SUM(provider_earned), 0) as total_earned,
                       COALESCE(AVG(latency_ms), 0) as avg_latency,
                       COUNT(CASE WHEN status = 'success' THEN 1 END) as successes
                FROM invocations WHERE provider_id = ?
            """, (provider_id,)).fetchone()

        total = row["total_calls"]
        return {
            "provider_id": provider_id,
            "total_calls": total,
            "total_earned": row["total_earned"],
            "avg_latency_ms": round(row["avg_latency"], 2),
            "success_rate": round(row["successes"] / total, 4) if total > 0 else 0.0,
        }

    def consumer_spending(self, consumer_id: str) -> Dict[str, Any]:
        """Get total spending for a consumer."""
        with self._lock:
            row = self._conn.execute("""
                SELECT COUNT(*) as total_calls,
                       COALESCE(SUM(CASE WHEN status = 'success' THEN amount ELSE 0 END), 0)
                           as total_spent,
                       COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0)
                           as failed_calls
                FROM invocations WHERE consumer_id = ?
            """, (consumer_id,)).fetchone()

        return {
            "consumer_id": consumer_id,
            "total_calls": row["total_calls"],
            "total_spent": row["total_spent"],
            "failed_calls": row["failed_calls"],
        }

    def expire_stale_escrows(self) -> int:
        """Expire stale escrows and update corresponding invocations."""
        expired = self._escrow.expire_stale()
        if expired > 0:
            # Mark timed-out invocations
            with self._lock:
                self._conn.execute("""
                    UPDATE invocations
                    SET status = ?, settled_at = ?, error = 'escrow timeout'
                    WHERE status = 'in_progress'
                      AND escrow_id IN (
                          SELECT escrow_id FROM escrow WHERE status = 'expired'
                      )
                """, (InvocationStatus.TIMEOUT, int(time.time())))
                # Note: this cross-DB query won't work if escrow is on
                # a different DB. For now both use :memory: or same file.
                self._conn.commit()
        return expired

    def close(self) -> None:
        self._conn.close()

    def _record_invocation(self, record: InvocationRecord) -> None:
        with self._lock:
            self._conn.execute("""
                INSERT INTO invocations
                    (invocation_id, capability_id, consumer_id, provider_id,
                     amount, status, input_hash, output_hash, escrow_id,
                     latency_ms, provider_earned, protocol_fee,
                     created_at, settled_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.invocation_id, record.capability_id,
                record.consumer_id, record.provider_id,
                record.amount, record.status,
                record.input_hash, record.output_hash,
                record.escrow_id, record.latency_ms,
                record.provider_earned, record.protocol_fee,
                record.created_at, record.settled_at,
                record.error,
            ))
            self._conn.commit()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> InvocationRecord:
        return InvocationRecord(
            invocation_id=row["invocation_id"],
            capability_id=row["capability_id"],
            consumer_id=row["consumer_id"],
            provider_id=row["provider_id"],
            amount=row["amount"],
            status=row["status"],
            input_hash=row["input_hash"],
            output_hash=row["output_hash"],
            escrow_id=row["escrow_id"],
            latency_ms=row["latency_ms"],
            provider_earned=row["provider_earned"],
            protocol_fee=row["protocol_fee"],
            created_at=row["created_at"],
            settled_at=row["settled_at"],
            error=row["error"],
        )

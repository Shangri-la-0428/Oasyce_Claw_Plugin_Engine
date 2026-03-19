"""Escrow Manager for capability invocations.

Locks consumer funds during execution, then releases to provider
or refunds to consumer based on outcome.

State machine: LOCKED → RELEASED | REFUNDED | DISPUTED
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional


class EscrowState(str, enum.Enum):
    """Escrow lifecycle states."""

    LOCKED = "locked"
    RELEASED = "released"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


@dataclass
class EscrowRecord:
    """A single escrow entry."""

    escrow_id: str
    consumer_id: str
    amount: float
    invocation_id: str
    state: EscrowState = EscrowState.LOCKED
    created_at: int = field(default_factory=lambda: int(time.time()))
    resolved_at: Optional[int] = None


class EscrowError(Exception):
    """Raised on invalid escrow operations."""


class EscrowManager:
    """In-memory escrow ledger for capability invocations.

    Maintains consumer balances and escrow records.  Funds are locked
    on invocation and released/refunded on settlement.
    """

    def __init__(self) -> None:
        self._balances: Dict[str, float] = {}
        self._escrows: Dict[str, EscrowRecord] = {}

    # ── Balance management ────────────────────────────────────────────

    def deposit(self, consumer_id: str, amount: float) -> float:
        """Add funds to a consumer's balance.  Returns new balance."""
        if amount <= 0:
            raise EscrowError("deposit amount must be positive")
        self._balances[consumer_id] = self._balances.get(consumer_id, 0.0) + amount
        return self._balances[consumer_id]

    def balance(self, consumer_id: str) -> float:
        """Return the available (unlocked) balance for a consumer."""
        return self._balances.get(consumer_id, 0.0)

    # ── Core escrow operations ────────────────────────────────────────

    def lock(self, consumer_id: str, amount: float, invocation_id: str) -> str:
        """Lock funds from consumer balance into escrow.

        Returns:
            escrow_id — unique identifier for this escrow.

        Raises:
            EscrowError: insufficient balance or invalid amount.
        """
        if amount <= 0:
            raise EscrowError("escrow amount must be positive")
        available = self._balances.get(consumer_id, 0.0)
        if available < amount:
            raise EscrowError(f"insufficient balance: {available:.4f} < {amount:.4f}")

        self._balances[consumer_id] = available - amount
        escrow_id = uuid.uuid4().hex[:16]
        self._escrows[escrow_id] = EscrowRecord(
            escrow_id=escrow_id,
            consumer_id=consumer_id,
            amount=amount,
            invocation_id=invocation_id,
        )
        return escrow_id

    def release(self, escrow_id: str) -> EscrowRecord:
        """Release escrow — funds go to provider via settlement.

        Returns the finalized EscrowRecord.  The caller (invocation engine)
        is responsible for distributing the funds per fee split.
        """
        rec = self._require(escrow_id, EscrowState.LOCKED)
        rec.state = EscrowState.RELEASED
        rec.resolved_at = int(time.time())
        return rec

    def refund(self, escrow_id: str) -> EscrowRecord:
        """Refund escrowed funds back to consumer."""
        rec = self._require(escrow_id, EscrowState.LOCKED)
        rec.state = EscrowState.REFUNDED
        rec.resolved_at = int(time.time())
        self._balances[rec.consumer_id] = self._balances.get(rec.consumer_id, 0.0) + rec.amount
        return rec

    def dispute(self, escrow_id: str) -> EscrowRecord:
        """Mark escrow as disputed — funds remain locked pending resolution."""
        rec = self._require(escrow_id, EscrowState.LOCKED)
        rec.state = EscrowState.DISPUTED
        return rec

    def resolve_release(self, escrow_id: str) -> EscrowRecord:
        """Release a DISPUTED escrow (provider wins dispute)."""
        rec = self._require(escrow_id, EscrowState.DISPUTED)
        rec.state = EscrowState.RELEASED
        rec.resolved_at = int(time.time())
        return rec

    def resolve_refund(self, escrow_id: str) -> EscrowRecord:
        """Refund a DISPUTED escrow back to consumer (consumer wins dispute)."""
        rec = self._require(escrow_id, EscrowState.DISPUTED)
        rec.state = EscrowState.REFUNDED
        rec.resolved_at = int(time.time())
        self._balances[rec.consumer_id] = self._balances.get(rec.consumer_id, 0.0) + rec.amount
        return rec

    def get(self, escrow_id: str) -> Optional[EscrowRecord]:
        """Return the escrow record, or None if not found."""
        return self._escrows.get(escrow_id)

    # ── Internals ─────────────────────────────────────────────────────

    def _require(self, escrow_id: str, expected_state: EscrowState) -> EscrowRecord:
        """Fetch escrow and verify it is in the expected state."""
        rec = self._escrows.get(escrow_id)
        if rec is None:
            raise EscrowError(f"escrow not found: {escrow_id}")
        if rec.state != expected_state:
            raise EscrowError(
                f"escrow {escrow_id} is {rec.state.value}, expected {expected_state.value}"
            )
        return rec

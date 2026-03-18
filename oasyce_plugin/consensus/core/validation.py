"""
Pure validation functions for consensus operations.

These functions are pure — they read state but never modify it.
They return (True, None) on success or (False, error_message) on failure.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Dict, Optional, TYPE_CHECKING, Tuple

from oasyce_plugin.consensus.core.types import Operation, OperationType, MAX_COMMISSION_BPS

if TYPE_CHECKING:
    from oasyce_plugin.consensus import ConsensusEngine

# Signature enforcement toggle.
# Signatures are REQUIRED by default for all user-initiated operations.
# Set OASYCE_REQUIRE_SIGNATURES=0 to opt-out (local dev / testing ONLY).
# Evaluated dynamically so env var changes take effect without re-import.
def _require_signatures() -> bool:
    return os.environ.get("OASYCE_REQUIRE_SIGNATURES", "1") != "0"

MAX_TIMESTAMP_DRIFT: int = 300  # 5 minutes


# ── Nonce-based replay protection ─────────────────────────────────────


class NonceTracker:
    """Lightweight per-sender nonce tracker for replay protection.

    Tracks the last accepted nonce per sender address.  The first
    operation from any address must carry nonce=0, the second nonce=1,
    and so on.  Operations with an empty sender identity (no ``sender``
    and no ``from_addr``) bypass nonce validation because there is no
    identity to track against.

    If *db_path* is provided, nonces are persisted to a SQLite database
    so that replay protection survives node restarts.  When *db_path* is
    ``None`` (the default), nonces are kept only in memory — suitable
    for tests and backward compatibility.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._nonces: Dict[str, int] = {}
        self._db: Optional[sqlite3.Connection] = None
        if db_path is not None:
            if db_path != ":memory:":
                db_dir = os.path.dirname(db_path)
                if db_dir:
                    os.makedirs(db_dir, exist_ok=True)
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            if db_path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS nonces "
                "(address TEXT PRIMARY KEY, last_nonce INTEGER NOT NULL)"
            )
            self._db.commit()
            # Warm the in-memory cache from the database
            for row in self._db.execute("SELECT address, last_nonce FROM nonces"):
                self._nonces[row[0]] = row[1]

    def validate_nonce(self, sender: str, nonce: int) -> Tuple[bool, str]:
        """Check that *nonce* is the expected next value for *sender*.

        For a new sender (not yet tracked), nonce must be 0.
        For an existing sender, nonce must equal last_nonce + 1.
        If *sender* is empty, validation is skipped (no identity to
        protect against replay).
        """
        if not sender:
            return True, ""
        if sender not in self._nonces:
            # First operation from this sender — must use nonce 0.
            if nonce != 0:
                return False, (
                    f"nonce mismatch for {sender}: "
                    f"expected 0 (first operation), got {nonce}"
                )
            return True, ""
        expected = self._nonces[sender] + 1
        if nonce != expected:
            return False, (
                f"nonce mismatch for {sender}: "
                f"expected {expected}, got {nonce}"
            )
        return True, ""

    def advance(self, sender: str, nonce: int) -> None:
        """Record a successfully applied nonce for *sender*."""
        if sender:
            self._nonces[sender] = nonce
            if self._db is not None:
                self._db.execute(
                    "INSERT INTO nonces (address, last_nonce) VALUES (?, ?) "
                    "ON CONFLICT(address) DO UPDATE SET last_nonce = excluded.last_nonce",
                    (sender, nonce),
                )
                self._db.commit()

    def get_nonce(self, sender: str) -> int:
        """Return the last accepted nonce for *sender* (-1 if unseen)."""
        return self._nonces.get(sender, -1)


# Module-level default tracker; engines may supply their own.
_default_nonce_tracker = NonceTracker()


def get_default_nonce_tracker() -> NonceTracker:
    return _default_nonce_tracker


def _validate_signature(op: Operation) -> Tuple[bool, str]:
    """Validate Ed25519 signature on an operation.

    Skipped for system-generated operations (SLASH, REWARD) and when
    REQUIRE_SIGNATURES is False.
    """
    if op.op_type in (OperationType.SLASH, OperationType.REWARD):
        return True, ""
    if not _require_signatures():
        return True, ""
    if not op.sender:
        return False, "missing sender public key"
    if not op.signature:
        return False, "missing signature"
    from oasyce_plugin.consensus.core.signature import verify_signature
    if not verify_signature(op, op.signature, op.sender):
        return False, "invalid signature"
    if op.timestamp <= 0:
        return False, "missing or invalid timestamp"
    return True, ""


def validate_operation(engine: ConsensusEngine, op: Operation,
                       block_height: int = 0,
                       nonce_tracker: NonceTracker | None = None) -> Tuple[bool, str]:
    """Validate an operation against current state. Pure function.

    Returns:
        (True, "") if valid, (False, error_message) if invalid.
    """
    sig_ok, sig_err = _validate_signature(op)
    if not sig_ok:
        return False, sig_err

    # Chain ID replay protection: if op specifies a chain_id, it must match
    if op.chain_id and hasattr(engine, "chain_id") and op.chain_id != engine.chain_id:
        return False, f"chain_id mismatch: op={op.chain_id}, engine={engine.chain_id}"

    # Nonce-based replay protection
    tracker = nonce_tracker or getattr(engine, "_nonce_tracker", _default_nonce_tracker)
    nonce_ok, nonce_err = tracker.validate_nonce(op.sender or op.from_addr, op.nonce)
    if not nonce_ok:
        return False, nonce_err

    if op.op_type == OperationType.REGISTER:
        return _validate_register(engine, op)
    elif op.op_type == OperationType.DELEGATE:
        return _validate_delegate(engine, op)
    elif op.op_type == OperationType.UNDELEGATE:
        return _validate_undelegate(engine, op)
    elif op.op_type == OperationType.EXIT:
        return _validate_exit(engine, op)
    elif op.op_type == OperationType.UNJAIL:
        return _validate_unjail(engine, op)
    elif op.op_type == OperationType.SLASH:
        return True, ""  # Slash operations are system-generated
    elif op.op_type == OperationType.REWARD:
        return True, ""  # Reward operations are system-generated
    elif op.op_type == OperationType.TRANSFER:
        return _validate_transfer(engine, op)
    elif op.op_type == OperationType.REGISTER_ASSET:
        return _validate_register_asset(engine, op)
    else:
        return False, f"unknown operation type: {op.op_type}"


def _validate_register(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    if op.amount < engine.registry.min_stake:
        return False, f"self_stake {op.amount} below min {engine.registry.min_stake}"
    if not (0 <= op.commission_rate <= MAX_COMMISSION_BPS):
        return False, f"commission must be 0-{MAX_COMMISSION_BPS} bps"

    existing = engine.state.get_validator(op.validator_id)
    if existing:
        if existing["status"] == "exited":
            pending = engine.state.get_pending_unbondings(op.validator_id)
            if pending:
                return False, "cannot re-register: unbonding still in progress"
            return True, ""
        return False, "validator already registered"
    return True, ""


def _validate_delegate(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    if op.amount <= 0:
        return False, "amount must be positive"
    val = engine.state.get_validator(op.validator_id)
    if val is None:
        return False, "validator not found"
    if val["status"] not in ("active", "jailed"):
        return False, f"validator is {val['status']}, cannot delegate"
    return True, ""


def _validate_undelegate(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    if op.amount <= 0:
        return False, "amount must be positive"
    val = engine.state.get_validator(op.validator_id)
    if val is None:
        return False, "validator not found"
    current = engine.state.get_delegation_amount(op.from_addr, op.validator_id)
    if current <= 0:
        return False, "no delegation found"
    return True, ""


def _validate_exit(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    val = engine.state.get_validator(op.validator_id)
    if val is None:
        return False, "validator not found"
    if val["status"] == "exited":
        return False, "already exited"
    return True, ""


def _validate_unjail(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    val = engine.state.get_validator(op.validator_id)
    if val is None:
        return False, "validator not found"
    if val["status"] != "jailed":
        return False, f"validator is {val['status']}, not jailed"
    return True, ""


# ── Multi-asset validation ─────────────────────────────────────────


def _validate_transfer(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    """Validate a multi-asset transfer operation."""
    if op.amount <= 0:
        return False, "transfer amount must be positive"
    if not op.from_addr:
        return False, "transfer requires from_addr"
    if not op.to_addr:
        return False, "transfer requires to_addr"
    if op.from_addr == op.to_addr:
        return False, "cannot transfer to self"

    # Asset type must be registered
    if not engine.asset_registry.is_registered(op.asset_type):
        return False, f"unknown asset type: {op.asset_type}"

    # Check balance
    balance = engine.state.balances.get_balance(op.from_addr, op.asset_type)
    if balance < op.amount:
        return False, (
            f"insufficient {op.asset_type} balance: "
            f"have {balance}, need {op.amount}"
        )
    return True, ""


def _validate_register_asset(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    """Validate an asset registration operation."""
    if not op.asset_type:
        return False, "asset_type cannot be empty"
    if engine.asset_registry.is_registered(op.asset_type):
        return False, f"asset type '{op.asset_type}' already registered"
    if not op.from_addr:
        return False, "register_asset requires issuer (from_addr)"
    return True, ""

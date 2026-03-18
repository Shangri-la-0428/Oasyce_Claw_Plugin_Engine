"""
Ed25519 signature operations for consensus Operations.

Provides deterministic serialization, signing, and verification
of Operation objects using the existing crypto.keys module.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from oasyce_plugin.crypto.keys import sign as _ed25519_sign, verify as _ed25519_verify

if TYPE_CHECKING:
    from oasyce_plugin.consensus.core.types import Operation


def serialize_operation(op: Operation) -> bytes:
    """Deterministically serialize an Operation for signing.

    The signature and sender fields are excluded from the serialized
    payload (signature is what we're producing; sender is the public key
    used for verification and is bound externally).

    Returns:
        Canonical JSON encoded as UTF-8 bytes.
    """
    payload = {
        "op_type": op.op_type.value if hasattr(op.op_type, "value") else str(op.op_type),
        "validator_id": op.validator_id,
        "amount": op.amount,
        "asset_type": op.asset_type,
        "from_addr": op.from_addr,
        "to_addr": op.to_addr,
        "reason": op.reason,
        "commission_rate": op.commission_rate,
        "chain_id": op.chain_id,
        "timestamp": op.timestamp,
    }
    # sort_keys for deterministic output
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_operation(op: Operation, secret_key_hex: str) -> str:
    """Sign an Operation with an Ed25519 private key.

    Args:
        op: The operation to sign (signature field is ignored during serialization).
        secret_key_hex: Hex-encoded 32-byte Ed25519 private key.

    Returns:
        Signature as a hex string.
    """
    message = serialize_operation(op)
    return _ed25519_sign(message, secret_key_hex)


def verify_signature(op: Operation, signature_hex: str, public_key_hex: str) -> bool:
    """Verify an Ed25519 signature on an Operation.

    Args:
        op: The operation whose payload is verified.
        signature_hex: Hex-encoded signature.
        public_key_hex: Hex-encoded 32-byte Ed25519 public key.

    Returns:
        True if the signature is valid, False otherwise.
    """
    if not signature_hex or not public_key_hex:
        return False
    message = serialize_operation(op)
    return _ed25519_verify(message, signature_hex, public_key_hex)


def operation_hash(op: Operation) -> str:
    """Compute a SHA-256 digest of the serialized operation.

    Useful for deduplication and replay detection.
    """
    return hashlib.sha256(serialize_operation(op)).hexdigest()

"""
Evidence submission interface — the boundary between off-chain proofs and on-chain disputes.

Design philosophy (borrowed from Bitcoin):
    The protocol does NOT verify truth. It makes participants bear economic
    consequences for their CLAIMS about truth. Evidence providers (fingerprint,
    watermark, leakage scanners) produce evidence. The protocol settles disputes
    based on that evidence via stake-weighted jury votes.

This means:
    - Fingerprint, watermark, leakage detection are NOT core protocol.
    - They are EVIDENCE PROVIDERS: off-chain, probabilistic, replaceable.
    - The protocol only defines: submit_evidence(hash, type, weight).
    - Dispute resolution consumes evidence; it doesn't produce it.

Layer classification:
    Protocol (on-chain, must be deterministic):
        settlement, escrow, reputation, dispute
    Evidence providers (off-chain, probabilistic, pluggable):
        fingerprint, watermark, leakage, risk classification
    Product (off-chain, can be centralized):
        discovery, capability delivery, GUI, CLI
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class EvidenceType(str, Enum):
    """Types of evidence that can be submitted to support a dispute."""

    FINGERPRINT_MATCH = "fingerprint_match"  # Content fingerprint matched
    WATERMARK_DETECTED = "watermark_detected"  # Watermark found in unauthorized copy
    LEAKAGE_DETECTED = "leakage_detected"  # Data found outside authorized scope
    HASH_MISMATCH = "hash_mismatch"  # Content hash doesn't match registration
    RIGHTS_VIOLATION = "rights_violation"  # Rights type claim is incorrect
    QUALITY_FAILURE = "quality_failure"  # Capability output below threshold


@dataclass(frozen=True)
class Evidence:
    """A single piece of evidence for dispute resolution.

    Evidence is immutable once created. It carries a content hash (for
    verifiability), a type, a confidence weight, and optional metadata.

    The protocol does not interpret the evidence — it passes it to jurors
    who vote on the dispute outcome. The weight is advisory: jurors may
    assign their own weight based on the evidence type and source reputation.
    """

    evidence_hash: str  # SHA-256 of the underlying proof data
    evidence_type: EvidenceType
    weight: float = 1.0  # 0.0-1.0 confidence (advisory, not binding)
    source: str = ""  # Who produced this evidence (agent_id)
    metadata: Dict[str, Any] = field(default_factory=dict)

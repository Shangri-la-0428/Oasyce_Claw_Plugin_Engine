"""
Contribution Proof — Three-Layer Fingerprint Verification for Data Provenance

Verifies data contribution authenticity through:
  1. Content hash (SHA-256) — integrity proof
  2. Semantic fingerprint (embedding vector) — similarity detection
  3. Source evidence — provenance chain (TEE capture / API log / sensor sig / git commit)

Contribution score formula:
  Score = Originality × Rarity × Freshness

  Originality = 1 - max_similarity   (vs. existing assets)
  Rarity      = 1 / (1 + similar_count)
  Freshness   = 1 / (1 + days_since_creation / 365)
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ─── Source proof types ──────────────────────────────────────────


class SourceProof(str, Enum):
    """Supported provenance source types."""

    TEE_CAPTURE = "tee_capture"
    API_LOG = "api_log"
    SENSOR_SIG = "sensor_sig"
    GIT_COMMIT = "git_commit"
    MANUAL = "manual"


VALID_SOURCE_TYPES = {s.value for s in SourceProof}


# ─── ContributionCertificate ────────────────────────────────────


@dataclass(frozen=True)
class ContributionCertificate:
    """Immutable proof of data contribution."""

    content_hash: str  # SHA-256(file bytes)
    semantic_fingerprint: Optional[List[float]]  # embedding vector (None if unavailable)
    source_type: str  # SourceProof value
    source_evidence: str  # hash / signature / URL
    creator_key: str  # creator public key
    timestamp: int  # unix epoch seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "semantic_fingerprint": self.semantic_fingerprint,
            "source_type": self.source_type,
            "source_evidence": self.source_evidence,
            "creator_key": self.creator_key,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ContributionCertificate":
        return cls(
            content_hash=d["content_hash"],
            semantic_fingerprint=d.get("semantic_fingerprint"),
            source_type=d["source_type"],
            source_evidence=d.get("source_evidence", ""),
            creator_key=d["creator_key"],
            timestamp=d["timestamp"],
        )


# ─── ContributionEngine ────────────────────────────────────────


class ContributionEngine:
    """Generates and verifies data contribution proofs."""

    _SIMILARITY_THRESHOLD = 0.85  # cosine similarity above this counts as "similar"

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────

    def generate_proof(
        self,
        file_path: str,
        creator_key: str,
        source_type: str = "manual",
        source_evidence: str = "",
    ) -> ContributionCertificate:
        """Generate a contribution proof for a file.

        Args:
            file_path: Path to the data file.
            creator_key: Creator's public key.
            source_type: One of SourceProof values.
            source_evidence: Supporting evidence (hash/sig/URL).

        Returns:
            A frozen ContributionCertificate.

        Raises:
            FileNotFoundError: if file_path does not exist.
            ValueError: if source_type is invalid.
        """
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(
                f"Invalid source_type '{source_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}"
            )

        content_hash = self._compute_content_hash(file_path)
        semantic_fp = self._generate_semantic_fingerprint(file_path)

        return ContributionCertificate(
            content_hash=content_hash,
            semantic_fingerprint=semantic_fp,
            source_type=source_type,
            source_evidence=source_evidence,
            creator_key=creator_key,
            timestamp=int(time.time()),
        )

    def verify_proof(self, cert: ContributionCertificate, file_path: str) -> Dict[str, Any]:
        """Verify a contribution proof against a file.

        Checks:
          1. content_hash matches SHA-256 of current file
          2. timestamp is not in the future

        Returns:
            {"valid": bool, "checks": {"content_hash": bool, "timestamp": bool}}
        """
        current_hash = self._compute_content_hash(file_path)
        hash_ok = current_hash == cert.content_hash
        ts_ok = cert.timestamp <= int(time.time())

        return {
            "valid": hash_ok and ts_ok,
            "checks": {
                "content_hash": hash_ok,
                "timestamp": ts_ok,
            },
        }

    def calculate_contribution_score(
        self,
        cert: ContributionCertificate,
        existing_assets: List[Dict[str, Any]],
    ) -> float:
        """Calculate contribution score = originality × rarity × freshness.

        Args:
            cert: The contribution certificate to score.
            existing_assets: List of dicts with optional 'semantic_fingerprint'
                             and 'content_hash' keys.

        Returns:
            Score in range [0, 1].
        """
        originality = self._compute_originality(cert, existing_assets)
        rarity = self._compute_rarity(cert, existing_assets)
        freshness = self._compute_freshness(cert)

        score = originality * rarity * freshness
        return round(min(max(score, 0.0), 1.0), 6)

    # ── Internal helpers ───────────────────────────────────────

    @staticmethod
    def _compute_content_hash(file_path: str) -> str:
        """SHA-256 of file contents."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _generate_semantic_fingerprint(file_path: str) -> Optional[List[float]]:
        """Generate a lightweight semantic fingerprint from file content.

        Uses a simple hash-based approach (no ML dependency).
        Returns a 32-dim vector derived from content trigrams, or None
        if the file is empty or binary.
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="strict") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError):
            return None

        if not text.strip():
            return None

        dims = 32
        vector = [0.0] * dims
        text_lower = text.lower()
        for i in range(len(text_lower) - 2):
            trigram = text_lower[i : i + 3]
            idx = hash(trigram) % dims
            vector[idx] += 1.0

        # L2-normalise
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Cosine similarity between two vectors of equal length."""
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _compute_originality(
        self, cert: ContributionCertificate, existing: List[Dict[str, Any]]
    ) -> float:
        """Originality = 1 - max_similarity with existing assets."""
        if not cert.semantic_fingerprint or not existing:
            return 1.0

        max_sim = 0.0
        for asset in existing:
            vec = asset.get("semantic_fingerprint")
            if vec and len(vec) == len(cert.semantic_fingerprint):
                sim = self._cosine_similarity(cert.semantic_fingerprint, vec)
                if sim > max_sim:
                    max_sim = sim

        return max(1.0 - max_sim, 0.0)

    def _compute_rarity(
        self, cert: ContributionCertificate, existing: List[Dict[str, Any]]
    ) -> float:
        """Rarity = 1 / (1 + similar_count)."""
        if not cert.semantic_fingerprint or not existing:
            return 1.0

        similar_count = 0
        for asset in existing:
            vec = asset.get("semantic_fingerprint")
            if vec and len(vec) == len(cert.semantic_fingerprint):
                sim = self._cosine_similarity(cert.semantic_fingerprint, vec)
                if sim >= self._SIMILARITY_THRESHOLD:
                    similar_count += 1

        return 1.0 / (1.0 + similar_count)

    @staticmethod
    def _compute_freshness(cert: ContributionCertificate) -> float:
        """Freshness = 1 / (1 + days_since_creation / 365)."""
        now = time.time()
        days = max((now - cert.timestamp) / 86400, 0)
        return 1.0 / (1.0 + days / 365.0)


__all__ = [
    "SourceProof",
    "ContributionCertificate",
    "ContributionEngine",
]

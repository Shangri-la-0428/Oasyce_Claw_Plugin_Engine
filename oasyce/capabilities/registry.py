"""
Capability Registry — register, discover, and manage capability assets.

DEPRECATED: Local fallback only. The canonical capability registry lives
in the Go chain (x/capability). For capability delivery, use
DeliveryRegistry (oasyce.services.capability_delivery.registry).
Scheduled for removal.

Each node maintains a local registry. Discovery uses semantic similarity
(cosine of embedding vectors) + tag overlap, following the AHRP match_score pattern.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

from oasyce.capabilities.manifest import (
    CapabilityManifest,
    VALID_STATUSES,
    compute_capability_id,
)


class RegistryError(Exception):
    """Raised for registry operations that violate invariants."""


class CapabilityRegistry:
    """In-memory capability registry with search and version management."""

    def __init__(self) -> None:
        self._capabilities: Dict[str, CapabilityManifest] = {}

    # ── Core CRUD ─────────────────────────────────────────────────────────────

    def register(self, manifest: CapabilityManifest) -> str:
        """Register a capability. Returns capability_id.

        Raises RegistryError if validation fails or ID already exists.
        """
        errors = manifest.validate()
        if errors:
            raise RegistryError(f"Invalid manifest: {'; '.join(errors)}")

        # Ensure capability_id is computed
        if not manifest.capability_id:
            manifest.capability_id = compute_capability_id(
                manifest.provider, manifest.name, manifest.version
            )

        cid = manifest.capability_id
        if cid in self._capabilities:
            existing = self._capabilities[cid]
            if existing.status != "deprecated":
                raise RegistryError(
                    f"Capability '{cid}' already registered. "
                    "Use a different version to register a new one."
                )
            # Re-registering a deprecated capability — allow it
        self._capabilities[cid] = manifest
        return cid

    def get(self, capability_id: str) -> Optional[CapabilityManifest]:
        """Get manifest by ID. Returns None if not found."""
        return self._capabilities.get(capability_id)

    def update_status(self, capability_id: str, status: str) -> None:
        """Update capability status. Raises RegistryError if invalid."""
        if status not in VALID_STATUSES:
            raise RegistryError(
                f"Invalid status '{status}'. Must be one of {sorted(VALID_STATUSES)}"
            )
        manifest = self._capabilities.get(capability_id)
        if manifest is None:
            raise RegistryError(f"Capability '{capability_id}' not found")
        manifest.status = status
        manifest.updated_at = int(time.time())

    def unregister(self, capability_id: str) -> None:
        """Mark a capability as deprecated (does not delete)."""
        self.update_status(capability_id, "deprecated")

    # ── Query ─────────────────────────────────────────────────────────────────

    def list_by_provider(self, provider_id: str) -> List[CapabilityManifest]:
        """List all capabilities registered by a provider."""
        return [m for m in self._capabilities.values() if m.provider == provider_id]

    def search(
        self,
        query_tags: Optional[List[str]] = None,
        semantic_vector: Optional[List[float]] = None,
        limit: int = 10,
        include_deprecated: bool = False,
    ) -> List[Tuple[CapabilityManifest, float]]:
        """Search capabilities by tags and/or semantic vector.

        Returns list of (manifest, score) tuples sorted by score descending.
        Score is weighted: 60% semantic similarity + 40% tag overlap.
        """
        results: List[Tuple[CapabilityManifest, float]] = []

        for manifest in self._capabilities.values():
            if not include_deprecated and manifest.status == "deprecated":
                continue

            score = self._match_score(
                query_tags=query_tags or [],
                semantic_vector=semantic_vector,
                manifest=manifest,
            )
            if score > 0:
                results.append((manifest, score))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def list_all(self, include_deprecated: bool = False) -> List[CapabilityManifest]:
        """List all registered capabilities."""
        return [
            m for m in self._capabilities.values() if include_deprecated or m.status != "deprecated"
        ]

    @property
    def count(self) -> int:
        """Number of registered capabilities (including deprecated)."""
        return len(self._capabilities)

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(0.0, dot / (norm_a * norm_b))

    @staticmethod
    def _tag_overlap(query_tags: List[str], manifest_tags: List[str]) -> float:
        """Jaccard index of tag sets."""
        if not query_tags and not manifest_tags:
            return 0.0
        s1, s2 = set(query_tags), set(manifest_tags)
        union = s1 | s2
        if not union:
            return 0.0
        return len(s1 & s2) / len(union)

    @classmethod
    def _match_score(
        cls,
        query_tags: List[str],
        semantic_vector: Optional[List[float]],
        manifest: CapabilityManifest,
    ) -> float:
        """Calculate match score following AHRP pattern.

        60% semantic similarity + 40% tag overlap.
        Returns 0.0 if no signal at all.
        """
        sem_score = 0.0
        if semantic_vector and manifest.semantic_vector:
            sem_score = cls._cosine_similarity(semantic_vector, manifest.semantic_vector)

        tag_score = cls._tag_overlap(query_tags, manifest.tags)

        # If no search criteria provided, return small score for all
        has_signal = (semantic_vector and manifest.semantic_vector) or query_tags
        if not has_signal:
            return 0.0

        return 0.60 * sem_score + 0.40 * tag_score

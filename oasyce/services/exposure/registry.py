"""
Exposure Registry — Cumulative Access Tracking & Anti-Fragmentation

Tracks how much value each agent has been exposed to per asset,
preventing fragmentation attacks where an agent accumulates full
dataset access through many small requests.

Anti-fragmentation rule:
  E*(agent, dataset) = max(V_current, Σ V_i)

  Where V_i are the values of individual access requests.
  The effective exposure is always the greater of the latest single
  request or the cumulative total, ensuring that many small requests
  cost at least as much as one large one.

Exposure factor grows with cumulative exposure relative to asset value:
  ExposureFactor = 1 + (cumulative_exposure / asset_value)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from oasyce.services.access.config import AccessControlConfig


# ─── Access record ────────────────────────────────────────────────


@dataclass
class AccessRecord:
    """Single access event for exposure tracking."""

    exposure_value: float
    access_level: str
    timestamp: float = 0.0


# ─── ExposureRegistry ─────────────────────────────────────────────


class ExposureRegistry:
    """Tracks cumulative exposure per (agent, asset) pair.

    Provides an exposure factor that scales bond requirements when
    an agent repeatedly accesses the same dataset.
    """

    def __init__(self, config: Optional[AccessControlConfig] = None) -> None:
        self.config = config or AccessControlConfig()
        # (agent_id, asset_id) → list of access records
        self._records: Dict[str, List[AccessRecord]] = {}
        # (agent_id, asset_id) → latest registered asset value
        self._asset_values: Dict[str, float] = {}
        # Monotonic access counter — never decreases, guards against state resets
        self._total_access_count: int = 0
        self._lock = threading.Lock()

    # ─── Public API ───────────────────────────────────────────────

    def track_access(
        self,
        agent_id: str,
        asset_id: str,
        exposure_value: float,
        access_level: str,
    ) -> None:
        """Record an access event for the (agent, asset) pair.

        Raises:
            ValueError: if exposure_value <= 0.
        """
        if exposure_value <= 0:
            raise ValueError(f"Exposure value must be positive, got {exposure_value}")
        with self._lock:
            key = self._key(agent_id, asset_id)
            if key not in self._records:
                self._records[key] = []
            self._records[key].append(
                AccessRecord(exposure_value=exposure_value, access_level=access_level)
            )
            self._asset_values[key] = exposure_value
            self._total_access_count += 1

    def get_cumulative_exposure(self, agent_id: str, asset_id: str) -> float:
        """Return total exposure value across all access events."""
        with self._lock:
            key = self._key(agent_id, asset_id)
            records = self._records.get(key, [])
            return round(sum(r.exposure_value for r in records), 6)

    def get_exposure_factor(self, agent_id: str, asset_id: str) -> float:
        """Compute exposure scaling factor.

        ExposureFactor = 1 + (cumulative_exposure / asset_value)

        Returns 1.0 when the agent has no prior exposure to the asset.
        """
        key = self._key(agent_id, asset_id)
        asset_value = self._asset_values.get(key)
        if not asset_value or asset_value <= 0:
            return 1.0
        cumulative = self.get_cumulative_exposure(agent_id, asset_id)
        return round(1.0 + cumulative / asset_value, 6)

    def check_fragmentation_attack(self, agent_id: str, asset_id: str) -> bool:
        """Detect potential fragmentation attack.

        Returns True if the cumulative exposure across multiple requests
        exceeds the maximum single-request value — indicating the agent
        is accumulating access through many small requests.

        E*(agent, dataset) = max(V_current, Σ V_i)
        Attack detected when Σ V_i > max(V_i).
        """
        key = self._key(agent_id, asset_id)
        records = self._records.get(key, [])
        if len(records) <= 1:
            return False
        max_single = max(r.exposure_value for r in records)
        total = sum(r.exposure_value for r in records)
        return total > max_single

    def check_registration_fragmentation(
        self,
        new_asset_vector: list,
        new_asset_size: int,
        existing_assets: list,
        similarity_threshold: float = 0.8,
        size_ratio_threshold: float = 0.3,
    ) -> dict:
        """Check if a new asset is a potential fragment of an existing dataset.

        A fragment is detected when the new asset is semantically similar
        (cosine similarity > similarity_threshold) to an existing asset
        AND significantly smaller (size_ratio < size_ratio_threshold).

        Args:
            new_asset_vector: Semantic vector of the new asset.
            new_asset_size: File size (bytes) of the new asset.
            existing_assets: List of dicts with keys:
                asset_id, semantic_vector, file_size_bytes.
            similarity_threshold: Cosine similarity above which assets
                are considered semantically related.
            size_ratio_threshold: Size ratio below which the new asset
                is considered a fragment of the existing one.

        Returns:
            dict with 'is_fragment' (bool), 'warning' (str or None),
            and 'matches' (list of matching asset_ids).
        """
        if not new_asset_vector or new_asset_size <= 0:
            return {"is_fragment": False, "warning": None, "matches": []}

        matches = []
        for asset in existing_assets:
            vec = asset.get("semantic_vector")
            size = asset.get("file_size_bytes", 0)
            if not vec or size <= 0:
                continue
            if len(vec) != len(new_asset_vector):
                continue

            # Cosine similarity
            dot = sum(a * b for a, b in zip(new_asset_vector, vec))
            mag_a = sum(a * a for a in new_asset_vector) ** 0.5
            mag_b = sum(b * b for b in vec) ** 0.5
            if mag_a == 0 or mag_b == 0:
                continue
            sim = dot / (mag_a * mag_b)

            size_ratio = new_asset_size / size
            if sim > similarity_threshold and size_ratio < size_ratio_threshold:
                matches.append(asset.get("asset_id", "unknown"))

        if matches:
            return {
                "is_fragment": True,
                "warning": (
                    f"Potential fragment detected: new asset is semantically similar "
                    f"to {matches} but significantly smaller (possible data fragmentation)"
                ),
                "matches": matches,
            }
        return {"is_fragment": False, "warning": None, "matches": []}

    @property
    def total_access_count(self) -> int:
        """Monotonic counter of all tracked access events (integrity check)."""
        return self._total_access_count

    # ─── Internals ────────────────────────────────────────────────

    @staticmethod
    def _key(agent_id: str, asset_id: str) -> str:
        return f"{agent_id}:{asset_id}"

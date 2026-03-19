"""
Liability Window — Time-Locked Bond Release

Bonds posted for data access are locked for a configurable period
that scales with access level, giving time to detect misuse.

Release periods:
  L0 (Query)   →  1 day    (86 400 s)
  L1 (Sample)  →  3 days   (259 200 s)
  L2 (Compute) →  7 days   (604 800 s)
  L3 (Deliver) → 30 days   (2 592 000 s)

A bond can only be released after its window has elapsed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

from oasyce.services.access.config import AccessControlConfig


# ─── Bond record ──────────────────────────────────────────────────


@dataclass
class BondRecord:
    """A locked bond for a specific access event."""

    agent_id: str
    asset_id: str
    amount: float
    access_level: str
    locked_at: float  # epoch seconds
    release_after: float  # epoch seconds
    released: bool = False


# ─── LiabilityWindow ─────────────────────────────────────────────


class LiabilityWindow:
    """Manages time-locked bonds for data access events.

    Bonds are locked on access and released after the level-specific
    liability window has elapsed.
    """

    def __init__(self, config: Optional[AccessControlConfig] = None) -> None:
        self.config = config or AccessControlConfig()
        # (agent_id, asset_id) → BondRecord
        self._bonds: Dict[str, BondRecord] = {}
        self._lock = threading.Lock()

    # ─── Public API ───────────────────────────────────────────────

    def lock_bond(
        self,
        agent_id: str,
        asset_id: str,
        amount: float,
        access_level: str,
    ) -> BondRecord:
        """Lock a bond for the given access event.

        If an unreleased bond already exists for this (agent, asset) pair,
        raises ValueError — the existing bond must be released first.
        Released bonds are replaced normally.

        Raises:
            ValueError: if amount <= 0 or an active bond already exists.
        """
        if amount <= 0:
            raise ValueError(f"Bond amount must be positive, got {amount}")

        with self._lock:
            key = self._key(agent_id, asset_id)
            existing = self._bonds.get(key)
            if existing is not None and not existing.released:
                raise ValueError(
                    f"Active bond already exists for ({agent_id}, {asset_id}). "
                    f"Release or forfeit the existing bond before locking a new one."
                )

            now = time.time()
            window = self.config.window_for(access_level)
            record = BondRecord(
                agent_id=agent_id,
                asset_id=asset_id,
                amount=round(amount, 6),
                access_level=access_level,
                locked_at=now,
                release_after=now + window,
            )
            self._bonds[key] = record
            return record

    def get_release_time(self, agent_id: str, asset_id: str) -> Optional[float]:
        """Return the epoch timestamp when the bond becomes releasable.

        Returns None if no bond exists.
        """
        record = self._bonds.get(self._key(agent_id, asset_id))
        if record is None:
            return None
        return record.release_after

    def release_bond(self, agent_id: str, asset_id: str) -> bool:
        """Attempt to release the bond.

        Returns True if the bond was released, False if the window has
        not elapsed or no bond exists.
        """
        with self._lock:
            key = self._key(agent_id, asset_id)
            record = self._bonds.get(key)
            if record is None or record.released:
                return False
            if time.time() < record.release_after:
                return False
            record.released = True
            return True

    def get_bond(self, agent_id: str, asset_id: str) -> Optional[BondRecord]:
        """Return the bond record for (agent, asset), or None."""
        return self._bonds.get(self._key(agent_id, asset_id))

    # ─── Internals ────────────────────────────────────────────────

    @staticmethod
    def _key(agent_id: str, asset_id: str) -> str:
        return f"{agent_id}:{asset_id}"

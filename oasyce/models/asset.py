from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import uuid


class AssetStatus(str, Enum):
    """Lifecycle states for an on-chain asset (per whitepaper).

    Valid transitions (forward-only, except DISPUTED):
        PROOF_PENDING → VERIFIED → LISTED → TRADED → DISPUTED
        Any state can transition to DISPUTED.
    """

    PROOF_PENDING = "proof_pending"
    VERIFIED = "verified"
    LISTED = "listed"
    TRADED = "traded"
    DISPUTED = "disputed"


# Allowed forward transitions (DISPUTED can be reached from any state).
_FORWARD_ORDER: list[AssetStatus] = [
    AssetStatus.PROOF_PENDING,
    AssetStatus.VERIFIED,
    AssetStatus.LISTED,
    AssetStatus.TRADED,
]


@dataclass
class Asset:
    """A registered on-chain asset backed by a verified CapturePack."""

    asset_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    creator: str = ""
    media_hash: str = ""
    supply: int = 0  # current bonding-curve supply
    metadata: dict[str, str] = field(default_factory=dict)
    status: AssetStatus = AssetStatus.VERIFIED  # default for backward compat

    def transition_to(self, new_status: AssetStatus) -> None:
        """Transition the asset to a new lifecycle state.

        Rules:
            - DISPUTED can be reached from any state.
            - Other transitions must move forward in the lifecycle.
            - Cannot transition out of DISPUTED.

        Raises:
            ValueError: If the transition is invalid.
        """
        if self.status == AssetStatus.DISPUTED:
            raise ValueError("cannot transition out of DISPUTED state")

        if new_status == AssetStatus.DISPUTED:
            self.status = new_status
            return

        if new_status == self.status:
            raise ValueError(f"already in {self.status.value} state")

        try:
            cur_idx = _FORWARD_ORDER.index(self.status)
            new_idx = _FORWARD_ORDER.index(new_status)
        except ValueError:
            raise ValueError(f"invalid status: {new_status}")

        if new_idx <= cur_idx:
            raise ValueError(f"cannot go backward from {self.status.value} to {new_status.value}")

        self.status = new_status

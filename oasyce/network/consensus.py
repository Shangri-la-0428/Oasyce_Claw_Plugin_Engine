"""Consensus stub — actual consensus lives on the Go chain (oasyce-chain).

This module provides no-op implementations of ConsensusManager and RoundStatus
so that ``oasyce.network.node`` can import without error.  All real consensus,
voting, and finalization are handled by CometBFT on the Cosmos SDK appchain.
"""

from __future__ import annotations

import enum
from typing import Any, Optional


class RoundStatus(enum.Enum):
    """Possible outcomes of a consensus voting round."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ConsensusManager:
    """Stub that satisfies the Node interface — consensus is on-chain now."""

    def __init__(self, config: Any = None) -> None:
        self._rounds: dict[str, dict[str, Any]] = {}

    async def open_round(self, msg_id: str) -> None:
        if msg_id not in self._rounds:
            self._rounds[msg_id] = {
                "status": RoundStatus.PENDING,
                "votes": {},
            }

    async def cast_vote(
        self,
        msg_id: str,
        voter_id: str,
        accept: bool = True,
        reason: str = "",
    ) -> None:
        if msg_id in self._rounds:
            self._rounds[msg_id]["votes"][voter_id] = {
                "accept": accept,
                "reason": reason,
            }

    async def finalise(self, msg_id: str) -> RoundStatus:
        """Stub always returns ACCEPTED (real logic is on-chain)."""
        rd = self._rounds.get(msg_id)
        if rd is None:
            return RoundStatus.PENDING
        rd["status"] = RoundStatus.ACCEPTED
        return RoundStatus.ACCEPTED

    async def wait_for_result(self, msg_id: str) -> RoundStatus:
        rd = self._rounds.get(msg_id)
        if rd is None:
            return RoundStatus.PENDING
        return rd["status"]

    async def get_round(self, msg_id: str) -> Optional[dict[str, Any]]:
        return self._rounds.get(msg_id)

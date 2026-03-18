"""Governance data types — proposals, votes, parameter changes.

All monetary values in integer units (1 OAS = 10^8 units).
All types are frozen (immutable) dataclasses.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Constants ──────────────────────────────────────────────────────

DEFAULT_VOTING_PERIOD: int = 60480  # ~7 days at 10s blocks
DEFAULT_MIN_DEPOSIT: int = 100_000_000_000  # 1000 OAS in units
QUORUM_BPS: int = 4000  # 40% of total stake must participate
PASS_THRESHOLD_BPS: int = 6667  # 2/3 majority (66.67%)

# Modules whose parameters can NOT be changed via governance
UNGOVERNABLE_KEYS = frozenset({
    "chain_id",
    "crypto_algorithm",
})


# ── Enums ──────────────────────────────────────────────────────────

class ProposalStatus(str, Enum):
    DEPOSIT = "deposit"      # Awaiting deposit threshold
    ACTIVE = "active"        # Voting open
    PASSED = "passed"        # Tally passed, awaiting execution
    REJECTED = "rejected"    # Tally failed
    EXECUTED = "executed"    # Parameter changes applied
    EXPIRED = "expired"      # Voting period ended without quorum


class VoteOption(str, Enum):
    YES = "yes"
    NO = "no"
    ABSTAIN = "abstain"


# ── Data types ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParameterChange:
    """A single parameter change within a proposal."""
    module: str       # "consensus", "slashing", "rewards"
    key: str          # "BLOCK_REWARD", "MIN_STAKE", etc.
    old_value: Any
    new_value: Any

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module": self.module,
            "key": self.key,
            "old_value": self.old_value,
            "new_value": self.new_value,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ParameterChange:
        return cls(
            module=d["module"],
            key=d["key"],
            old_value=d["old_value"],
            new_value=d["new_value"],
        )


@dataclass(frozen=True)
class Vote:
    """A single vote on a proposal."""
    proposal_id: str
    voter: str
    option: VoteOption
    weight: int          # stake-weighted voting power (units)
    timestamp: int       # block height when cast

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "voter": self.voter,
            "option": self.option.value,
            "weight": self.weight,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class VoteResult:
    """Tally result for a proposal."""
    proposal_id: str
    yes_votes: int       # total weight
    no_votes: int
    abstain_votes: int
    total_voting_power: int  # total stake at time of tally
    quorum_reached: bool
    passed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "yes_votes": self.yes_votes,
            "no_votes": self.no_votes,
            "abstain_votes": self.abstain_votes,
            "total_voting_power": self.total_voting_power,
            "quorum_reached": self.quorum_reached,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class Proposal:
    """A governance proposal."""
    id: str                              # deterministic hash
    proposer: str                        # address
    title: str
    description: str
    changes: List[ParameterChange]       # parameters to modify
    deposit: int                         # units
    status: ProposalStatus
    voting_start: int                    # block height
    voting_end: int                      # block height
    created_at: int                      # block height
    snapshot_height: int = 0             # block height at proposal creation for voting power snapshot
    stake_snapshot: Optional[Dict[str, int]] = None  # {address: weight} at snapshot_height

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "proposer": self.proposer,
            "title": self.title,
            "description": self.description,
            "changes": [c.to_dict() for c in self.changes],
            "deposit": self.deposit,
            "status": self.status.value,
            "voting_start": self.voting_start,
            "voting_end": self.voting_end,
            "created_at": self.created_at,
            "snapshot_height": self.snapshot_height,
        }
        if self.stake_snapshot is not None:
            d["stake_snapshot"] = self.stake_snapshot
        return d


def compute_proposal_id(proposer: str, title: str,
                         changes: List[ParameterChange],
                         created_at: int) -> str:
    """Deterministic proposal hash from content."""
    payload = json.dumps({
        "proposer": proposer,
        "title": title,
        "changes": [c.to_dict() for c in changes],
        "created_at": created_at,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()

"""
Proposer election — deterministic stake-weighted random leader selection.

Any node can independently compute and verify the leader schedule for an epoch.
Uses SHA-256 based deterministic randomness seeded by previous epoch data.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from oasyce_plugin.consensus.state import ConsensusState


def compute_epoch_seed(prev_block_hash: str, epoch_number: int) -> str:
    """Deterministic seed for an epoch based on previous epoch's last block hash."""
    data = f"{prev_block_hash}{epoch_number}"
    return hashlib.sha256(data.encode()).hexdigest()


def compute_slot_seed(epoch_seed: str, slot_index: int) -> str:
    """Deterministic seed for a specific slot."""
    data = f"{epoch_seed}{slot_index}"
    return hashlib.sha256(data.encode()).hexdigest()


def weighted_select(validators: List[Dict[str, Any]],
                    random_value: int) -> str:
    """Select a validator weighted by total_stake (integer arithmetic).

    Args:
        validators: List of validator dicts with 'validator_id' and 'total_stake'.
        random_value: An integer used for weighted random selection.

    Returns:
        The validator_id of the selected validator.
    """
    total = sum(v["total_stake"] for v in validators)
    if total <= 0:
        raise ValueError("No stake to select from")

    # Pure integer selection: map random_value into [0, total) using modulo
    target = random_value % total
    cumulative = 0
    for v in validators:
        cumulative += v["total_stake"]
        if target < cumulative:
            return v["validator_id"]
    return validators[-1]["validator_id"]


def compute_leader_schedule(
    validators: List[Dict[str, Any]],
    prev_block_hash: str,
    epoch_number: int,
    slots_per_epoch: int,
) -> List[Dict[str, Any]]:
    """Compute the full leader schedule for an epoch.

    Args:
        validators: Active validators with total_stake >= min_stake.
        prev_block_hash: Hash of the last block in the previous epoch.
        epoch_number: The epoch number to compute schedule for.
        slots_per_epoch: Number of slots in this epoch.

    Returns:
        List of {slot_index, validator_id} dicts.
    """
    if not validators:
        return []

    epoch_seed = compute_epoch_seed(prev_block_hash, epoch_number)
    schedule = []

    for i in range(slots_per_epoch):
        slot_seed = compute_slot_seed(epoch_seed, i)
        random_value = int(slot_seed[:16], 16)
        leader = weighted_select(validators, random_value)
        schedule.append({
            "slot_index": i,
            "validator_id": leader,
        })

    return schedule


class ProposerElection:
    """High-level proposer election that integrates with consensus state."""

    def __init__(self, state: ConsensusState, slots_per_epoch: int = 10,
                 min_stake: int = 10_000_000_000):
        self.state = state
        self.slots_per_epoch = slots_per_epoch
        self.min_stake = min_stake

    def elect_for_epoch(self, epoch_number: int,
                        prev_block_hash: str = "0" * 64) -> List[Dict[str, Any]]:
        """Compute and store leader schedule for an epoch."""
        validators = self.state.get_active_validators(self.min_stake)
        if not validators:
            return []

        schedule = compute_leader_schedule(
            validators, prev_block_hash, epoch_number, self.slots_per_epoch,
        )
        self.state.set_leader_schedule(epoch_number, schedule)
        return schedule

    def get_current_leader(self, epoch_number: int,
                           slot_index: int) -> str | None:
        """Get the designated leader for a specific slot."""
        return self.state.get_slot_leader(epoch_number, slot_index)

    def verify_proposer(self, epoch_number: int, slot_index: int,
                        validator_id: str) -> bool:
        """Verify that a validator is the legitimate proposer for a slot."""
        expected = self.state.get_slot_leader(epoch_number, slot_index)
        return expected == validator_id

    def get_backup_proposer(self, slot_index: int,
                            primary_proposer_id: str,
                            validators: List[Dict[str, Any]],
                            stakes: Optional[Dict[str, int]] = None) -> str | None:
        """Return the next validator by stake weight, excluding the primary.

        Args:
            slot_index: The slot index (unused in selection, kept for API clarity).
            primary_proposer_id: The validator to exclude.
            validators: Active validators with 'validator_id' and 'total_stake'.
            stakes: Optional override mapping validator_id -> stake.  If given,
                    these values replace the 'total_stake' field for ranking.

        Returns:
            The validator_id of the backup proposer, or None if no candidate.
        """
        candidates = [v for v in validators
                      if v["validator_id"] != primary_proposer_id]
        if not candidates:
            return None

        def _stake(v: Dict[str, Any]) -> int:
            if stakes:
                return stakes.get(v["validator_id"], v["total_stake"])
            return v["total_stake"]

        # Highest stake first; ties broken by validator_id for determinism
        candidates.sort(key=lambda v: (-_stake(v), v["validator_id"]))
        return candidates[0]["validator_id"]

    def get_schedule(self, epoch_number: int) -> List[Dict[str, Any]]:
        """Get the stored leader schedule for an epoch."""
        return self.state.get_leader_schedule(epoch_number)

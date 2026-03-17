"""
Epoch lifecycle management for Oasyce PoS consensus.

Handles epoch transitions, slot calculation, and epoch boundary processing
(finalization, unbonding releases, reward distribution triggers).
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from oasyce_plugin.consensus.state import ConsensusState


class EpochManager:
    """Manages epoch lifecycle: creation, slot tracking, finalization."""

    def __init__(self, state: ConsensusState, consensus_params: Dict[str, Any],
                 genesis_time: Optional[int] = None):
        self.state = state
        self.params = consensus_params
        self.genesis_time = genesis_time or self._resolve_genesis_time()
        # Always persist so subsequent restarts see the same value
        self.state.set_meta("genesis_time", str(self.genesis_time))

    def _resolve_genesis_time(self) -> int:
        """Derive genesis time from persisted meta, epoch 0, or current time."""
        # 1. Persisted meta (most reliable across restarts)
        stored = self.state.get_meta("genesis_time")
        if stored:
            return int(stored)
        # 2. First epoch record
        epoch = self.state.get_epoch(0)
        if epoch:
            return epoch["start_time"]
        # 3. Brand new network — use current time
        return int(time.time())

    @property
    def epoch_duration(self) -> int:
        return self.params["epoch_duration"]

    @property
    def slots_per_epoch(self) -> int:
        return self.params["slots_per_epoch"]

    @property
    def slot_duration(self) -> int:
        return self.params["slot_duration"]

    @property
    def unbonding_period(self) -> int:
        return self.params["unbonding_period"]

    def current_epoch(self, now: Optional[int] = None) -> int:
        now = now or int(time.time())
        return max(0, (now - self.genesis_time) // self.epoch_duration)

    def current_slot(self, now: Optional[int] = None) -> int:
        now = now or int(time.time())
        epoch_num = self.current_epoch(now)
        epoch_start = self.genesis_time + epoch_num * self.epoch_duration
        raw_slot = (now - epoch_start) // self.slot_duration
        return min(raw_slot, self.slots_per_epoch - 1)

    def epoch_start_time(self, epoch_number: int) -> int:
        return self.genesis_time + epoch_number * self.epoch_duration

    def epoch_end_time(self, epoch_number: int) -> int:
        return self.epoch_start_time(epoch_number) + self.epoch_duration

    def slot_start_time(self, epoch_number: int, slot_index: int) -> int:
        return self.epoch_start_time(epoch_number) + slot_index * self.slot_duration

    def time_until_next_epoch(self, now: Optional[int] = None) -> int:
        now = now or int(time.time())
        epoch_num = self.current_epoch(now)
        return self.epoch_end_time(epoch_num) - now

    def time_until_next_slot(self, now: Optional[int] = None) -> int:
        now = now or int(time.time())
        epoch_num = self.current_epoch(now)
        slot_num = self.current_slot(now)
        next_slot_time = self.slot_start_time(epoch_num, slot_num + 1)
        return max(0, next_slot_time - now)

    def ensure_epoch_exists(self, epoch_number: int,
                            start_block: int = 0,
                            validator_count: int = 0) -> Dict[str, Any]:
        """Ensure epoch record exists in state; create if missing."""
        existing = self.state.get_epoch(epoch_number)
        if existing:
            return existing
        start_time = self.epoch_start_time(epoch_number)
        self.state.create_epoch(
            epoch_number, start_time, start_block, validator_count,
        )
        return self.state.get_epoch(epoch_number)

    def finalize_epoch(self, epoch_number: int, end_block: int,
                       total_rewards: int) -> bool:
        """Mark an epoch as finalized with its final metrics."""
        end_time = self.epoch_end_time(epoch_number)
        return self.state.finalize_epoch(
            epoch_number, end_time, end_block, total_rewards,
        )

    def process_unbonding_queue(self, now: Optional[int] = None) -> int:
        """Release matured unbonding entries atomically. Returns count released."""
        now = now or int(time.time())
        return self.state.release_matured_unbondings(now)

    def get_status(self, now: Optional[int] = None) -> Dict[str, Any]:
        """Get current epoch/slot status summary."""
        now = now or int(time.time())
        epoch_num = self.current_epoch(now)
        slot_num = self.current_slot(now)
        return {
            "current_epoch": epoch_num,
            "current_slot": slot_num,
            "slots_per_epoch": self.slots_per_epoch,
            "epoch_start": self.epoch_start_time(epoch_num),
            "epoch_end": self.epoch_end_time(epoch_num),
            "time_until_next_epoch": self.time_until_next_epoch(now),
            "time_until_next_slot": self.time_until_next_slot(now),
            "genesis_time": self.genesis_time,
        }

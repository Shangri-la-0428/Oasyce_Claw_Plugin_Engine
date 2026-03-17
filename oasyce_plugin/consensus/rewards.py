"""
Unified reward distribution — block rewards + work rewards.

All amounts in integer units (1 OAS = 10^8 units).
Commission rates in basis points (1000 = 10%).

At each epoch end:
- Block rewards: proposed_blocks * block_reward (with halving)
- Work rewards: sum of final_value from settled work tasks in the epoch
- Commission: validator takes commission_rate of block rewards, 90% of work rewards
- Delegator pool: remainder distributed proportional to delegation amount

Rewards are recorded as stake events (append-only).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus.core.types import apply_rate_bps

if TYPE_CHECKING:
    from oasyce_plugin.consensus.state import ConsensusState

# Work reward split (basis points)
WORK_VALIDATOR_SHARE_BPS = 9000  # 90%
WORK_DELEGATOR_SHARE_BPS = 1000  # 10%


class RewardEngine:
    """Computes and distributes rewards at epoch boundaries."""

    def __init__(self, state: ConsensusState, block_reward: int = 4_000_000_000,
                 halving_interval: int = 10000):
        self.state = state
        self.base_block_reward = block_reward
        self.halving_interval = halving_interval

    def current_block_reward(self, block_height: int) -> int:
        """Block reward with halving applied (integer division)."""
        halvings = block_height // self.halving_interval
        return self.base_block_reward >> halvings  # divide by 2^halvings

    def compute_validator_rewards(
        self,
        validator_id: str,
        epoch_number: int,
        blocks_proposed: int,
        work_value: int,
        current_block_height: int,
    ) -> Dict[str, Any]:
        """Compute reward breakdown for a single validator in an epoch."""
        val = self.state.get_validator(validator_id)
        if val is None:
            return {"error": "validator not found"}

        commission_bps = val["commission_rate"]
        reward_per_block = self.current_block_reward(current_block_height)
        block_reward_total = blocks_proposed * reward_per_block

        # Validator income
        validator_block_income = apply_rate_bps(block_reward_total, commission_bps)
        validator_work_income = apply_rate_bps(work_value, WORK_VALIDATOR_SHARE_BPS)

        # Delegator pool
        delegator_block_pool = block_reward_total - validator_block_income
        delegator_work_pool = apply_rate_bps(work_value, WORK_DELEGATOR_SHARE_BPS)

        return {
            "validator_id": validator_id,
            "epoch_number": epoch_number,
            "blocks_proposed": blocks_proposed,
            "block_reward_total": block_reward_total,
            "work_value": work_value,
            "validator_income": validator_block_income + validator_work_income,
            "delegator_pool": delegator_block_pool + delegator_work_pool,
            "commission_rate": commission_bps,
        }

    def distribute_epoch_rewards(
        self,
        epoch_number: int,
        validator_metrics: List[Dict[str, Any]],
        current_block_height: int,
    ) -> Dict[str, Any]:
        """Distribute all rewards for an epoch.

        Args:
            epoch_number: The epoch to distribute rewards for.
            validator_metrics: List of {validator_id, blocks_proposed, work_value}.
            current_block_height: Current chain height (for halving calc).

        Returns:
            Summary with total_distributed and per-validator breakdowns.
        """
        total_distributed = 0
        breakdowns = []

        for metrics in validator_metrics:
            vid = metrics["validator_id"]
            blocks = metrics.get("blocks_proposed", 0)
            work_val = metrics.get("work_value", 0)

            reward_info = self.compute_validator_rewards(
                vid, epoch_number, blocks, work_val, current_block_height,
            )
            if "error" in reward_info:
                continue

            validator_income = reward_info["validator_income"]
            delegator_pool = reward_info["delegator_pool"]

            # Record validator reward as stake event + reward event
            if validator_income > 0:
                append_event(self.state, current_block_height, vid,
                             "reward", validator_income, from_addr=vid,
                             reason="block_commission")
                self.state.record_reward(
                    epoch_number, vid, vid, "block", validator_income,
                    current_block_height,
                )
                self.state.increment_validator(vid, total_rewards=validator_income)
                total_distributed += validator_income

            # Distribute to delegators
            if delegator_pool > 0:
                delegations = self.state.get_delegations(vid)
                total_stake = self.state.get_validator_stake(vid)
                if total_stake > 0:
                    for d in delegations:
                        # Integer proportion: (pool * d_amount) // total_stake
                        d_reward = (delegator_pool * d["amount"]) // total_stake
                        if d_reward > 0:
                            append_event(self.state, current_block_height, vid,
                                         "reward", d_reward,
                                         from_addr=d["delegator"],
                                         reason="delegation_reward")
                            self.state.record_reward(
                                epoch_number, vid, d["delegator"],
                                "delegation", d_reward, current_block_height,
                            )
                            total_distributed += d_reward

            # Update blocks_proposed counter
            if blocks > 0:
                self.state.increment_validator(vid, blocks_proposed=blocks)

            breakdowns.append(reward_info)

        return {
            "epoch_number": epoch_number,
            "total_distributed": total_distributed,
            "validators": breakdowns,
        }

    def get_reward_history(self, epoch_number: Optional[int] = None,
                           validator_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.state.get_reward_events(
            epoch_number=epoch_number, validator_id=validator_id,
        )

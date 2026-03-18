"""
Oasyce PoS Consensus Engine — public API.

All monetary values are in integer units (1 OAS = 10^8 units).
All state changes flow through apply_operation (single entry point).
State is derived from append-only stake_events.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from oasyce_plugin.consensus.state import ConsensusState
from oasyce_plugin.consensus.epoch import EpochManager
from oasyce_plugin.consensus.validator_registry import ValidatorRegistry
from oasyce_plugin.consensus.proposer import ProposerElection
from oasyce_plugin.consensus.slashing import SlashingEngine
from oasyce_plugin.consensus.rewards import RewardEngine
from oasyce_plugin.consensus.core.types import (
    OAS_DECIMALS, to_units, from_units,
    Operation, OperationType,
)
from oasyce_plugin.consensus.core.transition import apply_operation
from oasyce_plugin.consensus.core.validation import validate_operation
from oasyce_plugin.consensus.core.signature import (
    serialize_operation,
    sign_operation,
    verify_signature,
)

__all__ = [
    "ConsensusEngine",
    "ConsensusState",
    "EpochManager",
    "ValidatorRegistry",
    "ProposerElection",
    "SlashingEngine",
    "RewardEngine",
    "Operation",
    "OperationType",
    "apply_operation",
    "validate_operation",
    "serialize_operation",
    "sign_operation",
    "verify_signature",
    "to_units",
    "from_units",
    "OAS_DECIMALS",
]


class ConsensusEngine:
    """Unified PoS consensus engine — single entry point for all consensus operations.

    All monetary values are in integer units (1 OAS = 10^8 units).
    All state changes flow through apply_operation().
    """

    def __init__(self, db_path: Optional[str] = None,
                 consensus_params: Optional[Dict[str, Any]] = None,
                 economics: Optional[Dict[str, Any]] = None,
                 genesis_time: Optional[int] = None):
        from oasyce_plugin.config import get_economics, NetworkMode

        economics = economics or get_economics(NetworkMode.TESTNET)
        params = consensus_params or self._default_testnet_params()

        self.chain_id = params.get("chain_id", "oasyce-testnet-1")
        self.blocks_per_epoch = params.get("blocks_per_epoch", 10)
        self.unbonding_blocks = params.get("unbonding_blocks", 20)

        self.state = ConsensusState(db_path)
        self.epoch_manager = EpochManager(self.state, params, genesis_time)
        self.registry = ValidatorRegistry(
            self.state,
            min_stake=economics.get("min_stake", 10_000_000_000),
            unbonding_period=params.get("unbonding_period", 600),
            jail_duration=params.get("jail_duration", 120),
        )
        self.proposer = ProposerElection(
            self.state,
            slots_per_epoch=params.get("slots_per_epoch", 10),
            min_stake=economics.get("min_stake", 10_000_000_000),
        )
        self.slashing = SlashingEngine(
            self.state, self.registry,
            min_stake=economics.get("min_stake", 10_000_000_000),
            jail_duration=params.get("jail_duration", 120),
        )
        self.rewards = RewardEngine(
            self.state,
            block_reward=economics.get("block_reward", 4_000_000_000),
            halving_interval=economics.get("halving_interval", 10000),
        )

    @staticmethod
    def _default_testnet_params() -> Dict[str, Any]:
        return {
            "epoch_duration": 300,
            "slots_per_epoch": 10,
            "slot_duration": 30,
            "unbonding_period": 600,
            "jail_duration": 120,
            "blocks_per_epoch": 10,
            "unbonding_blocks": 20,
            "chain_id": "oasyce-testnet-1",
        }

    # ── Block-height based scheduling ──────────────────────────────

    def epoch_at_height(self, height: int) -> int:
        """Derive epoch from block height (deterministic, no time.time)."""
        from oasyce_plugin.consensus.execution.engine import current_epoch
        return current_epoch(height, self.blocks_per_epoch)

    def slot_at_height(self, height: int) -> int:
        """Derive slot from block height (deterministic, no time.time)."""
        from oasyce_plugin.consensus.execution.engine import current_slot
        return current_slot(height, self.blocks_per_epoch)

    def is_epoch_boundary(self, height: int) -> bool:
        """Check if height is the last block of an epoch."""
        from oasyce_plugin.consensus.execution.engine import is_epoch_boundary
        return is_epoch_boundary(height, self.blocks_per_epoch)

    def apply_block(self, block: Dict[str, Any]) -> Dict[str, Any]:
        """Execute all operations in a block through the state machine."""
        from oasyce_plugin.consensus.execution.engine import apply_block
        return apply_block(self, block)

    # ── High-level operations (via apply_operation) ────────────────

    def apply(self, op: Operation, block_height: int = 0) -> Dict[str, Any]:
        """Apply a single operation through the unified state machine."""
        return apply_operation(self, op, block_height)

    def status(self, now: Optional[int] = None) -> Dict[str, Any]:
        now = now or int(time.time())
        epoch_status = self.epoch_manager.get_status(now)
        active = self.state.get_active_validators(0)
        return {
            **epoch_status,
            "active_validators": len(active),
            "total_staked": sum(v["total_stake"] for v in active),
        }

    def register_validator(self, pubkey: str, self_stake: int,
                           commission: int = 1000,
                           block_height: int = 0) -> Dict[str, Any]:
        """Register a validator. self_stake and commission in units/bps."""
        op = Operation(
            op_type=OperationType.REGISTER,
            validator_id=pubkey,
            amount=self_stake,
            commission_rate=commission,
        )
        return self.apply(op, block_height)

    def delegate(self, delegator: str, validator_id: str,
                 amount: int, block_height: int = 0) -> Dict[str, Any]:
        op = Operation(
            op_type=OperationType.DELEGATE,
            validator_id=validator_id,
            amount=amount,
            from_addr=delegator,
        )
        return self.apply(op, block_height)

    def undelegate(self, delegator: str, validator_id: str,
                   amount: int, block_height: int = 0) -> Dict[str, Any]:
        op = Operation(
            op_type=OperationType.UNDELEGATE,
            validator_id=validator_id,
            amount=amount,
            from_addr=delegator,
        )
        return self.apply(op, block_height)

    def exit_validator(self, validator_id: str,
                       block_height: int = 0) -> Dict[str, Any]:
        op = Operation(
            op_type=OperationType.EXIT,
            validator_id=validator_id,
        )
        return self.apply(op, block_height)

    def unjail_validator(self, validator_id: str) -> Dict[str, Any]:
        op = Operation(
            op_type=OperationType.UNJAIL,
            validator_id=validator_id,
        )
        return self.apply(op)

    def get_validators(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        return self.registry.list_validators(include_inactive)

    def get_schedule(self, epoch_number: Optional[int] = None) -> List[Dict[str, Any]]:
        if epoch_number is None:
            epoch_number = self.epoch_manager.current_epoch()
        return self.proposer.get_schedule(epoch_number)

    def get_rewards(self, epoch_number: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.rewards.get_reward_history(epoch_number=epoch_number)

    def get_slashing(self, validator_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.slashing.get_slash_history(validator_id)

    def get_delegations(self, delegator: str) -> List[Dict[str, Any]]:
        return self.state.get_delegator_delegations(delegator)

    def get_unbondings(self, delegator: str) -> List[Dict[str, Any]]:
        return self.state.get_pending_unbondings(delegator)

    # ── Epoch boundary processing ─────────────────────────────────

    def on_epoch_boundary(self, epoch_number: int,
                          prev_block_hash: str = "0" * 64,
                          current_block_height: int = 0,
                          validator_metrics: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Process epoch boundary: finalize, slash, reward, elect next leaders."""
        results: Dict[str, Any] = {"epoch": epoch_number}

        # 1. Process slashing
        slash_results = self.slashing.process_epoch_slashing(
            epoch_number, current_block_height)
        results["slashing"] = slash_results

        # 2. Distribute rewards
        if validator_metrics:
            reward_results = self.rewards.distribute_epoch_rewards(
                epoch_number, validator_metrics, current_block_height,
            )
            results["rewards"] = reward_results
        else:
            results["rewards"] = {"total_distributed": 0}

        # 3. Finalize the ending epoch
        total_rewards = results["rewards"].get("total_distributed", 0)
        self.epoch_manager.finalize_epoch(
            epoch_number, current_block_height, total_rewards,
        )

        # 4. Process unbonding queue
        released = self.epoch_manager.process_unbonding_queue()
        results["unbondings_released"] = released

        # 5. Compute leader schedule for next epoch
        next_epoch = epoch_number + 1
        active = self.state.get_active_validators(0)
        self.epoch_manager.ensure_epoch_exists(
            next_epoch, current_block_height, len(active),
        )
        schedule = self.proposer.elect_for_epoch(next_epoch, prev_block_hash)
        results["next_epoch"] = next_epoch
        results["next_schedule_length"] = len(schedule)

        return results

    def verify_proposer(self, epoch_number: int, slot_index: int,
                        validator_id: str) -> bool:
        return self.proposer.verify_proposer(epoch_number, slot_index, validator_id)

    # ── Signature helpers ───────────────────────────────────────────

    @staticmethod
    def sign_op(op: Operation, secret_key_hex: str,
                public_key_hex: str) -> Operation:
        """Sign an operation and return a new Operation with signature + sender + timestamp."""
        import dataclasses
        ts = op.timestamp if op.timestamp > 0 else int(time.time())
        op_with_ts = dataclasses.replace(op, sender=public_key_hex, timestamp=ts)
        sig = sign_operation(op_with_ts, secret_key_hex)
        return dataclasses.replace(op_with_ts, signature=sig)

    def close(self) -> None:
        self.state.close()

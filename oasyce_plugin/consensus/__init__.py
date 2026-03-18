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
    AssetType, Resource, KNOWN_ASSET_TYPES, ASSET_DECIMALS,
)
from oasyce_plugin.consensus.assets.registry import AssetDefinition, AssetRegistry
from oasyce_plugin.consensus.assets.balances import MultiAssetBalance
from oasyce_plugin.consensus.governance.types import (
    Proposal,
    ParameterChange,
    Vote,
    VoteOption,
    VoteResult,
    ProposalStatus,
)
from oasyce_plugin.consensus.governance.engine import GovernanceEngine
from oasyce_plugin.consensus.governance.registry import ParameterRegistry
from oasyce_plugin.consensus.core.transition import apply_operation
from oasyce_plugin.consensus.core.validation import validate_operation, NonceTracker
from oasyce_plugin.consensus.core.signature import (
    serialize_operation,
    sign_operation,
    verify_signature,
)
from oasyce_plugin.consensus.core.fork_choice import (
    ChainInfo,
    ForkInfo,
    ForkPoint,
    ReorgResult,
    MAX_REORG_DEPTH,
    choose_fork,
    choose_best_chain,
    should_sync,
    rank_peers,
    get_chain_weight,
    find_common_ancestor,
    detect_fork,
    detect_fork_info,
    detect_fork_point,
    execute_reorg,
    reorg_to,
)
from oasyce_plugin.consensus.network.sync import BlockSyncProtocol
from oasyce_plugin.consensus.node import ConsensusNode, NodeState, JoinResult

__all__ = [
    "ConsensusEngine",
    "ConsensusState",
    "AssetDefinition",
    "AssetRegistry",
    "MultiAssetBalance",
    "AssetType",
    "Resource",
    "KNOWN_ASSET_TYPES",
    "ASSET_DECIMALS",
    "EpochManager",
    "ValidatorRegistry",
    "ProposerElection",
    "SlashingEngine",
    "RewardEngine",
    "Operation",
    "OperationType",
    "apply_operation",
    "validate_operation",
    "NonceTracker",
    "serialize_operation",
    "sign_operation",
    "verify_signature",
    "to_units",
    "from_units",
    "OAS_DECIMALS",
    "ChainInfo",
    "ForkInfo",
    "ForkPoint",
    "ReorgResult",
    "MAX_REORG_DEPTH",
    "choose_fork",
    "choose_best_chain",
    "should_sync",
    "rank_peers",
    "get_chain_weight",
    "find_common_ancestor",
    "detect_fork",
    "detect_fork_info",
    "detect_fork_point",
    "execute_reorg",
    "reorg_to",
    "BlockSyncProtocol",
    "ConsensusNode",
    "NodeState",
    "JoinResult",
    "Proposal",
    "ParameterChange",
    "Vote",
    "VoteOption",
    "VoteResult",
    "ProposalStatus",
    "GovernanceEngine",
    "ParameterRegistry",
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
        self.genesis_time = genesis_time or 0

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
        self.asset_registry = AssetRegistry()
        # Derive nonce DB path from the main db_path so nonces survive restarts.
        if db_path and db_path != ":memory:":
            import os
            _nonce_db = os.path.join(os.path.dirname(db_path), "nonces.db")
        else:
            _nonce_db = None
        self._nonce_tracker = NonceTracker(db_path=_nonce_db)

        # Governance
        self.param_registry = ParameterRegistry()
        self._register_default_params(economics, params)
        self.governance = GovernanceEngine(
            self.state, self.param_registry,
            min_deposit=economics.get("min_deposit", 100_000_000_000),
            voting_period=params.get("voting_period", 60480),
            balances=self.state.balances,
        )

    def _register_default_params(self, economics: Dict[str, Any],
                                  params: Dict[str, Any]) -> None:
        """Register governable parameters with the parameter registry."""
        reg = self.param_registry
        # Consensus parameters
        reg.register("consensus", "blocks_per_epoch", int,
                     self.blocks_per_epoch, min_value=1, max_value=10000,
                     description="Blocks per epoch",
                     applier=lambda v: setattr(self, "blocks_per_epoch", v))
        reg.register("consensus", "unbonding_blocks", int,
                     self.unbonding_blocks, min_value=1, max_value=100000,
                     description="Unbonding period in blocks")
        reg.register("consensus", "voting_period", int,
                     params.get("voting_period", 60480),
                     min_value=100, max_value=1000000,
                     description="Governance voting period in blocks")

        # Economics parameters
        reg.register("economics", "min_stake", int,
                     economics.get("min_stake", 10_000_000_000),
                     min_value=1_000_000_000, max_value=1_000_000_000_000,
                     description="Minimum validator stake (units)")
        reg.register("economics", "block_reward", int,
                     economics.get("block_reward", 4_000_000_000),
                     min_value=0, max_value=100_000_000_000,
                     description="Block reward per block (units)")
        reg.register("economics", "min_deposit", int,
                     economics.get("min_deposit", 100_000_000_000),
                     min_value=0, max_value=10_000_000_000_000,
                     description="Minimum governance proposal deposit (units)")

        # Slashing parameters
        reg.register("slashing", "offline_slash_bps", int,
                     100, min_value=0, max_value=5000,
                     description="Offline slash rate in basis points")
        reg.register("slashing", "double_sign_slash_bps", int,
                     500, min_value=0, max_value=10000,
                     description="Double-sign slash rate in basis points")
        reg.register("slashing", "low_quality_slash_bps", int,
                     50, min_value=0, max_value=5000,
                     description="Low-quality slash rate in basis points")

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

    def _next_nonce(self, sender: str) -> int:
        """Return the next expected nonce for *sender*.

        For an unseen sender the first nonce is 0; otherwise last + 1.
        """
        last = self._nonce_tracker.get_nonce(sender)
        return 0 if last < 0 else last + 1

    @staticmethod
    def sign_op(op: Operation, secret_key_hex: str, public_key_hex: str) -> Operation:
        """Return a copy of *op* with sender, timestamp, and signature filled in."""
        import time as _time
        from dataclasses import replace
        ts = op.timestamp if op.timestamp > 0 else int(_time.time())
        unsigned = replace(op, sender=public_key_hex, timestamp=ts)
        sig = sign_operation(unsigned, secret_key_hex)
        return replace(unsigned, signature=sig)

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
            nonce=self._next_nonce(delegator),
        )
        return self.apply(op, block_height)

    def undelegate(self, delegator: str, validator_id: str,
                   amount: int, block_height: int = 0) -> Dict[str, Any]:
        op = Operation(
            op_type=OperationType.UNDELEGATE,
            validator_id=validator_id,
            amount=amount,
            from_addr=delegator,
            nonce=self._next_nonce(delegator),
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

    # ── Block sync ─────────────────────────────────────────────────

    def get_genesis_hash(self) -> str:
        """Compute the genesis block hash for this chain."""
        from oasyce_plugin.consensus.network.sync_protocol import make_genesis_block
        genesis = make_genesis_block(self.chain_id, timestamp=self.genesis_time)
        return genesis.block_hash

    def sync_from_peers(self, peers, local_height: int = -1,
                        verify_signatures: bool = False,
                        on_progress=None) -> Dict[str, Any]:
        """Sync blocks from the best available peer."""
        from oasyce_plugin.consensus.network.block_sync import sync_from_network
        result = sync_from_network(
            peers, self, local_height, self.get_genesis_hash(),
            verify_signatures=verify_signatures,
            on_progress=on_progress,
        )
        return result.to_dict()

    # ── Multi-asset operations ──────────────────────────────────────

    def transfer_asset(self, from_addr: str, to_addr: str,
                       asset_type: str, amount: int,
                       block_height: int = 0) -> Dict[str, Any]:
        """Transfer assets between addresses via the state machine."""
        op = Operation(
            op_type=OperationType.TRANSFER,
            validator_id="",
            amount=amount,
            asset_type=asset_type,
            from_addr=from_addr,
            to_addr=to_addr,
            nonce=self._next_nonce(from_addr),
        )
        return self.apply(op, block_height)

    def register_asset_type(self, asset_type: str, name: str,
                            decimals: int, issuer: str,
                            block_height: int = 0) -> Dict[str, Any]:
        """Register a new asset type via the state machine."""
        op = Operation(
            op_type=OperationType.REGISTER_ASSET,
            validator_id="",
            asset_type=asset_type,
            reason=name,
            commission_rate=decimals,
            from_addr=issuer,
            nonce=self._next_nonce(issuer),
        )
        return self.apply(op, block_height)

    def get_balance(self, address: str,
                    asset_type: str = "OAS") -> int:
        return self.state.balances.get_balance(address, asset_type)

    def get_all_balances(self, address: str) -> Dict[str, int]:
        return self.state.balances.get_all_balances(address)

    def credit_balance(self, address: str, asset_type: str,
                       amount: int) -> int:
        """Directly credit an address (for faucet, rewards, etc.)."""
        return self.state.balances.credit(address, asset_type, amount)

    def list_asset_types(self) -> List[Dict[str, Any]]:
        return self.asset_registry.to_dict_list()

    # ── Governance operations ──────────────────────────────────────

    def submit_proposal(self, proposer: str, title: str,
                        description: str,
                        changes: List[ParameterChange],
                        deposit: int,
                        block_height: int = 0) -> Dict[str, Any]:
        return self.governance.submit_proposal(
            proposer, title, description, changes, deposit, block_height,
        )

    def cast_vote(self, proposal_id: str, voter: str,
                  option: VoteOption,
                  block_height: int = 0) -> Dict[str, Any]:
        return self.governance.cast_vote(proposal_id, voter, option, block_height)

    def tally_votes(self, proposal_id: str) -> Dict[str, Any]:
        return self.governance.tally_votes(proposal_id)

    def get_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        return self.governance.get_proposal(proposal_id)

    def list_proposals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.governance.list_proposals(status)

    def list_governable_params(self, module: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.param_registry.to_dict_list(module)

    def close(self) -> None:
        self.state.close()

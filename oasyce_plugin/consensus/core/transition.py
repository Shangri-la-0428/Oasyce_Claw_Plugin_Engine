"""
State transition — the ONLY function that changes consensus state.

All state changes in the consensus engine flow through apply_operation().
This is the single entry point for all mutations.
"""

from __future__ import annotations

from typing import Any, Dict, TYPE_CHECKING

from oasyce_plugin.consensus.core.types import Operation, OperationType
from oasyce_plugin.consensus.core.validation import validate_operation

if TYPE_CHECKING:
    from oasyce_plugin.consensus import ConsensusEngine


def apply_operation(engine: ConsensusEngine, op: Operation,
                    block_height: int = 0) -> Dict[str, Any]:
    """Apply a single operation to the consensus state.

    This is the ONLY function that modifies state.
    All CLI, GUI, and node code must go through this function.

    Args:
        engine: The ConsensusEngine instance.
        op: The Operation to apply (frozen, immutable).
        block_height: The block height at which this operation is applied.

    Returns:
        Result dict with 'ok' field and operation-specific data.
    """
    # 1. Validate
    valid, error = validate_operation(engine, op, block_height)
    if not valid:
        return {"ok": False, "error": error}

    # 2. Execute
    if op.op_type == OperationType.REGISTER:
        return engine.registry.register(
            op.validator_id, op.amount, op.commission_rate, block_height,
        )

    elif op.op_type == OperationType.DELEGATE:
        return engine.registry.delegate(
            op.from_addr, op.validator_id, op.amount, block_height,
        )

    elif op.op_type == OperationType.UNDELEGATE:
        return engine.registry.undelegate(
            op.from_addr, op.validator_id, op.amount, block_height,
        )

    elif op.op_type == OperationType.EXIT:
        return engine.registry.exit(op.validator_id, block_height)

    elif op.op_type == OperationType.UNJAIL:
        return engine.registry.unjail(op.validator_id)

    elif op.op_type == OperationType.SLASH:
        return engine.slashing.apply_slash(
            op.validator_id, op.reason,
            epoch_number=0, block_height=block_height,
        )

    elif op.op_type == OperationType.REWARD:
        # Rewards are handled in bulk by distribute_epoch_rewards
        return {"ok": True, "note": "reward applied via epoch boundary"}

    elif op.op_type == OperationType.TRANSFER:
        return engine.state.balances.transfer(
            op.from_addr, op.to_addr, op.asset_type, op.amount,
            block_height=block_height,
        )

    elif op.op_type == OperationType.REGISTER_ASSET:
        from oasyce_plugin.consensus.assets.registry import AssetDefinition
        definition = AssetDefinition(
            asset_type=op.asset_type,
            name=op.reason or op.asset_type,
            decimals=op.commission_rate,
            issuer=op.from_addr,
        )
        return engine.asset_registry.register_asset(definition)

    return {"ok": False, "error": f"unhandled operation type: {op.op_type}"}

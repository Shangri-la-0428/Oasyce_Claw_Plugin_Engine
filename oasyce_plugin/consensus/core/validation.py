"""
Pure validation functions for consensus operations.

These functions are pure — they read state but never modify it.
They return (True, None) on success or (False, error_message) on failure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

from oasyce_plugin.consensus.core.types import Operation, OperationType, MAX_COMMISSION_BPS

if TYPE_CHECKING:
    from oasyce_plugin.consensus import ConsensusEngine


def validate_operation(engine: ConsensusEngine, op: Operation,
                       block_height: int = 0) -> Tuple[bool, str]:
    """Validate an operation against current state. Pure function.

    Returns:
        (True, "") if valid, (False, error_message) if invalid.
    """
    if op.op_type == OperationType.REGISTER:
        return _validate_register(engine, op)
    elif op.op_type == OperationType.DELEGATE:
        return _validate_delegate(engine, op)
    elif op.op_type == OperationType.UNDELEGATE:
        return _validate_undelegate(engine, op)
    elif op.op_type == OperationType.EXIT:
        return _validate_exit(engine, op)
    elif op.op_type == OperationType.UNJAIL:
        return _validate_unjail(engine, op)
    elif op.op_type == OperationType.SLASH:
        return True, ""  # Slash operations are system-generated
    elif op.op_type == OperationType.REWARD:
        return True, ""  # Reward operations are system-generated
    else:
        return False, f"unknown operation type: {op.op_type}"


def _validate_register(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    if op.amount < engine.registry.min_stake:
        return False, f"self_stake {op.amount} below min {engine.registry.min_stake}"
    if not (0 <= op.commission_rate <= MAX_COMMISSION_BPS):
        return False, f"commission must be 0-{MAX_COMMISSION_BPS} bps"

    existing = engine.state.get_validator(op.validator_id)
    if existing:
        if existing["status"] == "exited":
            pending = engine.state.get_pending_unbondings(op.validator_id)
            if pending:
                return False, "cannot re-register: unbonding still in progress"
            return True, ""
        return False, "validator already registered"
    return True, ""


def _validate_delegate(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    if op.amount <= 0:
        return False, "amount must be positive"
    val = engine.state.get_validator(op.validator_id)
    if val is None:
        return False, "validator not found"
    if val["status"] not in ("active", "jailed"):
        return False, f"validator is {val['status']}, cannot delegate"
    return True, ""


def _validate_undelegate(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    if op.amount <= 0:
        return False, "amount must be positive"
    val = engine.state.get_validator(op.validator_id)
    if val is None:
        return False, "validator not found"
    current = engine.state.get_delegation_amount(op.from_addr, op.validator_id)
    if current <= 0:
        return False, "no delegation found"
    return True, ""


def _validate_exit(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    val = engine.state.get_validator(op.validator_id)
    if val is None:
        return False, "validator not found"
    if val["status"] == "exited":
        return False, "already exited"
    return True, ""


def _validate_unjail(engine: ConsensusEngine, op: Operation) -> Tuple[bool, str]:
    val = engine.state.get_validator(op.validator_id)
    if val is None:
        return False, "validator not found"
    if val["status"] != "jailed":
        return False, f"validator is {val['status']}, not jailed"
    return True, ""

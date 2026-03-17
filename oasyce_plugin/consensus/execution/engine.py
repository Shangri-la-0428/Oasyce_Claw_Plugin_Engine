"""
Block-height based epoch/slot scheduling.

All timing derived from block_height — no time.time() dependency.
Deterministic: given the same block_height, any node computes
the same epoch, slot, and schedule.

Functions:
  current_epoch(height)  → epoch number
  current_slot(height)   → slot within epoch
  epoch_start_block(epoch) → first block of epoch
  epoch_end_block(epoch)   → last block of epoch

# PERF-CRITICAL — candidate for PyO3 acceleration
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List


def current_epoch(height: int, blocks_per_epoch: int) -> int:
    """Derive epoch number from block height. Pure function."""
    return height // blocks_per_epoch


def current_slot(height: int, blocks_per_epoch: int) -> int:
    """Derive slot index within epoch from block height. Pure function."""
    return height % blocks_per_epoch


def epoch_start_block(epoch: int, blocks_per_epoch: int) -> int:
    """First block of an epoch."""
    return epoch * blocks_per_epoch


def epoch_end_block(epoch: int, blocks_per_epoch: int) -> int:
    """Last block of an epoch (inclusive)."""
    return (epoch + 1) * blocks_per_epoch - 1


def is_epoch_boundary(height: int, blocks_per_epoch: int) -> bool:
    """True if this block height is the last block of an epoch."""
    return (height + 1) % blocks_per_epoch == 0


def blocks_until_epoch_end(height: int, blocks_per_epoch: int) -> int:
    """Number of blocks until current epoch ends."""
    return blocks_per_epoch - 1 - (height % blocks_per_epoch)


def unbonding_release_block(current_height: int, unbonding_blocks: int) -> int:
    """Compute the block height at which unbonding completes."""
    return current_height + unbonding_blocks


# ── Block hashing ────────────────────────────────────────────────

def compute_block_hash(chain_id: str, block_number: int,
                       prev_hash: str, merkle_root: str,
                       timestamp: int) -> str:
    """Deterministic block hash including chain_id (replay protection).

    # PERF-CRITICAL
    """
    data = f"{chain_id}{block_number}{prev_hash}{merkle_root}{timestamp}"
    return hashlib.sha256(data.encode()).hexdigest()


# ── Block execution ──────────────────────────────────────────────

def apply_block(engine: Any, block: Dict[str, Any]) -> Dict[str, Any]:
    """Execute all operations in a block through the state machine.

    Args:
        engine: ConsensusEngine instance.
        block: Block dict with 'height' and 'operations' fields.

    Returns:
        Summary of applied operations.
    """
    from oasyce_plugin.consensus.core.transition import apply_operation

    height = block.get("height", block.get("block_number", 0))
    operations = block.get("operations", [])
    results = []

    for op in operations:
        result = apply_operation(engine, op, height)
        results.append(result)

    return {
        "height": height,
        "operations_applied": len(results),
        "results": results,
    }

"""
Append-only event store — the single write function for stake state.

All stake changes flow through append_event(). No other code may INSERT
into stake_events or UPDATE monetary columns in the validators table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oasyce_plugin.consensus.state import ConsensusState


def append_event(state: ConsensusState, block_height: int,
                 validator_id: str, event_type: str,
                 amount: int, from_addr: str = "",
                 reason: str = "") -> int:
    """Append a stake event — the ONLY function that writes stake state.

    Args:
        state: ConsensusState instance.
        block_height: The block height at which this event occurs.
        validator_id: The validator this event affects.
        event_type: One of: register_self, delegate, undelegate, slash, reward, exit.
        amount: Integer units (always positive; event_type determines direction).
        from_addr: Source address (delegator address for delegate/undelegate).
        reason: Human-readable reason (for slash events).

    Returns:
        The event ID (auto-incremented).
    """
    return state.append_stake_event(
        block_height=block_height,
        validator_id=validator_id,
        event_type=event_type,
        amount=amount,
        from_addr=from_addr,
        reason=reason,
    )

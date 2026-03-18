"""
Slashing — three penalty conditions for validator misbehavior.

All amounts in integer units (1 OAS = 10^8 units).
Slash rates in basis points (1% = 100 bps).

Conditions:
1. Offline: missed >50% of assigned slots in an epoch -> 1% stake, jail
2. Double sign: two different blocks at same height -> 5% stake, jail 3x
3. Low quality work: avg quality < 0.3 over last 10 tasks -> 0.5% stake, no jail
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus.core.types import (
    OFFLINE_SLASH_BPS,
    DOUBLE_SIGN_SLASH_BPS,
    LOW_QUALITY_SLASH_BPS,
    apply_rate_bps,
)

if TYPE_CHECKING:
    from oasyce_plugin.consensus.state import ConsensusState
    from oasyce_plugin.consensus.validator_registry import ValidatorRegistry

# Quality thresholds
QUALITY_THRESHOLD = 3000  # 0.3 * 10000 (basis points)
QUALITY_WINDOW = 10  # last N tasks


class SlashingEngine:
    """Detects and applies slashing conditions."""

    def __init__(self, state: ConsensusState, registry: ValidatorRegistry,
                 min_stake: int = 10_000_000_000, jail_duration: int = 120):
        self.state = state
        self.registry = registry
        self.min_stake = min_stake
        self.jail_duration = jail_duration

    def check_offline(self, validator_id: str,
                      epoch_number: int) -> Optional[Dict[str, Any]]:
        """Check if a validator missed >50% of assigned slots in an epoch."""
        assigned = self.state.count_assigned_slots(epoch_number, validator_id)
        if assigned == 0:
            return None
        proposed = self.state.count_proposed_slots(epoch_number, validator_id)
        missed = assigned - proposed

        if missed > assigned / 2:
            return {
                "validator_id": validator_id,
                "reason": "offline",
                "assigned": assigned,
                "proposed": proposed,
                "missed": missed,
            }
        return None

    def check_double_sign(self, validator_id: str,
                          block_hash_a: str,
                          block_hash_b: str,
                          block_height: int) -> Optional[Dict[str, Any]]:
        """Check for double signing (two different blocks at same height)."""
        if block_hash_a != block_hash_b:
            return {
                "validator_id": validator_id,
                "reason": "double_sign",
                "block_height": block_height,
                "hash_a": block_hash_a,
                "hash_b": block_hash_b,
            }
        return None

    def check_low_quality(self, validator_id: str,
                          recent_qualities: List[int]) -> Optional[Dict[str, Any]]:
        """Check if recent work quality is below threshold.

        Qualities are in basis points (10000 = 1.0, 3000 = 0.3).
        """
        if len(recent_qualities) < QUALITY_WINDOW:
            return None
        window = recent_qualities[-QUALITY_WINDOW:]
        avg = sum(window) // len(window)
        if avg < QUALITY_THRESHOLD:
            return {
                "validator_id": validator_id,
                "reason": "low_quality",
                "avg_quality": avg,
                "threshold": QUALITY_THRESHOLD,
                "window_size": len(window),
            }
        return None

    def apply_slash(self, validator_id: str, reason: str,
                    epoch_number: int,
                    block_height: int = 0) -> Dict[str, Any]:
        """Apply a slash penalty to a validator."""
        total_stake = self.state.get_validator_stake(validator_id)
        val = self.state.get_validator(validator_id)
        if val is None:
            return {"ok": False, "error": "validator not found"}

        # Determine slash rate and jail multiplier
        if reason == "offline":
            rate_bps = OFFLINE_SLASH_BPS
            jail_mult = 1.0
            should_jail = True
        elif reason == "double_sign":
            rate_bps = DOUBLE_SIGN_SLASH_BPS
            jail_mult = 3.0
            should_jail = True
        elif reason == "low_quality":
            rate_bps = LOW_QUALITY_SLASH_BPS
            jail_mult = 0.0
            should_jail = False
        else:
            return {"ok": False, "error": f"unknown slash reason: {reason}"}

        slash_amount = apply_rate_bps(total_stake, rate_bps)
        if slash_amount <= 0:
            return {"ok": True, "validator_id": validator_id, "reason": reason,
                    "slash_amount": 0, "new_total_stake": total_stake, "jailed": False}

        # Deduct from self_stake first, then proportionally from delegations
        self_stake = val["self_stake"]
        remaining = slash_amount

        if self_stake > 0:
            self_deduct = min(remaining, self_stake)
            if self_deduct > 0:
                append_event(self.state, block_height, validator_id,
                             "slash", self_deduct, from_addr=validator_id,
                             reason=reason)
                remaining -= self_deduct

        # Deduct remaining from delegations proportionally
        if remaining > 0:
            delegations = self.state.get_delegations(validator_id)
            total_delegated = sum(d["amount"] for d in delegations)
            if total_delegated > 0:
                for d in delegations:
                    d_deduct = (remaining * d["amount"]) // total_delegated
                    if d_deduct > 0:
                        append_event(self.state, block_height, validator_id,
                                     "slash", d_deduct, from_addr=d["delegator"],
                                     reason=reason)

        # Record slash event
        self.state.record_slash(validator_id, reason, slash_amount, epoch_number,
                                block_height)

        new_total = self.state.get_validator_stake(validator_id)

        # Jail if needed
        jail_result = None
        if should_jail:
            jail_result = self.registry.jail(
                validator_id, reason=reason, duration_multiplier=jail_mult,
                block_height=block_height if block_height > 0 else None,
            )

        # Auto-jail if below min_stake
        if not should_jail and new_total < self.min_stake:
            jail_result = self.registry.jail(
                validator_id, reason="below_min_stake",
                block_height=block_height if block_height > 0 else None,
            )

        return {
            "ok": True,
            "validator_id": validator_id,
            "reason": reason,
            "slash_amount": slash_amount,
            "new_total_stake": new_total,
            "jailed": jail_result is not None and jail_result.get("ok", False),
        }

    def process_epoch_slashing(self, epoch_number: int,
                               block_height: int = 0) -> List[Dict[str, Any]]:
        """Process all offline slashing for an epoch."""
        validators = self.state.get_all_validators()
        results = []
        for v in validators:
            if v["status"] != "active":
                continue
            evidence = self.check_offline(v["validator_id"], epoch_number)
            if evidence:
                result = self.apply_slash(
                    v["validator_id"], "offline", epoch_number, block_height,
                )
                result["evidence"] = evidence
                results.append(result)
        return results

    def get_slash_history(self, validator_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.state.get_slash_events(validator_id=validator_id)

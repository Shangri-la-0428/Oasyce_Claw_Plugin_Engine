"""
Validator registry — registration, delegation, undelegation, jailing, exit.

All monetary values are in integer units (1 OAS = 10^8 units).
All stake changes go through append_event (event sourcing).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus.core.types import MAX_COMMISSION_BPS

if TYPE_CHECKING:
    from oasyce_plugin.consensus.state import ConsensusState


class ValidatorRegistry:
    """Handles validator registration, delegation, and lifecycle transitions."""

    def __init__(self, state: ConsensusState, min_stake: int = 10_000_000_000,
                 unbonding_period: int = 600, jail_duration: int = 120,
                 max_commission: int = MAX_COMMISSION_BPS):
        self.state = state
        self.min_stake = min_stake
        self.unbonding_period = unbonding_period
        self.jail_duration = jail_duration
        self.max_commission = max_commission

    def register(self, pubkey: str, self_stake: int,
                 commission: int = 1000,
                 block_height: int = 0) -> Dict[str, Any]:
        """Register a new validator with self-stake.

        Args:
            pubkey: Validator public key (used as validator_id).
            self_stake: Self-stake in integer units.
            commission: Commission rate in basis points (1000 = 10%).
            block_height: Current block height.
        """
        if self_stake < self.min_stake:
            return {"ok": False, "error": f"self_stake {self_stake} below min {self.min_stake}"}
        if not (0 <= commission <= self.max_commission):
            return {"ok": False, "error": f"commission must be 0-{self.max_commission} bps"}

        existing = self.state.get_validator(pubkey)
        if existing:
            if existing["status"] == "exited":
                pending = self.state.get_pending_unbondings(pubkey)
                if pending:
                    return {"ok": False, "error": "cannot re-register: unbonding still in progress"}
                self.state.reactivate_validator(pubkey, commission)
                append_event(self.state, block_height, pubkey,
                             "register_self", self_stake, from_addr=pubkey)
                return {"ok": True, "validator_id": pubkey, "self_stake": self_stake,
                        "re_registered": True}
            return {"ok": False, "error": "validator already registered"}

        ok = self.state.register_validator(pubkey, commission, block_height)
        if not ok:
            return {"ok": False, "error": "registration failed"}

        append_event(self.state, block_height, pubkey,
                     "register_self", self_stake, from_addr=pubkey)

        return {"ok": True, "validator_id": pubkey, "self_stake": self_stake}

    def delegate(self, delegator: str, validator_id: str,
                 amount: int, block_height: int = 0) -> Dict[str, Any]:
        """Delegate stake to a validator."""
        if amount <= 0:
            return {"ok": False, "error": "amount must be positive"}
        val = self.state.get_validator(validator_id)
        if val is None:
            return {"ok": False, "error": "validator not found"}
        if val["status"] not in ("active", "jailed"):
            return {"ok": False, "error": f"validator is {val['status']}, cannot delegate"}

        append_event(self.state, block_height, validator_id,
                     "delegate", amount, from_addr=delegator)

        return {"ok": True, "delegator": delegator, "validator_id": validator_id,
                "amount": amount}

    def undelegate(self, delegator: str, validator_id: str,
                   amount: int, block_height: int = 0) -> Dict[str, Any]:
        """Undelegate stake — enters unbonding queue."""
        if amount <= 0:
            return {"ok": False, "error": "amount must be positive"}
        val = self.state.get_validator(validator_id)
        if val is None:
            return {"ok": False, "error": "validator not found"}

        # Check delegator has enough delegation
        current = self.state.get_delegation_amount(delegator, validator_id)
        if current <= 0:
            return {"ok": False, "error": "no delegation found"}
        if amount > current:
            amount = current

        append_event(self.state, block_height, validator_id,
                     "undelegate", amount, from_addr=delegator)
        self.state.add_unbonding(delegator, validator_id, amount,
                                 self.unbonding_period)

        # Check if validator falls below min_stake
        new_stake = self.state.get_validator_stake(validator_id)
        updated = self.state.get_validator(validator_id)
        if updated and updated["status"] == "active" and new_stake < self.min_stake:
            self.jail(validator_id, reason="below_min_stake",
                      block_height=block_height if block_height > 0 else None)

        return {"ok": True, "delegator": delegator, "validator_id": validator_id,
                "amount": amount, "unbonding_period": self.unbonding_period}

    # Assumed block interval for converting wall-clock duration to blocks.
    _SECONDS_PER_BLOCK = 6

    def jail(self, validator_id: str,
             reason: str = "offline",
             duration_multiplier: float = 1.0,
             now: Optional[int] = None,
             block_height: Optional[int] = None) -> Dict[str, Any]:
        """Jail a validator for a specified duration.

        Args:
            now: Current timestamp. Defaults to time.time() for P2P compat.
                 Pass explicitly for deterministic replay.
                 DEPRECATED — prefer *block_height* for deterministic consensus.
            block_height: Current block height.  When provided, jail duration
                 is expressed in blocks (1 block ≈ 6 s) rather than wall-clock
                 seconds, ensuring deterministic behaviour across nodes.
        """
        val = self.state.get_validator(validator_id)
        if val is None:
            return {"ok": False, "error": "validator not found"}
        if val["status"] == "exited":
            return {"ok": False, "error": "validator has exited"}

        if block_height is not None:
            # Deterministic path: compute jail release as a block height.
            duration_blocks = int(
                (self.jail_duration * duration_multiplier) / self._SECONDS_PER_BLOCK
            )
            jailed_until_height = block_height + duration_blocks
            ok = self.state.jail_validator(validator_id, jailed_until_height)
            return {"ok": ok, "validator_id": validator_id,
                    "jailed_until_height": jailed_until_height, "reason": reason}

        # DEPRECATED wall-clock fallback — kept for backward compatibility.
        now = now or int(time.time())
        until = now + int(self.jail_duration * duration_multiplier)
        ok = self.state.jail_validator(validator_id, until)
        return {"ok": ok, "validator_id": validator_id, "jailed_until": until,
                "reason": reason}

    def unjail(self, validator_id: str,
               now: Optional[int] = None,
               current_height: Optional[int] = None) -> Dict[str, Any]:
        """Unjail a validator if jail duration has passed and stake is sufficient.

        Args:
            now: Current timestamp. Defaults to time.time() for P2P compat.
                 DEPRECATED — prefer *current_height* for deterministic consensus.
            current_height: Current block height. When provided, compares
                 against *jailed_until* (which stores a block height when
                 ``jail()`` was called with *block_height*).
        """
        val = self.state.get_validator(validator_id)
        if val is None:
            return {"ok": False, "error": "validator not found"}
        if val["status"] != "jailed":
            return {"ok": False, "error": f"validator is {val['status']}, not jailed"}

        if current_height is not None:
            # Deterministic path — jailed_until stores a block height.
            if val["jailed_until"] > current_height:
                return {"ok": False, "error": "jail duration not yet expired",
                        "jailed_until_height": val["jailed_until"]}
        else:
            # DEPRECATED wall-clock fallback.
            now = now or int(time.time())
            if val["jailed_until"] > now:
                return {"ok": False, "error": "jail duration not yet expired",
                        "jailed_until": val["jailed_until"]}

        total_stake = self.state.get_validator_stake(validator_id)
        if total_stake < self.min_stake:
            return {"ok": False, "error": f"total_stake {total_stake} below min {self.min_stake}"}

        ok = self.state.unjail_validator(validator_id)
        return {"ok": ok, "validator_id": validator_id}

    def exit(self, validator_id: str, block_height: int = 0) -> Dict[str, Any]:
        """Voluntary exit — all stake enters unbonding queue."""
        val = self.state.get_validator(validator_id)
        if val is None:
            return {"ok": False, "error": "validator not found"}
        if val["status"] == "exited":
            return {"ok": False, "error": "already exited"}

        # Move self_stake to unbonding
        self_stake = val["self_stake"]
        if self_stake > 0:
            append_event(self.state, block_height, validator_id,
                         "exit", self_stake, from_addr=validator_id)
            self.state.add_unbonding(validator_id, validator_id, self_stake,
                                     self.unbonding_period)

        # Move all delegations to unbonding
        delegations = self.state.get_delegations(validator_id)
        for d in delegations:
            append_event(self.state, block_height, validator_id,
                         "undelegate", d["amount"], from_addr=d["delegator"],
                         reason="validator_exit")
            self.state.add_unbonding(d["delegator"], validator_id, d["amount"],
                                     self.unbonding_period)

        self.state.exit_validator(validator_id)
        return {"ok": True, "validator_id": validator_id}

    def get_validator_info(self, validator_id: str) -> Optional[Dict[str, Any]]:
        val = self.state.get_validator(validator_id)
        if val is None:
            return None
        val["delegations"] = self.state.get_delegations(validator_id)
        return val

    def list_validators(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        if include_inactive:
            return self.state.get_all_validators()
        return self.state.get_active_validators(self.min_stake)

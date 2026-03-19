"""
Staking -- now delegated to the Cosmos chain via standard SDK staking.

Provides backward-compatible type stubs for code that still references
StakingEngine. Actual staking is done via Cosmos SDK MsgDelegate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from oasyce.chain_client import ChainClientError, OasyceClient


class ValidatorStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    JAILED = "jailed"


class SlashReason(str, Enum):
    OFFLINE = "offline"
    DOUBLE_SIGN = "double_sign"
    LOW_QUALITY = "low_quality"


@dataclass
class SlashEvent:
    validator_id: str
    reason: SlashReason
    amount: int = 0


@dataclass
class RewardEvent:
    validator_id: str
    amount: int = 0
    epoch: int = 0


@dataclass
class StakingConfig:
    rest_url: str = "http://localhost:1317"


@dataclass
class Validator:
    validator_id: str
    status: ValidatorStatus = ValidatorStatus.ACTIVE
    total_stake: int = 0


class StakingEngine:
    """Staking engine that delegates to the Cosmos chain.

    Provides backward compatibility for code that references StakingEngine.
    """

    def __init__(self, config: Optional[StakingConfig] = None):
        cfg = config or StakingConfig()
        self._chain = OasyceClient(rest_url=cfg.rest_url)
        self.validators: Dict[str, Validator] = {}

    def delegate(self, delegator: str, validator_id: str, amount_uoas: int) -> Dict[str, Any]:
        """Delegate stake via Cosmos SDK MsgDelegate."""
        try:
            return self._chain.chain._broadcast_tx(
                "/cosmos.staking.v1beta1.MsgDelegate",
                {
                    "delegator_address": delegator,
                    "validator_address": validator_id,
                    "amount": {"denom": "uoas", "amount": str(amount_uoas)},
                },
            )
        except ChainClientError as exc:
            return {"error": str(exc)}

    def undelegate(self, delegator: str, validator_id: str, amount_uoas: int) -> Dict[str, Any]:
        """Undelegate stake via Cosmos SDK MsgUndelegate."""
        try:
            return self._chain.chain._broadcast_tx(
                "/cosmos.staking.v1beta1.MsgUndelegate",
                {
                    "delegator_address": delegator,
                    "validator_address": validator_id,
                    "amount": {"denom": "uoas", "amount": str(amount_uoas)},
                },
            )
        except ChainClientError as exc:
            return {"error": str(exc)}

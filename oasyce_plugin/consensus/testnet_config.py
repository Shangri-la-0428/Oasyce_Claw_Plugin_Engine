"""
Testnet deployment configuration.

Centralizes all testnet-specific parameters for genesis creation,
validator setup, and faucet operation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from oasyce_plugin.consensus.core.types import OAS_DECIMALS


_OAS = OAS_DECIMALS  # 10^8 units per OAS


# ── Testnet configuration ────────────────────────────────────────────

@dataclass(frozen=True)
class ValidatorInfo:
    """Initial validator for genesis."""
    pubkey: str
    stake: int          # integer units
    commission: int     # basis points (1000 = 10%)
    moniker: str = ""   # human-readable name


@dataclass(frozen=True)
class TestnetConfig:
    """Full testnet deployment configuration."""

    # Chain identity
    chain_id: str = "oasyce-testnet-1"
    genesis_time: int = 1710720000  # fixed genesis timestamp

    # Block timing
    blocks_per_epoch: int = 10
    block_time_seconds: int = 10
    slots_per_epoch: int = 10
    slot_duration: int = 30

    # Staking
    min_stake: int = 100 * _OAS       # 100 OAS (testnet low barrier)
    unbonding_blocks: int = 20
    unbonding_period: int = 600       # wall-clock fallback (seconds)
    jail_duration: int = 120

    # Economics
    block_reward: int = 4 * _OAS
    halving_interval: int = 10000

    # Governance
    voting_period: int = 100          # testnet fast voting
    min_deposit: int = 10 * _OAS     # testnet low deposit

    # Faucet
    faucet_enabled: bool = True
    faucet_amount: int = 10000 * _OAS  # 10,000 OAS per claim
    faucet_cooldown: int = 86400       # 24h cooldown

    # Initial validators (populated at genesis creation)
    initial_validators: List[ValidatorInfo] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "genesis_time": self.genesis_time,
            "blocks_per_epoch": self.blocks_per_epoch,
            "block_time_seconds": self.block_time_seconds,
            "slots_per_epoch": self.slots_per_epoch,
            "slot_duration": self.slot_duration,
            "min_stake": self.min_stake,
            "unbonding_blocks": self.unbonding_blocks,
            "unbonding_period": self.unbonding_period,
            "jail_duration": self.jail_duration,
            "block_reward": self.block_reward,
            "halving_interval": self.halving_interval,
            "voting_period": self.voting_period,
            "min_deposit": self.min_deposit,
            "faucet_enabled": self.faucet_enabled,
            "faucet_amount": self.faucet_amount,
            "faucet_cooldown": self.faucet_cooldown,
            "initial_validators": [
                {"pubkey": v.pubkey, "stake": v.stake,
                 "commission": v.commission, "moniker": v.moniker}
                for v in self.initial_validators
            ],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> TestnetConfig:
        validators = [
            ValidatorInfo(
                pubkey=v["pubkey"],
                stake=v["stake"],
                commission=v.get("commission", 1000),
                moniker=v.get("moniker", ""),
            )
            for v in d.get("initial_validators", [])
        ]
        return cls(
            chain_id=d.get("chain_id", "oasyce-testnet-1"),
            genesis_time=d.get("genesis_time", 1710720000),
            blocks_per_epoch=d.get("blocks_per_epoch", 10),
            block_time_seconds=d.get("block_time_seconds", 10),
            slots_per_epoch=d.get("slots_per_epoch", 10),
            slot_duration=d.get("slot_duration", 30),
            min_stake=d.get("min_stake", 100 * _OAS),
            unbonding_blocks=d.get("unbonding_blocks", 20),
            unbonding_period=d.get("unbonding_period", 600),
            jail_duration=d.get("jail_duration", 120),
            block_reward=d.get("block_reward", 4 * _OAS),
            halving_interval=d.get("halving_interval", 10000),
            voting_period=d.get("voting_period", 100),
            min_deposit=d.get("min_deposit", 10 * _OAS),
            faucet_enabled=d.get("faucet_enabled", True),
            faucet_amount=d.get("faucet_amount", 10000 * _OAS),
            faucet_cooldown=d.get("faucet_cooldown", 86400),
            initial_validators=validators,
        )

    def to_consensus_params(self) -> Dict[str, Any]:
        """Convert to consensus params dict (for ConsensusEngine)."""
        return {
            "chain_id": self.chain_id,
            "blocks_per_epoch": self.blocks_per_epoch,
            "slots_per_epoch": self.slots_per_epoch,
            "slot_duration": self.slot_duration,
            "unbonding_period": self.unbonding_period,
            "unbonding_blocks": self.unbonding_blocks,
            "jail_duration": self.jail_duration,
            "epoch_duration": self.blocks_per_epoch * self.block_time_seconds,
            "voting_period": self.voting_period,
        }

    def to_economics(self) -> Dict[str, Any]:
        """Convert to economics dict (for ConsensusEngine)."""
        return {
            "block_reward": self.block_reward,
            "min_stake": self.min_stake,
            "agent_stake": 1 * _OAS,
            "halving_interval": self.halving_interval,
            "min_deposit": self.min_deposit,
        }


# ── Pre-built configs ────────────────────────────────────────────────

DEFAULT_TESTNET_CONFIG = TestnetConfig()

DEVNET_CONFIG = TestnetConfig(
    chain_id="oasyce-devnet-1",
    blocks_per_epoch=5,
    block_time_seconds=5,
    min_stake=10 * _OAS,
    block_reward=10 * _OAS,
    voting_period=20,
    min_deposit=1 * _OAS,
    faucet_amount=100000 * _OAS,
)

"""
Genesis state creation, export, and import.

Creates the initial chain state from a TestnetConfig, including
genesis block, initial validators, and their stakes.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from oasyce_plugin.consensus.core.types import OAS_DECIMALS, from_units
from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    GENESIS_PREV_HASH,
    make_genesis_block,
)
from oasyce_plugin.consensus.testnet_config import TestnetConfig, ValidatorInfo


@dataclass
class GenesisValidator:
    """A validator in the genesis state."""
    pubkey: str
    stake: int          # integer units
    commission: int     # basis points
    moniker: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pubkey": self.pubkey,
            "stake": self.stake,
            "commission": self.commission,
            "moniker": self.moniker,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GenesisValidator:
        return cls(
            pubkey=d["pubkey"],
            stake=d["stake"],
            commission=d.get("commission", 1000),
            moniker=d.get("moniker", ""),
        )


@dataclass
class GenesisState:
    """Complete genesis state for chain initialization."""
    chain_id: str
    genesis_time: int
    genesis_block: Block
    validators: List[GenesisValidator] = field(default_factory=list)
    config: Optional[TestnetConfig] = None

    # Computed
    genesis_hash: str = ""
    total_stake: int = 0

    def __post_init__(self):
        self.genesis_hash = self.genesis_block.block_hash
        self.total_stake = sum(v.stake for v in self.validators)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "genesis_time": self.genesis_time,
            "genesis_hash": self.genesis_hash,
            "genesis_block": self.genesis_block.to_dict(),
            "validators": [v.to_dict() for v in self.validators],
            "total_stake": self.total_stake,
            "config": self.config.to_dict() if self.config else None,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GenesisState:
        block = Block.from_dict(d["genesis_block"])
        validators = [GenesisValidator.from_dict(v) for v in d.get("validators", [])]
        config = TestnetConfig.from_dict(d["config"]) if d.get("config") else None
        state = cls(
            chain_id=d["chain_id"],
            genesis_time=d["genesis_time"],
            genesis_block=block,
            validators=validators,
            config=config,
        )
        return state


def create_genesis(config: TestnetConfig,
                   validators: Optional[List[ValidatorInfo]] = None) -> GenesisState:
    """Create a genesis state from configuration.

    Args:
        config: Testnet configuration.
        validators: Override initial validators (uses config.initial_validators if None).

    Returns:
        GenesisState ready for export or chain initialization.
    """
    validators = validators or list(config.initial_validators)

    genesis_block = make_genesis_block(
        chain_id=config.chain_id,
        timestamp=config.genesis_time,
    )

    genesis_validators = [
        GenesisValidator(
            pubkey=v.pubkey,
            stake=v.stake,
            commission=v.commission,
            moniker=v.moniker,
        )
        for v in validators
    ]

    return GenesisState(
        chain_id=config.chain_id,
        genesis_time=config.genesis_time,
        genesis_block=genesis_block,
        validators=genesis_validators,
        config=config,
    )


def export_genesis(state: GenesisState, path: str) -> None:
    """Export genesis state to a JSON file.

    Args:
        state: The genesis state to export.
        path: File path for the JSON output.
    """
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True))


def import_genesis(path: str) -> GenesisState:
    """Import genesis state from a JSON file.

    Args:
        path: Path to the genesis JSON file.

    Returns:
        GenesisState parsed from the file.

    Raises:
        FileNotFoundError: If the genesis file does not exist.
        ValueError: If the genesis file is malformed.
    """
    genesis_path = Path(path)
    if not genesis_path.exists():
        raise FileNotFoundError(f"Genesis file not found: {path}")

    try:
        data = json.loads(genesis_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid genesis JSON: {e}")

    if "chain_id" not in data or "genesis_block" not in data:
        raise ValueError("Genesis file missing required fields: chain_id, genesis_block")

    return GenesisState.from_dict(data)


def validate_genesis(state: GenesisState) -> List[str]:
    """Validate a genesis state for correctness.

    Returns:
        List of error strings (empty if valid).
    """
    errors: List[str] = []

    if not state.chain_id:
        errors.append("chain_id is empty")

    if state.genesis_time <= 0:
        errors.append("genesis_time must be positive")

    if state.genesis_block.block_number != 0:
        errors.append(f"genesis block number must be 0, got {state.genesis_block.block_number}")

    if state.genesis_block.prev_hash != GENESIS_PREV_HASH:
        errors.append("genesis block prev_hash must be all zeros")

    if state.genesis_block.chain_id != state.chain_id:
        errors.append(
            f"genesis block chain_id '{state.genesis_block.chain_id}' "
            f"!= state chain_id '{state.chain_id}'"
        )

    # Validate genesis hash
    expected_hash = state.genesis_block.block_hash
    if state.genesis_hash != expected_hash:
        errors.append(f"genesis_hash mismatch: stored={state.genesis_hash}, computed={expected_hash}")

    # Validate validators
    seen_pubkeys = set()
    for v in state.validators:
        if not v.pubkey:
            errors.append("validator has empty pubkey")
        if v.pubkey in seen_pubkeys:
            errors.append(f"duplicate validator pubkey: {v.pubkey}")
        seen_pubkeys.add(v.pubkey)

        if v.stake <= 0:
            errors.append(f"validator {v.pubkey[:16]} has non-positive stake: {v.stake}")
        if v.commission < 0 or v.commission > 5000:
            errors.append(f"validator {v.pubkey[:16]} has invalid commission: {v.commission}")

    return errors


def initialize_chain(state: GenesisState, db_path: Optional[str] = None):
    """Initialize a ConsensusEngine from genesis state.

    Creates the engine, registers all genesis validators with their stakes.

    Args:
        state: Genesis state to initialize from.
        db_path: SQLite database path for consensus state.

    Returns:
        Initialized ConsensusEngine.
    """
    from oasyce_plugin.consensus import ConsensusEngine

    config = state.config or TestnetConfig(
        chain_id=state.chain_id,
        genesis_time=state.genesis_time,
    )

    engine = ConsensusEngine(
        db_path=db_path,
        consensus_params=config.to_consensus_params(),
        economics=config.to_economics(),
        genesis_time=state.genesis_time,
    )

    # Register genesis validators
    for v in state.validators:
        engine.register_validator(
            pubkey=v.pubkey,
            self_stake=v.stake,
            commission=v.commission,
            block_height=0,
        )

    return engine

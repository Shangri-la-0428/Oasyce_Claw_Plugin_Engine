"""
Staking & Slashing Engine — The Heart of Oasyce Economics

Everyone who participates is a stakeholder. Run a node → stake OAS → become
a validator → earn block rewards + tx fees. Misbehave → lose your stake.

Design principles:
  1. All participants hold OAS → everyone's interest aligned with platform
  2. Validators must stake → skin in the game
  3. Block rewards decrease over time → early adopters rewarded
  4. Slashing is brutal → one strike costs real money
  5. Extreme simplicity → few rules, hard to game

Economic Model:
  ┌─ Data access fee (100 OAS example)
  │   ├─ Creator reward  70% → 70 OAS (data creator gets the lion's share)
  │   ├─ Validator pool  20% → 20 OAS (split among validators by stake weight)
  │   └─ Burn           10% → 10 OAS (permanent deflation)
  │
  └─ Block reward (decreasing schedule)
      ├─ Year 1: 50 OAS/block
      ├─ Year 2: 25 OAS/block
      ├─ Year 3: 12.5 OAS/block
      └─ ... halving every year until fee revenue sustains the network
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ─── Configuration ────────────────────────────────────────

@dataclass(frozen=True)
class StakingConfig:
    """Staking parameters — change these to tune the economy."""
    min_stake: float = 1000.0              # Minimum OAS to become validator
    slash_rate_malicious: float = 1.0      # 100% — forge a block, lose everything
    slash_rate_double_block: float = 0.5   # 50% — produce two blocks at same height
    slash_rate_offline_per_day: float = 0.05  # 5%/day — go offline, slow bleed
    unbonding_period_seconds: int = 86400 * 7  # 7 days to withdraw (prevents hit-and-run)
    initial_block_reward: float = 50.0     # OAS per block in epoch 0
    halving_interval_blocks: int = 525_600  # ~1 year at 1 block/min
    creator_share: float = 0.70            # 70% of tx fees → data creator
    validator_share: float = 0.20          # 20% of tx fees → validator pool
    burn_share: float = 0.10              # 10% of tx fees → burned forever


# ─── Data Models ──────────────────────────────────────────

class ValidatorStatus(str, Enum):
    ACTIVE = "active"          # Staked and validating
    UNBONDING = "unbonding"    # Requested withdrawal, waiting period
    SLASHED = "slashed"        # Caught misbehaving
    EXITED = "exited"          # Fully withdrawn


class SlashReason(str, Enum):
    MALICIOUS_BLOCK = "malicious_block"      # Forged/invalid block
    DOUBLE_BLOCK = "double_block"            # Two blocks at same height
    PROLONGED_OFFLINE = "prolonged_offline"   # Offline > threshold


@dataclass
class Validator:
    """A staked network participant."""
    node_id: str
    public_key: str
    stake: float
    status: ValidatorStatus = ValidatorStatus.ACTIVE
    blocks_produced: int = 0
    rewards_earned: float = 0.0
    slash_count: int = 0
    slashed_amount: float = 0.0
    last_block_time: float = field(default_factory=time.time)
    staked_at: float = field(default_factory=time.time)
    unbonding_at: Optional[float] = None

    @property
    def is_eligible(self) -> bool:
        """Can this validator produce blocks?"""
        return self.status == ValidatorStatus.ACTIVE and self.stake > 0


@dataclass
class SlashEvent:
    """Record of a slashing incident."""
    validator_id: str
    reason: SlashReason
    amount_slashed: float
    stake_before: float
    stake_after: float
    timestamp: float = field(default_factory=time.time)
    evidence: Optional[str] = None


@dataclass
class RewardEvent:
    """Record of block reward or fee distribution."""
    validator_id: str
    block_number: int
    block_reward: float
    fee_reward: float
    total: float
    timestamp: float = field(default_factory=time.time)


# ─── Staking Engine ──────────────────────────────────────

class StakingEngine:
    """Manages validator lifecycle, rewards, and slashing."""

    def __init__(self, config: Optional[StakingConfig] = None):
        self.config = config or StakingConfig()
        self.validators: Dict[str, Validator] = {}
        self.slash_history: List[SlashEvent] = []
        self.reward_history: List[RewardEvent] = []
        self.total_staked: float = 0.0
        self.total_burned_from_slash: float = 0.0
        self.total_rewards_distributed: float = 0.0

    # ─── Validator Lifecycle ──────────────────────────────

    def stake(self, node_id: str, public_key: str, amount: float) -> Validator:
        """Stake OAS to become a validator. Everyone's a shareholder."""
        if node_id in self.validators:
            v = self.validators[node_id]
            if v.status == ValidatorStatus.SLASHED:
                raise ValueError("Slashed validators cannot re-stake")
            v.stake += amount
            if v.status == ValidatorStatus.EXITED:
                v.status = ValidatorStatus.ACTIVE
                v.unbonding_at = None
        else:
            if amount < self.config.min_stake:
                raise ValueError(
                    f"Minimum stake is {self.config.min_stake} OAS, got {amount}"
                )
            v = Validator(
                node_id=node_id,
                public_key=public_key,
                stake=amount,
            )
            self.validators[node_id] = v

        self.total_staked += amount
        return v

    def request_unstake(self, node_id: str) -> Validator:
        """Begin unbonding period. Stake locked for 7 days (no hit-and-run)."""
        v = self._get_active_validator(node_id)
        v.status = ValidatorStatus.UNBONDING
        v.unbonding_at = time.time()
        return v

    def complete_unstake(self, node_id: str) -> float:
        """Withdraw stake after unbonding period. Returns amount withdrawn."""
        v = self.validators.get(node_id)
        if not v or v.status != ValidatorStatus.UNBONDING:
            raise ValueError(f"Validator {node_id} is not unbonding")

        elapsed = time.time() - (v.unbonding_at or 0)
        if elapsed < self.config.unbonding_period_seconds:
            remaining = self.config.unbonding_period_seconds - elapsed
            raise ValueError(
                f"Unbonding period not complete. {remaining:.0f}s remaining"
            )

        amount = v.stake
        v.stake = 0
        v.status = ValidatorStatus.EXITED
        self.total_staked -= amount
        return amount

    # ─── Block Rewards ────────────────────────────────────

    def block_reward_amount(self, block_number: int) -> float:
        """Calculate block reward with halving schedule.

        Year 1: 50 OAS/block, Year 2: 25, Year 3: 12.5, ...
        Like Bitcoin: early believers get more, late joiners still earn.
        """
        halvings = block_number // self.config.halving_interval_blocks
        return self.config.initial_block_reward / (2 ** halvings)

    def distribute_block_reward(
        self, validator_id: str, block_number: int, tx_fees: float = 0.0
    ) -> RewardEvent:
        """Reward a validator for producing a valid block.

        Block reward (new OAS) + validator's share of transaction fees.
        """
        v = self._get_active_validator(validator_id)

        block_reward = self.block_reward_amount(block_number)
        fee_reward = tx_fees * self.config.validator_share

        total = block_reward + fee_reward
        v.rewards_earned += total
        v.blocks_produced += 1
        v.last_block_time = time.time()

        self.total_rewards_distributed += total

        event = RewardEvent(
            validator_id=validator_id,
            block_number=block_number,
            block_reward=round(block_reward, 6),
            fee_reward=round(fee_reward, 6),
            total=round(total, 6),
        )
        self.reward_history.append(event)
        return event

    def distribute_fees(self, creator: str, tx_fees: float) -> Dict[str, float]:
        """Split transaction fees: creator 70%, validators 20%, burn 10%.

        Returns the split amounts. Creator reward is direct.
        Validator share goes to the pool (distributed by stake weight on block).
        Burn is permanent — OAS destroyed forever.
        """
        creator_amount = round(tx_fees * self.config.creator_share, 6)
        validator_amount = round(tx_fees * self.config.validator_share, 6)
        burn_amount = round(tx_fees * self.config.burn_share, 6)

        return {
            "creator": creator_amount,
            "creator_addr": creator,
            "validators": validator_amount,
            "burn": burn_amount,
            "total": round(creator_amount + validator_amount + burn_amount, 6),
        }

    # ─── Slashing ─────────────────────────────────────────

    def slash(
        self, node_id: str, reason: SlashReason, evidence: Optional[str] = None
    ) -> SlashEvent:
        """Slash a validator. The punishment fits the crime.

        MALICIOUS_BLOCK → 100% stake gone (you tried to cheat, you lose it all)
        DOUBLE_BLOCK → 50% stake gone (could be accidental, but still costly)
        PROLONGED_OFFLINE → 5%/day (gentle bleed, come back online or exit)
        """
        v = self.validators.get(node_id)
        if not v:
            raise ValueError(f"Validator {node_id} not found")

        stake_before = v.stake

        rate = {
            SlashReason.MALICIOUS_BLOCK: self.config.slash_rate_malicious,
            SlashReason.DOUBLE_BLOCK: self.config.slash_rate_double_block,
            SlashReason.PROLONGED_OFFLINE: self.config.slash_rate_offline_per_day,
        }[reason]

        slash_amount = round(v.stake * rate, 6)
        v.stake = round(v.stake - slash_amount, 6)
        v.slash_count += 1
        v.slashed_amount += slash_amount

        # Malicious → permanently kicked
        if reason == SlashReason.MALICIOUS_BLOCK:
            v.status = ValidatorStatus.SLASHED

        # Stake too low → force exit
        if v.stake < self.config.min_stake and v.status == ValidatorStatus.ACTIVE:
            v.status = ValidatorStatus.EXITED

        self.total_staked -= slash_amount
        self.total_burned_from_slash += slash_amount  # slashed OAS is burned

        event = SlashEvent(
            validator_id=node_id,
            reason=reason,
            amount_slashed=slash_amount,
            stake_before=stake_before,
            stake_after=v.stake,
            evidence=evidence,
        )
        self.slash_history.append(event)
        return event

    def detect_double_block(
        self, node_id: str, height: int, block_hashes: List[str]
    ) -> bool:
        """Check if a validator produced two different blocks at the same height.

        Returns True if double-block detected (and slashing triggered).
        """
        if len(set(block_hashes)) > 1:
            self.slash(
                node_id,
                SlashReason.DOUBLE_BLOCK,
                evidence=f"height={height}, hashes={block_hashes}",
            )
            return True
        return False

    def check_offline(self, node_id: str, threshold_seconds: float = 86400) -> bool:
        """Check if validator has been offline too long. Slash if so."""
        v = self.validators.get(node_id)
        if not v or v.status != ValidatorStatus.ACTIVE:
            return False

        elapsed = time.time() - v.last_block_time
        if elapsed > threshold_seconds:
            days_offline = elapsed / 86400
            # Slash once per check (caller should rate-limit)
            self.slash(
                node_id,
                SlashReason.PROLONGED_OFFLINE,
                evidence=f"offline {days_offline:.1f} days",
            )
            return True
        return False

    # ─── Validator Selection ──────────────────────────────

    def select_block_producer(self) -> Optional[str]:
        """Select next block producer weighted by stake.

        Simple proportional selection: more stake = more likely to produce.
        This is the core of PoS — your "vote" is proportional to your investment.
        """
        active = [
            (vid, v) for vid, v in self.validators.items()
            if v.is_eligible
        ]
        if not active:
            return None

        # Deterministic round-robin weighted by stake
        # (In production, use VRF or similar for unpredictability)
        total = sum(v.stake for _, v in active)
        if total <= 0:
            return None

        # Pick validator with highest (stake / blocks_produced) ratio
        # This naturally balances: high stakers produce more, but everyone gets turns
        best_id = None
        best_score = -1.0
        for vid, v in active:
            score = v.stake / (v.blocks_produced + 1)
            if score > best_score:
                best_score = score
                best_id = vid

        return best_id

    # ─── Queries ──────────────────────────────────────────

    def get_validator(self, node_id: str) -> Optional[Validator]:
        return self.validators.get(node_id)

    def active_validators(self) -> List[Validator]:
        return [v for v in self.validators.values() if v.is_eligible]

    def total_active_stake(self) -> float:
        return sum(v.stake for v in self.validators.values() if v.is_eligible)

    def network_stats(self) -> Dict[str, Any]:
        active = self.active_validators()
        return {
            "total_validators": len(self.validators),
            "active_validators": len(active),
            "total_staked": round(self.total_staked, 6),
            "total_rewards_distributed": round(self.total_rewards_distributed, 6),
            "total_burned_from_slash": round(self.total_burned_from_slash, 6),
            "total_slash_events": len(self.slash_history),
            "avg_stake": round(
                sum(v.stake for v in active) / len(active), 6
            ) if active else 0,
        }

    # ─── Helpers ──────────────────────────────────────────

    def _get_active_validator(self, node_id: str) -> Validator:
        v = self.validators.get(node_id)
        if not v:
            raise ValueError(f"Validator {node_id} not found")
        if not v.is_eligible:
            raise ValueError(f"Validator {node_id} is not active (status={v.status})")
        return v

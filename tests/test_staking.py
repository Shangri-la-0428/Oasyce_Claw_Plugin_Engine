"""
Tests for the Staking & Slashing Engine — Phase 8 economics.
"""

import time
import pytest

from oasyce_plugin.services.staking import (
    StakingConfig,
    StakingEngine,
    SlashReason,
    ValidatorStatus,
)


@pytest.fixture
def engine():
    return StakingEngine()


@pytest.fixture
def small_engine():
    """Engine with low thresholds for faster testing."""
    return StakingEngine(StakingConfig(
        min_stake=100.0,
        unbonding_period_seconds=1,  # 1 second for testing
    ))


# ── Staking Lifecycle ────────────────────────────────────────────────


class TestStaking:
    def test_stake_success(self, engine):
        v = engine.stake("node-0", "pk_0", 20000.0)
        assert v.stake == 20000.0
        assert v.status == ValidatorStatus.ACTIVE
        assert engine.total_staked == 20000.0

    def test_stake_below_minimum_rejected(self, engine):
        with pytest.raises(ValueError, match="Minimum stake"):
            engine.stake("node-0", "pk_0", 5000.0)

    def test_stake_adds_to_existing(self, engine):
        engine.stake("node-0", "pk_0", 10000.0)
        engine.stake("node-0", "pk_0", 500.0)
        assert engine.validators["node-0"].stake == 10500.0
        assert engine.total_staked == 10500.0

    def test_multiple_validators(self, engine):
        engine.stake("node-0", "pk_0", 10000.0)
        engine.stake("node-1", "pk_1", 30000.0)
        assert len(engine.active_validators()) == 2
        assert engine.total_active_stake() == 40000.0


class TestUnstaking:
    def test_unbonding_period(self, engine):
        engine.stake("node-0", "pk_0", 20000.0)
        engine.request_unstake("node-0")
        assert engine.validators["node-0"].status == ValidatorStatus.UNBONDING

        # Can't withdraw immediately
        with pytest.raises(ValueError, match="not complete"):
            engine.complete_unstake("node-0")

    def test_unstake_after_period(self, small_engine):
        small_engine.stake("node-0", "pk_0", 1000.0)
        small_engine.request_unstake("node-0")
        time.sleep(1.1)  # Wait for unbonding
        amount = small_engine.complete_unstake("node-0")
        assert amount == 1000.0
        assert small_engine.validators["node-0"].status == ValidatorStatus.EXITED
        assert small_engine.total_staked == 0.0

    def test_exited_can_restake(self, small_engine):
        small_engine.stake("node-0", "pk_0", 1000.0)
        small_engine.request_unstake("node-0")
        time.sleep(1.1)
        small_engine.complete_unstake("node-0")
        # Re-stake
        small_engine.stake("node-0", "pk_0", 1000.0)
        assert small_engine.validators["node-0"].status == ValidatorStatus.ACTIVE


# ── Block Rewards ────────────────────────────────────────────────────


class TestBlockRewards:
    def test_initial_reward(self, engine):
        assert engine.block_reward_amount(0) == 4.0

    def test_halving(self, engine):
        # After 1051200 blocks (~2 years)
        assert engine.block_reward_amount(1_051_200) == 2.0
        assert engine.block_reward_amount(1_051_200 * 2) == 1.0
        assert engine.block_reward_amount(1_051_200 * 3) == 0.5

    def test_distribute_reward(self, engine):
        engine.stake("node-0", "pk_0", 20000.0)
        event = engine.distribute_block_reward("node-0", block_number=0, tx_fees=100.0)
        # Block reward 4 + validator share 20% of 100 = 20
        assert event.block_reward == 4.0
        assert event.fee_reward == 20.0
        assert event.total == 24.0
        assert engine.validators["node-0"].rewards_earned == 24.0
        assert engine.validators["node-0"].blocks_produced == 1

    def test_fee_distribution(self, engine):
        split = engine.distribute_fees("creator_01", 100.0)
        assert split["creator"] == 60.0
        assert split["validators"] == 20.0
        assert split["burn"] == 15.0
        assert split["treasury"] == 5.0


# ── Slashing ─────────────────────────────────────────────────────────


class TestSlashing:
    def test_slash_malicious_block(self, engine):
        engine.stake("node-0", "pk_0", 50000.0)
        event = engine.slash("node-0", SlashReason.MALICIOUS_BLOCK)
        assert event.amount_slashed == 50000.0  # 100% gone
        assert engine.validators["node-0"].stake == 0.0
        assert engine.validators["node-0"].status == ValidatorStatus.SLASHED
        assert engine.total_burned_from_slash == 50000.0

    def test_slashed_cannot_restake(self, engine):
        engine.stake("node-0", "pk_0", 50000.0)
        engine.slash("node-0", SlashReason.MALICIOUS_BLOCK)
        with pytest.raises(ValueError, match="cannot re-stake"):
            engine.stake("node-0", "pk_0", 10000.0)

    def test_slash_double_block(self, engine):
        engine.stake("node-0", "pk_0", 40000.0)
        event = engine.slash("node-0", SlashReason.DOUBLE_BLOCK)
        assert event.amount_slashed == 20000.0  # 50%
        assert engine.validators["node-0"].stake == 20000.0

    def test_slash_offline(self, engine):
        engine.stake("node-0", "pk_0", 20000.0)
        event = engine.slash("node-0", SlashReason.PROLONGED_OFFLINE)
        assert event.amount_slashed == 1000.0  # 5%
        assert engine.validators["node-0"].stake == 19000.0

    def test_slash_below_minimum_forces_exit(self, engine):
        engine.stake("node-0", "pk_0", 10000.0)
        engine.slash("node-0", SlashReason.DOUBLE_BLOCK)  # 50% = 5000, below 10000 min
        assert engine.validators["node-0"].status == ValidatorStatus.EXITED

    def test_detect_double_block(self, engine):
        engine.stake("node-0", "pk_0", 40000.0)
        detected = engine.detect_double_block(
            "node-0", height=5, block_hashes=["aaa", "bbb"]
        )
        assert detected is True
        assert engine.validators["node-0"].slashed_amount == 20000.0

    def test_no_double_block_same_hash(self, engine):
        engine.stake("node-0", "pk_0", 40000.0)
        detected = engine.detect_double_block(
            "node-0", height=5, block_hashes=["aaa", "aaa"]
        )
        assert detected is False


class TestOfflineDetection:
    def test_check_offline_recent(self, engine):
        engine.stake("node-0", "pk_0", 20000.0)
        # Just staked, last_block_time is now → not offline
        assert engine.check_offline("node-0", threshold_seconds=86400) is False

    def test_check_offline_stale(self, engine):
        engine.stake("node-0", "pk_0", 20000.0)
        # Fake old last_block_time
        engine.validators["node-0"].last_block_time = time.time() - 100000
        assert engine.check_offline("node-0", threshold_seconds=86400) is True
        assert engine.validators["node-0"].slashed_amount > 0


# ── Validator Selection ──────────────────────────────────────────────


class TestValidatorSelection:
    def test_select_from_single(self, engine):
        engine.stake("node-0", "pk_0", 20000.0)
        selected = engine.select_block_producer()
        assert selected == "node-0"

    def test_select_favors_higher_stake(self, engine):
        engine.stake("node-0", "pk_0", 10000.0)
        engine.stake("node-1", "pk_1", 90000.0)
        # node-1 has 9x stake, should be selected first
        selected = engine.select_block_producer()
        assert selected == "node-1"

    def test_select_balances_over_time(self, engine):
        engine.stake("node-0", "pk_0", 20000.0)
        engine.stake("node-1", "pk_1", 20000.0)
        # After node-0 produces a block, node-1 should get next turn
        engine.distribute_block_reward("node-0", 0)
        selected = engine.select_block_producer()
        assert selected == "node-1"

    def test_no_active_validators(self, engine):
        assert engine.select_block_producer() is None

    def test_slashed_not_selected(self, engine):
        engine.stake("node-0", "pk_0", 50000.0)
        engine.stake("node-1", "pk_1", 10000.0)
        engine.slash("node-0", SlashReason.MALICIOUS_BLOCK)
        selected = engine.select_block_producer()
        assert selected == "node-1"


# ── Network Stats ────────────────────────────────────────────────────


class TestNetworkStats:
    def test_empty_network(self, engine):
        stats = engine.network_stats()
        assert stats["total_validators"] == 0
        assert stats["active_validators"] == 0

    def test_stats_after_activity(self, engine):
        engine.stake("node-0", "pk_0", 30000.0)
        engine.stake("node-1", "pk_1", 20000.0)
        engine.distribute_block_reward("node-0", 0, tx_fees=50.0)
        engine.slash("node-1", SlashReason.PROLONGED_OFFLINE)

        stats = engine.network_stats()
        assert stats["total_validators"] == 2
        assert stats["active_validators"] == 2  # node-1 still active (stake 19000 > min 10000)
        assert stats["total_rewards_distributed"] > 0
        assert stats["total_slash_events"] == 1


# ── Incentive Alignment (the soul of the protocol) ───────────────────


class TestIncentiveAlignment:
    """These tests verify the game-theoretic properties of the system."""

    def test_honest_validator_profits(self, engine):
        """An honest validator earns rewards over time."""
        engine.stake("honest", "pk_h", 50000.0)
        for i in range(10):
            engine.distribute_block_reward("honest", i, tx_fees=100.0)
        v = engine.validators["honest"]
        assert v.rewards_earned > 0
        assert v.slash_count == 0
        # Net positive: rewards > 0, losses = 0
        assert v.rewards_earned > v.slashed_amount

    def test_malicious_validator_loses_everything(self, engine):
        """A malicious validator loses their entire stake."""
        engine.stake("evil", "pk_e", 100000.0)
        # Even if they earned some rewards first
        engine.distribute_block_reward("evil", 0, tx_fees=100.0)
        rewards_before = engine.validators["evil"].rewards_earned

        engine.slash("evil", SlashReason.MALICIOUS_BLOCK)
        v = engine.validators["evil"]
        assert v.stake == 0.0
        assert v.slashed_amount == 100000.0
        # Net negative: lost 100000 stake, earned only ~24 rewards
        assert v.slashed_amount > rewards_before

    def test_attack_cost_exceeds_benefit(self, engine):
        """The cost of attacking always exceeds any possible benefit."""
        engine.stake("attacker", "pk_a", 50000.0)
        # Best case: attacker produces a few blocks before getting caught
        for i in range(3):
            engine.distribute_block_reward("attacker", i, tx_fees=100.0)
        max_earnings = engine.validators["attacker"].rewards_earned

        # Then gets slashed
        engine.slash("attacker", SlashReason.MALICIOUS_BLOCK)
        loss = engine.validators["attacker"].slashed_amount

        # Loss always > gain (50000 stake lost vs ~72 earned)
        assert loss > max_earnings * 10  # By a huge margin

    def test_everyone_is_a_stakeholder(self, engine):
        """Every participant has OAS at risk → aligned interests."""
        engine.stake("node-0", "pk_0", 20000.0)
        engine.stake("node-1", "pk_1", 30000.0)
        engine.stake("node-2", "pk_2", 50000.0)

        # Total staked = total at risk = total alignment
        assert engine.total_active_stake() == 100000.0
        # Every validator has skin in the game
        for v in engine.active_validators():
            assert v.stake >= engine.config.min_stake

"""
Tests for reward distribution — block rewards + work rewards with commission.
Updated for integer units and event-sourced architecture.
"""

import pytest

from oasyce_plugin.consensus.state import ConsensusState
from oasyce_plugin.consensus.rewards import RewardEngine
from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus.core.types import to_units, from_units, apply_rate_bps, OAS_DECIMALS


@pytest.fixture
def state():
    s = ConsensusState(":memory:")
    yield s
    s.close()


@pytest.fixture
def engine(state):
    return RewardEngine(
        state, block_reward=to_units(40), halving_interval=10000,
    )


def _setup_validator(state, vid="v1", stake_oas=1000, commission_bps=1000):
    state.register_validator(vid, commission_bps, 0)
    append_event(state, 0, vid, "register_self", to_units(stake_oas), from_addr=vid)


class TestBlockRewardHalving:
    def test_no_halving(self, engine):
        assert engine.current_block_reward(0) == to_units(40)
        assert engine.current_block_reward(9999) == to_units(40)

    def test_first_halving(self, engine):
        assert engine.current_block_reward(10000) == to_units(20)

    def test_second_halving(self, engine):
        assert engine.current_block_reward(20000) == to_units(10)


class TestComputeValidatorRewards:
    def test_block_rewards_only(self, state, engine):
        _setup_validator(state, "v1", 1000, 1000)  # 10% commission
        result = engine.compute_validator_rewards(
            "v1", epoch_number=0, blocks_proposed=5,
            work_value=0, current_block_height=0,
        )
        # 5 blocks * 40 OAS = 200 OAS total
        assert result["block_reward_total"] == to_units(200)
        # validator gets 10% commission = 20 OAS
        assert result["validator_income"] == apply_rate_bps(to_units(200), 1000)
        # delegator pool = 200 - 20 = 180 OAS
        assert result["delegator_pool"] == to_units(200) - apply_rate_bps(to_units(200), 1000)

    def test_work_rewards_only(self, state, engine):
        _setup_validator(state, "v1", 1000, 1000)
        result = engine.compute_validator_rewards(
            "v1", epoch_number=0, blocks_proposed=0,
            work_value=to_units(100), current_block_height=0,
        )
        # work_value = 100 OAS
        # validator: 90% of work = 90 OAS
        assert result["validator_income"] == apply_rate_bps(to_units(100), 9000)
        # delegator: 10% of work = 10 OAS
        assert result["delegator_pool"] == apply_rate_bps(to_units(100), 1000)

    def test_combined(self, state, engine):
        _setup_validator(state, "v1", 1000, 1000)
        result = engine.compute_validator_rewards(
            "v1", epoch_number=0, blocks_proposed=2,
            work_value=to_units(50), current_block_height=0,
        )
        # block: 2*40 = 80 OAS, commission 10% = 8, delegator = 72
        # work: validator 90% = 45, delegator 10% = 5
        block_total = to_units(80)
        block_commission = apply_rate_bps(block_total, 1000)
        work_val_share = apply_rate_bps(to_units(50), 9000)
        work_del_share = apply_rate_bps(to_units(50), 1000)
        assert result["validator_income"] == block_commission + work_val_share
        assert result["delegator_pool"] == (block_total - block_commission) + work_del_share

    def test_nonexistent_validator(self, state, engine):
        result = engine.compute_validator_rewards("missing", 0, 1, 0, 0)
        assert "error" in result


class TestDistributeEpochRewards:
    def test_single_validator_no_delegators(self, state, engine):
        _setup_validator(state, "v1", 1000, 1000)
        metrics = [{"validator_id": "v1", "blocks_proposed": 3, "work_value": 0}]
        result = engine.distribute_epoch_rewards(0, metrics, 0)
        assert result["total_distributed"] > 0
        events = state.get_reward_events(epoch_number=0)
        assert len(events) >= 1

    def test_with_delegators(self, state, engine):
        _setup_validator(state, "v1", 500, 1000)
        append_event(state, 1, "v1", "delegate", to_units(300), from_addr="d1")
        append_event(state, 1, "v1", "delegate", to_units(200), from_addr="d2")
        metrics = [{"validator_id": "v1", "blocks_proposed": 2, "work_value": to_units(100)}]
        result = engine.distribute_epoch_rewards(0, metrics, 0)
        events = state.get_reward_events(epoch_number=0)
        delegation_events = [e for e in events if e["reward_type"] == "delegation"]
        assert len(delegation_events) == 2

    def test_multiple_validators(self, state, engine):
        _setup_validator(state, "v1", 1000, 1000)
        _setup_validator(state, "v2", 500, 2000)
        metrics = [
            {"validator_id": "v1", "blocks_proposed": 5, "work_value": to_units(50)},
            {"validator_id": "v2", "blocks_proposed": 3, "work_value": to_units(30)},
        ]
        result = engine.distribute_epoch_rewards(0, metrics, 0)
        assert result["total_distributed"] > 0
        assert len(result["validators"]) == 2

    def test_updates_blocks_proposed(self, state, engine):
        _setup_validator(state, "v1", 1000)
        metrics = [{"validator_id": "v1", "blocks_proposed": 5, "work_value": 0}]
        engine.distribute_epoch_rewards(0, metrics, 0)
        v = state.get_validator("v1")
        assert v["blocks_proposed"] == 5

    def test_empty_metrics(self, state, engine):
        result = engine.distribute_epoch_rewards(0, [], 0)
        assert result["total_distributed"] == 0

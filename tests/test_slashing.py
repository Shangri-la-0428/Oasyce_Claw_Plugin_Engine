"""
Tests for slashing engine — offline, double sign, low quality.
Updated for integer units and event-sourced architecture.
"""

import pytest

from oasyce_plugin.consensus.state import ConsensusState
from oasyce_plugin.consensus.validator_registry import ValidatorRegistry
from oasyce_plugin.consensus.slashing import SlashingEngine
from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus.core.types import to_units, apply_rate_bps, OFFLINE_SLASH_BPS, DOUBLE_SIGN_SLASH_BPS, LOW_QUALITY_SLASH_BPS


@pytest.fixture
def state():
    s = ConsensusState(":memory:")
    yield s
    s.close()


@pytest.fixture
def registry(state):
    return ValidatorRegistry(
        state, min_stake=to_units(100), unbonding_period=600, jail_duration=120,
    )


@pytest.fixture
def slashing(state, registry):
    return SlashingEngine(state, registry, min_stake=to_units(100), jail_duration=120)


def _setup_validator(state, vid="v1", stake_oas=1000):
    state.register_validator(vid, 1000, 0)
    append_event(state, 0, vid, "register_self", to_units(stake_oas), from_addr=vid)


class TestCheckOffline:
    def test_no_assigned_slots(self, state, slashing):
        _setup_validator(state)
        result = slashing.check_offline("v1", 0)
        assert result is None

    def test_all_proposed(self, state, slashing):
        _setup_validator(state)
        schedule = [{"slot_index": i, "validator_id": "v1"} for i in range(5)]
        state.set_leader_schedule(0, schedule)
        for i in range(5):
            state.mark_slot_proposed(0, i)
        result = slashing.check_offline("v1", 0)
        assert result is None

    def test_missed_majority(self, state, slashing):
        _setup_validator(state)
        schedule = [{"slot_index": i, "validator_id": "v1"} for i in range(10)]
        state.set_leader_schedule(0, schedule)
        for i in range(3):
            state.mark_slot_proposed(0, i)
        result = slashing.check_offline("v1", 0)
        assert result is not None
        assert result["reason"] == "offline"
        assert result["missed"] == 7


class TestCheckDoubleSign:
    def test_no_double_sign(self, slashing):
        result = slashing.check_double_sign("v1", "hash_a", "hash_a", 5)
        assert result is None

    def test_double_sign_detected(self, slashing):
        result = slashing.check_double_sign("v1", "hash_a", "hash_b", 5)
        assert result is not None
        assert result["reason"] == "double_sign"


class TestCheckLowQuality:
    def test_not_enough_tasks(self, slashing):
        result = slashing.check_low_quality("v1", [5000, 6000])  # basis points
        assert result is None

    def test_good_quality(self, slashing):
        result = slashing.check_low_quality("v1", [8000] * 10)  # 80% quality
        assert result is None

    def test_low_quality_detected(self, slashing):
        result = slashing.check_low_quality("v1", [1000] * 10)  # 10% quality
        assert result is not None
        assert result["reason"] == "low_quality"
        assert result["avg_quality"] == 1000


class TestApplySlash:
    def test_slash_offline(self, state, slashing):
        _setup_validator(state, stake_oas=1000)
        result = slashing.apply_slash("v1", "offline", 0)
        assert result["ok"] is True
        expected = apply_rate_bps(to_units(1000), OFFLINE_SLASH_BPS)
        assert result["slash_amount"] == expected  # 1%
        assert result["jailed"] is True
        v = state.get_validator("v1")
        assert v["status"] == "jailed"
        assert v["total_stake"] == to_units(1000) - expected

    def test_slash_double_sign(self, state, slashing):
        _setup_validator(state, stake_oas=1000)
        result = slashing.apply_slash("v1", "double_sign", 0)
        assert result["ok"] is True
        expected = apply_rate_bps(to_units(1000), DOUBLE_SIGN_SLASH_BPS)
        assert result["slash_amount"] == expected  # 5%
        assert result["jailed"] is True

    def test_slash_low_quality(self, state, slashing):
        _setup_validator(state, stake_oas=1000)
        result = slashing.apply_slash("v1", "low_quality", 0)
        assert result["ok"] is True
        expected = apply_rate_bps(to_units(1000), LOW_QUALITY_SLASH_BPS)
        assert result["slash_amount"] == expected  # 0.5%
        assert result["jailed"] is False

    def test_slash_with_delegations(self, state, slashing):
        _setup_validator(state, "v1", 500)
        append_event(state, 1, "v1", "delegate", to_units(500), from_addr="d1")
        # Total stake = 1000, slash offline = 1%
        result = slashing.apply_slash("v1", "offline", 0)
        assert result["ok"] is True
        expected = apply_rate_bps(to_units(1000), OFFLINE_SLASH_BPS)
        assert result["slash_amount"] == expected

    def test_slash_drops_below_min(self, state, slashing):
        _setup_validator(state, stake_oas=105)
        result = slashing.apply_slash("v1", "low_quality", 0)
        assert result["ok"] is True
        v = state.get_validator("v1")
        assert v["total_stake"] < to_units(105)

    def test_slash_nonexistent(self, slashing):
        result = slashing.apply_slash("missing", "offline", 0)
        assert result["ok"] is False

    def test_slash_events_recorded(self, state, slashing):
        _setup_validator(state, stake_oas=1000)
        slashing.apply_slash("v1", "offline", 0)
        events = state.get_slash_events(validator_id="v1")
        assert len(events) == 1
        assert events[0]["reason"] == "offline"


class TestProcessEpochSlashing:
    def test_slashes_offline_validators(self, state, slashing):
        _setup_validator(state, "v1", 1000)
        _setup_validator(state, "v2", 1000)
        schedule = [{"slot_index": i, "validator_id": "v1"} for i in range(10)]
        state.set_leader_schedule(0, schedule)
        for i in range(2):
            state.mark_slot_proposed(0, i)
        results = slashing.process_epoch_slashing(0)
        assert len(results) == 1
        assert results[0]["validator_id"] == "v1"

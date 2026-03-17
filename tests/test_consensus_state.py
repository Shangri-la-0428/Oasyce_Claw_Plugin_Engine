"""
Tests for consensus state, epoch management, validator registry.
Updated for event-sourced architecture with integer units.
"""

import time

import pytest

from oasyce_plugin.consensus.state import ConsensusState
from oasyce_plugin.consensus.epoch import EpochManager
from oasyce_plugin.consensus.validator_registry import ValidatorRegistry
from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus.core.types import to_units


@pytest.fixture
def state():
    s = ConsensusState(":memory:")
    yield s
    s.close()


@pytest.fixture
def epoch_mgr(state):
    params = {
        "epoch_duration": 300,
        "slots_per_epoch": 10,
        "slot_duration": 30,
        "unbonding_period": 600,
        "jail_duration": 120,
    }
    return EpochManager(state, params, genesis_time=1000000)


@pytest.fixture
def registry(state):
    return ValidatorRegistry(
        state, min_stake=to_units(100), unbonding_period=600, jail_duration=120,
    )


def _setup_validator(state, vid="v1", stake_oas=500):
    """Register a validator and record self-stake event."""
    state.register_validator(vid, 1000, 0)  # 10% commission in bps
    append_event(state, 0, vid, "register_self", to_units(stake_oas), from_addr=vid)


# ── ConsensusState ────────────────────────────────────────────────


class TestValidatorCRUD:
    def test_register_and_get(self, state):
        _setup_validator(state, "val_a", 500)
        v = state.get_validator("val_a")
        assert v is not None
        assert v["self_stake"] == to_units(500)
        assert v["total_stake"] == to_units(500)
        assert v["status"] == "active"

    def test_duplicate_register_fails(self, state):
        state.register_validator("val_a", 1000)
        ok = state.register_validator("val_a", 1000)
        assert ok is False

    def test_get_active_validators(self, state):
        _setup_validator(state, "v1", 200)
        _setup_validator(state, "v2", 500)
        _setup_validator(state, "v3", 50)
        active = state.get_active_validators(min_stake=to_units(100))
        ids = [v["validator_id"] for v in active]
        assert "v1" in ids
        assert "v2" in ids
        assert "v3" not in ids

    def test_jail_and_unjail(self, state):
        _setup_validator(state, "v1", 500)
        state.jail_validator("v1", until=9999999999)
        v = state.get_validator("v1")
        assert v["status"] == "jailed"

        state.unjail_validator("v1")
        v = state.get_validator("v1")
        assert v["status"] == "active"

    def test_exit(self, state):
        _setup_validator(state, "v1", 500)
        state.exit_validator("v1")
        v = state.get_validator("v1")
        assert v["status"] == "exited"


class TestDelegations:
    def test_add_delegation(self, state):
        _setup_validator(state, "v1", 500)
        append_event(state, 1, "v1", "delegate", to_units(100), from_addr="d1")
        v = state.get_validator("v1")
        assert v["total_stake"] == to_units(600)

    def test_remove_delegation(self, state):
        _setup_validator(state, "v1", 500)
        append_event(state, 1, "v1", "delegate", to_units(200), from_addr="d1")
        append_event(state, 2, "v1", "undelegate", to_units(100), from_addr="d1")
        v = state.get_validator("v1")
        assert v["total_stake"] == to_units(600)

    def test_remove_full_delegation(self, state):
        _setup_validator(state, "v1", 500)
        append_event(state, 1, "v1", "delegate", to_units(200), from_addr="d1")
        append_event(state, 2, "v1", "undelegate", to_units(200), from_addr="d1")
        v = state.get_validator("v1")
        assert v["total_stake"] == to_units(500)
        dels = state.get_delegations("v1")
        assert len(dels) == 0


class TestUnbonding:
    def test_add_and_mature(self, state):
        _setup_validator(state, "v1", 500)
        now = int(time.time())
        state.add_unbonding("d1", "v1", to_units(100), 10)  # 10s period
        matured = state.get_matured_unbondings(now)
        assert len(matured) == 0
        matured = state.get_matured_unbondings(now + 15)
        assert len(matured) == 1
        assert matured[0]["amount"] == to_units(100)


class TestEpochs:
    def test_create_and_get(self, state):
        ok = state.create_epoch(0, 1000000, start_block=0, validator_count=3)
        assert ok is True
        e = state.get_epoch(0)
        assert e["start_time"] == 1000000
        assert e["status"] == "active"

    def test_finalize(self, state):
        state.create_epoch(0, 1000000)
        state.finalize_epoch(0, 1000300, 10, to_units(400))
        e = state.get_epoch(0)
        assert e["status"] == "finalized"
        assert e["total_rewards"] == to_units(400)


class TestLeaderSchedule:
    def test_set_and_get(self, state):
        schedule = [
            {"slot_index": 0, "validator_id": "v1"},
            {"slot_index": 1, "validator_id": "v2"},
            {"slot_index": 2, "validator_id": "v1"},
        ]
        state.set_leader_schedule(0, schedule)
        result = state.get_leader_schedule(0)
        assert len(result) == 3
        assert result[0]["validator_id"] == "v1"

    def test_slot_leader(self, state):
        schedule = [
            {"slot_index": 0, "validator_id": "v1"},
            {"slot_index": 1, "validator_id": "v2"},
        ]
        state.set_leader_schedule(0, schedule)
        assert state.get_slot_leader(0, 0) == "v1"
        assert state.get_slot_leader(0, 1) == "v2"
        assert state.get_slot_leader(0, 5) is None

    def test_mark_proposed(self, state):
        schedule = [{"slot_index": 0, "validator_id": "v1"}]
        state.set_leader_schedule(0, schedule)
        state.mark_slot_proposed(0, 0)
        assert state.count_proposed_slots(0, "v1") == 1
        assert state.count_assigned_slots(0, "v1") == 1


class TestSlashAndRewardEvents:
    def test_record_slash(self, state):
        sid = state.record_slash("v1", "offline", to_units(5), 0)
        assert sid > 0
        events = state.get_slash_events(validator_id="v1")
        assert len(events) == 1
        assert events[0]["reason"] == "offline"

    def test_record_reward(self, state):
        rid = state.record_reward(0, "v1", "v1", "block", to_units(40))
        assert rid > 0
        events = state.get_reward_events(epoch_number=0)
        assert len(events) == 1
        assert events[0]["amount"] == to_units(40)


# ── EpochManager ──────────────────────────────────────────────────


class TestEpochManager:
    def test_current_epoch(self, epoch_mgr):
        assert epoch_mgr.current_epoch(1000000) == 0
        assert epoch_mgr.current_epoch(1000299) == 0
        assert epoch_mgr.current_epoch(1000300) == 1
        assert epoch_mgr.current_epoch(1000600) == 2

    def test_current_slot(self, epoch_mgr):
        assert epoch_mgr.current_slot(1000000) == 0
        assert epoch_mgr.current_slot(1000029) == 0
        assert epoch_mgr.current_slot(1000030) == 1
        assert epoch_mgr.current_slot(1000060) == 2

    def test_epoch_times(self, epoch_mgr):
        assert epoch_mgr.epoch_start_time(0) == 1000000
        assert epoch_mgr.epoch_end_time(0) == 1000300
        assert epoch_mgr.epoch_start_time(1) == 1000300

    def test_time_until_next_epoch(self, epoch_mgr):
        remaining = epoch_mgr.time_until_next_epoch(1000100)
        assert remaining == 200

    def test_ensure_epoch_exists(self, epoch_mgr):
        e = epoch_mgr.ensure_epoch_exists(0, start_block=0, validator_count=3)
        assert e["epoch_number"] == 0
        e2 = epoch_mgr.ensure_epoch_exists(0)
        assert e2["epoch_number"] == 0

    def test_process_unbonding(self, epoch_mgr):
        _setup_validator(epoch_mgr.state, "v1", 500)
        now = int(time.time())
        epoch_mgr.state.add_unbonding("d1", "v1", to_units(50), 1)
        released = epoch_mgr.process_unbonding_queue(now + 5)
        assert released == 1

    def test_get_status(self, epoch_mgr):
        status = epoch_mgr.get_status(1000150)
        assert status["current_epoch"] == 0
        assert status["current_slot"] == 5


# ── ValidatorRegistry ─────────────────────────────────────────────


class TestValidatorRegistry:
    def test_register(self, registry):
        result = registry.register("v1", to_units(500), 1000)
        assert result["ok"] is True

    def test_register_below_min_stake(self, registry):
        result = registry.register("v1", to_units(50))
        assert result["ok"] is False
        assert "below min" in result["error"]

    def test_register_bad_commission(self, registry):
        result = registry.register("v1", to_units(500), 6000)  # 60% > max 50%
        assert result["ok"] is False

    def test_delegate(self, registry):
        registry.register("v1", to_units(500))
        result = registry.delegate("d1", "v1", to_units(200))
        assert result["ok"] is True
        v = registry.state.get_validator("v1")
        assert v["total_stake"] == to_units(700)

    def test_delegate_to_nonexistent(self, registry):
        result = registry.delegate("d1", "missing", to_units(100))
        assert result["ok"] is False

    def test_undelegate(self, registry):
        registry.register("v1", to_units(500))
        registry.delegate("d1", "v1", to_units(200))
        result = registry.undelegate("d1", "v1", to_units(100))
        assert result["ok"] is True
        v = registry.state.get_validator("v1")
        assert v["total_stake"] == to_units(600)

    def test_undelegate_causes_jail(self, registry):
        # v2 has self_stake=200, delegate 100 from d3
        registry.register("v2", to_units(200), 1000)
        registry.delegate("d3", "v2", to_units(100))
        # Now slash v2's self stake below min via slash event
        append_event(registry.state, 1, "v2", "slash", to_units(150),
                     from_addr="v2", reason="test")
        # v2: self≈50, delegated=100, total≈150
        # Undelegate 100 → total≈50 < 100 → should jail
        registry.undelegate("d3", "v2", to_units(100))
        v = registry.state.get_validator("v2")
        assert v["status"] == "jailed"

    def test_jail_and_unjail(self, registry):
        registry.register("v1", to_units(500))
        result = registry.jail("v1")
        assert result["ok"] is True
        v = registry.state.get_validator("v1")
        assert v["status"] == "jailed"

        result = registry.unjail("v1")
        assert result["ok"] is False  # jail duration not expired

    def test_exit(self, registry):
        registry.register("v1", to_units(500))
        registry.delegate("d1", "v1", to_units(100))
        result = registry.exit("v1")
        assert result["ok"] is True
        v = registry.state.get_validator("v1")
        assert v["status"] == "exited"
        unbondings = registry.state.get_pending_unbondings("v1")
        assert len(unbondings) >= 1

    def test_list_validators(self, registry):
        registry.register("v1", to_units(500))
        registry.register("v2", to_units(200))
        active = registry.list_validators()
        assert len(active) == 2

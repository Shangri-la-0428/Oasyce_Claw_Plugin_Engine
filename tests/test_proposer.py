"""
Tests for proposer election — deterministic weighted random leader selection.
Updated for integer units.
"""

import pytest

from oasyce_plugin.consensus.state import ConsensusState
from oasyce_plugin.consensus.proposer import (
    ProposerElection,
    compute_epoch_seed,
    compute_slot_seed,
    compute_leader_schedule,
    weighted_select,
)
from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus.core.types import to_units


@pytest.fixture
def state():
    s = ConsensusState(":memory:")
    yield s
    s.close()


@pytest.fixture
def proposer(state):
    return ProposerElection(state, slots_per_epoch=10, min_stake=to_units(100))


# Integer stakes for test validators
VALIDATORS = [
    {"validator_id": "v1", "total_stake": to_units(1000)},
    {"validator_id": "v2", "total_stake": to_units(500)},
    {"validator_id": "v3", "total_stake": to_units(200)},
]


def _setup_validator(state, vid, stake_oas):
    state.register_validator(vid, 1000, 0)
    append_event(state, 0, vid, "register_self", to_units(stake_oas), from_addr=vid)


class TestDeterminism:
    def test_epoch_seed_deterministic(self):
        seed1 = compute_epoch_seed("abc123", 0)
        seed2 = compute_epoch_seed("abc123", 0)
        assert seed1 == seed2

    def test_epoch_seed_changes_with_input(self):
        seed1 = compute_epoch_seed("abc123", 0)
        seed2 = compute_epoch_seed("abc123", 1)
        seed3 = compute_epoch_seed("def456", 0)
        assert seed1 != seed2
        assert seed1 != seed3

    def test_slot_seed_deterministic(self):
        epoch_seed = compute_epoch_seed("abc", 0)
        s1 = compute_slot_seed(epoch_seed, 0)
        s2 = compute_slot_seed(epoch_seed, 0)
        assert s1 == s2

    def test_slot_seeds_differ(self):
        epoch_seed = compute_epoch_seed("abc", 0)
        seeds = [compute_slot_seed(epoch_seed, i) for i in range(10)]
        assert len(set(seeds)) == 10


class TestWeightedSelect:
    def test_single_validator(self):
        vals = [{"validator_id": "v1", "total_stake": to_units(100)}]
        result = weighted_select(vals, 42)
        assert result == "v1"

    def test_returns_valid_id(self):
        for rv in range(100):
            result = weighted_select(VALIDATORS, rv)
            assert result in ("v1", "v2", "v3")

    def test_higher_stake_more_likely(self):
        import hashlib
        counts = {"v1": 0, "v2": 0, "v3": 0}
        for i in range(10000):
            h = hashlib.sha256(str(i).encode()).hexdigest()
            rv = int(h[:16], 16)
            result = weighted_select(VALIDATORS, rv)
            counts[result] += 1
        assert counts["v1"] > counts["v2"] > counts["v3"]


class TestComputeSchedule:
    def test_schedule_length(self):
        schedule = compute_leader_schedule(VALIDATORS, "0" * 64, 0, 10)
        assert len(schedule) == 10

    def test_schedule_deterministic(self):
        s1 = compute_leader_schedule(VALIDATORS, "abc", 0, 10)
        s2 = compute_leader_schedule(VALIDATORS, "abc", 0, 10)
        for a, b in zip(s1, s2):
            assert a["validator_id"] == b["validator_id"]

    def test_empty_validators(self):
        schedule = compute_leader_schedule([], "abc", 0, 10)
        assert schedule == []

    def test_different_epochs_differ(self):
        s1 = compute_leader_schedule(VALIDATORS, "abc", 0, 10)
        s2 = compute_leader_schedule(VALIDATORS, "abc", 1, 10)
        leaders1 = [s["validator_id"] for s in s1]
        leaders2 = [s["validator_id"] for s in s2]
        assert leaders1 != leaders2


class TestProposerElection:
    def test_elect_and_verify(self, state, proposer):
        _setup_validator(state, "v1", 1000)
        _setup_validator(state, "v2", 500)
        schedule = proposer.elect_for_epoch(0, "0" * 64)
        assert len(schedule) == 10

        leader = schedule[0]["validator_id"]
        assert proposer.verify_proposer(0, 0, leader) is True
        assert proposer.verify_proposer(0, 0, "wrong_id") is False

    def test_get_current_leader(self, state, proposer):
        _setup_validator(state, "v1", 1000)
        proposer.elect_for_epoch(0, "0" * 64)
        leader = proposer.get_current_leader(0, 0)
        assert leader is not None

    def test_no_validators_empty_schedule(self, state, proposer):
        schedule = proposer.elect_for_epoch(0, "0" * 64)
        assert schedule == []

    def test_schedule_persisted(self, state, proposer):
        _setup_validator(state, "v1", 500)
        proposer.elect_for_epoch(0, "test_hash")
        schedule = proposer.get_schedule(0)
        assert len(schedule) == 10

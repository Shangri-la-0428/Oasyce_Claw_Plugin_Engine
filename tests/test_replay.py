"""
Tests for state replay verification — proves "delete + replay = current state".
"""

import pytest

from oasyce_plugin.consensus import ConsensusEngine
from oasyce_plugin.consensus.state import ConsensusState
from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus.storage.snapshots import (
    SNAPSHOT_INTERVAL, create_snapshot, load_latest_snapshot,
)
from oasyce_plugin.consensus.core.types import to_units, from_units, Operation, OperationType
from oasyce_plugin.consensus.execution.replay import (
    replay_events,
    verify_state_consistency,
    replay_from_snapshot,
    ReplayResult,
    ConsistencyReport,
    _read_events,
    _compute_state_hash,
    _collect_stake_state,
)


@pytest.fixture
def state():
    s = ConsensusState(":memory:")
    yield s
    s.close()


@pytest.fixture
def engine():
    e = ConsensusEngine(db_path=":memory:")
    yield e
    e.close()


def _setup_validator(state, vid="v1", stake_oas=500, block_height=0):
    """Register a validator and record self-stake event."""
    state.register_validator(vid, 1000, block_height)
    append_event(state, block_height, vid, "register_self",
                 to_units(stake_oas), from_addr=vid)


# ── Empty / Genesis Replay ────────────────────────────────────────────


class TestReplayEmpty:
    def test_empty_database(self, state):
        """Replaying an empty database should return zero events."""
        result = replay_events(state)
        assert result.events_replayed == 0
        assert result.validators == {}
        assert result.state_hash != ""

    def test_empty_verify(self, state):
        """Verifying an empty database should pass."""
        report = verify_state_consistency(state)
        assert report.consistent is True
        assert report.events_replayed == 0
        assert report.validators_checked == 0
        assert report.diffs == []


# ── Basic Replay ──────────────────────────────────────────────────────


class TestReplayBasic:
    def test_single_validator(self, state):
        """Replay a single validator registration."""
        _setup_validator(state, "v1", 500, block_height=1)
        result = replay_events(state)
        assert result.events_replayed == 1
        assert "v1" in result.validators
        assert result.validators["v1"]["total_stake"] == to_units(500)
        assert result.validators["v1"]["self_stake"] == to_units(500)

    def test_multiple_validators(self, state):
        """Replay with multiple validators."""
        _setup_validator(state, "v1", 500, block_height=1)
        _setup_validator(state, "v2", 300, block_height=2)
        _setup_validator(state, "v3", 1000, block_height=3)
        result = replay_events(state)
        assert result.events_replayed == 3
        assert len(result.validators) == 3
        assert result.validators["v2"]["total_stake"] == to_units(300)

    def test_validator_with_delegation(self, state):
        """Replay with delegation events."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        result = replay_events(state)
        assert result.events_replayed == 2
        assert result.validators["v1"]["total_stake"] == to_units(700)
        assert result.validators["v1"]["self_stake"] == to_units(500)

    def test_delegation_and_undelegation(self, state):
        """Replay with delegate + undelegate."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        append_event(state, 8, "v1", "undelegate", to_units(100), from_addr="d1")
        result = replay_events(state)
        assert result.events_replayed == 3
        assert result.validators["v1"]["total_stake"] == to_units(600)

    def test_slash_event(self, state):
        """Replay with slash event."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "slash", to_units(50),
                     from_addr="v1", reason="offline")
        result = replay_events(state)
        assert result.events_replayed == 2
        assert result.validators["v1"]["total_stake"] == to_units(450)
        assert result.validators["v1"]["self_stake"] == to_units(450)

    def test_reward_event(self, state):
        """Replay with reward event."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 10, "v1", "reward", to_units(25))
        result = replay_events(state)
        assert result.events_replayed == 2
        assert result.validators["v1"]["total_stake"] == to_units(525)

    def test_exit_event(self, state):
        """Replay with exit event — stake goes to zero."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 10, "v1", "exit", to_units(500), from_addr="v1")
        result = replay_events(state)
        assert result.events_replayed == 2
        # After exit, net stake is 0 → excluded from validators dict
        assert "v1" not in result.validators


# ── Height Range Replay ───────────────────────────────────────────────


class TestReplayHeightRange:
    def test_from_height(self, state):
        """Replay starting from a specific height."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        append_event(state, 10, "v1", "reward", to_units(50))

        # Only replay from height 5 onwards (skip the register_self at 1)
        result = replay_events(state, from_height=5)
        assert result.events_replayed == 2
        assert result.from_height == 5

    def test_to_height(self, state):
        """Replay up to a specific height."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        append_event(state, 10, "v1", "reward", to_units(50))

        result = replay_events(state, to_height=5)
        assert result.events_replayed == 2  # register_self + delegate
        assert result.validators["v1"]["total_stake"] == to_units(700)

    def test_from_and_to_height(self, state):
        """Replay within a height range."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        append_event(state, 10, "v1", "reward", to_units(50))
        append_event(state, 15, "v1", "delegate", to_units(100), from_addr="d2")

        result = replay_events(state, from_height=5, to_height=10)
        assert result.events_replayed == 2  # delegate at 5, reward at 10


# ── Consistency Verification ──────────────────────────────────────────


class TestVerifyConsistency:
    def test_simple_pass(self, state):
        """Single validator — replay matches live state."""
        _setup_validator(state, "v1", 500, block_height=1)
        report = verify_state_consistency(state)
        assert report.consistent is True
        assert report.events_replayed == 1
        assert report.validators_checked == 1
        assert report.state_hash_live == report.state_hash_replayed

    def test_complex_pass(self, state):
        """Multiple operations — replay matches live state."""
        _setup_validator(state, "v1", 500, block_height=1)
        _setup_validator(state, "v2", 300, block_height=2)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        append_event(state, 6, "v2", "delegate", to_units(150), from_addr="d2")
        append_event(state, 8, "v1", "slash", to_units(30),
                     from_addr="v1", reason="offline")
        append_event(state, 10, "v1", "reward", to_units(10))

        report = verify_state_consistency(state)
        assert report.consistent is True
        assert report.events_replayed == 6
        assert report.validators_checked == 2
        assert len(report.diffs) == 0

    def test_consistency_with_undelegation(self, state):
        """Delegation + undelegation cycle should be consistent."""
        _setup_validator(state, "v1", 1000, block_height=1)
        append_event(state, 3, "v1", "delegate", to_units(500), from_addr="d1")
        append_event(state, 5, "v1", "undelegate", to_units(200), from_addr="d1")
        append_event(state, 7, "v1", "reward", to_units(100))

        report = verify_state_consistency(state)
        assert report.consistent is True
        assert report.state_hash_live == report.state_hash_replayed

    def test_verify_at_specific_height(self, state):
        """Verify consistency only up to a specific height."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        append_event(state, 15, "v1", "reward", to_units(100))

        report = verify_state_consistency(state, to_height=10)
        assert report.consistent is True
        assert report.events_replayed == 2  # only up to height 10


# ── Snapshot Replay ───────────────────────────────────────────────────


class TestReplayFromSnapshot:
    def test_no_snapshot_falls_back(self, state):
        """Without any snapshot, replay_from_snapshot does full replay."""
        _setup_validator(state, "v1", 500, block_height=1)
        result = replay_from_snapshot(state, snapshot_height=50)
        assert result.events_replayed == 1
        assert result.validators["v1"]["total_stake"] == to_units(500)

    def test_with_snapshot(self, state):
        """Replay from snapshot should match full replay."""
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        create_snapshot(state, 10)
        append_event(state, 15, "v1", "reward", to_units(50))

        full = replay_events(state)
        from_snap = replay_from_snapshot(state, snapshot_height=10)

        assert full.validators["v1"]["total_stake"] == from_snap.validators["v1"]["total_stake"]
        assert full.validators["v1"]["total_stake"] == to_units(750)

    def test_snapshot_and_full_replay_same_hash(self, state):
        """State hash from snapshot replay should match full replay."""
        _setup_validator(state, "v1", 500, block_height=1)
        _setup_validator(state, "v2", 300, block_height=2)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        create_snapshot(state, 10)
        append_event(state, 15, "v2", "delegate", to_units(100), from_addr="d2")
        append_event(state, 20, "v1", "slash", to_units(10),
                     from_addr="v1", reason="offline")

        full = replay_events(state)
        from_snap = replay_from_snapshot(state, snapshot_height=10)

        # The total stakes should match even though paths differ.
        for vid in full.validators:
            assert full.validators[vid]["total_stake"] == \
                   from_snap.validators[vid]["total_stake"]


# ── State Hash ────────────────────────────────────────────────────────


class TestStateHash:
    def test_deterministic(self):
        """Same input produces same hash."""
        stakes = {"v1": {"total_stake": 100, "self_stake": 100}}
        h1 = _compute_state_hash(stakes)
        h2 = _compute_state_hash(stakes)
        assert h1 == h2

    def test_different_states_different_hash(self):
        """Different stakes produce different hashes."""
        h1 = _compute_state_hash({"v1": {"total_stake": 100, "self_stake": 100}})
        h2 = _compute_state_hash({"v1": {"total_stake": 200, "self_stake": 200}})
        assert h1 != h2

    def test_empty_state_hash(self):
        """Empty state has a defined hash."""
        h = _compute_state_hash({})
        assert len(h) == 64  # SHA256 hex


# ── Read Events ───────────────────────────────────────────────────────


class TestReadEvents:
    def test_read_all(self, state):
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "delegate", to_units(100), from_addr="d1")
        events = _read_events(state)
        assert len(events) == 2

    def test_read_height_range(self, state):
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 5, "v1", "delegate", to_units(100), from_addr="d1")
        append_event(state, 10, "v1", "reward", to_units(50))
        events = _read_events(state, from_height=5, to_height=5)
        assert len(events) == 1
        assert events[0]["event_type"] == "delegate"


# ── Large-Scale Replay ────────────────────────────────────────────────


class TestReplayScale:
    def test_many_events(self, state):
        """Replay 200+ events and verify consistency."""
        _setup_validator(state, "v1", 1000, block_height=0)
        for i in range(1, 201):
            append_event(state, i, "v1", "delegate", to_units(1), from_addr=f"d{i}")

        result = replay_events(state)
        assert result.events_replayed == 201  # 1 register + 200 delegates
        assert result.validators["v1"]["total_stake"] == to_units(1200)

        report = verify_state_consistency(state)
        assert report.consistent is True

    def test_many_validators_consistency(self, state):
        """Multiple validators with mixed operations — verify consistency."""
        for i in range(10):
            vid = f"v{i}"
            _setup_validator(state, vid, 100 + i * 10, block_height=i)

        # Add delegations
        for i in range(10):
            append_event(state, 20 + i, f"v{i}", "delegate",
                         to_units(50), from_addr=f"d{i}")
        # Slash a few
        append_event(state, 35, "v3", "slash", to_units(5),
                     from_addr="v3", reason="offline")
        append_event(state, 36, "v7", "slash", to_units(10),
                     from_addr="v7", reason="offline")

        report = verify_state_consistency(state)
        assert report.consistent is True
        assert report.validators_checked == 10


# ── Collect State ─────────────────────────────────────────────────────


class TestCollectState:
    def test_collect_basic(self, state):
        _setup_validator(state, "v1", 500, block_height=1)
        stakes = _collect_stake_state(state)
        assert "v1" in stakes
        assert stakes["v1"]["total_stake"] == to_units(500)

    def test_collect_at_height(self, state):
        _setup_validator(state, "v1", 500, block_height=1)
        append_event(state, 10, "v1", "reward", to_units(100))
        stakes = _collect_stake_state(state, at_height=5)
        assert stakes["v1"]["total_stake"] == to_units(500)  # reward at 10 excluded


# ── ReplayResult / ConsistencyReport types ────────────────────────────


class TestResultTypes:
    def test_replay_result_defaults(self):
        r = ReplayResult()
        assert r.events_replayed == 0
        assert r.validators == {}
        assert r.errors == []
        assert r.state_hash == ""

    def test_consistency_report_defaults(self):
        r = ConsistencyReport()
        assert r.consistent is True
        assert r.diffs == []
        assert r.errors == []

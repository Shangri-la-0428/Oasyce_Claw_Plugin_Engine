"""
Tests for state snapshots — snapshot creation, loading, and
snapshot-accelerated stake queries.
"""

import pytest

from oasyce_plugin.consensus.state import ConsensusState
from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus.storage.snapshots import (
    SNAPSHOT_INTERVAL,
    create_snapshot,
    load_latest_snapshot,
    load_snapshot_at,
    get_validator_stake_fast,
    get_self_stake_fast,
    _full_scan_stake,
    _incremental_stake,
)
from oasyce_plugin.consensus.core.types import to_units


@pytest.fixture
def state():
    s = ConsensusState(":memory:")
    yield s
    s.close()


def _setup_validator(state, vid="v1", stake_oas=500, block_height=0):
    """Register a validator and record self-stake event."""
    state.register_validator(vid, 1000, block_height)
    append_event(state, block_height, vid, "register_self",
                 to_units(stake_oas), from_addr=vid)


# ── Snapshot Creation ─────────────────────────────────────────────────


class TestCreateSnapshot:
    def test_create_empty_state(self, state):
        """Snapshot of empty state should succeed."""
        ok = create_snapshot(state, 0)
        assert ok is True

    def test_create_with_validators(self, state):
        _setup_validator(state, "v1", 500, block_height=1)
        _setup_validator(state, "v2", 300, block_height=2)
        ok = create_snapshot(state, 5)
        assert ok is True

    def test_idempotent(self, state):
        """Creating a snapshot at the same height twice should not error."""
        _setup_validator(state, "v1", 500)
        assert create_snapshot(state, 10) is True
        assert create_snapshot(state, 10) is False  # already exists

    def test_multiple_heights(self, state):
        """Snapshots at different heights should coexist."""
        _setup_validator(state, "v1", 100)
        assert create_snapshot(state, 10) is True
        append_event(state, 15, "v1", "reward", to_units(50))
        assert create_snapshot(state, 20) is True


# ── Snapshot Loading ──────────────────────────────────────────────────


class TestLoadSnapshot:
    def test_load_no_snapshot(self, state):
        """Loading from empty snapshot table returns None."""
        result = load_latest_snapshot(state)
        assert result is None

    def test_load_latest(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        create_snapshot(state, 10)
        append_event(state, 15, "v1", "reward", to_units(50))
        create_snapshot(state, 20)

        snap = load_latest_snapshot(state)
        assert snap is not None
        height, vs, ss = snap
        assert height == 20

    def test_load_before_height(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        create_snapshot(state, 10)
        create_snapshot(state, 20)
        create_snapshot(state, 30)

        snap = load_latest_snapshot(state, before_height=25)
        assert snap is not None
        assert snap[0] == 20

    def test_load_at_exact_height(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        create_snapshot(state, 10)

        snap = load_snapshot_at(state, 10)
        assert snap is not None
        assert snap[0] == 10

    def test_load_at_height_between_snapshots(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        create_snapshot(state, 10)
        create_snapshot(state, 20)

        snap = load_snapshot_at(state, 15)
        assert snap is not None
        assert snap[0] == 10

    def test_load_before_any_snapshot(self, state):
        _setup_validator(state, "v1", 500, block_height=5)
        create_snapshot(state, 10)

        snap = load_snapshot_at(state, 3)
        assert snap is None


# ── Snapshot Content Correctness ──────────────────────────────────────


class TestSnapshotContent:
    def test_validator_states_captured(self, state):
        _setup_validator(state, "v1", 500)
        state.jail_validator("v1", until=9999)
        create_snapshot(state, 10)

        snap = load_latest_snapshot(state)
        assert snap is not None
        _, vs, _ = snap
        assert "v1" in vs
        assert vs["v1"]["status"] == "jailed"
        assert vs["v1"]["jailed_until"] == 9999

    def test_stake_states_captured(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        # Add delegation
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        create_snapshot(state, 10)

        snap = load_latest_snapshot(state)
        assert snap is not None
        _, _, ss = snap
        assert "v1" in ss
        assert ss["v1"]["total"] == to_units(700)  # 500 self + 200 delegation
        assert ss["v1"]["self"] == to_units(500)

    def test_slash_reduces_stake_in_snapshot(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        append_event(state, 3, "v1", "slash", to_units(50), from_addr="v1", reason="offline")
        create_snapshot(state, 10)

        snap = load_latest_snapshot(state)
        _, _, ss = snap
        assert ss["v1"]["total"] == to_units(450)
        assert ss["v1"]["self"] == to_units(450)

    def test_zero_or_negative_stake_excluded(self, state):
        _setup_validator(state, "v1", 100, block_height=0)
        append_event(state, 2, "v1", "delegate", to_units(50), from_addr="d1")
        # Fully undelegate d1
        append_event(state, 5, "v1", "undelegate", to_units(50), from_addr="d1")
        create_snapshot(state, 10)

        snap = load_latest_snapshot(state)
        _, _, ss = snap
        # Total stake is just self-stake (100)
        assert ss["v1"]["total"] == to_units(100)

    def test_only_events_up_to_height(self, state):
        """Snapshot at height 10 should NOT include events at height 15."""
        _setup_validator(state, "v1", 500, block_height=0)
        append_event(state, 15, "v1", "delegate", to_units(200), from_addr="d1")
        create_snapshot(state, 10)

        snap = load_latest_snapshot(state)
        _, _, ss = snap
        # Only self-stake at height 10 (delegation at 15 excluded)
        assert ss["v1"]["total"] == to_units(500)


# ── Snapshot-Accelerated Queries ──────────────────────────────────────


class TestSnapshotAcceleratedStake:
    def test_matches_full_scan_no_snapshot(self, state):
        """Without snapshots, fast path falls back to full scan."""
        _setup_validator(state, "v1", 500)
        full = _full_scan_stake(state, "v1", None)
        fast = get_validator_stake_fast(state, "v1")
        assert fast == full == to_units(500)

    def test_matches_full_scan_with_snapshot(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        create_snapshot(state, 10)
        append_event(state, 15, "v1", "delegate", to_units(100), from_addr="d2")

        full = _full_scan_stake(state, "v1", None)
        fast = get_validator_stake_fast(state, "v1")
        assert fast == full == to_units(800)

    def test_at_height_with_snapshot(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        create_snapshot(state, 10)
        append_event(state, 15, "v1", "delegate", to_units(100), from_addr="d2")

        # at_height=12 → should use snapshot(10) + no incremental
        fast = get_validator_stake_fast(state, "v1", at_height=12)
        full = _full_scan_stake(state, "v1", at_height=12)
        assert fast == full == to_units(700)

    def test_at_height_before_snapshot(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        create_snapshot(state, 10)

        # Query at height 5 — no snapshot available before 5
        # (snapshot at 10 is after 5)
        fast = get_validator_stake_fast(state, "v1", at_height=5)
        full = _full_scan_stake(state, "v1", at_height=5)
        assert fast == full

    def test_incremental_events_correctly_applied(self, state):
        _setup_validator(state, "v1", 1000, block_height=0)
        create_snapshot(state, 10)

        # Events after snapshot
        append_event(state, 12, "v1", "delegate", to_units(300), from_addr="d1")
        append_event(state, 14, "v1", "slash", to_units(50), from_addr="v1", reason="offline")
        append_event(state, 16, "v1", "undelegate", to_units(100), from_addr="d1")

        fast = get_validator_stake_fast(state, "v1")
        full = _full_scan_stake(state, "v1", None)
        # 1000 + 300 - 50 - 100 = 1150
        assert fast == full == to_units(1150)

    def test_multiple_validators(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        _setup_validator(state, "v2", 300, block_height=1)
        create_snapshot(state, 10)

        append_event(state, 15, "v1", "reward", to_units(10))
        append_event(state, 15, "v2", "delegate", to_units(100), from_addr="d1")

        assert get_validator_stake_fast(state, "v1") == to_units(510)
        assert get_validator_stake_fast(state, "v2") == to_units(400)

    def test_unknown_validator(self, state):
        create_snapshot(state, 10)
        assert get_validator_stake_fast(state, "nonexistent") == 0


class TestSnapshotAcceleratedSelfStake:
    def test_self_stake_no_snapshot(self, state):
        _setup_validator(state, "v1", 500)
        fast = get_self_stake_fast(state, "v1")
        assert fast == to_units(500)

    def test_self_stake_with_snapshot(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        append_event(state, 5, "v1", "delegate", to_units(200), from_addr="d1")
        create_snapshot(state, 10)

        fast = get_self_stake_fast(state, "v1")
        # self-stake is only register_self, not delegations
        assert fast == to_units(500)

    def test_self_stake_with_incremental_slash(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        create_snapshot(state, 10)
        append_event(state, 15, "v1", "slash", to_units(30), from_addr="v1")

        fast = get_self_stake_fast(state, "v1")
        assert fast == to_units(470)


# ── Integration: get_validator_stake delegates to snapshot path ───────


class TestStateIntegration:
    def test_state_get_validator_stake_uses_snapshots(self, state):
        """ConsensusState.get_validator_stake now delegates to snapshot path."""
        _setup_validator(state, "v1", 500, block_height=0)
        create_snapshot(state, 10)
        append_event(state, 15, "v1", "reward", to_units(25))

        result = state.get_validator_stake("v1")
        assert result == to_units(525)

    def test_state_get_self_stake_uses_snapshots(self, state):
        _setup_validator(state, "v1", 500, block_height=0)
        create_snapshot(state, 10)

        result = state.get_self_stake("v1")
        assert result == to_units(500)

    def test_get_validator_includes_snapshot_accelerated_stake(self, state):
        """get_validator() should return correct stakes even with snapshots."""
        _setup_validator(state, "v1", 500, block_height=0)
        append_event(state, 3, "v1", "delegate", to_units(200), from_addr="d1")
        create_snapshot(state, 10)
        append_event(state, 15, "v1", "reward", to_units(10))

        v = state.get_validator("v1")
        assert v["total_stake"] == to_units(710)
        assert v["self_stake"] == to_units(500)


# ── apply_block snapshot trigger ──────────────────────────────────────


class TestApplyBlockSnapshot:
    def test_snapshot_at_interval(self, state):
        """apply_block should create snapshot at SNAPSHOT_INTERVAL multiples."""
        from oasyce_plugin.consensus import ConsensusEngine

        engine = ConsensusEngine(db_path=":memory:")
        # Register a validator first
        engine.register_validator("v1", to_units(500), 1000, block_height=1)

        # Apply block at SNAPSHOT_INTERVAL
        result = engine.apply_block({"height": SNAPSHOT_INTERVAL, "operations": []})
        assert result["snapshot_created"] is True

        # Verify snapshot exists
        snap = load_latest_snapshot(engine.state)
        assert snap is not None
        assert snap[0] == SNAPSHOT_INTERVAL

    def test_no_snapshot_at_non_interval(self, state):
        from oasyce_plugin.consensus import ConsensusEngine

        engine = ConsensusEngine(db_path=":memory:")
        result = engine.apply_block({"height": 7, "operations": []})
        assert result["snapshot_created"] is False

    def test_no_snapshot_at_height_zero(self, state):
        from oasyce_plugin.consensus import ConsensusEngine

        engine = ConsensusEngine(db_path=":memory:")
        result = engine.apply_block({"height": 0, "operations": []})
        assert result["snapshot_created"] is False


# ── Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_genesis_no_snapshot(self, state):
        """At genesis (no events, no snapshots), stake should be 0."""
        assert get_validator_stake_fast(state, "v1") == 0

    def test_snapshot_with_exit_and_re_register(self, state):
        """Validator exits, snapshot taken, re-registers after snapshot."""
        _setup_validator(state, "v1", 500, block_height=0)
        append_event(state, 5, "v1", "exit", to_units(500), from_addr="v1")
        create_snapshot(state, 10)

        # At snapshot, v1 has 0 stake
        snap = load_latest_snapshot(state)
        _, _, ss = snap
        assert "v1" not in ss  # zero stake excluded

        # Re-register after snapshot
        state.reactivate_validator("v1", 1000)
        append_event(state, 15, "v1", "register_self", to_units(600), from_addr="v1")

        fast = get_validator_stake_fast(state, "v1")
        full = _full_scan_stake(state, "v1", None)
        assert fast == full == to_units(600)

    def test_many_snapshots_picks_closest(self, state):
        """With multiple snapshots, query picks the closest one before at_height."""
        _setup_validator(state, "v1", 100, block_height=0)

        for h in [10, 20, 30, 40, 50]:
            append_event(state, h, "v1", "reward", to_units(10))
            create_snapshot(state, h)

        # at_height=35 → should use snapshot at 30
        snap = load_snapshot_at(state, 35)
        assert snap[0] == 30

        fast = get_validator_stake_fast(state, "v1", at_height=35)
        full = _full_scan_stake(state, "v1", at_height=35)
        assert fast == full

    def test_snapshot_consistency_across_many_events(self, state):
        """Snapshot + incremental must equal full scan across many events."""
        _setup_validator(state, "v1", 1000, block_height=0)

        # 50 events before snapshot
        for i in range(1, 51):
            append_event(state, i, "v1", "delegate", to_units(1), from_addr=f"d{i}")

        create_snapshot(state, 50)

        # 50 events after snapshot
        for i in range(51, 101):
            append_event(state, i, "v1", "delegate", to_units(1), from_addr=f"d{i}")

        fast = get_validator_stake_fast(state, "v1")
        full = _full_scan_stake(state, "v1", None)
        # 1000 + 100 delegations of 1 OAS each = 1100 OAS
        assert fast == full == to_units(1100)

    def test_snapshot_interval_constant(self):
        """SNAPSHOT_INTERVAL should be 100."""
        assert SNAPSHOT_INTERVAL == 100

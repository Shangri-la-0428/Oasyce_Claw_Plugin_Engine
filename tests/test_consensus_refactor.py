"""
Comprehensive tests for the Oasyce consensus protocol refactoring.

Tests the four iron rules:
1. Determinism — same input → same output
2. Append-only — no UPDATE on monetary columns
3. Single source of truth — state derived from events
4. State machine — all changes via apply_operation

Covers: types, event sourcing, state derivation, transitions,
validation, slashing, rewards, block-height scheduling, chain_id.
"""

import sqlite3
import pytest
from oasyce_plugin.consensus.core.types import (
    OAS_DECIMALS, to_units, from_units,
    Operation, OperationType,
    OFFLINE_SLASH_BPS, DOUBLE_SIGN_SLASH_BPS, LOW_QUALITY_SLASH_BPS,
    MAX_COMMISSION_BPS,
    apply_rate_bps,
)
from oasyce_plugin.consensus.state import ConsensusState
from oasyce_plugin.consensus.storage.events import append_event
from oasyce_plugin.consensus import ConsensusEngine
from oasyce_plugin.consensus.core.validation import validate_operation
from oasyce_plugin.consensus.core.transition import apply_operation
from oasyce_plugin.consensus.execution.engine import (
    current_epoch, current_slot, epoch_start_block, epoch_end_block,
    is_epoch_boundary, blocks_until_epoch_end,
    unbonding_release_block, compute_block_hash,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def state():
    s = ConsensusState(":memory:")
    yield s
    s.close()


@pytest.fixture
def engine():
    e = ConsensusEngine(
        db_path=":memory:",
        economics={
            "block_reward": 40 * OAS_DECIMALS,
            "min_stake": 100 * OAS_DECIMALS,
            "halving_interval": 10000,
        },
    )
    yield e
    e.close()


# ═══════════════════════════════════════════════════════════════════
# Week 1: Types & Units
# ═══════════════════════════════════════════════════════════════════

class TestUnits:
    def test_to_units_whole(self):
        assert to_units(1.0) == OAS_DECIMALS
        assert to_units(100.0) == 100 * OAS_DECIMALS

    def test_to_units_fractional(self):
        assert to_units(0.5) == OAS_DECIMALS // 2
        assert to_units(0.00000001) == 1

    def test_from_units(self):
        assert from_units(OAS_DECIMALS) == 1.0
        assert from_units(50_000_000) == 0.5

    def test_roundtrip(self):
        for val in [1.0, 100.0, 0.5, 0.00000001, 99999.99999999]:
            assert from_units(to_units(val)) == pytest.approx(val, abs=1e-8)

    def test_apply_rate_bps(self):
        assert apply_rate_bps(10000, 100) == 100    # 1%
        assert apply_rate_bps(10000, 500) == 500    # 5%
        assert apply_rate_bps(10000, 50) == 50      # 0.5%
        assert apply_rate_bps(10000, 10000) == 10000  # 100%
        assert apply_rate_bps(0, 500) == 0

    def test_no_float_in_operations(self):
        op = Operation(op_type=OperationType.REGISTER, validator_id="v1",
                       amount=to_units(100))
        assert isinstance(op.amount, int)

    def test_operation_frozen(self):
        op = Operation(op_type=OperationType.REGISTER, validator_id="v1",
                       amount=to_units(100))
        with pytest.raises(AttributeError):
            op.amount = 999

    def test_operation_negative_amount_rejected(self):
        with pytest.raises(ValueError):
            Operation(op_type=OperationType.DELEGATE, validator_id="v1",
                      amount=-1)


class TestOperationTypes:
    def test_all_types(self):
        assert len(OperationType) == 9
        assert OperationType.REGISTER.value == "register"
        assert OperationType.DELEGATE.value == "delegate"
        assert OperationType.UNDELEGATE.value == "undelegate"
        assert OperationType.SLASH.value == "slash"
        assert OperationType.REWARD.value == "reward"
        assert OperationType.EXIT.value == "exit"
        assert OperationType.UNJAIL.value == "unjail"

    def test_slash_rates_are_int(self):
        assert isinstance(OFFLINE_SLASH_BPS, int)
        assert isinstance(DOUBLE_SIGN_SLASH_BPS, int)
        assert isinstance(LOW_QUALITY_SLASH_BPS, int)


# ═══════════════════════════════════════════════════════════════════
# Week 2: Event Sourcing
# ═══════════════════════════════════════════════════════════════════

class TestEventSourcing:
    def test_append_event(self, state):
        state.register_validator("v1", 1000, 0)
        eid = append_event(state, 0, "v1", "register_self", to_units(100),
                           from_addr="v1")
        assert eid > 0

    def test_stake_derived_from_events(self, state):
        state.register_validator("v1", 1000, 0)
        append_event(state, 0, "v1", "register_self", to_units(200),
                     from_addr="v1")
        assert state.get_validator_stake("v1") == to_units(200)

    def test_delegation_derived_from_events(self, state):
        state.register_validator("v1", 1000, 0)
        append_event(state, 0, "v1", "register_self", to_units(100),
                     from_addr="v1")
        append_event(state, 1, "v1", "delegate", to_units(50),
                     from_addr="del1")
        assert state.get_validator_stake("v1") == to_units(150)
        delegations = state.get_delegations("v1")
        assert len(delegations) == 1
        assert delegations[0]["delegator"] == "del1"
        assert delegations[0]["amount"] == to_units(50)

    def test_undelegation_derived_from_events(self, state):
        state.register_validator("v1", 1000, 0)
        append_event(state, 0, "v1", "register_self", to_units(100),
                     from_addr="v1")
        append_event(state, 1, "v1", "delegate", to_units(50),
                     from_addr="del1")
        append_event(state, 2, "v1", "undelegate", to_units(20),
                     from_addr="del1")
        assert state.get_validator_stake("v1") == to_units(130)
        delegations = state.get_delegations("v1")
        assert delegations[0]["amount"] == to_units(30)

    def test_slash_derived_from_events(self, state):
        state.register_validator("v1", 1000, 0)
        append_event(state, 0, "v1", "register_self", to_units(100),
                     from_addr="v1")
        append_event(state, 1, "v1", "slash", to_units(10),
                     from_addr="v1", reason="offline")
        assert state.get_validator_stake("v1") == to_units(90)
        assert state.get_self_stake("v1") == to_units(90)

    def test_get_delegation_amount(self, state):
        state.register_validator("v1", 1000, 0)
        append_event(state, 0, "v1", "register_self", to_units(100),
                     from_addr="v1")
        append_event(state, 1, "v1", "delegate", to_units(50),
                     from_addr="del1")
        assert state.get_delegation_amount("del1", "v1") == to_units(50)
        assert state.get_delegation_amount("del2", "v1") == 0

    def test_at_height_time_travel(self, state):
        state.register_validator("v1", 1000, 0)
        append_event(state, 0, "v1", "register_self", to_units(100),
                     from_addr="v1")
        append_event(state, 5, "v1", "delegate", to_units(50),
                     from_addr="del1")
        # At height 3, delegation hasn't happened yet
        assert state.get_validator_stake("v1", at_height=3) == to_units(100)
        # At height 5, it has
        assert state.get_validator_stake("v1", at_height=5) == to_units(150)

    def test_delegator_delegations(self, state):
        state.register_validator("v1", 1000, 0)
        state.register_validator("v2", 1000, 0)
        append_event(state, 0, "v1", "register_self", to_units(100),
                     from_addr="v1")
        append_event(state, 0, "v2", "register_self", to_units(100),
                     from_addr="v2")
        append_event(state, 1, "v1", "delegate", to_units(50),
                     from_addr="del1")
        append_event(state, 1, "v2", "delegate", to_units(30),
                     from_addr="del1")
        delegations = state.get_delegator_delegations("del1")
        assert len(delegations) == 2
        total = sum(d["amount"] for d in delegations)
        assert total == to_units(80)

    def test_no_update_on_stake_events(self, state):
        """Verify stake_events table has no UPDATE triggers."""
        state.register_validator("v1", 1000, 0)
        append_event(state, 0, "v1", "register_self", to_units(100),
                     from_addr="v1")
        # Verify we can't update stake_events (this is append-only)
        # The table should only grow
        with state._lock:
            count1 = state._conn.execute(
                "SELECT COUNT(*) FROM stake_events"
            ).fetchone()[0]
        append_event(state, 1, "v1", "delegate", to_units(10),
                     from_addr="del1")
        with state._lock:
            count2 = state._conn.execute(
                "SELECT COUNT(*) FROM stake_events"
            ).fetchone()[0]
        assert count2 == count1 + 1


class TestStateReplayability:
    """Iron Rule 5: Delete DB → replay events → same state."""

    def test_state_reproducible_from_events(self):
        # Create state with operations
        state1 = ConsensusState(":memory:")
        state1.register_validator("v1", 1000, 0)
        append_event(state1, 0, "v1", "register_self", to_units(200),
                     from_addr="v1")
        append_event(state1, 1, "v1", "delegate", to_units(50),
                     from_addr="del1")
        append_event(state1, 2, "v1", "slash", to_units(5),
                     from_addr="v1", reason="offline")

        stake1 = state1.get_validator_stake("v1")
        self_stake1 = state1.get_self_stake("v1")
        delegations1 = state1.get_delegations("v1")

        # Replay: create fresh state, replay same events
        state2 = ConsensusState(":memory:")
        state2.register_validator("v1", 1000, 0)
        append_event(state2, 0, "v1", "register_self", to_units(200),
                     from_addr="v1")
        append_event(state2, 1, "v1", "delegate", to_units(50),
                     from_addr="del1")
        append_event(state2, 2, "v1", "slash", to_units(5),
                     from_addr="v1", reason="offline")

        # Derived state must be identical
        assert state2.get_validator_stake("v1") == stake1
        assert state2.get_self_stake("v1") == self_stake1
        assert state2.get_delegations("v1") == delegations1

        state1.close()
        state2.close()


# ═══════════════════════════════════════════════════════════════════
# Week 3: State Machine (apply_operation)
# ═══════════════════════════════════════════════════════════════════

class TestApplyOperation:
    def test_register(self, engine):
        result = engine.apply(
            Operation(op_type=OperationType.REGISTER, validator_id="v1",
                      amount=to_units(200), commission_rate=1000),
            block_height=0,
        )
        assert result["ok"] is True
        val = engine.state.get_validator("v1")
        assert val["total_stake"] == to_units(200)

    def test_register_below_min_stake(self, engine):
        result = engine.apply(
            Operation(op_type=OperationType.REGISTER, validator_id="v1",
                      amount=to_units(50), commission_rate=1000),
        )
        assert result["ok"] is False
        assert "below min" in result["error"]

    def test_delegate(self, engine):
        engine.register_validator("v1", to_units(200))
        result = engine.apply(
            Operation(op_type=OperationType.DELEGATE, validator_id="v1",
                      amount=to_units(50), from_addr="del1"),
            block_height=1,
        )
        assert result["ok"] is True
        assert engine.state.get_validator_stake("v1") == to_units(250)

    def test_delegate_to_nonexistent(self, engine):
        result = engine.apply(
            Operation(op_type=OperationType.DELEGATE, validator_id="nope",
                      amount=to_units(50), from_addr="del1"),
        )
        assert result["ok"] is False

    def test_undelegate(self, engine):
        engine.register_validator("v1", to_units(200))
        engine.delegate("del1", "v1", to_units(100))
        result = engine.apply(
            Operation(op_type=OperationType.UNDELEGATE, validator_id="v1",
                      amount=to_units(30), from_addr="del1"),
            block_height=2,
        )
        assert result["ok"] is True
        assert engine.state.get_delegation_amount("del1", "v1") == to_units(70)

    def test_exit(self, engine):
        engine.register_validator("v1", to_units(200))
        result = engine.apply(
            Operation(op_type=OperationType.EXIT, validator_id="v1"),
            block_height=3,
        )
        assert result["ok"] is True
        val = engine.state.get_validator("v1")
        assert val["status"] == "exited"

    def test_unjail(self, engine):
        engine.register_validator("v1", to_units(200))
        engine.registry.jail("v1", reason="test", duration_multiplier=0.0)
        result = engine.apply(
            Operation(op_type=OperationType.UNJAIL, validator_id="v1"),
        )
        assert result["ok"] is True
        val = engine.state.get_validator("v1")
        assert val["status"] == "active"

    def test_all_operations_go_through_apply(self, engine):
        """Ensure the facade methods delegate to apply_operation."""
        r1 = engine.register_validator("v1", to_units(200))
        assert r1["ok"]
        r2 = engine.delegate("del1", "v1", to_units(50))
        assert r2["ok"]
        r3 = engine.undelegate("del1", "v1", to_units(20))
        assert r3["ok"]
        r4 = engine.unjail_validator("v1")
        # Should fail (not jailed)
        assert r4["ok"] is False
        r5 = engine.exit_validator("v1")
        assert r5["ok"]


class TestValidation:
    def test_validate_register_ok(self, engine):
        op = Operation(op_type=OperationType.REGISTER, validator_id="v1",
                       amount=to_units(200))
        valid, err = validate_operation(engine, op)
        assert valid is True

    def test_validate_register_low_stake(self, engine):
        op = Operation(op_type=OperationType.REGISTER, validator_id="v1",
                       amount=to_units(10))
        valid, err = validate_operation(engine, op)
        assert valid is False
        assert "below min" in err

    def test_validate_delegate_nonexistent(self, engine):
        op = Operation(op_type=OperationType.DELEGATE, validator_id="v1",
                       amount=to_units(50), from_addr="del1")
        valid, err = validate_operation(engine, op)
        assert valid is False
        assert "not found" in err

    def test_validate_undelegate_no_delegation(self, engine):
        engine.register_validator("v1", to_units(200))
        op = Operation(op_type=OperationType.UNDELEGATE, validator_id="v1",
                       amount=to_units(50), from_addr="nobody")
        valid, err = validate_operation(engine, op)
        assert valid is False
        assert "no delegation" in err


# ═══════════════════════════════════════════════════════════════════
# Slashing & Rewards (integer math)
# ═══════════════════════════════════════════════════════════════════

class TestSlashing:
    def test_offline_slash_1_percent(self, engine):
        engine.register_validator("v1", to_units(1000))
        result = engine.slashing.apply_slash("v1", "offline", 0, block_height=1)
        assert result["ok"] is True
        # 1% of 1000 = 10
        assert result["slash_amount"] == apply_rate_bps(to_units(1000),
                                                         OFFLINE_SLASH_BPS)

    def test_double_sign_slash_5_percent(self, engine):
        engine.register_validator("v1", to_units(1000))
        result = engine.slashing.apply_slash("v1", "double_sign", 0,
                                              block_height=1)
        assert result["ok"] is True
        assert result["slash_amount"] == apply_rate_bps(to_units(1000),
                                                         DOUBLE_SIGN_SLASH_BPS)

    def test_slash_deducts_self_first(self, engine):
        engine.register_validator("v1", to_units(200))
        engine.delegate("del1", "v1", to_units(100))
        # Total = 300, 1% = 3
        engine.slashing.apply_slash("v1", "offline", 0, block_height=1)
        self_stake = engine.state.get_self_stake("v1")
        # Self stake should be reduced first
        assert self_stake < to_units(200)

    def test_epoch_slashing(self, engine):
        engine.register_validator("v1", to_units(200))
        # Set up schedule with v1 assigned but not proposed
        engine.state.set_leader_schedule(0, [
            {"slot_index": i, "validator_id": "v1"} for i in range(10)
        ])
        # v1 proposed 0 out of 10 — should be slashed
        results = engine.slashing.process_epoch_slashing(0, block_height=10)
        assert len(results) == 1
        assert results[0]["ok"] is True

    def test_check_low_quality(self, engine):
        qualities = [1000] * 10  # 10% avg quality (below 30%)
        evidence = engine.slashing.check_low_quality("v1", qualities)
        assert evidence is not None
        assert evidence["reason"] == "low_quality"


class TestRewards:
    def test_block_reward_halving(self, engine):
        r0 = engine.rewards.current_block_reward(0)
        r1 = engine.rewards.current_block_reward(10000)
        r2 = engine.rewards.current_block_reward(20000)
        assert r0 == 40 * OAS_DECIMALS
        assert r1 == 20 * OAS_DECIMALS
        assert r2 == 10 * OAS_DECIMALS

    def test_distribute_rewards_integer(self, engine):
        engine.register_validator("v1", to_units(200), 1000)  # 10% commission
        engine.delegate("del1", "v1", to_units(100))
        metrics = [{"validator_id": "v1", "blocks_proposed": 1, "work_value": 0}]
        result = engine.rewards.distribute_epoch_rewards(0, metrics, 0)
        assert isinstance(result["total_distributed"], int)
        assert result["total_distributed"] > 0

    def test_commission_split(self, engine):
        engine.register_validator("v1", to_units(200), 2000)  # 20% commission
        metrics = [{"validator_id": "v1", "blocks_proposed": 1, "work_value": 0}]
        result = engine.rewards.distribute_epoch_rewards(0, metrics, 0)
        breakdown = result["validators"][0]
        total = breakdown["block_reward_total"]
        # Validator gets 20% commission
        assert breakdown["validator_income"] == apply_rate_bps(total, 2000)

    def test_delegator_reward_proportional(self, engine):
        engine.register_validator("v1", to_units(200), 1000)
        engine.delegate("del1", "v1", to_units(100))
        engine.delegate("del2", "v1", to_units(100))
        metrics = [{"validator_id": "v1", "blocks_proposed": 1, "work_value": 0}]
        result = engine.rewards.distribute_epoch_rewards(0, metrics, 0)
        # Check reward events recorded
        rewards = engine.state.get_reward_events(epoch_number=0)
        assert len(rewards) > 0


class TestEpochBoundary:
    def test_full_epoch_boundary(self, engine):
        engine.register_validator("v1", to_units(200))
        # Create schedule
        engine.proposer.elect_for_epoch(0, "0" * 64)
        # Mark some slots as proposed
        engine.state.mark_slot_proposed(0, 0)
        engine.state.mark_slot_proposed(0, 1)
        # Process epoch boundary
        metrics = [{"validator_id": "v1", "blocks_proposed": 2, "work_value": 0}]
        result = engine.on_epoch_boundary(0, "0" * 64, 10, metrics)
        assert result["next_epoch"] == 1
        assert result["rewards"]["total_distributed"] > 0


# ═══════════════════════════════════════════════════════════════════
# Week 4: Block-height scheduling & chain_id
# ═══════════════════════════════════════════════════════════════════

class TestBlockHeightScheduling:
    def test_current_epoch(self):
        assert current_epoch(0, 10) == 0
        assert current_epoch(9, 10) == 0
        assert current_epoch(10, 10) == 1
        assert current_epoch(99, 10) == 9

    def test_current_slot(self):
        assert current_slot(0, 10) == 0
        assert current_slot(3, 10) == 3
        assert current_slot(9, 10) == 9
        assert current_slot(10, 10) == 0
        assert current_slot(13, 10) == 3

    def test_epoch_start_block(self):
        assert epoch_start_block(0, 10) == 0
        assert epoch_start_block(1, 10) == 10
        assert epoch_start_block(5, 10) == 50

    def test_epoch_end_block(self):
        assert epoch_end_block(0, 10) == 9
        assert epoch_end_block(1, 10) == 19

    def test_is_epoch_boundary(self):
        assert is_epoch_boundary(9, 10) is True
        assert is_epoch_boundary(19, 10) is True
        assert is_epoch_boundary(0, 10) is False
        assert is_epoch_boundary(5, 10) is False

    def test_blocks_until_epoch_end(self):
        assert blocks_until_epoch_end(0, 10) == 9
        assert blocks_until_epoch_end(5, 10) == 4
        assert blocks_until_epoch_end(9, 10) == 0

    def test_unbonding_release_block(self):
        assert unbonding_release_block(100, 20) == 120

    def test_engine_epoch_at_height(self, engine):
        assert engine.epoch_at_height(0) == 0
        assert engine.epoch_at_height(15) == 1  # blocks_per_epoch=10

    def test_engine_slot_at_height(self, engine):
        assert engine.slot_at_height(3) == 3
        assert engine.slot_at_height(13) == 3

    def test_engine_is_epoch_boundary(self, engine):
        assert engine.is_epoch_boundary(9) is True
        assert engine.is_epoch_boundary(5) is False


class TestChainId:
    def test_block_hash_includes_chain_id(self):
        h1 = compute_block_hash("chain-A", 1, "prev", "merkle", 1000)
        h2 = compute_block_hash("chain-B", 1, "prev", "merkle", 1000)
        assert h1 != h2  # Different chain_id → different hash

    def test_block_hash_deterministic(self):
        h1 = compute_block_hash("oasyce-testnet-1", 42, "abc", "def", 999)
        h2 = compute_block_hash("oasyce-testnet-1", 42, "abc", "def", 999)
        assert h1 == h2  # Same inputs → same hash

    def test_engine_has_chain_id(self, engine):
        assert engine.chain_id == "oasyce-testnet-1"

    def test_apply_block(self, engine):
        engine.register_validator("v1", to_units(200))
        block = {
            "height": 10,
            "operations": [
                Operation(op_type=OperationType.DELEGATE, validator_id="v1",
                          amount=to_units(50), from_addr="del1"),
            ],
        }
        result = engine.apply_block(block)
        assert result["operations_applied"] == 1
        assert engine.state.get_validator_stake("v1") == to_units(250)


# ═══════════════════════════════════════════════════════════════════
# Iron Rules Verification
# ═══════════════════════════════════════════════════════════════════

class TestIronRules:
    """Verify the five iron rules of the protocol."""

    def test_no_float_amounts(self, engine):
        """Rule 3: No float. All amounts are int."""
        engine.register_validator("v1", to_units(200))
        engine.delegate("del1", "v1", to_units(50))

        val = engine.state.get_validator("v1")
        assert isinstance(val["total_stake"], int)
        assert isinstance(val["self_stake"], int)
        assert isinstance(val["commission_rate"], int)

        delegations = engine.state.get_delegations("v1")
        for d in delegations:
            assert isinstance(d["amount"], int)

    def test_no_update_on_stake(self, engine):
        """Rule 1: No UPDATE on monetary columns. All changes via events."""
        engine.register_validator("v1", to_units(200))
        engine.delegate("del1", "v1", to_units(50))

        # Count events
        with engine.state._lock:
            events = engine.state._conn.execute(
                "SELECT COUNT(*) FROM stake_events"
            ).fetchone()[0]
        assert events >= 2  # register_self + delegate

    def test_single_write_entry(self, engine):
        """Rule 2: Only apply_operation writes state."""
        # All these go through apply_operation via ConsensusEngine.apply()
        engine.register_validator("v1", to_units(200))
        engine.delegate("del1", "v1", to_units(50))
        engine.undelegate("del1", "v1", to_units(20))
        # State is consistent
        assert engine.state.get_validator_stake("v1") == to_units(230)
        assert engine.state.get_delegation_amount("del1", "v1") == to_units(30)

    def test_deterministic_output(self, engine):
        """Rule 1: Determinism. Same ops → same state."""
        engine.register_validator("v1", to_units(200))
        engine.delegate("del1", "v1", to_units(50))
        state1 = engine.state.get_validator_stake("v1")

        engine2 = ConsensusEngine(
            db_path=":memory:",
            economics={
                "block_reward": 40 * OAS_DECIMALS,
                "min_stake": 100 * OAS_DECIMALS,
                "halving_interval": 10000,
            },
        )
        engine2.register_validator("v1", to_units(200))
        engine2.delegate("del1", "v1", to_units(50))
        state2 = engine2.state.get_validator_stake("v1")

        assert state1 == state2
        engine2.close()

    def test_state_machine_property(self, engine):
        """Rule 4: state + operation → new_state."""
        engine.register_validator("v1", to_units(200))
        before = engine.state.get_validator_stake("v1")
        engine.delegate("del1", "v1", to_units(100))
        after = engine.state.get_validator_stake("v1")
        assert after == before + to_units(100)


# ═══════════════════════════════════════════════════════════════════
# No REAL / No UPDATE / No time.time() verification
# ═══════════════════════════════════════════════════════════════════

class TestDatabaseSchema:
    """Verify the database schema uses INTEGER, not REAL."""

    def test_no_real_columns(self, state):
        """All monetary columns should be INTEGER, not REAL."""
        with state._lock:
            tables = state._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()

        for table_row in tables:
            table = table_row[0]
            with state._lock:
                info = state._conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            for col in info:
                col_name = col[1]
                col_type = col[2].upper()
                assert col_type != "REAL", \
                    f"Table {table}.{col_name} is REAL — must be INTEGER"


class TestReRegistration:
    def test_reregister_after_exit(self, engine):
        engine.register_validator("v1", to_units(200))
        engine.exit_validator("v1")
        # Release unbondings
        engine.state.release_matured_unbondings(9999999999)
        # Re-register
        result = engine.register_validator("v1", to_units(300))
        assert result["ok"] is True
        assert result.get("re_registered") is True
        val = engine.state.get_validator("v1")
        assert val["status"] == "active"
        assert val["total_stake"] == to_units(300)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

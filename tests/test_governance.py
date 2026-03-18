"""Tests for the governance module — proposals, voting, tallying, execution.

Covers:
- Proposal submission (valid / invalid deposit / invalid params)
- Voting (stake-weighted, duplicate, no-stake, expired)
- Tallying (2/3 majority, quorum 40%, various scenarios)
- Execution (parameter change applied, status transitions)
- End-of-block automation (auto-execute, auto-reject, auto-expire)
- Parameter registry (register, validate, apply, constraints)
- Edge cases (malicious proposals, boundary conditions)
"""

import pytest

from oasyce_plugin.consensus import ConsensusEngine
from oasyce_plugin.consensus.core.types import (
    OAS_DECIMALS, to_units, from_units,
    Operation, OperationType,
)
from oasyce_plugin.consensus.governance.types import (
    DEFAULT_MIN_DEPOSIT,
    DEFAULT_VOTING_PERIOD,
    QUORUM_BPS,
    PASS_THRESHOLD_BPS,
    UNGOVERNABLE_KEYS,
    ParameterChange,
    Proposal,
    ProposalStatus,
    Vote,
    VoteOption,
    VoteResult,
    compute_proposal_id,
)
from oasyce_plugin.consensus.governance.registry import ParameterRegistry
from oasyce_plugin.consensus.governance.engine import GovernanceEngine


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """Create an in-memory ConsensusEngine for testing."""
    e = ConsensusEngine(db_path=":memory:")
    yield e
    e.close()


@pytest.fixture
def engine_with_validators(engine):
    """Engine with 3 validators for voting tests.

    Total stake = 50000 OAS (v1=20000, v2=15000, v3=15000).
    Quorum (40%) = 20000 OAS.
    """
    v1_stake = to_units(20000)
    v2_stake = to_units(15000)
    v3_stake = to_units(15000)

    r1 = engine.register_validator("validator_1", v1_stake)
    r2 = engine.register_validator("validator_2", v2_stake)
    r3 = engine.register_validator("validator_3", v3_stake)
    assert r1["ok"] and r2["ok"] and r3["ok"]
    return engine


def _make_change(engine, module="economics", key="block_reward",
                 new_value=5_000_000_000):
    """Helper to create a valid ParameterChange."""
    old_value = engine.param_registry.get_current_value(module, key)
    return ParameterChange(
        module=module, key=key,
        old_value=old_value, new_value=new_value,
    )


# ══════════════════════════════════════════════════════════════════
#  1. Proposal Submission
# ══════════════════════════════════════════════════════════════════


class TestProposalSubmission:
    """Test proposal submission validation and creation."""

    def test_submit_valid_proposal(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        result = eng.submit_proposal(
            proposer="validator_1",
            title="Increase Block Reward",
            description="Raise block reward from 40 to 50 OAS",
            changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert result["ok"]
        p = result["proposal"]
        assert p["status"] == "active"
        assert p["title"] == "Increase Block Reward"
        assert len(p["changes"]) == 1
        assert p["deposit"] == DEFAULT_MIN_DEPOSIT

    def test_submit_insufficient_deposit(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        result = eng.submit_proposal(
            proposer="validator_1",
            title="Test",
            description="",
            changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT - 1,
        )
        assert not result["ok"]
        assert "below minimum" in result["error"]

    def test_submit_empty_title(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        result = eng.submit_proposal(
            proposer="validator_1",
            title="",
            description="desc",
            changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert not result["ok"]
        assert "title" in result["error"]

    def test_submit_no_changes(self, engine_with_validators):
        eng = engine_with_validators
        result = eng.submit_proposal(
            proposer="validator_1",
            title="Empty",
            description="no changes",
            changes=[],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert not result["ok"]
        assert "parameter change" in result["error"]

    def test_submit_ungovernable_param(self, engine_with_validators):
        eng = engine_with_validators
        change = ParameterChange(
            module="consensus", key="chain_id",
            old_value="oasyce-testnet-1", new_value="oasyce-mainnet",
        )
        result = eng.submit_proposal(
            proposer="validator_1",
            title="Change chain_id",
            description="",
            changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert not result["ok"]
        assert "not governable" in result["error"]

    def test_submit_unknown_param(self, engine_with_validators):
        eng = engine_with_validators
        change = ParameterChange(
            module="nonexistent", key="foo",
            old_value=0, new_value=1,
        )
        result = eng.submit_proposal(
            proposer="validator_1",
            title="Unknown param",
            description="",
            changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert not result["ok"]
        assert "unknown" in result["error"]

    def test_submit_out_of_range_param(self, engine_with_validators):
        eng = engine_with_validators
        # block_reward max is 100_000_000_000
        change = ParameterChange(
            module="economics", key="block_reward",
            old_value=eng.param_registry.get_current_value("economics", "block_reward"),
            new_value=999_000_000_000,
        )
        result = eng.submit_proposal(
            proposer="validator_1",
            title="Block reward too high",
            description="",
            changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert not result["ok"]
        assert "above maximum" in result["error"]

    def test_submit_old_value_mismatch(self, engine_with_validators):
        eng = engine_with_validators
        change = ParameterChange(
            module="economics", key="block_reward",
            old_value=999,  # wrong old value
            new_value=5_000_000_000,
        )
        result = eng.submit_proposal(
            proposer="validator_1",
            title="Wrong old value",
            description="",
            changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert not result["ok"]
        assert "old_value mismatch" in result["error"]

    def test_submit_duplicate_proposal(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r1 = eng.submit_proposal(
            proposer="validator_1", title="Dup",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert r1["ok"]
        # Same content at same block height -> same ID
        r2 = eng.submit_proposal(
            proposer="validator_1", title="Dup",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert not r2["ok"]
        assert "duplicate" in r2["error"]

    def test_submit_multiple_changes(self, engine_with_validators):
        eng = engine_with_validators
        c1 = _make_change(eng, "economics", "block_reward", 5_000_000_000)
        c2 = _make_change(eng, "economics", "min_stake", 20_000_000_000)
        result = eng.submit_proposal(
            proposer="validator_1",
            title="Multi-change",
            description="Two changes",
            changes=[c1, c2],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert result["ok"]
        assert len(result["proposal"]["changes"]) == 2

    def test_proposal_id_deterministic(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        pid = compute_proposal_id("validator_1", "Test", [change], 0)
        result = eng.submit_proposal(
            proposer="validator_1", title="Test",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert result["ok"]
        assert result["proposal"]["id"] == pid


# ══════════════════════════════════════════════════════════════════
#  2. Voting
# ══════════════════════════════════════════════════════════════════


class TestVoting:
    """Test vote casting — stake-weighted, duplicates, edge cases."""

    def _submit_proposal(self, eng):
        change = _make_change(eng)
        result = eng.submit_proposal(
            proposer="validator_1", title="Vote Test",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert result["ok"]
        return result["proposal"]["id"]

    def test_cast_vote_yes(self, engine_with_validators):
        eng = engine_with_validators
        pid = self._submit_proposal(eng)
        result = eng.cast_vote(pid, "validator_1", VoteOption.YES)
        assert result["ok"]
        assert result["vote"]["option"] == "yes"
        assert result["vote"]["weight"] == to_units(20000)

    def test_cast_vote_no(self, engine_with_validators):
        eng = engine_with_validators
        pid = self._submit_proposal(eng)
        result = eng.cast_vote(pid, "validator_2", VoteOption.NO)
        assert result["ok"]
        assert result["vote"]["option"] == "no"

    def test_cast_vote_abstain(self, engine_with_validators):
        eng = engine_with_validators
        pid = self._submit_proposal(eng)
        result = eng.cast_vote(pid, "validator_3", VoteOption.ABSTAIN)
        assert result["ok"]
        assert result["vote"]["option"] == "abstain"

    def test_vote_updates_on_duplicate(self, engine_with_validators):
        eng = engine_with_validators
        pid = self._submit_proposal(eng)
        eng.cast_vote(pid, "validator_1", VoteOption.YES)
        # Change vote
        result = eng.cast_vote(pid, "validator_1", VoteOption.NO)
        assert result["ok"]
        assert result["vote"]["option"] == "no"
        # Should only have 1 vote, not 2
        votes = eng.governance.get_votes(pid)
        v1_votes = [v for v in votes if v["voter"] == "validator_1"]
        assert len(v1_votes) == 1
        assert v1_votes[0]["option"] == "no"

    def test_vote_no_stake(self, engine_with_validators):
        eng = engine_with_validators
        pid = self._submit_proposal(eng)
        result = eng.cast_vote(pid, "random_user_no_stake", VoteOption.YES)
        assert not result["ok"]
        assert "no stake" in result["error"]

    def test_vote_nonexistent_proposal(self, engine_with_validators):
        eng = engine_with_validators
        result = eng.cast_vote("nonexistent_id", "validator_1", VoteOption.YES)
        assert not result["ok"]
        assert "not found" in result["error"]

    def test_vote_after_voting_period(self, engine_with_validators):
        eng = engine_with_validators
        pid = self._submit_proposal(eng)
        # Vote at block height past voting_end
        result = eng.cast_vote(
            pid, "validator_1", VoteOption.YES,
            block_height=DEFAULT_VOTING_PERIOD + 100,
        )
        assert not result["ok"]
        assert "ended" in result["error"]

    def test_vote_on_non_active_proposal(self, engine_with_validators):
        eng = engine_with_validators
        pid = self._submit_proposal(eng)
        # Manually mark as rejected
        eng.governance._update_status(pid, ProposalStatus.REJECTED)
        result = eng.cast_vote(pid, "validator_1", VoteOption.YES)
        assert not result["ok"]
        assert "not active" in result["error"]

    def test_vote_weight_from_delegation(self, engine_with_validators):
        """Delegators should also be able to vote with their delegation weight."""
        eng = engine_with_validators
        # delegator_a delegates 5000 to validator_1
        delegator = "delegator_a"
        eng.delegate(delegator, "validator_1", to_units(5000))
        pid = self._submit_proposal(eng)
        result = eng.cast_vote(pid, delegator, VoteOption.YES)
        assert result["ok"]
        assert result["vote"]["weight"] == to_units(5000)

    def test_multiple_voters(self, engine_with_validators):
        eng = engine_with_validators
        pid = self._submit_proposal(eng)
        eng.cast_vote(pid, "validator_1", VoteOption.YES)
        eng.cast_vote(pid, "validator_2", VoteOption.NO)
        eng.cast_vote(pid, "validator_3", VoteOption.ABSTAIN)
        votes = eng.governance.get_votes(pid)
        assert len(votes) == 3


# ══════════════════════════════════════════════════════════════════
#  3. Tallying
# ══════════════════════════════════════════════════════════════════


class TestTallying:
    """Test vote tallying — quorum, 2/3 majority, various outcomes."""

    def _submit_and_vote(self, eng, votes_dict):
        """Submit a proposal and cast votes.

        votes_dict: {"voter": VoteOption, ...}
        """
        change = _make_change(eng)
        result = eng.submit_proposal(
            proposer="validator_1", title="Tally Test",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert result["ok"]
        pid = result["proposal"]["id"]
        for voter, option in votes_dict.items():
            r = eng.cast_vote(pid, voter, option)
            assert r["ok"], f"vote failed for {voter}: {r.get('error')}"
        return pid

    def test_tally_unanimous_yes(self, engine_with_validators):
        """All 3 validators vote YES -> passes."""
        eng = engine_with_validators
        pid = self._submit_and_vote(eng, {
            "validator_1": VoteOption.YES,
            "validator_2": VoteOption.YES,
            "validator_3": VoteOption.YES,
        })
        result = eng.tally_votes(pid)
        assert result["ok"]
        r = result["result"]
        assert r["quorum_reached"]
        assert r["passed"]
        assert r["yes_votes"] == to_units(50000)

    def test_tally_unanimous_no(self, engine_with_validators):
        """All vote NO -> fails."""
        eng = engine_with_validators
        pid = self._submit_and_vote(eng, {
            "validator_1": VoteOption.NO,
            "validator_2": VoteOption.NO,
            "validator_3": VoteOption.NO,
        })
        result = eng.tally_votes(pid)
        assert result["ok"]
        r = result["result"]
        assert r["quorum_reached"]
        assert not r["passed"]

    def test_tally_exactly_two_thirds(self, engine_with_validators):
        """v1(20k YES) + v2(15k NO) + v3(15k YES) = 35k/50k voted.
        YES=35k, NO=15k -> 70% YES > 66.67% -> passes.
        """
        eng = engine_with_validators
        pid = self._submit_and_vote(eng, {
            "validator_1": VoteOption.YES,
            "validator_2": VoteOption.NO,
            "validator_3": VoteOption.YES,
        })
        result = eng.tally_votes(pid)
        assert result["ok"]
        r = result["result"]
        assert r["quorum_reached"]
        assert r["passed"]

    def test_tally_below_two_thirds(self, engine_with_validators):
        """v1(20k YES) + v2(15k NO) + v3(15k NO) -> YES=20k/50k = 40% < 66.67% -> fails."""
        eng = engine_with_validators
        pid = self._submit_and_vote(eng, {
            "validator_1": VoteOption.YES,
            "validator_2": VoteOption.NO,
            "validator_3": VoteOption.NO,
        })
        result = eng.tally_votes(pid)
        r = result["result"]
        assert r["quorum_reached"]
        assert not r["passed"]

    def test_tally_no_quorum(self, engine_with_validators):
        """Only v3(15k) votes -> 15k/50k = 30% < 40% quorum -> expired."""
        eng = engine_with_validators
        pid = self._submit_and_vote(eng, {
            "validator_3": VoteOption.YES,
        })
        result = eng.tally_votes(pid)
        r = result["result"]
        assert not r["quorum_reached"]
        assert not r["passed"]

    def test_tally_quorum_exactly_40_pct(self, engine_with_validators):
        """v1(20k YES) -> 20k/50k = 40% = exactly quorum -> quorum met."""
        eng = engine_with_validators
        pid = self._submit_and_vote(eng, {
            "validator_1": VoteOption.YES,
        })
        result = eng.tally_votes(pid)
        r = result["result"]
        assert r["quorum_reached"]
        assert r["passed"]  # 100% yes

    def test_tally_abstain_counts_for_quorum(self, engine_with_validators):
        """Abstain counts toward quorum but not majority threshold."""
        eng = engine_with_validators
        pid = self._submit_and_vote(eng, {
            "validator_1": VoteOption.YES,
            "validator_2": VoteOption.ABSTAIN,
            "validator_3": VoteOption.ABSTAIN,
        })
        result = eng.tally_votes(pid)
        r = result["result"]
        assert r["quorum_reached"]  # 50k/50k = 100%
        # yes=20k, no=0 -> 100% YES of yes+no -> passes
        assert r["passed"]

    def test_tally_abstain_doesnt_count_for_majority(self, engine_with_validators):
        """Only YES and NO count for 2/3 majority threshold."""
        eng = engine_with_validators
        pid = self._submit_and_vote(eng, {
            "validator_1": VoteOption.ABSTAIN,  # 20k abstain
            "validator_2": VoteOption.YES,       # 15k yes
            "validator_3": VoteOption.NO,        # 15k no
        })
        result = eng.tally_votes(pid)
        r = result["result"]
        assert r["quorum_reached"]
        # yes=15k, no=15k -> 50% < 66.67% -> fails
        assert not r["passed"]

    def test_tally_nonexistent_proposal(self, engine_with_validators):
        eng = engine_with_validators
        result = eng.tally_votes("nonexistent")
        assert not result["ok"]

    def test_tally_no_votes(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="No votes",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        result = eng.tally_votes(pid)
        r = result["result"]
        assert not r["quorum_reached"]
        assert not r["passed"]


# ══════════════════════════════════════════════════════════════════
#  4. Execution
# ══════════════════════════════════════════════════════════════════


class TestExecution:
    """Test proposal execution — parameter changes applied."""

    def test_execute_passed_proposal(self, engine_with_validators):
        eng = engine_with_validators
        old_reward = eng.param_registry.get_current_value("economics", "block_reward")
        new_reward = 5_000_000_000
        change = _make_change(eng, "economics", "block_reward", new_reward)

        r = eng.submit_proposal(
            proposer="validator_1", title="Exec Test",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]

        # All vote yes
        for v in ["validator_1", "validator_2", "validator_3"]:
            eng.cast_vote(pid, v, VoteOption.YES)

        # Manually transition to passed
        eng.governance._update_status(pid, ProposalStatus.PASSED)

        result = eng.governance.execute_proposal(pid)
        assert result["ok"]
        assert result["count"] == 1
        # Verify parameter was changed
        assert eng.param_registry.get_current_value("economics", "block_reward") == new_reward

    def test_execute_non_passed_proposal(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Not passed",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        # Status is still ACTIVE, not PASSED
        result = eng.governance.execute_proposal(pid)
        assert not result["ok"]
        assert "must be 'passed'" in result["error"]

    def test_execute_multiple_changes(self, engine_with_validators):
        eng = engine_with_validators
        c1 = _make_change(eng, "economics", "block_reward", 5_000_000_000)
        c2 = _make_change(eng, "economics", "min_stake", 20_000_000_000)

        r = eng.submit_proposal(
            proposer="validator_1", title="Multi exec",
            description="", changes=[c1, c2],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        eng.governance._update_status(pid, ProposalStatus.PASSED)
        result = eng.governance.execute_proposal(pid)
        assert result["ok"]
        assert result["count"] == 2
        assert eng.param_registry.get_current_value("economics", "block_reward") == 5_000_000_000
        assert eng.param_registry.get_current_value("economics", "min_stake") == 20_000_000_000

    def test_execute_sets_status_to_executed(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Status test",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        eng.governance._update_status(pid, ProposalStatus.PASSED)
        eng.governance.execute_proposal(pid)
        p = eng.get_proposal(pid)
        assert p["status"] == "executed"

    def test_cannot_execute_twice(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Double exec",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        eng.governance._update_status(pid, ProposalStatus.PASSED)
        eng.governance.execute_proposal(pid)
        # Try again
        result = eng.governance.execute_proposal(pid)
        assert not result["ok"]
        assert "must be 'passed'" in result["error"]


# ══════════════════════════════════════════════════════════════════
#  5. End-of-block automation
# ══════════════════════════════════════════════════════════════════


class TestEndBlock:
    """Test end_block auto-processing of expired voting periods."""

    def test_auto_execute_passed_proposal(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Auto exec",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]

        for v in ["validator_1", "validator_2", "validator_3"]:
            eng.cast_vote(pid, v, VoteOption.YES)

        # Advance past voting end
        changed = eng.governance.end_block(DEFAULT_VOTING_PERIOD + 1)
        assert len(changed) == 1
        assert changed[0]["proposal_id"] == pid
        assert changed[0]["new_status"] == "executed"

    def test_auto_reject_failed_proposal(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Auto reject",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]

        # All vote NO -> quorum met but majority fails
        for v in ["validator_1", "validator_2", "validator_3"]:
            eng.cast_vote(pid, v, VoteOption.NO)

        changed = eng.governance.end_block(DEFAULT_VOTING_PERIOD + 1)
        assert len(changed) == 1
        assert changed[0]["new_status"] == "rejected"

    def test_auto_expire_no_quorum(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Auto expire",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]

        # Only v3 votes (15k/50k = 30% < 40% quorum)
        eng.cast_vote(pid, "validator_3", VoteOption.YES)

        changed = eng.governance.end_block(DEFAULT_VOTING_PERIOD + 1)
        assert len(changed) == 1
        assert changed[0]["new_status"] == "expired"

    def test_end_block_no_expired_proposals(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        eng.submit_proposal(
            proposer="validator_1", title="Not yet",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        # Block height before voting_end
        changed = eng.governance.end_block(10)
        assert len(changed) == 0

    def test_end_block_multiple_proposals(self, engine_with_validators):
        eng = engine_with_validators

        # Proposal 1: will pass
        c1 = _make_change(eng, "economics", "block_reward", 5_000_000_000)
        r1 = eng.submit_proposal(
            proposer="validator_1", title="Pass me",
            description="", changes=[c1],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid1 = r1["proposal"]["id"]
        for v in ["validator_1", "validator_2", "validator_3"]:
            eng.cast_vote(pid1, v, VoteOption.YES)

        # Proposal 2: will fail
        c2 = _make_change(eng, "economics", "min_stake", 20_000_000_000)
        r2 = eng.submit_proposal(
            proposer="validator_2", title="Reject me",
            description="", changes=[c2],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid2 = r2["proposal"]["id"]
        for v in ["validator_1", "validator_2", "validator_3"]:
            eng.cast_vote(pid2, v, VoteOption.NO)

        changed = eng.governance.end_block(DEFAULT_VOTING_PERIOD + 1)
        assert len(changed) == 2
        statuses = {c["proposal_id"]: c["new_status"] for c in changed}
        assert statuses[pid1] == "executed"
        assert statuses[pid2] == "rejected"


# ══════════════════════════════════════════════════════════════════
#  6. Parameter Registry
# ══════════════════════════════════════════════════════════════════


class TestParameterRegistry:
    """Test the parameter registry standalone."""

    def test_register_and_get(self):
        reg = ParameterRegistry()
        reg.register("test", "param1", int, 100, min_value=0, max_value=1000)
        spec = reg.get("test", "param1")
        assert spec is not None
        assert spec.current_value == 100

    def test_register_ungovernable(self):
        reg = ParameterRegistry()
        with pytest.raises(ValueError, match="not governable"):
            reg.register("consensus", "chain_id", str, "test")

    def test_validate_valid_change(self):
        reg = ParameterRegistry()
        reg.register("test", "p", int, 100, min_value=0, max_value=1000)
        ok, err = reg.validate_change("test", "p", 500)
        assert ok
        assert err == ""

    def test_validate_below_min(self):
        reg = ParameterRegistry()
        reg.register("test", "p", int, 100, min_value=10, max_value=1000)
        ok, err = reg.validate_change("test", "p", 5)
        assert not ok
        assert "below minimum" in err

    def test_validate_above_max(self):
        reg = ParameterRegistry()
        reg.register("test", "p", int, 100, min_value=0, max_value=1000)
        ok, err = reg.validate_change("test", "p", 5000)
        assert not ok
        assert "above maximum" in err

    def test_validate_unknown_param(self):
        reg = ParameterRegistry()
        ok, err = reg.validate_change("test", "unknown", 100)
        assert not ok
        assert "unknown" in err

    def test_validate_type_coercion(self):
        reg = ParameterRegistry()
        reg.register("test", "p", int, 100, min_value=0, max_value=1000)
        # String "500" should coerce to int 500
        ok, err = reg.validate_change("test", "p", "500")
        assert ok

    def test_validate_type_mismatch(self):
        reg = ParameterRegistry()
        reg.register("test", "p", int, 100, min_value=0, max_value=1000)
        ok, err = reg.validate_change("test", "p", "not_a_number")
        assert not ok
        assert "type mismatch" in err

    def test_apply_change(self):
        reg = ParameterRegistry()
        applied_values = []
        reg.register("test", "p", int, 100, min_value=0, max_value=1000,
                     applier=lambda v: applied_values.append(v))
        ok = reg.apply_change("test", "p", 500)
        assert ok
        assert reg.get_current_value("test", "p") == 500
        assert applied_values == [500]

    def test_apply_nonexistent(self):
        reg = ParameterRegistry()
        ok = reg.apply_change("test", "nonexistent", 100)
        assert not ok

    def test_list_parameters(self):
        reg = ParameterRegistry()
        reg.register("mod_a", "p1", int, 100)
        reg.register("mod_a", "p2", int, 200)
        reg.register("mod_b", "p3", int, 300)
        assert len(reg.list_parameters()) == 3
        assert len(reg.list_parameters("mod_a")) == 2
        assert len(reg.list_parameters("mod_b")) == 1

    def test_to_dict_list(self):
        reg = ParameterRegistry()
        reg.register("test", "p", int, 100, min_value=0, max_value=1000,
                     description="test param")
        dicts = reg.to_dict_list()
        assert len(dicts) == 1
        assert dicts[0]["module"] == "test"
        assert dicts[0]["key"] == "p"
        assert dicts[0]["value_type"] == "int"


# ══════════════════════════════════════════════════════════════════
#  7. Query helpers
# ══════════════════════════════════════════════════════════════════


class TestQueryHelpers:
    """Test proposal listing and retrieval."""

    def test_get_proposal(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Query test",
            description="desc", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        p = eng.get_proposal(pid)
        assert p is not None
        assert p["title"] == "Query test"
        assert p["description"] == "desc"
        assert "vote_count" in p

    def test_get_nonexistent_proposal(self, engine_with_validators):
        eng = engine_with_validators
        assert eng.get_proposal("nonexistent") is None

    def test_list_all_proposals(self, engine_with_validators):
        eng = engine_with_validators
        c1 = _make_change(eng, "economics", "block_reward", 5_000_000_000)
        c2 = _make_change(eng, "economics", "min_stake", 20_000_000_000)
        eng.submit_proposal("v1", "P1", "", [c1], DEFAULT_MIN_DEPOSIT)
        eng.submit_proposal("v2", "P2", "", [c2], DEFAULT_MIN_DEPOSIT)
        proposals = eng.list_proposals()
        assert len(proposals) == 2

    def test_list_proposals_by_status(self, engine_with_validators):
        eng = engine_with_validators
        c1 = _make_change(eng, "economics", "block_reward", 5_000_000_000)
        r = eng.submit_proposal("v1", "Active", "", [c1], DEFAULT_MIN_DEPOSIT)
        pid = r["proposal"]["id"]
        assert len(eng.list_proposals(status="active")) == 1
        assert len(eng.list_proposals(status="rejected")) == 0
        eng.governance._update_status(pid, ProposalStatus.REJECTED)
        assert len(eng.list_proposals(status="active")) == 0
        assert len(eng.list_proposals(status="rejected")) == 1

    def test_list_governable_params(self, engine_with_validators):
        eng = engine_with_validators
        params = eng.list_governable_params()
        assert len(params) >= 9  # 3 consensus + 3 economics + 3 slashing

    def test_list_governable_params_by_module(self, engine_with_validators):
        eng = engine_with_validators
        params = eng.list_governable_params(module="economics")
        assert all(p["module"] == "economics" for p in params)
        assert len(params) == 3


# ══════════════════════════════════════════════════════════════════
#  8. Edge Cases & Boundary Conditions
# ══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Test boundary conditions and edge cases."""

    def test_proposal_with_min_deposit_exactly(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        result = eng.submit_proposal(
            proposer="validator_1", title="Min deposit",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert result["ok"]

    def test_proposal_whitespace_title(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        result = eng.submit_proposal(
            proposer="validator_1", title="   ",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert not result["ok"]

    def test_vote_at_exact_voting_end(self, engine_with_validators):
        """Vote at exactly voting_end block is still valid (end is inclusive)."""
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Boundary vote",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        voting_end = r["proposal"]["voting_end"]
        result = eng.cast_vote(pid, "validator_1", VoteOption.YES,
                               block_height=voting_end)
        assert result["ok"]

    def test_vote_one_past_voting_end(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Past boundary",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        voting_end = r["proposal"]["voting_end"]
        result = eng.cast_vote(pid, "validator_1", VoteOption.YES,
                               block_height=voting_end + 1)
        assert not result["ok"]

    def test_parameter_change_below_min(self, engine_with_validators):
        """Proposal with parameter below allowed minimum."""
        eng = engine_with_validators
        change = ParameterChange(
            module="economics", key="min_stake",
            old_value=eng.param_registry.get_current_value("economics", "min_stake"),
            new_value=100,  # below min_value of 1_000_000_000
        )
        result = eng.submit_proposal(
            proposer="validator_1", title="Below min",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        assert not result["ok"]
        assert "below minimum" in result["error"]

    def test_end_block_idempotent(self, engine_with_validators):
        """Calling end_block multiple times shouldn't re-process proposals."""
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            proposer="validator_1", title="Idempotent",
            description="", changes=[change],
            deposit=DEFAULT_MIN_DEPOSIT,
        )
        for v in ["validator_1", "validator_2", "validator_3"]:
            eng.cast_vote(r["proposal"]["id"], v, VoteOption.YES)

        changed1 = eng.governance.end_block(DEFAULT_VOTING_PERIOD + 1)
        changed2 = eng.governance.end_block(DEFAULT_VOTING_PERIOD + 1)
        assert len(changed1) == 1
        assert len(changed2) == 0  # already processed

    def test_proposal_to_dict_roundtrip(self):
        """ParameterChange serialization roundtrip."""
        change = ParameterChange(
            module="test", key="param",
            old_value=100, new_value=200,
        )
        d = change.to_dict()
        restored = ParameterChange.from_dict(d)
        assert restored == change

    def test_vote_result_to_dict(self):
        vr = VoteResult(
            proposal_id="abc", yes_votes=100, no_votes=50,
            abstain_votes=25, total_voting_power=1000,
            quorum_reached=True, passed=True,
        )
        d = vr.to_dict()
        assert d["proposal_id"] == "abc"
        assert d["passed"] is True

    def test_compute_proposal_id_deterministic(self):
        change = ParameterChange("m", "k", 0, 1)
        id1 = compute_proposal_id("addr", "title", [change], 42)
        id2 = compute_proposal_id("addr", "title", [change], 42)
        assert id1 == id2

    def test_compute_proposal_id_differs(self):
        change = ParameterChange("m", "k", 0, 1)
        id1 = compute_proposal_id("addr", "title1", [change], 42)
        id2 = compute_proposal_id("addr", "title2", [change], 42)
        assert id1 != id2


# ══════════════════════════════════════════════════════════════════
#  9. Integration with ConsensusEngine
# ══════════════════════════════════════════════════════════════════


class TestConsensusEngineIntegration:
    """Test governance through the ConsensusEngine facade."""

    def test_engine_has_governance(self, engine):
        assert hasattr(engine, "governance")
        assert hasattr(engine, "param_registry")
        assert isinstance(engine.governance, GovernanceEngine)
        assert isinstance(engine.param_registry, ParameterRegistry)

    def test_engine_submit_proposal(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        result = eng.submit_proposal(
            "validator_1", "Test", "desc", [change], DEFAULT_MIN_DEPOSIT,
        )
        assert result["ok"]

    def test_engine_cast_vote(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            "validator_1", "Test", "", [change], DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        result = eng.cast_vote(pid, "validator_1", VoteOption.YES)
        assert result["ok"]

    def test_engine_tally_votes(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            "validator_1", "Test", "", [change], DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        eng.cast_vote(pid, "validator_1", VoteOption.YES)
        result = eng.tally_votes(pid)
        assert result["ok"]

    def test_engine_list_proposals(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        eng.submit_proposal(
            "validator_1", "Test", "", [change], DEFAULT_MIN_DEPOSIT,
        )
        proposals = eng.list_proposals()
        assert len(proposals) == 1

    def test_engine_get_proposal(self, engine_with_validators):
        eng = engine_with_validators
        change = _make_change(eng)
        r = eng.submit_proposal(
            "validator_1", "Test", "", [change], DEFAULT_MIN_DEPOSIT,
        )
        pid = r["proposal"]["id"]
        p = eng.get_proposal(pid)
        assert p is not None
        assert p["id"] == pid

    def test_engine_list_governable_params(self, engine_with_validators):
        eng = engine_with_validators
        params = eng.list_governable_params()
        assert len(params) >= 9

    def test_full_lifecycle(self, engine_with_validators):
        """Full governance lifecycle: submit -> vote -> tally -> execute."""
        eng = engine_with_validators
        old_reward = eng.param_registry.get_current_value("economics", "block_reward")
        new_reward = 5_000_000_000

        # Submit
        change = _make_change(eng, "economics", "block_reward", new_reward)
        r = eng.submit_proposal(
            "validator_1", "Change reward", "Increase",
            [change], DEFAULT_MIN_DEPOSIT,
        )
        assert r["ok"]
        pid = r["proposal"]["id"]

        # Vote
        for v in ["validator_1", "validator_2", "validator_3"]:
            vr = eng.cast_vote(pid, v, VoteOption.YES)
            assert vr["ok"]

        # Tally (before end_block — just check)
        tally = eng.tally_votes(pid)
        assert tally["result"]["passed"]

        # End block triggers execution
        changed = eng.governance.end_block(DEFAULT_VOTING_PERIOD + 1)
        assert len(changed) == 1
        assert changed[0]["new_status"] == "executed"

        # Verify parameter changed
        assert eng.param_registry.get_current_value("economics", "block_reward") == new_reward
        # Verify proposal status
        p = eng.get_proposal(pid)
        assert p["status"] == "executed"

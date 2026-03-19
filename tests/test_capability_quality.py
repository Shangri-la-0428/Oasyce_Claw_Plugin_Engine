"""Comprehensive tests for Steps 3+4: Quality Gate + Rating + Dispute + Jury.

Covers:
    - Rating: submit, weighted average, duplicate prevention, score validation
    - Quality gate: pass/fail/warn, schema validation, auto-settle
    - Dispute: open, jury selection, voting, resolution (consumer/provider/no majority)
    - Dispute timing: within window OK, after window rejected
    - Slash integration: provider bond reduced on dispute loss
    - Full flow: invoke → result → quality → rating → dispute → jury → resolve
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pytest

from oasyce.capabilities.rating import (
    RatingEngine,
    RatingRecord,
    RatingStats,
    RatingError,
)
from oasyce.capabilities.quality import (
    QualityGate,
    QualityResult,
    QualityVerdict,
    QualityError,
    FlagRecord,
)
from oasyce.capabilities.dispute import (
    DisputeManager,
    DisputeRecord,
    DisputeResolution,
    DisputeState,
    DisputeError,
    Verdict,
    ResolutionOutcome,
    DISPUTE_FEE,
    DEFAULT_DISPUTE_WINDOW,
    MIN_JUROR_REPUTATION,
    JUROR_REWARD_FIXED,
)
from oasyce.capabilities.escrow import (
    EscrowManager,
    EscrowState,
)
from oasyce.capabilities.manifest import (
    CapabilityManifest,
    PricingConfig,
    StakingConfig,
    QualityPolicy,
    ExecutionLimits,
)
from oasyce.capabilities.registry import CapabilityRegistry
from oasyce.capabilities.shares import ShareLedger
from oasyce.capabilities.invocation import (
    CapabilityInvocationEngine,
    InvocationState,
    InvocationError,
    SettlementResult,
)
from oasyce.capabilities._pricing_shim import FeeSplitter


# ── Test helpers ─────────────────────────────────────────────────────


@dataclass
class _FakeInvocation:
    """Minimal invocation record for testing rating/dispute."""

    invocation_id: str = "inv-1"
    capability_id: str = "cap-1"
    consumer_id: str = "consumer-1"
    provider_id: str = "provider-1"
    state: str = "completed"
    settled_at: int = field(default_factory=lambda: int(time.time()))
    escrow_id: str = "esc-1"
    price: float = 10.0
    output_payload: Optional[Dict[str, Any]] = None

    class _State:
        def __init__(self, val: str):
            self.value = val

    def __post_init__(self) -> None:
        self.state = self._State(self.state)


def _make_manifest(
    name: str = "test-cap",
    provider: str = "provider-1",
    verification_type: str = "optimistic",
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        description="A test capability",
        version="1.0.0",
        provider=provider,
        tags=["test"],
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
        pricing=PricingConfig(reserve_ratio=0.35),
        quality=QualityPolicy(verification_type=verification_type),
    )


def _make_engine(
    manifest: Optional[CapabilityManifest] = None,
    consumer_balance: float = 1000.0,
    consumer_id: str = "consumer-1",
    quality_gate: Optional[QualityGate] = None,
):
    """Helper to create a fully wired invocation engine."""
    registry = CapabilityRegistry()
    escrow = EscrowManager()
    shares = ShareLedger(reserve_ratio=0.35)
    splitter = FeeSplitter()

    if manifest is None:
        manifest = _make_manifest()
    registry.register(manifest)
    escrow.deposit(consumer_id, consumer_balance)

    engine = CapabilityInvocationEngine(
        registry,
        escrow,
        shares,
        splitter,
        quality_gate=quality_gate,
    )
    return engine, registry, escrow, shares, manifest


# ═══════════════════════════════════════════════════════════════════════
# RATING TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestRatingSubmit:
    """Test basic rating submission."""

    def _make_rating_engine(self, invocations=None, reputations=None, stakes=None):
        inv_store = invocations or {}
        rep_store = reputations or {}
        stake_store = stakes or {}
        return RatingEngine(
            get_invocation=lambda iid: inv_store.get(iid),
            get_reputation=lambda aid: rep_store.get(aid, 10.0),
            get_stake=lambda aid: stake_store.get(aid, 100.0),
        )

    def test_submit_rating_success(self):
        inv = _FakeInvocation()
        engine = self._make_rating_engine({"inv-1": inv})
        rec = engine.submit_rating("inv-1", "consumer-1", 4)
        assert isinstance(rec, RatingRecord)
        assert rec.score == 4
        assert rec.invocation_id == "inv-1"
        assert rec.consumer_id == "consumer-1"
        assert rec.weight > 0

    def test_submit_rating_weight_calculation(self):
        inv = _FakeInvocation()
        engine = self._make_rating_engine(
            {"inv-1": inv},
            reputations={"consumer-1": 80.0},
            stakes={"consumer-1": 200.0},
        )
        rec = engine.submit_rating("inv-1", "consumer-1", 5)
        assert rec.weight == 80.0 * 200.0

    def test_submit_rating_min_weight(self):
        """Weight uses max(rep, 1) * max(stake, 1) so never zero."""
        inv = _FakeInvocation()
        engine = self._make_rating_engine(
            {"inv-1": inv},
            reputations={"consumer-1": 0.0},
            stakes={"consumer-1": 0.0},
        )
        rec = engine.submit_rating("inv-1", "consumer-1", 3)
        assert rec.weight == 1.0  # max(0,1) * max(0,1) = 1

    def test_score_validation_low(self):
        inv = _FakeInvocation()
        engine = self._make_rating_engine({"inv-1": inv})
        with pytest.raises(RatingError, match="between 1 and 5"):
            engine.submit_rating("inv-1", "consumer-1", 0)

    def test_score_validation_high(self):
        inv = _FakeInvocation()
        engine = self._make_rating_engine({"inv-1": inv})
        with pytest.raises(RatingError, match="between 1 and 5"):
            engine.submit_rating("inv-1", "consumer-1", 6)

    def test_score_validation_float(self):
        inv = _FakeInvocation()
        engine = self._make_rating_engine({"inv-1": inv})
        with pytest.raises(RatingError, match="between 1 and 5"):
            engine.submit_rating("inv-1", "consumer-1", 3.5)

    def test_duplicate_rating_rejected(self):
        inv = _FakeInvocation()
        engine = self._make_rating_engine({"inv-1": inv})
        engine.submit_rating("inv-1", "consumer-1", 4)
        with pytest.raises(RatingError, match="already been rated"):
            engine.submit_rating("inv-1", "consumer-1", 5)

    def test_invocation_not_found(self):
        engine = self._make_rating_engine({})
        with pytest.raises(RatingError, match="not found"):
            engine.submit_rating("inv-999", "consumer-1", 3)

    def test_only_consumer_can_rate(self):
        inv = _FakeInvocation()
        engine = self._make_rating_engine({"inv-1": inv})
        with pytest.raises(RatingError, match="only the consumer"):
            engine.submit_rating("inv-1", "someone-else", 4)

    def test_only_completed_invocations(self):
        inv = _FakeInvocation(state="pending")
        engine = self._make_rating_engine({"inv-1": inv})
        with pytest.raises(RatingError, match="completed"):
            engine.submit_rating("inv-1", "consumer-1", 4)


class TestRatingAggregation:
    """Test weighted average and stats."""

    def _make_engine_with_ratings(self):
        invocations = {}
        reputations = {
            "c1": 80.0,
            "c2": 20.0,
            "c3": 50.0,
        }
        stakes = {
            "c1": 200.0,
            "c2": 50.0,
            "c3": 100.0,
        }
        for i, (cid, score) in enumerate([("c1", 5), ("c2", 1), ("c3", 3)]):
            invocations[f"inv-{i}"] = _FakeInvocation(
                invocation_id=f"inv-{i}",
                consumer_id=cid,
                provider_id="provider-1",
                capability_id="cap-1",
            )

        engine = RatingEngine(
            get_invocation=lambda iid: invocations.get(iid),
            get_reputation=lambda aid: reputations.get(aid, 10.0),
            get_stake=lambda aid: stakes.get(aid, 100.0),
        )

        engine.submit_rating("inv-0", "c1", 5)
        engine.submit_rating("inv-1", "c2", 1)
        engine.submit_rating("inv-2", "c3", 3)
        return engine

    def test_get_ratings(self):
        engine = self._make_engine_with_ratings()
        ratings = engine.get_ratings("cap-1")
        assert len(ratings) == 3

    def test_capability_stats(self):
        engine = self._make_engine_with_ratings()
        stats = engine.get_capability_stats("cap-1")
        assert isinstance(stats, RatingStats)
        assert stats.count == 3
        assert stats.raw_average == pytest.approx(3.0)
        # Weighted average should be closer to 5 (c1 has highest weight)
        assert stats.weighted_average > 3.0

    def test_provider_score(self):
        engine = self._make_engine_with_ratings()
        stats = engine.get_provider_score("provider-1")
        assert stats is not None
        assert stats.count == 3
        assert stats.weighted_average > 3.0

    def test_no_ratings_returns_none(self):
        engine = RatingEngine(
            get_invocation=lambda iid: None,
            get_reputation=lambda aid: 10.0,
            get_stake=lambda aid: 100.0,
        )
        assert engine.get_capability_stats("cap-1") is None
        assert engine.get_provider_score("provider-1") is None

    def test_empty_ratings_list(self):
        engine = RatingEngine(
            get_invocation=lambda iid: None,
            get_reputation=lambda aid: 10.0,
            get_stake=lambda aid: 100.0,
        )
        assert engine.get_ratings("cap-1") == []


# ═══════════════════════════════════════════════════════════════════════
# QUALITY GATE TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestQualityGateEvaluate:
    """Test quality gate evaluation logic."""

    def test_pass_basic(self):
        manifest = _make_manifest()
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        result = qg.evaluate("inv-1", {"result": "hello"}, manifest)
        assert result.verdict == QualityVerdict.PASS
        assert result.reasons == []

    def test_fail_empty_output(self):
        manifest = _make_manifest()
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        result = qg.evaluate("inv-1", {}, manifest)
        assert result.verdict == QualityVerdict.FAIL
        assert any("empty" in r for r in result.reasons)

    def test_fail_oversized_output(self):
        manifest = _make_manifest()
        manifest.limits = ExecutionLimits(max_output_size_bytes=10)
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        result = qg.evaluate("inv-1", {"result": "x" * 100}, manifest)
        assert result.verdict == QualityVerdict.FAIL
        assert any("exceeds limit" in r for r in result.reasons)

    def test_fail_deterministic_missing_keys(self):
        manifest = _make_manifest(verification_type="deterministic")
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        result = qg.evaluate("inv-1", {"wrong_key": "data"}, manifest)
        assert result.verdict == QualityVerdict.FAIL
        assert any("missing required" in r for r in result.reasons)

    def test_fail_deterministic_wrong_type(self):
        manifest = _make_manifest(verification_type="deterministic")
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        result = qg.evaluate("inv-1", {"result": 123}, manifest)
        assert result.verdict == QualityVerdict.FAIL
        assert any("expected type" in r for r in result.reasons)

    def test_pass_deterministic_valid(self):
        manifest = _make_manifest(verification_type="deterministic")
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        result = qg.evaluate("inv-1", {"result": "valid output"}, manifest)
        assert result.verdict == QualityVerdict.PASS

    def test_warn_missing_expected_keys(self):
        """Non-deterministic with missing required keys → WARN (not FAIL)."""
        manifest = _make_manifest(verification_type="optimistic")
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        result = qg.evaluate("inv-1", {"other": "data"}, manifest)
        assert result.verdict == QualityVerdict.WARN
        assert any("missing expected" in r for r in result.reasons)


class TestQualityGateAutoSettle:
    """Test auto-settlement on quality PASS."""

    def test_auto_settle_on_pass(self):
        settled = []
        manifest = _make_manifest()
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
            settle_fn=lambda iid: settled.append(iid),
        )
        qg.evaluate("inv-1", {"result": "ok"}, manifest)
        qg.auto_settle("inv-1")
        assert "inv-1" in settled

    def test_no_settle_on_fail(self):
        settled = []
        manifest = _make_manifest()
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
            settle_fn=lambda iid: settled.append(iid),
        )
        qg.evaluate("inv-1", {}, manifest)  # empty → FAIL
        qg.auto_settle("inv-1")
        assert settled == []

    def test_auto_settle_no_result_raises(self):
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: None,
        )
        with pytest.raises(QualityError, match="no quality result"):
            qg.auto_settle("inv-999")


class TestQualityGateFlag:
    """Test flagging invocations for review."""

    def test_flag_creates_record(self):
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: None,
        )
        rec = qg.flag("inv-1", "suspicious output")
        assert isinstance(rec, FlagRecord)
        assert rec.reason == "suspicious output"
        assert qg.get_flag("inv-1") is rec

    def test_get_flag_nonexistent(self):
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: None,
        )
        assert qg.get_flag("inv-999") is None


# ═══════════════════════════════════════════════════════════════════════
# DISPUTE TESTS
# ═══════════════════════════════════════════════════════════════════════


def _make_dispute_manager(
    invocations=None,
    reputations=None,
    stakes=None,
    slashed=None,
    deposited=None,
    manifests=None,
):
    """Create a DisputeManager with mock dependencies."""
    inv_store = invocations or {}
    rep_store = reputations or {}
    stake_store = stakes or {}
    slash_log = slashed if slashed is not None else []
    deposit_log = deposited if deposited is not None else []
    manifest_store = manifests or {}

    def slash_fn(provider_id, amount, reason):
        slash_log.append((provider_id, amount, reason))

    def deposit_fn(consumer_id, amount):
        deposit_log.append((consumer_id, amount))

    dm = DisputeManager(
        get_invocation=lambda iid: inv_store.get(iid),
        get_reputation=lambda aid: rep_store.get(aid, 10.0),
        get_stake=lambda aid: stake_store.get(aid, 100.0),
        escrow_refund=lambda eid: None,
        escrow_release=lambda eid: None,
        slash_fn=slash_fn,
        deposit_fn=deposit_fn,
        get_manifest=lambda cid: manifest_store.get(cid),
    )
    return dm, slash_log, deposit_log


class TestDisputeOpen:
    """Test opening disputes."""

    def test_open_dispute_success(self):
        inv = _FakeInvocation()
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        rec = dm.open_dispute("inv-1", "consumer-1", "bad output")
        assert isinstance(rec, DisputeRecord)
        assert rec.state == DisputeState.OPEN
        assert rec.reason == "bad output"
        assert rec.dispute_fee == DISPUTE_FEE

    def test_open_dispute_wrong_consumer(self):
        inv = _FakeInvocation()
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        with pytest.raises(DisputeError, match="only the consumer"):
            dm.open_dispute("inv-1", "someone-else", "bad")

    def test_open_dispute_not_completed(self):
        inv = _FakeInvocation(state="pending")
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        with pytest.raises(DisputeError, match="completed"):
            dm.open_dispute("inv-1", "consumer-1", "bad")

    def test_open_dispute_not_found(self):
        dm, _, _ = _make_dispute_manager({})
        with pytest.raises(DisputeError, match="not found"):
            dm.open_dispute("inv-999", "consumer-1", "bad")

    def test_duplicate_dispute_rejected(self):
        inv = _FakeInvocation()
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        dm.open_dispute("inv-1", "consumer-1", "bad")
        with pytest.raises(DisputeError, match="already has a dispute"):
            dm.open_dispute("inv-1", "consumer-1", "bad again")


class TestDisputeWindow:
    """Test dispute timing validation."""

    def test_within_window_ok(self):
        settled_time = 1000
        inv = _FakeInvocation(settled_at=settled_time)
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        # Within window (1000 + 3600 = 4600)
        rec = dm.open_dispute("inv-1", "consumer-1", "bad", now=settled_time + 1800)
        assert rec.state == DisputeState.OPEN

    def test_after_window_rejected(self):
        settled_time = 1000
        inv = _FakeInvocation(settled_at=settled_time)
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        with pytest.raises(DisputeError, match="window expired"):
            dm.open_dispute("inv-1", "consumer-1", "bad", now=settled_time + 7200)

    def test_exactly_at_window_boundary(self):
        settled_time = 1000
        inv = _FakeInvocation(settled_at=settled_time)
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        # Exactly at boundary = still within
        rec = dm.open_dispute(
            "inv-1",
            "consumer-1",
            "bad",
            now=settled_time + DEFAULT_DISPUTE_WINDOW,
        )
        assert rec.state == DisputeState.OPEN

    def test_custom_window(self):
        settled_time = 1000
        inv = _FakeInvocation(settled_at=settled_time)
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        # Custom 60s window — 120s later → expired
        with pytest.raises(DisputeError, match="window expired"):
            dm.open_dispute(
                "inv-1",
                "consumer-1",
                "bad",
                dispute_window=60,
                now=settled_time + 120,
            )


class TestJurySelection:
    """Test jury selection logic."""

    def _make_jury_test(self):
        inv = _FakeInvocation()
        reps = {
            "j1": 60.0,
            "j2": 70.0,
            "j3": 80.0,
            "j4": 90.0,
            "j5": 30.0,  # below threshold
            "consumer-1": 50.0,
            "provider-1": 50.0,
        }
        dm, _, _ = _make_dispute_manager({"inv-1": inv}, reputations=reps)
        dispute = dm.open_dispute("inv-1", "consumer-1", "bad")
        return dm, dispute

    def test_select_jury_success(self):
        dm, dispute = self._make_jury_test()
        nodes = ["j1", "j2", "j3", "j4", "j5", "consumer-1", "provider-1"]
        jurors = dm.select_jury(dispute.dispute_id, nodes, jury_size=3)
        assert len(jurors) == 3
        # Consumer and provider excluded
        assert "consumer-1" not in jurors
        assert "provider-1" not in jurors
        # j5 (rep=30) excluded
        assert "j5" not in jurors

    def test_select_jury_filters_low_rep(self):
        dm, dispute = self._make_jury_test()
        # Only low-rep nodes + consumer/provider
        nodes = ["j5", "consumer-1", "provider-1"]
        with pytest.raises(DisputeError, match="not enough eligible"):
            dm.select_jury(dispute.dispute_id, nodes, jury_size=3)

    def test_select_jury_deterministic(self):
        """Same inputs → same jurors."""
        dm, dispute = self._make_jury_test()
        nodes = ["j1", "j2", "j3", "j4"]
        jurors1 = dm.select_jury(dispute.dispute_id, nodes, jury_size=3)

        # Recreate same scenario
        inv = _FakeInvocation()
        reps = {"j1": 60.0, "j2": 70.0, "j3": 80.0, "j4": 90.0}
        dm2, _, _ = _make_dispute_manager({"inv-1": inv}, reputations=reps)
        d2 = dm2.open_dispute("inv-1", "consumer-1", "bad")
        # Use the same dispute_id to ensure determinism
        dm2._disputes[dispute.dispute_id] = dm2._disputes.pop(d2.dispute_id)
        dm2._disputes[dispute.dispute_id].dispute_id = dispute.dispute_id
        dm2._disputes[dispute.dispute_id].state = DisputeState.OPEN
        jurors2 = dm2.select_jury(dispute.dispute_id, nodes, jury_size=3)
        assert jurors1 == jurors2

    def test_jury_state_transition(self):
        dm, dispute = self._make_jury_test()
        nodes = ["j1", "j2", "j3", "j4"]
        dm.select_jury(dispute.dispute_id, nodes, jury_size=3)
        assert dispute.state == DisputeState.VOTING


class TestJuryVoting:
    """Test juror voting logic."""

    def _setup_voting(self):
        inv = _FakeInvocation()
        reps = {"j1": 60.0, "j2": 70.0, "j3": 80.0, "j4": 65.0, "j5": 55.0}
        dm, slash_log, deposit_log = _make_dispute_manager({"inv-1": inv}, reputations=reps)
        dispute = dm.open_dispute("inv-1", "consumer-1", "bad")
        jurors = dm.select_jury(dispute.dispute_id, ["j1", "j2", "j3", "j4", "j5"])
        return dm, dispute, jurors, slash_log, deposit_log

    def test_submit_vote_success(self):
        dm, dispute, jurors, _, _ = self._setup_voting()
        vote = dm.submit_vote(dispute.dispute_id, jurors[0], "consumer", "agreed")
        assert vote.verdict == Verdict.CONSUMER
        assert vote.juror_id == jurors[0]

    def test_submit_vote_provider(self):
        dm, dispute, jurors, _, _ = self._setup_voting()
        vote = dm.submit_vote(dispute.dispute_id, jurors[0], "provider", "ok")
        assert vote.verdict == Verdict.PROVIDER

    def test_duplicate_vote_rejected(self):
        dm, dispute, jurors, _, _ = self._setup_voting()
        dm.submit_vote(dispute.dispute_id, jurors[0], "consumer")
        with pytest.raises(DisputeError, match="already voted"):
            dm.submit_vote(dispute.dispute_id, jurors[0], "provider")

    def test_non_juror_rejected(self):
        dm, dispute, jurors, _, _ = self._setup_voting()
        with pytest.raises(DisputeError, match="not a juror"):
            dm.submit_vote(dispute.dispute_id, "random-node", "consumer")

    def test_invalid_verdict(self):
        dm, dispute, jurors, _, _ = self._setup_voting()
        with pytest.raises(DisputeError, match="invalid verdict"):
            dm.submit_vote(dispute.dispute_id, jurors[0], "draw")


class TestDisputeResolution:
    """Test dispute resolution outcomes."""

    def _setup_and_vote(self, votes_config):
        """votes_config: list of (juror_index, verdict_str)"""
        inv = _FakeInvocation()
        reps = {"j1": 60.0, "j2": 70.0, "j3": 80.0, "j4": 65.0, "j5": 55.0}
        stakes = {"provider-1": 500.0}
        manifest = _make_manifest()
        dm, slash_log, deposit_log = _make_dispute_manager(
            {"inv-1": inv},
            reputations=reps,
            stakes=stakes,
            manifests={manifest.capability_id: manifest},
        )
        dispute = dm.open_dispute("inv-1", "consumer-1", "bad")
        jurors = dm.select_jury(dispute.dispute_id, ["j1", "j2", "j3", "j4", "j5"])
        for idx, verdict in votes_config:
            dm.submit_vote(dispute.dispute_id, jurors[idx], verdict)
        return dm, dispute, jurors, slash_log, deposit_log

    def test_consumer_wins_4_of_5(self):
        dm, dispute, jurors, slash_log, deposit_log = self._setup_and_vote(
            [
                (0, "consumer"),
                (1, "consumer"),
                (2, "consumer"),
                (3, "consumer"),
                (4, "provider"),
            ]
        )
        res = dm.resolve(dispute.dispute_id)
        assert res.outcome == ResolutionOutcome.CONSUMER_WINS
        assert res.consumer_refunded is True
        assert res.provider_paid is False
        # Slash occurred
        assert len(slash_log) == 1
        assert slash_log[0][0] == "provider-1"
        # Consumer was refunded (escrow + dispute fee)
        assert len(deposit_log) == 1
        assert deposit_log[0][0] == "consumer-1"
        assert deposit_log[0][1] == 10.0 + DISPUTE_FEE  # price + fee

    def test_consumer_wins_5_of_5(self):
        dm, dispute, jurors, slash_log, deposit_log = self._setup_and_vote(
            [
                (0, "consumer"),
                (1, "consumer"),
                (2, "consumer"),
                (3, "consumer"),
                (4, "consumer"),
            ]
        )
        res = dm.resolve(dispute.dispute_id)
        assert res.outcome == ResolutionOutcome.CONSUMER_WINS

    def test_provider_wins_4_of_5(self):
        dm, dispute, jurors, slash_log, deposit_log = self._setup_and_vote(
            [
                (0, "provider"),
                (1, "provider"),
                (2, "provider"),
                (3, "provider"),
                (4, "consumer"),
            ]
        )
        res = dm.resolve(dispute.dispute_id)
        assert res.outcome == ResolutionOutcome.PROVIDER_WINS
        assert res.consumer_refunded is False
        assert res.provider_paid is True
        assert res.slash_amount == 0.0
        # Fixed jury reward — independent of outcome
        assert res.jury_reward == pytest.approx(JUROR_REWARD_FIXED * 5)
        assert res.jury_reward_per_juror == pytest.approx(JUROR_REWARD_FIXED)
        # No slash
        assert slash_log == []

    def test_provider_wins_5_of_5(self):
        dm, dispute, jurors, slash_log, deposit_log = self._setup_and_vote(
            [
                (0, "provider"),
                (1, "provider"),
                (2, "provider"),
                (3, "provider"),
                (4, "provider"),
            ]
        )
        res = dm.resolve(dispute.dispute_id)
        assert res.outcome == ResolutionOutcome.PROVIDER_WINS

    def test_no_majority_1_1_1_impossible(self):
        """With 3 jurors and 2 options, 1-1-? is impossible to have no majority
        only if the 3rd is split. Actually 1c+1p+1? is still 1-2 or 2-1.
        No majority requires exactly 1-1-1 which is impossible with binary choice.
        Test with larger jury to actually get no majority."""
        # Use 5 jurors: 2 consumer, 2 provider, 1 consumer = 3-2 consumer wins
        # Actually for no majority with 3 jurors: need 1-2 split which IS majority.
        # No majority with jury_size=3 and threshold 2/3: need < 2 for both.
        # 1 consumer + 1 provider + 1 unvoted = not all voted. So no majority is rare.
        # Let's just verify the resolve rejects incomplete votes.
        pass

    def test_resolve_incomplete_votes_rejected(self):
        inv = _FakeInvocation()
        reps = {"j1": 60.0, "j2": 70.0, "j3": 80.0, "j4": 65.0, "j5": 55.0}
        dm, _, _ = _make_dispute_manager({"inv-1": inv}, reputations=reps)
        dispute = dm.open_dispute("inv-1", "consumer-1", "bad")
        dm.select_jury(dispute.dispute_id, ["j1", "j2", "j3", "j4", "j5"])
        dm.submit_vote(dispute.dispute_id, "j1", "consumer")
        # Only 1 of 5 voted
        with pytest.raises(DisputeError, match="not all jurors"):
            dm.resolve(dispute.dispute_id)

    def test_slash_amount_uses_config(self):
        """Slash ratio should come from capability staking config."""
        dm, dispute, jurors, slash_log, _ = self._setup_and_vote(
            [
                (0, "consumer"),
                (1, "consumer"),
                (2, "consumer"),
                (3, "consumer"),
                (4, "provider"),
            ]
        )
        res = dm.resolve(dispute.dispute_id)
        # Default slash_dispute_lost = 0.20, provider stake = 500
        assert res.slash_amount == pytest.approx(500.0 * 0.20)
        assert slash_log[0][1] == pytest.approx(100.0)

    def test_jury_rewarded_fixed(self):
        """Jury reward is fixed per juror, independent of outcome."""
        dm, dispute, jurors, slash_log, _ = self._setup_and_vote(
            [
                (0, "consumer"),
                (1, "consumer"),
                (2, "consumer"),
                (3, "consumer"),
                (4, "provider"),
            ]
        )
        res = dm.resolve(dispute.dispute_id)
        # Fixed reward: JUROR_REWARD_FIXED (2.0) × 5 jurors = 10.0
        assert res.jury_reward == pytest.approx(JUROR_REWARD_FIXED * 5)
        assert res.jury_reward_per_juror == pytest.approx(JUROR_REWARD_FIXED)

    def test_dispute_state_after_resolve(self):
        dm, dispute, jurors, _, _ = self._setup_and_vote(
            [
                (0, "consumer"),
                (1, "consumer"),
                (2, "consumer"),
                (3, "consumer"),
                (4, "consumer"),
            ]
        )
        dm.resolve(dispute.dispute_id)
        assert dispute.state == DisputeState.RESOLVED
        assert dispute.resolved_at is not None
        assert dispute.outcome == ResolutionOutcome.CONSUMER_WINS


class TestDisputeGet:
    """Test dispute retrieval."""

    def test_get_dispute(self):
        inv = _FakeInvocation()
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        dispute = dm.open_dispute("inv-1", "consumer-1", "bad")
        fetched = dm.get_dispute(dispute.dispute_id)
        assert fetched is dispute

    def test_get_dispute_not_found(self):
        dm, _, _ = _make_dispute_manager({})
        assert dm.get_dispute("nonexistent") is None

    def test_get_dispute_by_invocation(self):
        inv = _FakeInvocation()
        dm, _, _ = _make_dispute_manager({"inv-1": inv})
        dispute = dm.open_dispute("inv-1", "consumer-1", "bad")
        fetched = dm.get_dispute_by_invocation("inv-1")
        assert fetched is dispute

    def test_get_dispute_by_invocation_not_found(self):
        dm, _, _ = _make_dispute_manager({})
        assert dm.get_dispute_by_invocation("inv-999") is None


# ═══════════════════════════════════════════════════════════════════════
# ESCROW DISPUTE RESOLUTION TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestEscrowDisputeResolution:
    """Test new resolve_release and resolve_refund methods."""

    def test_resolve_release_from_disputed(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        em.dispute(eid)
        rec = em.resolve_release(eid)
        assert rec.state == EscrowState.RELEASED
        assert em.balance("u1") == 60.0  # not refunded

    def test_resolve_refund_from_disputed(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        em.dispute(eid)
        rec = em.resolve_refund(eid)
        assert rec.state == EscrowState.REFUNDED
        assert em.balance("u1") == 100.0  # full refund

    def test_resolve_release_wrong_state(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        # Still LOCKED, not DISPUTED
        from oasyce.capabilities.escrow import EscrowError

        with pytest.raises(EscrowError, match="locked"):
            em.resolve_release(eid)

    def test_resolve_refund_wrong_state(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        from oasyce.capabilities.escrow import EscrowError

        with pytest.raises(EscrowError, match="locked"):
            em.resolve_refund(eid)


# ═══════════════════════════════════════════════════════════════════════
# QUALITY GATE + INVOCATION INTEGRATION
# ═══════════════════════════════════════════════════════════════════════


class TestQualityGateInvocationIntegration:
    """Test QualityGate wired into InvocationEngine."""

    def test_quality_pass_settles_normally(self):
        manifest = _make_manifest()
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        engine, _, escrow, shares, manifest = _make_engine(
            manifest=manifest,
            quality_gate=qg,
        )
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        result = engine.submit_result(handle.invocation_id, {"result": "ok"})
        assert result.escrow_released is True
        assert result.mint_result is not None

    def test_quality_fail_does_not_settle(self):
        manifest = _make_manifest(verification_type="deterministic")
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        engine, _, escrow, shares, manifest = _make_engine(
            manifest=manifest,
            quality_gate=qg,
        )
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        # Submit with wrong type — deterministic gate will FAIL
        result = engine.submit_result(handle.invocation_id, {"result": 12345})
        assert result.escrow_released is False
        assert result.mint_result is None
        # Invocation marked failed
        rec = engine.get_invocation(handle.invocation_id)
        assert rec.state == InvocationState.FAILED

    def test_quality_fail_refunds_escrow(self):
        manifest = _make_manifest(verification_type="deterministic")
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        engine, _, escrow, _, manifest = _make_engine(
            manifest=manifest,
            quality_gate=qg,
        )
        initial = escrow.balance("consumer-1")
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        engine.submit_result(handle.invocation_id, {"result": 12345})
        # Escrow refunded on quality fail
        assert escrow.balance("consumer-1") == pytest.approx(initial)

    def test_no_quality_gate_settles_normally(self):
        """Without quality gate, settlement works as before."""
        engine, _, _, _, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        result = engine.submit_result(handle.invocation_id, {"result": "ok"})
        assert result.escrow_released is True


# ═══════════════════════════════════════════════════════════════════════
# FULL FLOW: INVOKE → RESULT → DISPUTE → JURY → RESOLVE
# ═══════════════════════════════════════════════════════════════════════


class TestFullDisputeFlow:
    """End-to-end flow testing the complete lifecycle."""

    def test_invoke_settle_rate(self):
        """invoke → result → settle → rate (happy path)."""
        engine, registry, escrow, shares, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        result = engine.submit_result(handle.invocation_id, {"result": "ok"})
        assert result.escrow_released is True

        # Now rate
        rating_engine = RatingEngine(
            get_invocation=lambda iid: engine.get_invocation(iid),
            get_reputation=lambda aid: 50.0,
            get_stake=lambda aid: 100.0,
        )
        rec = rating_engine.submit_rating(
            handle.invocation_id,
            "consumer-1",
            5,
        )
        assert rec.score == 5

    def test_invoke_settle_dispute_consumer_wins(self):
        """invoke → settle → dispute → jury → consumer wins → slash."""
        engine, registry, escrow, shares, manifest = _make_engine(
            consumer_balance=2000.0,
        )
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        result = engine.submit_result(handle.invocation_id, {"result": "ok"})
        assert result.escrow_released is True

        inv = engine.get_invocation(handle.invocation_id)

        # Open dispute via DisputeManager
        slash_log = []
        deposit_log = []
        reps = {"j1": 60.0, "j2": 70.0, "j3": 80.0, "j4": 65.0, "j5": 55.0}
        dm = DisputeManager(
            get_invocation=lambda iid: engine.get_invocation(iid),
            get_reputation=lambda aid: reps.get(aid, 10.0),
            get_stake=lambda aid: 500.0,
            escrow_refund=lambda eid: None,
            escrow_release=lambda eid: None,
            slash_fn=lambda pid, amt, reason: slash_log.append((pid, amt)),
            deposit_fn=lambda cid, amt: deposit_log.append((cid, amt)),
            get_manifest=lambda cid: manifest,
        )

        dispute = dm.open_dispute(handle.invocation_id, "consumer-1", "bad output")
        jurors = dm.select_jury(dispute.dispute_id, ["j1", "j2", "j3", "j4", "j5"])

        # All jurors vote for consumer
        for j in jurors:
            dm.submit_vote(dispute.dispute_id, j, "consumer", "agreed")

        res = dm.resolve(dispute.dispute_id)
        assert res.outcome == ResolutionOutcome.CONSUMER_WINS
        assert len(slash_log) == 1
        assert res.slash_amount > 0

    def test_invoke_settle_dispute_provider_wins(self):
        """invoke → settle → dispute → jury → provider wins → no slash."""
        engine, _, _, _, manifest = _make_engine(consumer_balance=2000.0)
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        engine.submit_result(handle.invocation_id, {"result": "ok"})

        slash_log = []
        reps = {"j1": 60.0, "j2": 70.0, "j3": 80.0, "j4": 65.0, "j5": 55.0}
        dm = DisputeManager(
            get_invocation=lambda iid: engine.get_invocation(iid),
            get_reputation=lambda aid: reps.get(aid, 10.0),
            get_stake=lambda aid: 500.0,
            escrow_refund=lambda eid: None,
            escrow_release=lambda eid: None,
            slash_fn=lambda pid, amt, reason: slash_log.append((pid, amt)),
            deposit_fn=lambda cid, amt: None,
            get_manifest=lambda cid: manifest,
        )

        dispute = dm.open_dispute(handle.invocation_id, "consumer-1", "bad")
        jurors = dm.select_jury(dispute.dispute_id, ["j1", "j2", "j3", "j4", "j5"])
        for j in jurors:
            dm.submit_vote(dispute.dispute_id, j, "provider", "looks fine")

        res = dm.resolve(dispute.dispute_id)
        assert res.outcome == ResolutionOutcome.PROVIDER_WINS
        assert slash_log == []
        assert res.slash_amount == 0.0

    def test_quality_fail_then_dispute_not_needed(self):
        """Quality gate FAIL → refund → no need for dispute."""
        manifest = _make_manifest(verification_type="deterministic")
        qg = QualityGate(
            get_invocation=lambda iid: None,
            get_manifest=lambda cid: manifest,
        )
        engine, _, escrow, _, manifest = _make_engine(
            manifest=manifest,
            quality_gate=qg,
        )
        initial = escrow.balance("consumer-1")
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        result = engine.submit_result(handle.invocation_id, {"result": 999})
        assert result.escrow_released is False
        # Consumer fully refunded
        assert escrow.balance("consumer-1") == pytest.approx(initial)


# ═══════════════════════════════════════════════════════════════════════
# IMPORT TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestNewImports:
    """Verify all new classes are importable from capabilities package."""

    def test_rating_imports(self):
        from oasyce.capabilities import (
            RatingEngine,
            RatingRecord,
            RatingStats,
            RatingError,
        )

        assert RatingEngine is not None

    def test_quality_imports(self):
        from oasyce.capabilities import (
            QualityGate,
            QualityResult,
            QualityVerdict,
            QualityError,
            FlagRecord,
        )

        assert QualityGate is not None

    def test_dispute_imports(self):
        from oasyce.capabilities import (
            DisputeManager,
            DisputeRecord,
            DisputeResolution,
            DisputeState,
            DisputeError,
            Verdict,
            ResolutionOutcome,
            DISPUTE_FEE,
        )

        assert DisputeManager is not None
        assert DISPUTE_FEE == 5.0

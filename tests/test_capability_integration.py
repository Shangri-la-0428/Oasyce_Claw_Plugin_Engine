"""Integration tests for capability assets — full lifecycle end-to-end.

These tests wire up real components (registry + escrow + shares + invocation
engine + quality gate + dispute + rating) and verify complete flows.
"""

from __future__ import annotations

import pytest

from oasyce.capabilities.manifest import (
    CapabilityManifest,
    PricingConfig,
    StakingConfig,
    QualityPolicy,
    ExecutionLimits,
)
from oasyce.capabilities.registry import CapabilityRegistry
from oasyce.capabilities.escrow import EscrowManager
from oasyce.capabilities.shares import ShareLedger
from oasyce.capabilities.invocation import (
    CapabilityInvocationEngine,
    InvocationError,
    InvocationState,
)
from oasyce.capabilities.quality import QualityGate, QualityVerdict
from oasyce.capabilities.rating import RatingEngine
from oasyce.capabilities.dispute import (
    DisputeManager,
    Verdict,
    ResolutionOutcome,
)
from oasyce.capabilities._pricing_shim import FeeSplitter


# ── Helpers ───────────────────────────────────────────────────────────

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["summary"],
}


def _make_manifest(
    provider: str = "provider_alice",
    name: str = "summarize",
    version: str = "1.0.0",
    tags: list = None,
    verification_type: str = "optimistic",
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        version=version,
        provider=provider,
        description=f"{name} v{version} by {provider}",
        tags=tags or ["nlp", "summarize"],
        input_schema=INPUT_SCHEMA,
        output_schema=OUTPUT_SCHEMA,
        pricing=PricingConfig(base_price=1.0, reserve_ratio=0.35),
        staking=StakingConfig(min_bond=100.0),
        quality=QualityPolicy(verification_type=verification_type),
        limits=ExecutionLimits(timeout_seconds=60),
    )


GOOD_INPUT = {"text": "The quick brown fox jumps over the lazy dog."}
GOOD_OUTPUT = {"summary": "A fox jumped over a dog.", "confidence": 0.95}
BAD_OUTPUT_EMPTY = {}
BAD_OUTPUT_MISSING_KEY = {"confidence": 0.5}


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def stack():
    """Wire up the full capability stack with real components."""
    registry = CapabilityRegistry()
    escrow = EscrowManager()
    shares = ShareLedger(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.35)
    fee_splitter = FeeSplitter()

    engine = CapabilityInvocationEngine(
        registry=registry,
        escrow=escrow,
        shares=shares,
        fee_splitter=fee_splitter,
    )

    # Reputation/stake lookups for rating and dispute
    _reputations = {"consumer_bob": 60.0, "consumer_carol": 70.0, "provider_alice": 80.0}
    _stakes = {"consumer_bob": 1000.0, "consumer_carol": 500.0, "provider_alice": 5000.0}

    rating = RatingEngine(
        get_invocation=engine.get_invocation,
        get_reputation=lambda agent_id: _reputations.get(agent_id, 50.0),
        get_stake=lambda agent_id: _stakes.get(agent_id, 100.0),
    )

    dispute = DisputeManager(
        get_invocation=engine.get_invocation,
        get_reputation=lambda agent_id: _reputations.get(agent_id, 50.0),
        get_stake=lambda agent_id: _stakes.get(agent_id, 100.0),
        escrow_refund=escrow.resolve_refund,
        escrow_release=escrow.resolve_release,
    )

    return {
        "registry": registry,
        "escrow": escrow,
        "shares": shares,
        "engine": engine,
        "rating": rating,
        "dispute": dispute,
        "reputations": _reputations,
        "stakes": _stakes,
    }


@pytest.fixture
def registered_stack(stack):
    """Stack with one capability already registered and consumer funded."""
    manifest = _make_manifest()
    cap_id = stack["registry"].register(manifest)
    stack["escrow"].deposit("consumer_bob", 500.0)
    stack["cap_id"] = cap_id
    stack["manifest"] = manifest
    return stack


# ── 1. Happy Path ─────────────────────────────────────────────────────


class TestHappyPath:
    """Register → deposit → invoke → submit result → settlement complete."""

    def test_full_lifecycle(self, registered_stack):
        s = registered_stack
        cap_id = s["cap_id"]

        # Invoke
        handle = s["engine"].invoke("consumer_bob", cap_id, GOOD_INPUT, max_price=50.0)
        assert handle.consumer_id == "consumer_bob"
        assert handle.provider_id == "provider_alice"
        assert handle.price > 0

        # Consumer balance reduced by escrow
        assert s["escrow"].balance("consumer_bob") < 500.0

        # Submit result
        result = s["engine"].submit_result(handle.invocation_id, GOOD_OUTPUT)
        assert result.escrow_released is True
        assert result.protocol_fee > 0
        assert result.burn_amount > 0
        assert result.net_to_curve > 0
        assert result.mint_result is not None
        assert result.mint_result.shares_minted > 0
        assert result.fee_split is not None

        # Consumer now holds shares
        shares_held = s["shares"].balance(cap_id, "consumer_bob")
        assert shares_held > 0

        # Invocation state is COMPLETED
        record = s["engine"].get_invocation(handle.invocation_id)
        assert record.state == InvocationState.COMPLETED

    def test_settlement_fees_add_up(self, registered_stack):
        s = registered_stack
        handle = s["engine"].invoke("consumer_bob", s["cap_id"], GOOD_INPUT, max_price=50.0)
        result = s["engine"].submit_result(handle.invocation_id, GOOD_OUTPUT)

        # protocol_fee = 5% of price
        assert result.protocol_fee == pytest.approx(handle.price * 0.05, rel=1e-6)
        # burn + verifier = protocol_fee
        assert result.burn_amount + result.verifier_amount == pytest.approx(
            result.protocol_fee, rel=1e-6
        )
        # net_to_curve = price - protocol_fee
        assert result.net_to_curve == pytest.approx(handle.price - result.protocol_fee, rel=1e-6)

    def test_rating_after_settlement(self, registered_stack):
        s = registered_stack
        handle = s["engine"].invoke("consumer_bob", s["cap_id"], GOOD_INPUT, max_price=50.0)
        s["engine"].submit_result(handle.invocation_id, GOOD_OUTPUT)

        # Rate the invocation
        rating_rec = s["rating"].submit_rating(handle.invocation_id, "consumer_bob", 5)
        assert rating_rec.score == 5
        assert rating_rec.weight > 0  # reputation * stake

        # Provider rating stats
        stats = s["rating"].get_provider_score("provider_alice")
        assert stats is not None
        assert stats.count == 1
        assert stats.raw_average == 5.0


# ── 2. Failure Path ───────────────────────────────────────────────────


class TestFailurePath:
    """Invoke → provider fails → escrow refunded, no shares."""

    def test_provider_timeout_refund(self, registered_stack):
        s = registered_stack
        balance_before = s["escrow"].balance("consumer_bob")
        handle = s["engine"].invoke("consumer_bob", s["cap_id"], GOOD_INPUT, max_price=50.0)

        # Balance reduced during escrow
        balance_during = s["escrow"].balance("consumer_bob")
        assert balance_during < balance_before

        # Provider fails
        ok = s["engine"].fail(handle.invocation_id, "timeout", "provider did not respond")
        assert ok is True

        # Escrow refunded — balance restored
        balance_after = s["escrow"].balance("consumer_bob")
        assert balance_after == pytest.approx(balance_before, rel=1e-6)

        # No shares minted
        shares = s["shares"].balance(s["cap_id"], "consumer_bob")
        assert shares == 0.0

        # State is FAILED
        record = s["engine"].get_invocation(handle.invocation_id)
        assert record.state == InvocationState.FAILED

    def test_invalid_input_rejected(self, registered_stack):
        s = registered_stack
        with pytest.raises(InvocationError, match="missing required keys"):
            s["engine"].invoke("consumer_bob", s["cap_id"], {"wrong_key": "value"}, max_price=50.0)

    def test_price_exceeded(self, registered_stack):
        s = registered_stack
        with pytest.raises(InvocationError, match="exceeds max_price"):
            s["engine"].invoke("consumer_bob", s["cap_id"], GOOD_INPUT, max_price=0.0001)

    def test_insufficient_balance(self, stack):
        """Consumer has no funds deposited."""
        manifest = _make_manifest()
        cap_id = stack["registry"].register(manifest)
        # No deposit for consumer
        with pytest.raises(InvocationError, match="insufficient balance"):
            stack["engine"].invoke("consumer_broke", cap_id, GOOD_INPUT, max_price=50.0)

    def test_capability_not_found(self, registered_stack):
        s = registered_stack
        with pytest.raises(InvocationError, match="capability not found"):
            s["engine"].invoke("consumer_bob", "nonexistent_id", GOOD_INPUT, max_price=50.0)

    def test_paused_capability_rejected(self, registered_stack):
        s = registered_stack
        s["registry"].update_status(s["cap_id"], "paused")
        with pytest.raises(InvocationError, match="paused"):
            s["engine"].invoke("consumer_bob", s["cap_id"], GOOD_INPUT, max_price=50.0)


# ── 3. Dispute Path ──────────────────────────────────────────────────


class TestDisputePath:
    """Invoke → submit result → dispute → jury votes → resolution."""

    def _invoke_and_complete(self, s):
        """Helper: invoke and submit result (completed). Returns handle."""
        handle = s["engine"].invoke("consumer_bob", s["cap_id"], GOOD_INPUT, max_price=50.0)
        s["engine"].submit_result(handle.invocation_id, GOOD_OUTPUT)
        return handle

    def test_consumer_wins_dispute(self, registered_stack):
        s = registered_stack
        handle = self._invoke_and_complete(s)

        # Open dispute in dispute manager (invocation is now COMPLETED)
        dispute_rec = s["dispute"].open_dispute(
            handle.invocation_id, "consumer_bob", "output is garbage"
        )

        # Select jury from eligible nodes
        eligible = ["juror_1", "juror_2", "juror_3"]
        s["dispute"].select_jury(dispute_rec.dispute_id, eligible)

        # All jurors vote for consumer
        dispute_state = s["dispute"].get_dispute(dispute_rec.dispute_id)
        for juror_id in dispute_state.juror_ids:
            s["dispute"].submit_vote(
                dispute_rec.dispute_id, juror_id, Verdict.CONSUMER, "bad output"
            )

        # Resolve
        resolution = s["dispute"].resolve(dispute_rec.dispute_id)
        assert resolution.outcome == ResolutionOutcome.CONSUMER_WINS

    def test_provider_wins_dispute(self, registered_stack):
        s = registered_stack
        handle = self._invoke_and_complete(s)

        dispute_rec = s["dispute"].open_dispute(
            handle.invocation_id, "consumer_bob", "I don't like it"
        )
        eligible = ["juror_1", "juror_2", "juror_3"]
        s["dispute"].select_jury(dispute_rec.dispute_id, eligible)

        # All jurors vote for provider
        dispute_state = s["dispute"].get_dispute(dispute_rec.dispute_id)
        for juror_id in dispute_state.juror_ids:
            s["dispute"].submit_vote(
                dispute_rec.dispute_id, juror_id, Verdict.PROVIDER, "output is fine"
            )

        resolution = s["dispute"].resolve(dispute_rec.dispute_id)
        assert resolution.outcome == ResolutionOutcome.PROVIDER_WINS


# ── 4. Diminishing Returns ───────────────────────────────────────────


class TestDiminishingReturns:
    """Same consumer invokes 4 times → shares decrease per tier."""

    def test_four_calls_diminishing(self, registered_stack):
        s = registered_stack
        cap_id = s["cap_id"]
        s["escrow"].deposit("consumer_bob", 5000.0)  # extra funds

        shares_per_call = []
        for i in range(4):
            handle = s["engine"].invoke("consumer_bob", cap_id, GOOD_INPUT, max_price=50.0)
            result = s["engine"].submit_result(handle.invocation_id, GOOD_OUTPUT)
            shares_per_call.append(result.mint_result.shares_minted)

        # Each call should mint fewer shares
        assert shares_per_call[0] > shares_per_call[1] > shares_per_call[2] > shares_per_call[3]

        # Verify tiers
        assert result.mint_result.diminishing_tier == 3
        assert result.mint_result.diminishing_multiplier == 0.4

    def test_different_consumers_no_diminishing(self, registered_stack):
        s = registered_stack
        cap_id = s["cap_id"]
        s["escrow"].deposit("consumer_carol", 500.0)

        # Bob's first call
        h1 = s["engine"].invoke("consumer_bob", cap_id, GOOD_INPUT, max_price=50.0)
        r1 = s["engine"].submit_result(h1.invocation_id, GOOD_OUTPUT)

        # Carol's first call — should get same tier (100%) as Bob's first
        h2 = s["engine"].invoke("consumer_carol", cap_id, GOOD_INPUT, max_price=50.0)
        r2 = s["engine"].submit_result(h2.invocation_id, GOOD_OUTPUT)

        assert r1.mint_result.diminishing_multiplier == 1.0
        assert r2.mint_result.diminishing_multiplier == 1.0


# ── 5. Share Trading ─────────────────────────────────────────────────


class TestShareTrading:
    """Consumer invokes → gets shares → second consumer invokes → first burns for profit."""

    def test_early_investor_profits(self, registered_stack):
        s = registered_stack
        cap_id = s["cap_id"]
        s["escrow"].deposit("consumer_carol", 500.0)

        # Bob invokes first
        h1 = s["engine"].invoke("consumer_bob", cap_id, GOOD_INPUT, max_price=50.0)
        r1 = s["engine"].submit_result(h1.invocation_id, GOOD_OUTPUT)
        bob_shares = r1.mint_result.shares_minted

        # Pool reserve increased
        reserve_after_bob = s["shares"].pool_reserve(cap_id)

        # Carol invokes (pushes curve up)
        h2 = s["engine"].invoke("consumer_carol", cap_id, GOOD_INPUT, max_price=50.0)
        r2 = s["engine"].submit_result(h2.invocation_id, GOOD_OUTPUT)

        reserve_after_carol = s["shares"].pool_reserve(cap_id)
        assert reserve_after_carol > reserve_after_bob

        # Bob burns his shares — should get more OAS than he put in (via curve)
        burn_result = s["shares"].burn(cap_id, "consumer_bob", bob_shares)
        assert burn_result.oas_returned > 0
        # The returned OAS should be > what went into curve for Bob's call
        # (because Carol's call added to the reserve)
        assert burn_result.oas_returned > r1.net_to_curve


# ── 6. Quality Gate Fail ─────────────────────────────────────────────


class TestQualityGateFail:
    """Quality gate rejects bad output → escrow refunded."""

    @pytest.fixture
    def stack_with_quality(self, stack):
        """Stack with QualityGate wired into the invocation engine."""
        manifest = _make_manifest(verification_type="deterministic")
        cap_id = stack["registry"].register(manifest)
        stack["escrow"].deposit("consumer_bob", 500.0)
        stack["cap_id"] = cap_id

        # Create quality gate
        qg = QualityGate(
            get_invocation=stack["engine"].get_invocation,
            get_manifest=stack["registry"].get,
        )

        # Rebuild engine with quality gate
        engine = CapabilityInvocationEngine(
            registry=stack["registry"],
            escrow=stack["escrow"],
            shares=stack["shares"],
            quality_gate=qg,
        )
        stack["engine"] = engine
        stack["quality"] = qg
        return stack

    def test_empty_output_rejected(self, stack_with_quality):
        s = stack_with_quality
        balance_before = s["escrow"].balance("consumer_bob")

        handle = s["engine"].invoke("consumer_bob", s["cap_id"], GOOD_INPUT, max_price=50.0)

        # Empty output fails schema validation (missing required 'summary')
        with pytest.raises(InvocationError, match="missing required keys"):
            s["engine"].submit_result(handle.invocation_id, BAD_OUTPUT_EMPTY)

        # Invocation still pending — consumer can get refund via fail()
        s["engine"].fail(handle.invocation_id, "invalid_output", "empty output")
        balance_after = s["escrow"].balance("consumer_bob")
        assert balance_after == pytest.approx(balance_before, rel=1e-6)

    def test_missing_required_key_rejected(self, stack_with_quality):
        s = stack_with_quality
        handle = s["engine"].invoke("consumer_bob", s["cap_id"], GOOD_INPUT, max_price=50.0)

        # Missing 'summary' key triggers schema validation error
        with pytest.raises(InvocationError, match="missing required keys"):
            s["engine"].submit_result(handle.invocation_id, BAD_OUTPUT_MISSING_KEY)


# ── 7. Multi-Provider Discovery ──────────────────────────────────────


class TestMultiProviderDiscovery:
    """Register 3 capabilities → search by tags → verify ranking."""

    def test_tag_search_ranking(self, stack):
        r = stack["registry"]

        # Three providers with different tags
        m1 = _make_manifest(provider="p1", name="translate", tags=["nlp", "translate", "language"])
        m2 = _make_manifest(provider="p2", name="summarize", tags=["nlp", "summarize"])
        m3 = _make_manifest(provider="p3", name="image-gen", tags=["vision", "generation"])

        r.register(m1)
        r.register(m2)
        r.register(m3)

        # Search for NLP tasks
        results = r.search(query_tags=["nlp", "summarize"])
        assert len(results) >= 2

        # Summarize provider should rank higher (more tag overlap)
        top_manifest, top_score = results[0]
        assert "summarize" in top_manifest.tags

    def test_deprecated_excluded(self, stack):
        r = stack["registry"]
        m1 = _make_manifest(provider="p1", name="old-tool", tags=["nlp"])
        cap_id = r.register(m1)
        r.update_status(cap_id, "deprecated")

        results = r.search(query_tags=["nlp"])
        cap_ids = [m.capability_id for m, _ in results]
        assert cap_id not in cap_ids

    def test_list_by_provider(self, stack):
        r = stack["registry"]
        r.register(_make_manifest(provider="p1", name="a", version="1.0.0"))
        r.register(_make_manifest(provider="p1", name="b", version="1.0.0"))
        r.register(_make_manifest(provider="p2", name="c", version="1.0.0"))

        p1_caps = r.list_by_provider("p1")
        assert len(p1_caps) == 2
        assert all(m.provider == "p1" for m in p1_caps)

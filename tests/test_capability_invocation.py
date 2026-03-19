"""Comprehensive tests for Step 2: Invocation + Escrow + Share Minting.

Covers:
    - Escrow: lock, release, refund, dispute, state transitions
    - Shares: mint, burn, balance, diminishing returns, pool state
    - Pricing: bonding curve integration, diminishing returns tiers, protocol fee
    - Invocation: full lifecycle (invoke→result→settle), failure, dispute
    - AHRP extensions: new message types, TxState.ESCROWED, payload dataclasses
    - Network message: new MessageType literals
"""

from __future__ import annotations

import pytest

from oasyce.capabilities.escrow import (
    EscrowManager,
    EscrowError,
    EscrowState,
)
from oasyce.capabilities.shares import (
    ShareLedger,
    ShareLedgerError,
    MintResult,
    BurnResult,
)
from oasyce.capabilities.pricing import (
    CapabilityPricing,
    QuoteResult,
)
from oasyce.capabilities.invocation import (
    CapabilityInvocationEngine,
    InvocationError,
    InvocationState,
    InvocationHandle,
    SettlementResult,
    DisputeHandle,
)
from oasyce.capabilities.manifest import (
    CapabilityManifest,
    PricingConfig,
)
from oasyce.capabilities.registry import CapabilityRegistry
from oasyce.capabilities._pricing_shim import FeeSplitter
from oasyce.capabilities._pricing_shim import BancorCurve
from oasyce.ahrp import (
    MessageType as AhrpMessageType,
    TxState,
    Transaction,
    CapabilityQueryPayload,
    CapabilityInvokePayload,
    CapabilityResultPayload,
    CapabilityFailPayload,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_manifest(
    name: str = "test-cap",
    provider: str = "provider-abc",
    version: str = "1.0.0",
    reserve_ratio: float = 0.35,
) -> CapabilityManifest:
    """Helper to create a valid CapabilityManifest."""
    return CapabilityManifest(
        name=name,
        description="A test capability",
        version=version,
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
        pricing=PricingConfig(reserve_ratio=reserve_ratio),
    )


def _make_engine(
    manifest: CapabilityManifest = None,
    consumer_balance: float = 1000.0,
    consumer_id: str = "consumer-1",
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

    engine = CapabilityInvocationEngine(registry, escrow, shares, splitter)
    return engine, registry, escrow, shares, manifest


# ═══════════════════════════════════════════════════════════════════════
# ESCROW TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestEscrowDeposit:
    def test_deposit_increases_balance(self):
        em = EscrowManager()
        assert em.balance("u1") == 0.0
        em.deposit("u1", 100.0)
        assert em.balance("u1") == 100.0

    def test_deposit_multiple(self):
        em = EscrowManager()
        em.deposit("u1", 50.0)
        em.deposit("u1", 30.0)
        assert em.balance("u1") == 80.0

    def test_deposit_negative_raises(self):
        em = EscrowManager()
        with pytest.raises(EscrowError, match="positive"):
            em.deposit("u1", -10)

    def test_deposit_zero_raises(self):
        em = EscrowManager()
        with pytest.raises(EscrowError, match="positive"):
            em.deposit("u1", 0)


class TestEscrowLock:
    def test_lock_deducts_balance(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        assert em.balance("u1") == 60.0
        rec = em.get(eid)
        assert rec is not None
        assert rec.amount == 40.0
        assert rec.state == EscrowState.LOCKED

    def test_lock_insufficient_balance(self):
        em = EscrowManager()
        em.deposit("u1", 10.0)
        with pytest.raises(EscrowError, match="insufficient"):
            em.lock("u1", 50.0, "inv-1")

    def test_lock_no_balance(self):
        em = EscrowManager()
        with pytest.raises(EscrowError, match="insufficient"):
            em.lock("u1", 1.0, "inv-1")

    def test_lock_zero_raises(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        with pytest.raises(EscrowError, match="positive"):
            em.lock("u1", 0, "inv-1")


class TestEscrowRelease:
    def test_release_changes_state(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        rec = em.release(eid)
        assert rec.state == EscrowState.RELEASED
        assert rec.resolved_at is not None

    def test_release_does_not_refund(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        em.release(eid)
        assert em.balance("u1") == 60.0  # not 100

    def test_double_release_raises(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        em.release(eid)
        with pytest.raises(EscrowError, match="released"):
            em.release(eid)


class TestEscrowRefund:
    def test_refund_returns_funds(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        assert em.balance("u1") == 60.0
        rec = em.refund(eid)
        assert rec.state == EscrowState.REFUNDED
        assert em.balance("u1") == 100.0

    def test_refund_after_release_raises(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        em.release(eid)
        with pytest.raises(EscrowError):
            em.refund(eid)


class TestEscrowDispute:
    def test_dispute_marks_state(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        rec = em.dispute(eid)
        assert rec.state == EscrowState.DISPUTED
        # Balance stays deducted
        assert em.balance("u1") == 60.0

    def test_dispute_not_found(self):
        em = EscrowManager()
        with pytest.raises(EscrowError, match="not found"):
            em.dispute("nonexistent")


class TestEscrowGet:
    def test_get_existing(self):
        em = EscrowManager()
        em.deposit("u1", 100.0)
        eid = em.lock("u1", 40.0, "inv-1")
        rec = em.get(eid)
        assert rec is not None
        assert rec.consumer_id == "u1"

    def test_get_nonexistent(self):
        em = EscrowManager()
        assert em.get("nope") is None


# ═══════════════════════════════════════════════════════════════════════
# SHARES TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestShareMint:
    def test_mint_basic(self):
        sl = ShareLedger(reserve_ratio=0.35)
        result = sl.mint("cap1", "user1", 10.0)
        assert isinstance(result, MintResult)
        assert result.shares_minted > 0
        assert result.diminishing_tier == 0
        assert result.diminishing_multiplier == 1.0

    def test_mint_increases_balance(self):
        sl = ShareLedger(reserve_ratio=0.35)
        result = sl.mint("cap1", "user1", 10.0)
        assert sl.balance("cap1", "user1") == result.shares_minted

    def test_mint_updates_pool(self):
        sl = ShareLedger(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.35)
        sl.mint("cap1", "user1", 10.0)
        assert sl.pool_reserve("cap1") == 110.0
        assert sl.total_supply("cap1") > 100.0

    def test_mint_zero_raises(self):
        sl = ShareLedger()
        with pytest.raises(ShareLedgerError, match="positive"):
            sl.mint("cap1", "user1", 0.0)

    def test_mint_negative_raises(self):
        sl = ShareLedger()
        with pytest.raises(ShareLedgerError, match="positive"):
            sl.mint("cap1", "user1", -5.0)


class TestShareDiminishingReturns:
    def test_first_call_100pct(self):
        sl = ShareLedger(reserve_ratio=0.5)
        r = sl.mint("cap1", "user1", 10.0)
        assert r.diminishing_multiplier == 1.0
        assert r.diminishing_tier == 0

    def test_second_call_80pct(self):
        sl = ShareLedger(reserve_ratio=0.5)
        r1 = sl.mint("cap1", "user1", 10.0)
        r2 = sl.mint("cap1", "user1", 10.0)
        assert r2.diminishing_multiplier == 0.8
        assert r2.diminishing_tier == 1

    def test_third_call_60pct(self):
        sl = ShareLedger(reserve_ratio=0.5)
        for _ in range(2):
            sl.mint("cap1", "user1", 10.0)
        r3 = sl.mint("cap1", "user1", 10.0)
        assert r3.diminishing_multiplier == 0.6
        assert r3.diminishing_tier == 2

    def test_fourth_plus_call_40pct(self):
        sl = ShareLedger(reserve_ratio=0.5)
        for _ in range(3):
            sl.mint("cap1", "user1", 10.0)
        r4 = sl.mint("cap1", "user1", 10.0)
        assert r4.diminishing_multiplier == 0.4
        assert r4.diminishing_tier == 3

    def test_fifth_call_still_40pct(self):
        sl = ShareLedger(reserve_ratio=0.5)
        for _ in range(4):
            sl.mint("cap1", "user1", 10.0)
        r5 = sl.mint("cap1", "user1", 10.0)
        assert r5.diminishing_multiplier == 0.4
        assert r5.diminishing_tier == 3

    def test_diminishing_per_consumer(self):
        sl = ShareLedger(reserve_ratio=0.5)
        sl.mint("cap1", "user1", 10.0)  # user1 call 1
        r_user2 = sl.mint("cap1", "user2", 10.0)  # user2 call 1
        assert r_user2.diminishing_multiplier == 1.0

    def test_diminishing_per_capability(self):
        sl = ShareLedger(reserve_ratio=0.5)
        sl.mint("cap1", "user1", 10.0)  # cap1 call 1
        r_cap2 = sl.mint("cap2", "user1", 10.0)  # cap2 call 1
        assert r_cap2.diminishing_multiplier == 1.0

    def test_diminishing_reduces_shares(self):
        """Same OAS deposit yields fewer shares on subsequent calls."""
        sl = ShareLedger(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.5)
        # Use a separate pool for each call to keep curve state identical
        sl2 = ShareLedger(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.5)
        r1 = sl.mint("cap1", "user1", 10.0)
        r2 = sl2.mint("cap1", "user1", 10.0)
        # r2 is also first call on a fresh pool, so same
        assert abs(r1.shares_minted - r2.shares_minted) < 1e-10
        # Now second call on sl (curve has moved + diminishing)
        r3 = sl.mint("cap1", "user1", 10.0)
        assert r3.shares_minted < r1.shares_minted


class TestShareBurn:
    def test_burn_basic(self):
        sl = ShareLedger(reserve_ratio=0.5)
        mint_r = sl.mint("cap1", "user1", 50.0)
        burn_r = sl.burn("cap1", "user1", mint_r.shares_minted / 2)
        assert isinstance(burn_r, BurnResult)
        assert burn_r.oas_returned > 0
        assert burn_r.shares_burned == mint_r.shares_minted / 2

    def test_burn_reduces_balance(self):
        sl = ShareLedger(reserve_ratio=0.5)
        mint_r = sl.mint("cap1", "user1", 50.0)
        sl.burn("cap1", "user1", mint_r.shares_minted)
        assert sl.balance("cap1", "user1") == pytest.approx(0.0, abs=1e-10)

    def test_burn_insufficient_shares(self):
        sl = ShareLedger(reserve_ratio=0.5)
        sl.mint("cap1", "user1", 10.0)
        with pytest.raises(ShareLedgerError, match="insufficient"):
            sl.burn("cap1", "user1", 99999.0)

    def test_burn_zero_raises(self):
        sl = ShareLedger()
        with pytest.raises(ShareLedgerError, match="positive"):
            sl.burn("cap1", "user1", 0.0)

    def test_burn_returns_less_than_deposited_due_to_diminishing(self):
        """If shares were diminished, burning returns proportionally less OAS."""
        sl = ShareLedger(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.5)
        deposit = 10.0
        mint_r = sl.mint("cap1", "user1", deposit)
        burn_r = sl.burn("cap1", "user1", mint_r.shares_minted)
        # With 100% multiplier on first call, burn should return close to deposit
        # (not exact due to curve mechanics, but close for small deposits)
        assert burn_r.oas_returned > 0
        assert burn_r.oas_returned <= deposit + 0.01  # allow tiny float error


class TestShareBalance:
    def test_zero_balance(self):
        sl = ShareLedger()
        assert sl.balance("cap1", "user1") == 0.0

    def test_balance_after_mint(self):
        sl = ShareLedger()
        r = sl.mint("cap1", "user1", 10.0)
        assert sl.balance("cap1", "user1") == r.shares_minted

    def test_total_supply_initial(self):
        sl = ShareLedger(initial_supply=100.0)
        assert sl.total_supply("cap1") == 100.0

    def test_pool_reserve_initial(self):
        sl = ShareLedger(initial_reserve=100.0)
        assert sl.pool_reserve("cap1") == 100.0

    def test_call_count_tracking(self):
        sl = ShareLedger()
        assert sl.call_count("user1", "cap1") == 0
        sl.mint("cap1", "user1", 10.0)
        assert sl.call_count("user1", "cap1") == 1
        sl.mint("cap1", "user1", 10.0)
        assert sl.call_count("user1", "cap1") == 2


# ═══════════════════════════════════════════════════════════════════════
# PRICING TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestCapabilityPricing:
    def test_quote_basic(self):
        cp = CapabilityPricing(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.35)
        q = cp.quote("cap1", "user1")
        assert isinstance(q, QuoteResult)
        assert q.spot_price > 0
        assert q.protocol_fee == pytest.approx(q.spot_price * 0.05)
        assert q.net_to_curve == pytest.approx(q.spot_price * 0.95)

    def test_quote_shares_estimate(self):
        cp = CapabilityPricing(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.35)
        q = cp.quote("cap1", "user1")
        assert q.shares_estimate > 0
        assert q.diminishing_tier == 0
        assert q.diminishing_multiplier == 1.0

    def test_quote_diminishing_tiers(self):
        cp = CapabilityPricing()
        cp.increment_call_count("user1", "cap1")
        q = cp.quote("cap1", "user1")
        assert q.diminishing_tier == 1
        assert q.diminishing_multiplier == 0.8

    def test_protocol_fee_5pct(self):
        cp = CapabilityPricing(protocol_fee_pct=0.05)
        q = cp.quote("cap1", "user1")
        assert q.protocol_fee == pytest.approx(q.spot_price * 0.05)

    def test_sync_pool(self):
        cp = CapabilityPricing(initial_reserve=100.0, initial_supply=100.0)
        cp.sync_pool("cap1", 200.0, 150.0)
        q = cp.quote("cap1", "user1")
        # Spot price with synced pool
        curve = BancorCurve()
        expected = curve.calculate_price(200.0, 150.0, 0.35)
        assert q.spot_price == pytest.approx(expected)


# ═══════════════════════════════════════════════════════════════════════
# INVOCATION ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestInvokeBasic:
    def test_invoke_returns_handle(self):
        engine, _, _, _, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        assert isinstance(handle, InvocationHandle)
        assert handle.capability_id == manifest.capability_id
        assert handle.consumer_id == "consumer-1"
        assert handle.price > 0

    def test_invoke_locks_escrow(self):
        engine, _, escrow, _, manifest = _make_engine()
        initial = escrow.balance("consumer-1")
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        assert escrow.balance("consumer-1") == pytest.approx(initial - handle.price)
        rec = escrow.get(handle.escrow_id)
        assert rec is not None
        assert rec.state == EscrowState.LOCKED

    def test_invoke_capability_not_found(self):
        engine, _, _, _, _ = _make_engine()
        with pytest.raises(InvocationError, match="not found"):
            engine.invoke("consumer-1", "nonexistent", {"text": "hi"}, 100.0)

    def test_invoke_missing_required_input(self):
        engine, _, _, _, manifest = _make_engine()
        with pytest.raises(InvocationError, match="missing required"):
            engine.invoke("consumer-1", manifest.capability_id, {}, 100.0)

    def test_invoke_price_exceeds_max(self):
        engine, _, _, _, manifest = _make_engine()
        with pytest.raises(InvocationError, match="exceeds max_price"):
            engine.invoke(
                "consumer-1",
                manifest.capability_id,
                {"text": "hi"},
                max_price=0.001,
            )

    def test_invoke_insufficient_balance(self):
        engine, _, _, _, manifest = _make_engine(consumer_balance=0.001)
        with pytest.raises(InvocationError, match="insufficient"):
            engine.invoke(
                "consumer-1",
                manifest.capability_id,
                {"text": "hi"},
                max_price=100.0,
            )

    def test_invoke_paused_capability(self):
        manifest = _make_manifest()
        engine, registry, _, _, _ = _make_engine(manifest=manifest)
        registry.update_status(manifest.capability_id, "paused")
        with pytest.raises(InvocationError, match="paused"):
            engine.invoke(
                "consumer-1",
                manifest.capability_id,
                {"text": "hi"},
                max_price=100.0,
            )


class TestFullLifecycle:
    """invoke → submit_result → settlement + shares minted."""

    def test_happy_path(self):
        engine, _, escrow, shares, manifest = _make_engine()

        # 1. Invoke
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        assert handle.price > 0

        # 2. Submit result
        result = engine.submit_result(
            handle.invocation_id,
            {"result": "world"},
            provider_signature="sig123",
        )
        assert isinstance(result, SettlementResult)
        assert result.escrow_released is True

        # 3. Protocol fee = 5%
        assert result.protocol_fee == pytest.approx(handle.price * 0.05)
        assert result.burn_amount == pytest.approx(handle.price * 0.025)
        assert result.verifier_amount == pytest.approx(handle.price * 0.025)
        assert result.net_to_curve == pytest.approx(handle.price * 0.95)

        # 4. Shares minted
        assert result.mint_result is not None
        assert result.mint_result.shares_minted > 0
        assert shares.balance(manifest.capability_id, "consumer-1") > 0

        # 5. Fee split
        assert result.fee_split is not None
        assert result.fee_split.creator > 0

        # 6. Invocation state
        rec = engine.get_invocation(handle.invocation_id)
        assert rec.state == InvocationState.COMPLETED

    def test_multiple_invocations_diminishing(self):
        engine, _, escrow, shares, manifest = _make_engine(consumer_balance=10000.0)
        cap_id = manifest.capability_id

        shares_per_call = []
        for i in range(4):
            handle = engine.invoke(
                "consumer-1",
                cap_id,
                {"text": f"call {i}"},
                max_price=100.0,
            )
            result = engine.submit_result(
                handle.invocation_id,
                {"result": f"out {i}"},
            )
            shares_per_call.append(result.mint_result.shares_minted)

        # Shares should decrease due to diminishing returns + curve movement
        assert shares_per_call[0] > shares_per_call[1]
        assert shares_per_call[1] > shares_per_call[2]
        assert shares_per_call[2] > shares_per_call[3]


class TestFailPath:
    """invoke → fail → refund."""

    def test_fail_refunds_escrow(self):
        engine, _, escrow, _, manifest = _make_engine()
        initial_balance = escrow.balance("consumer-1")

        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        assert escrow.balance("consumer-1") < initial_balance

        ok = engine.fail(handle.invocation_id, "timeout", "provider timed out")
        assert ok is True
        assert escrow.balance("consumer-1") == pytest.approx(initial_balance)

        rec = engine.get_invocation(handle.invocation_id)
        assert rec.state == InvocationState.FAILED

    def test_fail_nonexistent(self):
        engine, _, _, _, _ = _make_engine()
        with pytest.raises(InvocationError, match="not found"):
            engine.fail("nonexistent", "timeout")

    def test_fail_already_completed(self):
        engine, _, _, _, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        engine.submit_result(handle.invocation_id, {"result": "ok"})
        with pytest.raises(InvocationError, match="completed"):
            engine.fail(handle.invocation_id, "timeout")


class TestDisputePath:
    """invoke → dispute."""

    def test_dispute_marks_state(self):
        engine, _, escrow, _, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        dh = engine.dispute(handle.invocation_id, "consumer-1", "bad result")
        assert isinstance(dh, DisputeHandle)
        assert dh.reason == "bad result"

        rec = engine.get_invocation(handle.invocation_id)
        assert rec.state == InvocationState.DISPUTED

        # Escrow is disputed (funds still locked)
        erec = escrow.get(handle.escrow_id)
        assert erec.state == EscrowState.DISPUTED

    def test_dispute_wrong_consumer(self):
        engine, _, _, _, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        with pytest.raises(InvocationError, match="only the consumer"):
            engine.dispute(handle.invocation_id, "someone-else", "fraud")


class TestSubmitResultValidation:
    def test_missing_output_keys(self):
        engine, _, _, _, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        with pytest.raises(InvocationError, match="missing required"):
            engine.submit_result(handle.invocation_id, {"wrong_key": "value"})

    def test_submit_already_failed(self):
        engine, _, _, _, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        engine.fail(handle.invocation_id, "timeout")
        with pytest.raises(InvocationError, match="failed"):
            engine.submit_result(handle.invocation_id, {"result": "late"})


# ═══════════════════════════════════════════════════════════════════════
# AHRP EXTENSION TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestAhrpMessageTypes:
    def test_capability_query(self):
        assert AhrpMessageType.CAPABILITY_QUERY.value == "capability_query"

    def test_capability_invoke(self):
        assert AhrpMessageType.CAPABILITY_INVOKE.value == "capability_invoke"

    def test_capability_result(self):
        assert AhrpMessageType.CAPABILITY_RESULT.value == "capability_result"

    def test_capability_fail(self):
        assert AhrpMessageType.CAPABILITY_FAIL.value == "capability_fail"

    def test_original_types_unchanged(self):
        assert AhrpMessageType.ANNOUNCE.value == "announce"
        assert AhrpMessageType.REQUEST.value == "request"
        assert AhrpMessageType.OFFER.value == "offer"
        assert AhrpMessageType.ACCEPT.value == "accept"
        assert AhrpMessageType.DELIVER.value == "deliver"
        assert AhrpMessageType.CONFIRM.value == "confirm"


class TestTxStateEscrowed:
    def test_escrowed_state_exists(self):
        assert TxState.ESCROWED.value == "escrowed"

    def test_escrowed_transition(self):
        tx = Transaction(tx_id="tx1", buyer="b", seller="s", state=TxState.ACCEPTED)
        tx.advance(AhrpMessageType.CAPABILITY_INVOKE)
        assert tx.state == TxState.ESCROWED

    def test_escrowed_to_delivered(self):
        tx = Transaction(tx_id="tx1", buyer="b", seller="s", state=TxState.ESCROWED)
        tx.advance(AhrpMessageType.CAPABILITY_RESULT)
        assert tx.state == TxState.DELIVERED

    def test_escrowed_to_expired_on_fail(self):
        tx = Transaction(tx_id="tx1", buyer="b", seller="s", state=TxState.ESCROWED)
        tx.advance(AhrpMessageType.CAPABILITY_FAIL)
        assert tx.state == TxState.EXPIRED


class TestCapabilityPayloads:
    def test_query_payload(self):
        p = CapabilityQueryPayload(
            query_tags=["finance"],
            query_text="financial analysis",
            max_price=100.0,
            limit=5,
        )
        assert p.query_tags == ["finance"]
        assert p.max_price == 100.0

    def test_invoke_payload(self):
        p = CapabilityInvokePayload(
            invocation_id="inv-1",
            capability_id="cap-1",
            input={"text": "hello"},
            max_price=10.0,
            escrow_tx_id="esc-1",
        )
        assert p.invocation_id == "inv-1"
        assert p.input == {"text": "hello"}

    def test_result_payload(self):
        p = CapabilityResultPayload(
            invocation_id="inv-1",
            output={"summary": "done"},
            content_hash="abc123",
            execution_time_ms=150,
        )
        assert p.execution_time_ms == 150

    def test_fail_payload(self):
        p = CapabilityFailPayload(
            invocation_id="inv-1",
            error_code="timeout",
            error_message="took too long",
        )
        assert p.error_code == "timeout"

    def test_query_payload_defaults(self):
        p = CapabilityQueryPayload()
        assert p.query_tags == []
        assert p.max_price == float("inf")
        assert p.limit == 10

    def test_invoke_payload_defaults(self):
        p = CapabilityInvokePayload()
        assert p.invocation_id == ""
        assert p.input == {}


# ═══════════════════════════════════════════════════════════════════════
# NETWORK MESSAGE TYPE TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestNetworkMessageTypes:
    def test_capability_types_in_literal(self):
        """Verify the new types are valid for NetworkMessage.msg_type."""
        from oasyce.network.message import NetworkMessage

        for mt in ["CAPABILITY_QUERY", "CAPABILITY_INVOKE", "CAPABILITY_RESULT", "CAPABILITY_FAIL"]:
            msg = NetworkMessage(msg_type=mt, sender_id="node1")
            assert msg.msg_type == mt

    def test_original_types_still_work(self):
        from oasyce.network.message import NetworkMessage

        for mt in ["ASSET_SUBMIT", "VOTE", "PEER_EXCHANGE", "HEARTBEAT"]:
            msg = NetworkMessage(msg_type=mt, sender_id="node1")
            assert msg.msg_type == mt


# ═══════════════════════════════════════════════════════════════════════
# BONDING CURVE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════


class TestBondingCurveIntegration:
    """Verify shares math against BancorCurve directly."""

    def test_mint_matches_curve(self):
        curve = BancorCurve()
        sl = ShareLedger(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.35)
        deposit = 10.0

        expected_raw = curve.calculate_purchase_return(100.0, 100.0, 0.35, deposit)
        result = sl.mint("cap1", "user1", deposit)
        # First call: 100% multiplier, so shares_minted == raw
        assert result.shares_minted == pytest.approx(expected_raw)

    def test_burn_round_trip(self):
        """Mint then burn all shares — should get back original deposit."""
        sl = ShareLedger(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.5)
        deposit = 10.0
        mint_r = sl.mint("cap1", "user1", deposit)
        burn_r = sl.burn("cap1", "user1", mint_r.shares_minted)
        # Round trip should return the original deposit (within float precision)
        assert burn_r.oas_returned == pytest.approx(deposit, rel=1e-9)

    def test_price_increases_with_supply(self):
        """Buying should increase the spot price."""
        sl = ShareLedger(initial_reserve=100.0, initial_supply=100.0, reserve_ratio=0.35)
        curve = BancorCurve()

        price_before = curve.calculate_price(100.0, 100.0, 0.35)
        sl.mint("cap1", "user1", 50.0)
        price_after = curve.calculate_price(
            sl.pool_reserve("cap1"),
            sl.total_supply("cap1"),
            0.35,
        )
        assert price_after > price_before


# ═══════════════════════════════════════════════════════════════════════
# FEE SPLIT INTEGRATION
# ═══════════════════════════════════════════════════════════════════════


class TestFeeSplitIntegration:
    def test_settlement_uses_60_20_15_5(self):
        engine, _, _, _, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        result = engine.submit_result(handle.invocation_id, {"result": "ok"})
        fs = result.fee_split
        net = result.net_to_curve

        # Default FeeSplitter: 60/20/15/5
        assert fs.creator == pytest.approx(net * 0.60, rel=1e-6)
        assert fs.validator == pytest.approx(net * 0.20, rel=1e-6)
        assert fs.burn == pytest.approx(net * 0.15, rel=1e-6)
        assert fs.treasury == pytest.approx(net * 0.05, rel=1e-6)

    def test_protocol_fee_burn_verifier_split(self):
        engine, _, _, _, manifest = _make_engine()
        handle = engine.invoke(
            "consumer-1",
            manifest.capability_id,
            {"text": "hello"},
            max_price=100.0,
        )
        result = engine.submit_result(handle.invocation_id, {"result": "ok"})
        # 2.5% burn + 2.5% verifier of gross
        assert result.burn_amount == pytest.approx(result.verifier_amount)
        assert result.burn_amount + result.verifier_amount == pytest.approx(result.protocol_fee)


# ═══════════════════════════════════════════════════════════════════════
# IMPORT / EXPORT TESTS
# ═══════════════════════════════════════════════════════════════════════


class TestImports:
    def test_top_level_imports(self):
        """All new classes importable from capabilities package."""
        from oasyce.capabilities import (
            EscrowManager,
            EscrowRecord,
            EscrowState,
            EscrowError,
            ShareLedger,
            ShareLedgerError,
            MintResult,
            BurnResult,
            CapabilityPricing,
            QuoteResult,
            CapabilityInvocationEngine,
            InvocationHandle,
            InvocationState,
            InvocationError,
            SettlementResult,
            DisputeHandle,
        )

        # All should be importable without error
        assert EscrowManager is not None
        assert ShareLedger is not None
        assert CapabilityPricing is not None
        assert CapabilityInvocationEngine is not None

    def test_ahrp_payload_imports(self):
        from oasyce.ahrp import (
            CapabilityQueryPayload,
            CapabilityInvokePayload,
            CapabilityResultPayload,
            CapabilityFailPayload,
        )

        assert CapabilityQueryPayload is not None

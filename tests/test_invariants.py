"""Tests for critical invariants added in P7-P10."""
from __future__ import annotations

import pytest


def test_bootstrap_pricing_uses_initial_price():
    """Unfunded pool should price at INITIAL_PRICE (1.0 OAS/token), not 10x."""
    from oasyce.services.settlement.engine import SettlementEngine, INITIAL_PRICE
    from oasyce.core.formulas import CREATOR_RATE

    se = SettlementEngine()
    se.register_asset("BOOT", "creator", initial_reserve=0.0)

    # Buy 1 OAS into unfunded pool
    q = se.quote("BOOT", 1.0)
    # After fees (20% + 15% + 5% = 40%), net = 0.60 OAS (CREATOR_RATE)
    # tokens = net_payment / INITIAL_PRICE = 0.60 / 1.0 = 0.60
    assert q.equity_minted == pytest.approx(CREATOR_RATE, abs=0.01)
    assert q.equity_minted < 2.0  # Must NOT be 10x (old bug gave 9.3)


def test_cannot_dispute_own_invocation():
    """Provider-as-consumer cannot dispute their own invocation."""
    from oasyce.capabilities.dispute import DisputeManager, DisputeError
    import types

    # Create invocation where consumer == provider
    self_inv = types.SimpleNamespace(
        consumer_id="alice",
        provider_id="alice",  # Same as consumer
        capability_id="cap1",
        state=types.SimpleNamespace(value="completed"),
        settled_at=1000,
        escrow_id="esc1",
        price=10.0,
    )

    dm = DisputeManager(
        get_invocation=lambda iid: self_inv,
        get_reputation=lambda aid: 60.0,
        get_stake=lambda aid: 100.0,
        escrow_refund=lambda eid: None,
        escrow_release=lambda eid: None,
    )

    with pytest.raises(DisputeError, match="Cannot dispute own invocation"):
        dm.open_dispute("inv1", "alice", "self-dispute attempt")


def test_sell_validates_reserve_sufficiency():
    """Sell should fail if it would drain more than available reserve."""
    from oasyce.services.settlement.engine import SettlementEngine, SettlementConfig

    se = SettlementEngine(config=SettlementConfig(chain_required=False))
    se.register_asset("DRAIN", "creator", initial_reserve=100.0)

    # Buy to get tokens
    se.execute("DRAIN", "buyer", 100.0)
    pool = se.get_pool("DRAIN")
    tokens_owned = pool.equity.get("buyer", 0)

    # Trying to sell almost everything should work (up to 95% reserve cap)
    # But the system should never allow reserve to go negative
    sq = se.sell_quote("DRAIN", tokens_owned * 0.5, "buyer")
    assert sq.payout_oas > 0
    assert sq.payout_oas <= pool.reserve_balance * 0.95


def test_decay_all_applies_to_multiple_agents():
    """decay_all() should decay all tracked agents."""
    from oasyce.services.reputation import ReputationEngine
    from oasyce.services.access.config import AccessControlConfig

    config = AccessControlConfig(
        rep_decay_days=0.0001,    # ~8.6 seconds, for fast test
        rep_decay_amount=-5.0,
    )

    engine = ReputationEngine(config=config)

    # Build up reputation for two agents
    for _ in range(10):
        engine.update("agent_a", success=True)
        engine.update("agent_b", success=True)

    score_a = engine.get_reputation("agent_a")
    score_b = engine.get_reputation("agent_b")
    assert score_a > 0
    assert score_b > 0

    # Simulate time passing
    for agent in engine._agents.values():
        agent.last_decay_check -= 86400  # 1 day ago

    changed = engine.decay_all()
    assert changed == 2
    assert engine.get_reputation("agent_a") < score_a
    assert engine.get_reputation("agent_b") < score_b


def test_cannot_delete_asset_with_equity_holders():
    """Deleting an asset with active equity holders must be rejected."""
    from oasyce.services.facade import OasyceServiceFacade
    from oasyce.services.settlement.engine import SettlementConfig
    from oasyce.storage.ledger import Ledger

    ledger = Ledger(db_path=":memory:")
    ledger.register_asset("DEL_TEST", "creator", "hash123", {"tags": ["test"]})

    facade = OasyceServiceFacade(ledger=ledger, allow_local_fallback=True)
    se = facade._get_settlement()
    se._config = SettlementConfig(chain_required=False)

    # Register and buy to create equity
    se.register_asset("DEL_TEST", "creator", initial_reserve=100.0)
    se.execute("DEL_TEST", "buyer", 10.0)

    # Attempt to delete — should fail (asset is ACTIVE, must shutdown first)
    result = facade.delete_asset("DEL_TEST")
    assert not result.success
    assert "cannot delete" in result.error.lower()


def test_sell_has_default_slippage_protection():
    """Sell without explicit max_slippage should use safe default (10%)."""
    from oasyce.services.facade import OasyceServiceFacade
    from oasyce.services.settlement.engine import SettlementConfig

    facade = OasyceServiceFacade(allow_local_fallback=True)
    se = facade._get_settlement()
    se._config = SettlementConfig(chain_required=False)

    se.register_asset("SLIP_TEST", "creator", initial_reserve=100.0)
    se.execute("SLIP_TEST", "buyer", 50.0)

    pool = se.get_pool("SLIP_TEST")
    tokens_owned = pool.equity.get("buyer", 0)
    assert tokens_owned > 0

    # Sell a small fraction of owned tokens — should succeed with default slippage
    result = facade.sell("SLIP_TEST", "buyer", tokens_owned * 0.1)
    assert result.success  # Small sell should be within 10% slippage


def test_share_adjustment_must_sum_to_100():
    """Dispute resolution with share_adjustment must validate shares sum."""
    from oasyce.services.facade import OasyceServiceFacade
    from oasyce.storage.ledger import Ledger

    ledger = Ledger(db_path=":memory:")
    # Create a disputed asset in the ledger
    ledger.register_asset(
        "SHARE_TEST", "creator", "hash123",
        {"tags": ["test"], "disputed": True, "dispute_status": "open"},
    )

    facade = OasyceServiceFacade(ledger=ledger)

    result = facade.resolve_dispute(
        asset_id="SHARE_TEST",
        remedy="share_adjustment",
        details={"co_creators": [
            {"address": "alice", "share": 60},
            {"address": "bob", "share": 60},  # Sum = 120, invalid
        ]},
    )
    assert not result.success
    assert "sum to 100" in result.error.lower()


def test_identity_verification_rejects_unsigned():
    """When verify_identity=True, operations without signature are rejected."""
    from oasyce.services.facade import OasyceServiceFacade

    facade = OasyceServiceFacade(verify_identity=True, allow_local_fallback=True)
    se = facade._get_settlement()
    se.register_asset("AUTH_TEST", "creator", initial_reserve=100.0)

    # Buy without signature — should fail
    result = facade.buy("AUTH_TEST", "buyer", 10.0)
    assert not result.success
    assert "identity verification" in result.error.lower() or "signature" in result.error.lower()

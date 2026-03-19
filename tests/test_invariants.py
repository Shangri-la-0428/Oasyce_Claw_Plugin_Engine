"""Tests for critical invariants added in P7-P10."""
from __future__ import annotations

import pytest


def test_bootstrap_pricing_uses_initial_price():
    """Unfunded pool should price at INITIAL_PRICE (1.0 OAS/token), not 10x."""
    from oasyce.services.settlement.engine import SettlementEngine, INITIAL_PRICE

    se = SettlementEngine()
    se.register_asset("BOOT", "creator", initial_reserve=0.0)

    # Buy 1 OAS into unfunded pool
    q = se.quote("BOOT", 1.0)
    # After fees (5% + 2% = 7%), net = 0.93 OAS
    # tokens = net_payment / INITIAL_PRICE = 0.93 / 1.0 = 0.93
    assert q.equity_minted == pytest.approx(0.93, abs=0.01)
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

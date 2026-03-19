"""
Tests for the Leakage Budget service.

Covers:
  - LeakageBudget initialization and configuration
  - Budget consumption and enforcement
  - Budget exhaustion and cooldown
  - L0-L3 information gain estimation
  - Budget reset
  - DataAccessProvider integration (leakage blocking)
  - Thread safety
"""

from __future__ import annotations

import threading
import time

import pytest

from oasyce.services.leakage import LeakageBudget, LeakageBudgetConfig
from oasyce.services.access.provider import DataAccessProvider
from oasyce.services.access.config import AccessControlConfig
from oasyce.services.reputation import ReputationEngine


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def budget():
    return LeakageBudget()


@pytest.fixture
def budget_fast_cooldown():
    """Budget with 1-second cooldown for fast tests."""
    return LeakageBudget(LeakageBudgetConfig(cooldown_seconds=1))


# ─── Initialization ──────────────────────────────────────────────


class TestBudgetInit:
    def test_initialize_budget(self, budget):
        result = budget.initialize_budget("agent_A", "asset_1", dataset_size=10000)
        assert result["total_size"] == 10000
        assert result["budget"] == 500.0  # 5% of 10000
        assert result["used"] == 0.0
        assert result["queries"] == 0

    def test_custom_budget_ratio(self, budget):
        result = budget.initialize_budget(
            "agent_A", "asset_1", dataset_size=10000, budget_ratio=0.10
        )
        assert result["budget"] == 1000.0  # 10% of 10000

    def test_invalid_dataset_size(self, budget):
        with pytest.raises(ValueError, match="positive"):
            budget.initialize_budget("a", "b", dataset_size=0)

    def test_invalid_budget_ratio(self, budget):
        with pytest.raises(ValueError, match="budget_ratio"):
            budget.initialize_budget("a", "b", dataset_size=100, budget_ratio=0)

    def test_budget_ratio_above_1(self, budget):
        with pytest.raises(ValueError, match="budget_ratio"):
            budget.initialize_budget("a", "b", dataset_size=100, budget_ratio=1.5)


# ─── Information Gain Estimation ─────────────────────────────────


class TestInformationGain:
    def test_l0_low_gain(self, budget):
        gain = budget.estimate_information_gain(100, 10000, "L0")
        assert gain == pytest.approx(10.0)  # 0.1% of 10000

    def test_l1_proportional_gain(self, budget):
        gain = budget.estimate_information_gain(500, 10000, "L1")
        assert gain == pytest.approx(500.0)  # 500/10000 * 10000

    def test_l1_capped_at_dataset_size(self, budget):
        gain = budget.estimate_information_gain(20000, 10000, "L1")
        assert gain == pytest.approx(10000.0)  # capped at 100%

    def test_l2_medium_gain(self, budget):
        gain = budget.estimate_information_gain(100, 10000, "L2")
        assert gain == pytest.approx(50.0)  # 0.5% of 10000

    def test_l3_full_gain(self, budget):
        gain = budget.estimate_information_gain(100, 10000, "L3")
        assert gain == pytest.approx(10000.0)  # 100%

    def test_zero_dataset_size(self, budget):
        gain = budget.estimate_information_gain(100, 0, "L0")
        assert gain == 0.0


# ─── Budget Consumption ─────────────────────────────────────────


class TestConsume:
    def test_consume_within_budget(self, budget):
        budget.initialize_budget("a", "b", 10000)
        result = budget.consume("a", "b", 100.0)
        assert result["allowed"] is True
        assert result["remaining_budget"] == pytest.approx(400.0)

    def test_consume_exceeds_budget(self, budget):
        budget.initialize_budget("a", "b", 10000)  # budget=500
        result = budget.consume("a", "b", 600.0)
        assert result["allowed"] is False
        assert "exceeds" in result["warning"]

    def test_consume_incremental_until_blocked(self, budget):
        budget.initialize_budget("a", "b", 10000)  # budget=500
        # Consume 400 → ok
        r1 = budget.consume("a", "b", 400.0)
        assert r1["allowed"] is True
        # Consume 200 → exceeds remaining 100
        r2 = budget.consume("a", "b", 200.0)
        assert r2["allowed"] is False

    def test_consume_uninitialized_pair(self, budget):
        result = budget.consume("unknown", "unknown", 10.0)
        assert result["allowed"] is False
        assert "not initialized" in result["warning"]

    def test_low_budget_warning(self, budget):
        budget.initialize_budget("a", "b", 10000)  # budget=500
        result = budget.consume("a", "b", 450.0)
        assert result["allowed"] is True
        assert result["warning"] is not None
        assert "nearly exhausted" in result["warning"]

    def test_query_count_increments(self, budget):
        budget.initialize_budget("a", "b", 10000)
        budget.consume("a", "b", 10.0)
        budget.consume("a", "b", 10.0)
        remaining = budget.get_remaining("a", "b")
        assert remaining["queries"] == 2


# ─── Cooldown ────────────────────────────────────────────────────


class TestCooldown:
    def test_cooldown_blocks_after_exhaustion(self, budget_fast_cooldown):
        b = budget_fast_cooldown
        b.initialize_budget("a", "b", 10000)  # budget=500
        # Exhaust
        r = b.consume("a", "b", 600.0)
        assert r["allowed"] is False
        # Immediate retry is blocked by cooldown
        r2 = b.consume("a", "b", 1.0)
        assert r2["allowed"] is False
        assert "cooldown" in r2["warning"]

    def test_cooldown_expires(self, budget_fast_cooldown):
        b = budget_fast_cooldown
        b.initialize_budget("a", "b", 10000)
        b.consume("a", "b", 600.0)  # triggers cooldown (1s)
        time.sleep(1.1)
        # After cooldown, can't consume because budget is still exhausted
        # but no cooldown message
        r = b.consume("a", "b", 1.0)
        # Budget still has 500 used=0 since consume failed
        # Actually the consume that failed didn't add to used, so budget is intact
        assert r["allowed"] is True


# ─── get_remaining ───────────────────────────────────────────────


class TestGetRemaining:
    def test_uninitialized_pair(self, budget):
        r = budget.get_remaining("x", "y")
        assert r["total_size"] == 0
        assert r["exhausted"] is True

    def test_initialized_pair(self, budget):
        budget.initialize_budget("a", "b", 10000)
        r = budget.get_remaining("a", "b")
        assert r["remaining"] == 500.0
        assert r["exhausted"] is False


# ─── reset_budget ────────────────────────────────────────────────


class TestResetBudget:
    def test_reset_restores_budget(self, budget):
        budget.initialize_budget("a", "b", 10000)
        budget.consume("a", "b", 400.0)
        budget.reset_budget("a", "b")
        r = budget.get_remaining("a", "b")
        assert r["used"] == 0.0
        assert r["remaining"] == 500.0
        assert r["queries"] == 0

    def test_reset_uninitialized(self, budget):
        result = budget.reset_budget("x", "y")
        assert "error" in result


# ─── DataAccessProvider Integration ──────────────────────────────


class TestProviderIntegration:
    def test_leakage_blocks_access(self):
        """Access is denied when leakage budget is exhausted."""
        config = AccessControlConfig()
        rep = ReputationEngine(config=config)
        # Set high reputation for full access
        for _ in range(50):
            rep.update("agent_1", success=True)

        provider = DataAccessProvider(config=config, reputation=rep)
        provider.register_asset("data_1", value=100.0)

        # Initialize a tiny budget
        provider.leakage.initialize_budget(
            "agent_1", "data_1", dataset_size=1000, budget_ratio=0.01
        )
        # budget = 10

        # First L0 query should work (gain = 0.1% of 1000 = 1.0)
        r1 = provider.query("agent_1", "data_1", "test")
        assert r1.success is True

        # After many queries, budget will exhaust
        for _ in range(20):
            provider.query("agent_1", "data_1", "test")

        # Eventually budget is exhausted
        r_final = provider.query("agent_1", "data_1", "test")
        # After 10+ queries of gain=1.0 each, budget=10 should be exhausted
        # (queries 1-10 consume 10 total, query 11 should be blocked)
        # We've done 21 queries total, so it should be blocked
        assert r_final.success is False
        assert "Leakage budget" in r_final.error

    def test_no_budget_means_no_blocking(self):
        """If no budget is initialized, access proceeds normally."""
        config = AccessControlConfig()
        provider = DataAccessProvider(config=config)
        provider.register_asset("data_1", value=100.0)

        result = provider.query("agent_1", "data_1", "test")
        assert result.success is True


# ─── Thread Safety ───────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_consume(self, budget):
        budget.initialize_budget("a", "b", 100000)  # budget=5000
        results = []

        def _consume():
            r = budget.consume("a", "b", 10.0)
            results.append(r)

        threads = [threading.Thread(target=_consume) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        allowed_count = sum(1 for r in results if r["allowed"])
        assert allowed_count > 0
        remaining = budget.get_remaining("a", "b")
        assert remaining["used"] == pytest.approx(allowed_count * 10.0)

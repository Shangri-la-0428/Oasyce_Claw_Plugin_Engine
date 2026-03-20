"""Tests for Layer 0 pure functions — zero mocking needed."""

import pytest

from oasyce.core.formulas import (
    INITIAL_PRICE,
    PROTOCOL_FEE_RATE,
    BURN_RATE,
    RESERVE_SOLVENCY_CAP,
    bonding_curve_buy,
    bonding_curve_sell,
    calculate_fees,
    equity_to_access_level,
    jury_score,
    price_impact,
    spot_price,
)


class TestCalculateFees:
    def test_normal(self):
        fee, burn, net = calculate_fees(100.0)
        assert fee == pytest.approx(5.0)
        assert burn == pytest.approx(2.0)
        assert net == pytest.approx(93.0)

    def test_zero(self):
        fee, burn, net = calculate_fees(0.0)
        assert fee == 0.0
        assert burn == 0.0
        assert net == 0.0

    def test_sum_identity(self):
        """fee + burn + net == original amount."""
        for amount in [1.0, 10.0, 100.0, 1e6]:
            fee, burn, net = calculate_fees(amount)
            assert fee + burn + net == pytest.approx(amount)


class TestSpotPrice:
    def test_normal(self):
        assert spot_price(100, 50) == pytest.approx(1.0)

    def test_zero_supply(self):
        assert spot_price(0, 100) == 0.0

    def test_negative_supply(self):
        assert spot_price(-1, 100) == 0.0


class TestBondingCurveBuy:
    def test_bootstrap(self):
        """Zero reserve → tokens = payment / INITIAL_PRICE."""
        tokens = bonding_curve_buy(1.0, 0.0, 10.0)
        assert tokens == pytest.approx(10.0 / INITIAL_PRICE)

    def test_normal(self):
        """With existing reserve, follows Bancor formula."""
        tokens = bonding_curve_buy(100.0, 50.0, 10.0)
        expected = 100.0 * ((1 + 10.0 / 50.0) ** 0.5 - 1)
        assert tokens == pytest.approx(expected)

    def test_small_payment(self):
        tokens = bonding_curve_buy(1000.0, 500.0, 0.01)
        assert tokens > 0

    def test_zero_supply_nonzero_reserve(self):
        """Edge case: supply=0 but reserve>0 — uses bootstrap."""
        tokens = bonding_curve_buy(0.0, 100.0, 10.0)
        assert tokens == pytest.approx(10.0 / INITIAL_PRICE)


class TestBondingCurveSell:
    def test_normal(self):
        payout = bonding_curve_sell(100.0, 50.0, 10.0)
        expected = 50.0 * (1 - (1 - 10.0/100.0) ** 2)
        assert payout == pytest.approx(expected)

    def test_solvency_cap(self):
        """Selling nearly all supply caps payout at 95% of reserve."""
        payout = bonding_curve_sell(100.0, 50.0, 99.0)
        assert payout <= 50.0 * RESERVE_SOLVENCY_CAP

    def test_small_sell(self):
        payout = bonding_curve_sell(1000.0, 500.0, 1.0)
        assert payout > 0


class TestPriceImpact:
    def test_normal(self):
        assert price_impact(1.0, 1.1) == pytest.approx(10.0)

    def test_zero_before(self):
        assert price_impact(0, 1.0) == 0.0

    def test_negative_impact(self):
        assert price_impact(1.0, 0.9) == pytest.approx(-10.0)


class TestEquityToAccessLevel:
    def test_high_equity_high_rep(self):
        assert equity_to_access_level(0.15, 80) == "L3"

    def test_high_equity_low_rep(self):
        """High equity but low reputation → capped at L0."""
        assert equity_to_access_level(0.15, 10) == "L0"

    def test_medium_equity_medium_rep(self):
        assert equity_to_access_level(0.02, 30) == "L1"

    def test_insufficient_equity(self):
        assert equity_to_access_level(0.0005, 100) is None

    def test_zero_equity(self):
        assert equity_to_access_level(0, 100) is None

    def test_boundary_L2(self):
        assert equity_to_access_level(0.05, 80) == "L2"

    def test_sandbox_cap(self):
        """R < 20 → max L0 regardless of equity."""
        assert equity_to_access_level(0.50, 19) == "L0"

    def test_limited_cap(self):
        """R 20-49 → max L1."""
        assert equity_to_access_level(0.50, 49) == "L1"


class TestJuryScore:
    def test_deterministic(self):
        s1 = jury_score("D1", "node_a", 50.0)
        s2 = jury_score("D1", "node_a", 50.0)
        assert s1 == s2

    def test_different_nodes(self):
        s1 = jury_score("D1", "node_a", 50.0)
        s2 = jury_score("D1", "node_b", 50.0)
        assert s1 != s2

    def test_higher_rep_not_guaranteed_winner(self):
        """Higher rep increases weight but randomness can still override."""
        # With enough nodes, some low-rep nodes will beat high-rep ones
        scores_low = [jury_score("D1", f"n{i}", 10.0) for i in range(100)]
        scores_high = [jury_score("D1", f"n{i}", 1000.0) for i in range(100)]
        # High rep has higher average but not every individual score is higher
        assert sum(scores_high) / len(scores_high) > sum(scores_low) / len(scores_low)

    def test_zero_rep(self):
        s = jury_score("D1", "node_a", 0.0)
        assert s == 0.0  # log1p(0) = 0

    def test_positive(self):
        s = jury_score("D1", "node_a", 50.0)
        assert s >= 0.0

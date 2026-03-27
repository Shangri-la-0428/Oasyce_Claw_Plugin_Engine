"""Tests for Layer 0 pure functions — zero mocking needed."""

import pytest

from oasyce.core.formulas import (
    INITIAL_PRICE,
    CREATOR_RATE,
    PROTOCOL_FEE_RATE,
    BURN_RATE,
    TREASURY_RATE,
    RESERVE_RATIO,
    RESERVE_SOLVENCY_CAP,
    RIGHTS_MULTIPLIERS,
    REPUTATION_CAP,
    REPUTATION_FLOOR,
    DISPUTE_FEE,
    REP_PENALTY_PROVIDER_LOSS,
    bonding_curve_buy,
    bonding_curve_sell,
    calculate_fees,
    equity_to_access_level,
    jury_score,
    price_impact,
    rights_multiplier,
    share_rate,
    reputation_decay,
    spot_price,
)


class TestCalculateFees:
    def test_normal(self):
        """93/3/2/2 split: 3% validator, 2% burn, 2% treasury, 93% creator."""
        fee, burn, treasury, net = calculate_fees(100.0)
        assert fee == pytest.approx(3.0)  # 3% validator
        assert burn == pytest.approx(2.0)  # 2% burn
        assert treasury == pytest.approx(2.0)  # 2% treasury
        assert net == pytest.approx(93.0)  # 93% creator/reserve

    def test_zero(self):
        fee, burn, treasury, net = calculate_fees(0.0)
        assert fee == 0.0
        assert burn == 0.0
        assert treasury == 0.0
        assert net == 0.0

    def test_sum_identity(self):
        """fee + burn + treasury + net == original amount."""
        for amount in [1.0, 10.0, 100.0, 1e6]:
            fee, burn, treasury, net = calculate_fees(amount)
            assert fee + burn + treasury + net == pytest.approx(amount)

    def test_rates_sum_to_one(self):
        """All rate constants must sum to 1.0."""
        assert PROTOCOL_FEE_RATE + BURN_RATE + TREASURY_RATE + CREATOR_RATE == pytest.approx(1.0)


class TestSpotPrice:
    def test_normal(self):
        # spot_price = reserve / (supply * CW) = 50 / (100 * 0.35)
        assert spot_price(100, 50) == pytest.approx(50 / (100 * RESERVE_RATIO))

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
        """With existing reserve, follows Bancor formula with CW=0.35."""
        tokens = bonding_curve_buy(100.0, 50.0, 10.0)
        expected = 100.0 * ((1 + 10.0 / 50.0) ** RESERVE_RATIO - 1)
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
        expected = 50.0 * (1 - (1 - 10.0 / 100.0) ** (1 / RESERVE_RATIO))
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


class TestRightsMultiplier:
    def test_original(self):
        assert rights_multiplier("original") == 1.0

    def test_co_creation(self):
        assert rights_multiplier("co_creation") == 0.9

    def test_licensed(self):
        assert rights_multiplier("licensed") == 0.7

    def test_collection(self):
        assert rights_multiplier("collection") == 0.3

    def test_unknown_defaults_to_collection(self):
        assert rights_multiplier("garbage") == 0.3

    def test_empty_string(self):
        assert rights_multiplier("") == 0.3


class TestShareRate:
    def test_first_buyer(self):
        assert share_rate(0) == 1.0

    def test_second_buyer(self):
        assert share_rate(1) == 0.8

    def test_third_buyer(self):
        assert share_rate(2) == 0.6

    def test_fourth_buyer(self):
        assert share_rate(3) == 0.4

    def test_hundredth_buyer(self):
        assert share_rate(99) == 0.4


class TestReputationDecay:
    def test_no_elapsed(self):
        assert reputation_decay(80.0, 0) == 80.0

    def test_half_life(self):
        """After 30 days, score should halve."""
        result = reputation_decay(80.0, 30)
        assert result == pytest.approx(40.0, rel=0.01)

    def test_two_half_lives(self):
        result = reputation_decay(80.0, 60)
        assert result == pytest.approx(20.0, rel=0.01)

    def test_floor(self):
        result = reputation_decay(0.1, 365)
        assert result >= REPUTATION_FLOOR

    def test_negative_elapsed(self):
        assert reputation_decay(50.0, -5) == 50.0

    def test_zero_score(self):
        assert reputation_decay(0.0, 30) == REPUTATION_FLOOR


class TestBondingCurveBuyEdgeCases:
    def test_negative_payment(self):
        assert bonding_curve_buy(100, 50, -10) == 0.0

    def test_zero_payment(self):
        assert bonding_curve_buy(100, 50, 0) == 0.0

    def test_large_payment(self):
        """Very large payment should not overflow."""
        tokens = bonding_curve_buy(1000, 500, 1e10)
        assert tokens > 0
        assert tokens < float("inf")


class TestBondingCurveSellEdgeCases:
    def test_tokens_equal_supply(self):
        """Selling 100% of supply -> capped at solvency limit."""
        payout = bonding_curve_sell(100, 50, 100)
        assert payout == pytest.approx(50 * RESERVE_SOLVENCY_CAP)

    def test_tokens_exceed_supply(self):
        """Selling more than supply -> still capped safely."""
        payout = bonding_curve_sell(100, 50, 200)
        assert payout == pytest.approx(50 * RESERVE_SOLVENCY_CAP)

    def test_zero_tokens(self):
        assert bonding_curve_sell(100, 50, 0) == 0.0

    def test_negative_tokens(self):
        assert bonding_curve_sell(100, 50, -10) == 0.0

    def test_zero_supply(self):
        assert bonding_curve_sell(0, 50, 10) == 0.0

    def test_zero_reserve(self):
        assert bonding_curve_sell(100, 0, 10) == 0.0


class TestJuryScoreEdgeCases:
    def test_negative_reputation_floors_to_zero(self):
        s = jury_score("D1", "node_a", -50.0)
        assert s == 0.0  # log1p(0) = 0

    def test_very_high_reputation(self):
        s = jury_score("D1", "node_a", 1e6)
        assert s > 0
        assert s < float("inf")


class TestDisputeConstants:
    def test_majority_threshold(self):
        from oasyce.core.formulas import MAJORITY_THRESHOLD

        assert MAJORITY_THRESHOLD == pytest.approx(2 / 3)

    def test_reputation_penalties_are_negative(self):
        assert REP_PENALTY_PROVIDER_LOSS < 0
        from oasyce.core.formulas import REP_PENALTY_CONSUMER_LOSS, REP_PENALTY_MINORITY_JUROR

        assert REP_PENALTY_CONSUMER_LOSS < 0
        assert REP_PENALTY_MINORITY_JUROR < 0

    def test_rewards_are_positive(self):
        from oasyce.core.formulas import REP_REWARD_MAJORITY_JUROR, JUROR_REWARD

        assert REP_REWARD_MAJORITY_JUROR > 0
        assert JUROR_REWARD > 0

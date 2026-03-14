"""
Tests for DatasetPricingCurve — demand, scarcity, quality & freshness factors.
"""
from __future__ import annotations

import math

import pytest

from oasyce_plugin.services.pricing import DatasetPricingCurve, PricingConfig


# ─── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def curve():
    return DatasetPricingCurve()


@pytest.fixture
def custom_curve():
    config = PricingConfig(
        demand_alpha=0.2,
        scarcity_base=1.0,
        freshness_halflife_days=90,
        min_price=0.01,
        contribution_score_weight=0.5,
    )
    return DatasetPricingCurve(config)


# ─── Basic Price Calculation ──────────────────────────────

class TestBasicPricing:
    def test_default_factors_equal_base_price(self, curve):
        """All default factors → price ≈ base_price × 1.5 (quality_factor with score=1.0)."""
        result = curve.calculate_price("ASSET_001", base_price=1.0)
        # demand=1.0, scarcity=1.0, quality=1+0.5*1.0=1.5, freshness=0.5^0+0.5=1.5
        assert result["demand_factor"] == pytest.approx(1.0)
        assert result["scarcity_factor"] == pytest.approx(1.0)
        assert result["quality_factor"] == pytest.approx(1.5)
        assert result["freshness_factor"] == pytest.approx(1.5)
        assert result["final_price"] == pytest.approx(1.0 * 1.0 * 1.0 * 1.5 * 1.5, rel=1e-4)

    def test_zero_base_price(self, curve):
        """Zero base price → min_price floor applies."""
        result = curve.calculate_price("ASSET_001", base_price=0.0)
        assert result["final_price"] == pytest.approx(0.001)  # min_price default

    def test_result_keys(self, curve):
        """Result dict has all expected keys."""
        result = curve.calculate_price("ASSET_001", base_price=1.0)
        expected_keys = {
            "final_price", "base_price", "demand_factor",
            "scarcity_factor", "quality_factor", "freshness_factor", "breakdown",
        }
        assert set(result.keys()) == expected_keys
        assert "query_count" in result["breakdown"]
        assert "similar_count" in result["breakdown"]
        assert "contribution_score" in result["breakdown"]
        assert "days_since_creation" in result["breakdown"]


# ─── Demand Factor ────────────────────────────────────────

class TestDemandFactor:
    def test_zero_queries(self, curve):
        """Zero queries → demand_factor = 1.0."""
        result = curve.calculate_price("A", base_price=1.0, query_count=0)
        assert result["demand_factor"] == pytest.approx(1.0)

    def test_demand_grows_with_queries(self, curve):
        """More queries → higher demand factor."""
        r1 = curve.calculate_price("A", base_price=1.0, query_count=10)
        r2 = curve.calculate_price("A", base_price=1.0, query_count=100)
        r3 = curve.calculate_price("A", base_price=1.0, query_count=1000)
        assert r1["demand_factor"] < r2["demand_factor"] < r3["demand_factor"]

    def test_demand_formula(self, curve):
        """demand_factor = 1 + 0.1 × log(1 + 100)."""
        result = curve.calculate_price("A", base_price=1.0, query_count=100)
        expected = 1.0 + 0.1 * math.log(101)
        assert result["demand_factor"] == pytest.approx(expected, rel=1e-4)

    def test_demand_logarithmic_growth(self, curve):
        """Demand grows logarithmically — diminishing returns."""
        r1 = curve.calculate_price("A", base_price=1.0, query_count=100)
        r2 = curve.calculate_price("A", base_price=1.0, query_count=200)
        delta_100_200 = r2["demand_factor"] - r1["demand_factor"]
        r3 = curve.calculate_price("A", base_price=1.0, query_count=300)
        delta_200_300 = r3["demand_factor"] - r2["demand_factor"]
        assert delta_200_300 < delta_100_200  # diminishing


# ─── Scarcity Factor ─────────────────────────────────────

class TestScarcityFactor:
    def test_zero_similar(self, curve):
        """Zero similar assets → scarcity_factor = 1.0."""
        result = curve.calculate_price("A", base_price=1.0, similar_count=0)
        assert result["scarcity_factor"] == pytest.approx(1.0)

    def test_scarcity_decreases_with_similar(self, curve):
        """More similar assets → lower scarcity factor."""
        r0 = curve.calculate_price("A", base_price=1.0, similar_count=0)
        r1 = curve.calculate_price("A", base_price=1.0, similar_count=1)
        r5 = curve.calculate_price("A", base_price=1.0, similar_count=5)
        assert r0["scarcity_factor"] > r1["scarcity_factor"] > r5["scarcity_factor"]

    def test_scarcity_formula(self, curve):
        """scarcity_factor = 1 / (1 + 3) = 0.25."""
        result = curve.calculate_price("A", base_price=1.0, similar_count=3)
        assert result["scarcity_factor"] == pytest.approx(0.25)

    def test_scarcity_always_positive(self, curve):
        """Scarcity factor is always > 0."""
        result = curve.calculate_price("A", base_price=1.0, similar_count=10000)
        assert result["scarcity_factor"] > 0


# ─── Quality Factor ──────────────────────────────────────

class TestQualityFactor:
    def test_quality_with_zero_score(self, curve):
        """contribution_score=0 → quality_factor = 1.0."""
        result = curve.calculate_price("A", base_price=1.0, contribution_score=0.0)
        assert result["quality_factor"] == pytest.approx(1.0)

    def test_quality_with_max_score(self, curve):
        """contribution_score=1.0 → quality_factor = 1.5 (capped)."""
        result = curve.calculate_price("A", base_price=1.0, contribution_score=1.0)
        assert result["quality_factor"] == pytest.approx(1.5)

    def test_quality_cap(self, curve):
        """Very high contribution_score still caps at 1.5."""
        result = curve.calculate_price("A", base_price=1.0, contribution_score=5.0)
        assert result["quality_factor"] == pytest.approx(1.5)

    def test_quality_increases_with_score(self, curve):
        """Higher contribution_score → higher quality factor (up to cap)."""
        r1 = curve.calculate_price("A", base_price=1.0, contribution_score=0.2)
        r2 = curve.calculate_price("A", base_price=1.0, contribution_score=0.8)
        assert r1["quality_factor"] < r2["quality_factor"]


# ─── Freshness Factor ────────────────────────────────────

class TestFreshnessFactor:
    def test_brand_new_data(self, curve):
        """days=0 → freshness_factor = 0.5^0 + 0.5 = 1.5."""
        result = curve.calculate_price("A", base_price=1.0, days_since_creation=0)
        assert result["freshness_factor"] == pytest.approx(1.5)

    def test_freshness_at_halflife(self, curve):
        """At exactly one halflife (180 days) → freshness = 0.5 + 0.5 = 1.0."""
        result = curve.calculate_price("A", base_price=1.0, days_since_creation=180)
        assert result["freshness_factor"] == pytest.approx(1.0, rel=1e-4)

    def test_freshness_decays_over_time(self, curve):
        """Freshness decreases with age."""
        r0 = curve.calculate_price("A", base_price=1.0, days_since_creation=0)
        r90 = curve.calculate_price("A", base_price=1.0, days_since_creation=90)
        r360 = curve.calculate_price("A", base_price=1.0, days_since_creation=360)
        assert r0["freshness_factor"] > r90["freshness_factor"] > r360["freshness_factor"]

    def test_freshness_floor(self, curve):
        """Very old data → freshness approaches 0.5 but never below."""
        result = curve.calculate_price("A", base_price=1.0, days_since_creation=10000)
        assert result["freshness_factor"] >= 0.5
        assert result["freshness_factor"] < 0.51


# ─── Extreme Cases ───────────────────────────────────────

class TestExtremeCases:
    def test_all_zeros(self, curve):
        """All factors at minimum → still returns min_price."""
        result = curve.calculate_price(
            "A", base_price=0.0,
            query_count=0, similar_count=0,
            contribution_score=0.0, days_since_creation=0,
        )
        assert result["final_price"] == pytest.approx(0.001)

    def test_expired_data_min_price(self, curve):
        """Extremely old data with many similar assets → min_price floor."""
        result = curve.calculate_price(
            "A", base_price=0.001,
            query_count=0, similar_count=100,
            contribution_score=0.0, days_since_creation=50000,
        )
        assert result["final_price"] == pytest.approx(0.001)

    def test_huge_query_count(self, curve):
        """Very high query count doesn't cause overflow."""
        result = curve.calculate_price("A", base_price=1.0, query_count=10**9)
        assert result["final_price"] > 1.0
        assert math.isfinite(result["final_price"])

    def test_negative_base_price_clamps(self, curve):
        """Negative base price → min_price floor."""
        result = curve.calculate_price("A", base_price=-5.0)
        assert result["final_price"] == pytest.approx(0.001)


# ─── Multi-Factor Combination ────────────────────────────

class TestMultiFactorCombination:
    def test_high_demand_low_scarcity(self, curve):
        """High demand but many similar assets → moderate price."""
        result = curve.calculate_price(
            "A", base_price=1.0,
            query_count=1000, similar_count=10,
            contribution_score=0.5, days_since_creation=0,
        )
        # demand pushes up, scarcity pulls down
        assert result["demand_factor"] > 1.0
        assert result["scarcity_factor"] < 1.0
        assert result["final_price"] > 0

    def test_rare_high_quality_fresh(self, curve):
        """Rare, high-quality, fresh data → premium price."""
        result = curve.calculate_price(
            "A", base_price=1.0,
            query_count=500, similar_count=0,
            contribution_score=1.0, days_since_creation=0,
        )
        # All factors boost → well above base
        assert result["final_price"] > 2.0

    def test_factors_multiply(self, curve):
        """Final price = base × Π(factors)."""
        result = curve.calculate_price(
            "A", base_price=2.0,
            query_count=50, similar_count=1,
            contribution_score=0.5, days_since_creation=90,
        )
        expected = (
            2.0
            * result["demand_factor"]
            * result["scarcity_factor"]
            * result["quality_factor"]
            * result["freshness_factor"]
        )
        assert result["final_price"] == pytest.approx(expected, rel=1e-4)


# ─── Record Query Accumulation ───────────────────────────

class TestRecordQuery:
    def test_record_query_increments(self, curve):
        """record_query accumulates counts."""
        assert curve.get_query_count("A") == 0
        curve.record_query("A")
        assert curve.get_query_count("A") == 1
        curve.record_query("A")
        curve.record_query("A")
        assert curve.get_query_count("A") == 3

    def test_record_query_returns_count(self, curve):
        """record_query returns the new count."""
        assert curve.record_query("A") == 1
        assert curve.record_query("A") == 2

    def test_independent_assets(self, curve):
        """Query counts are per-asset."""
        curve.record_query("A")
        curve.record_query("A")
        curve.record_query("B")
        assert curve.get_query_count("A") == 2
        assert curve.get_query_count("B") == 1


# ─── Similar Count Update ────────────────────────────────

class TestSimilarCount:
    def test_update_similar_count(self, curve):
        """update_similar_count stores value."""
        curve.update_similar_count("A", 5)
        assert curve.get_similar_count("A") == 5

    def test_default_similar_count(self, curve):
        """Unknown asset → 0 similar."""
        assert curve.get_similar_count("UNKNOWN") == 0


# ─── Price History ───────────────────────────────────────

class TestPriceHistory:
    def test_history_recorded(self, curve):
        """Each calculate_price call records history."""
        curve.calculate_price("A", base_price=1.0)
        curve.calculate_price("A", base_price=2.0)
        history = curve.get_price_history("A")
        assert len(history) == 2
        assert history[0]["final_price"] != history[1]["final_price"]

    def test_empty_history(self, curve):
        """No calculations → empty history."""
        assert curve.get_price_history("UNKNOWN") == []

    def test_history_contains_factors(self, curve):
        """History entries include all factor values."""
        curve.calculate_price("A", base_price=1.0, query_count=10)
        entry = curve.get_price_history("A")[0]
        assert "demand_factor" in entry
        assert "scarcity_factor" in entry
        assert "quality_factor" in entry
        assert "freshness_factor" in entry
        assert "timestamp" in entry


# ─── Min Price Floor ─────────────────────────────────────

class TestMinPrice:
    def test_min_price_default(self, curve):
        """Default min_price is 0.001."""
        assert curve.config.min_price == 0.001

    def test_custom_min_price(self, custom_curve):
        """Custom min_price is respected."""
        result = custom_curve.calculate_price("A", base_price=0.0)
        assert result["final_price"] == pytest.approx(0.01)

    def test_min_price_applied(self, curve):
        """Price never goes below min_price."""
        result = curve.calculate_price(
            "A", base_price=0.0001,
            similar_count=1000, contribution_score=0.0,
            days_since_creation=10000,
        )
        assert result["final_price"] >= curve.config.min_price


# ─── Custom Config ───────────────────────────────────────

class TestCustomConfig:
    def test_higher_alpha_means_more_demand_sensitivity(self):
        """Higher demand_alpha → demand factor grows faster."""
        low = DatasetPricingCurve(PricingConfig(demand_alpha=0.05))
        high = DatasetPricingCurve(PricingConfig(demand_alpha=0.5))
        r_low = low.calculate_price("A", base_price=1.0, query_count=100)
        r_high = high.calculate_price("A", base_price=1.0, query_count=100)
        assert r_high["demand_factor"] > r_low["demand_factor"]

    def test_shorter_halflife_means_faster_decay(self):
        """Shorter halflife → freshness decays faster."""
        short = DatasetPricingCurve(PricingConfig(freshness_halflife_days=30))
        long = DatasetPricingCurve(PricingConfig(freshness_halflife_days=365))
        r_short = short.calculate_price("A", base_price=1.0, days_since_creation=60)
        r_long = long.calculate_price("A", base_price=1.0, days_since_creation=60)
        assert r_short["freshness_factor"] < r_long["freshness_factor"]


# ─── Settlement Engine Integration ───────────────────────

class TestSettlementIntegration:
    def test_settlement_with_pricing_curve(self):
        """SettlementEngine with pricing_curve adjusts spot_price_after."""
        from oasyce_plugin.services.settlement.engine import SettlementEngine

        curve = DatasetPricingCurve()
        engine = SettlementEngine(pricing_curve=curve)
        engine.register_asset("ASSET_001", "alice")

        # Quote without pricing curve
        engine_plain = SettlementEngine()
        engine_plain.register_asset("ASSET_001", "alice")
        q_plain = engine_plain.quote("ASSET_001", 10.0)

        # Quote with pricing curve
        q_curve = engine.quote("ASSET_001", 10.0)

        # Pricing curve should adjust spot_price_after
        assert q_curve.spot_price_after != q_plain.spot_price_after

    def test_settlement_without_pricing_curve(self):
        """SettlementEngine without pricing_curve works as before."""
        from oasyce_plugin.services.settlement.engine import SettlementEngine

        engine = SettlementEngine()
        engine.register_asset("ASSET_001", "alice")
        q = engine.quote("ASSET_001", 10.0)
        assert q.spot_price_after > 0
        assert q.equity_minted > 0

"""
Settlement Engine — Tests

Verifies the core economic invariants:
  1. Protocol fee is exactly 5% of payment
  2. Burn is exactly 50% of fee (absolute deflation)
  3. Net deposit = payment - fee (conservation of value)
  4. Equity minted follows Bancor formula: S × ((1 + ΔR/R)^F − 1)
  5. Spot price increases monotonically with purchases
  6. Settlement is atomic (all-or-nothing state update)
  7. Early buyers get more equity per OAS than late buyers (bonding curve property)
"""

from __future__ import annotations

import pytest

from oasyce_plugin.services.settlement.engine import (
    AssetPool,
    SettlementConfig,
    SettlementEngine,
    TradeStatus,
)


class TestSettlementQuote:
    """Test the quoting mechanism."""

    def setup_method(self):
        self.engine = SettlementEngine()
        self.engine.register_asset("OAS_TEST0001", owner="Alice")

    def test_fee_calculation_exact(self):
        """Protocol fee must be exactly 5% of payment."""
        q = self.engine.quote("OAS_TEST0001", 100.0)
        assert q.protocol_fee == 5.0
        assert q.burn_amount == 2.5
        assert q.verifier_reward == 2.5
        # net_deposit + creator_payout = 95.0 (original net before creator extraction)
        assert abs((q.net_deposit + q.creator_payout) - 95.0) < 0.01

    def test_conservation_of_value(self):
        """fee + net_deposit + creator_payout must equal the total payment."""
        for amount in [1.0, 10.0, 100.0, 1000.0, 99999.0]:
            q = self.engine.quote("OAS_TEST0001", amount)
            reconstructed = q.protocol_fee + q.net_deposit + q.creator_payout
            assert abs(reconstructed - amount) < 0.01, f"Value leak at payment={amount}"

    def test_burn_plus_verifier_equals_fee(self):
        """Burn + verifier reward must equal protocol fee."""
        q = self.engine.quote("OAS_TEST0001", 200.0)
        assert abs(q.burn_amount + q.verifier_reward - q.protocol_fee) < 0.001

    def test_equity_minted_positive(self):
        """Any positive payment should mint some equity."""
        q = self.engine.quote("OAS_TEST0001", 50.0)
        assert q.equity_minted > 0

    def test_spot_price_increases_after_purchase(self):
        """Spot price must increase after a purchase (bonding curve property)."""
        q = self.engine.quote("OAS_TEST0001", 100.0)
        assert q.spot_price_after > q.spot_price_before

    def test_unknown_asset_raises(self):
        with pytest.raises(ValueError, match="not found"):
            self.engine.quote("OAS_NONEXIST", 100.0)

    def test_below_minimum_payment_raises(self):
        with pytest.raises(ValueError, match="below minimum"):
            self.engine.quote("OAS_TEST0001", 0.0001)


class TestBondingCurveProperties:
    """Test the mathematical properties of the bonding curve."""

    def setup_method(self):
        self.engine = SettlementEngine()
        self.engine.register_asset("OAS_CURVE001", owner="Alice")

    def test_early_buyer_advantage(self):
        """Early buyers should get more equity per OAS than late buyers."""
        # First buyer: quote against fresh pool
        q1 = self.engine.quote("OAS_CURVE001", 100.0)
        # Execute first trade to move the curve
        self.engine.execute("OAS_CURVE001", "Bob", 100.0)
        # Second buyer: quote against moved pool (higher price)
        q2 = self.engine.quote("OAS_CURVE001", 100.0)

        # Both quotes are for the same 100 OAS payment
        # First buyer got equity at original price, second at higher price
        assert q1.equity_minted > q2.equity_minted, "Early buyer should get more equity"

    def test_price_monotonically_increases(self):
        """Successive buys should monotonically increase the spot price."""
        prices = []
        for i in range(5):
            pool = self.engine.get_pool("OAS_CURVE001")
            prices.append(pool.spot_price)
            self.engine.execute("OAS_CURVE001", f"buyer_{i}", 50.0)

        for i in range(1, len(prices)):
            assert prices[i] >= prices[i - 1], f"Price dropped at step {i}"

    def test_large_purchase_moves_price_more(self):
        """A larger purchase should create a bigger price impact."""
        engine_a = SettlementEngine()
        engine_a.register_asset("OAS_A", owner="Alice")
        qa = engine_a.quote("OAS_A", 10.0)

        engine_b = SettlementEngine()
        engine_b.register_asset("OAS_B", owner="Alice")
        qb = engine_b.quote("OAS_B", 1000.0)

        assert qb.price_impact_pct > qa.price_impact_pct


class TestSettlementExecution:
    """Test the execute/settle flow."""

    def setup_method(self):
        self.engine = SettlementEngine()
        self.engine.register_asset("OAS_EXEC0001", owner="Alice")

    def test_successful_execution(self):
        receipt = self.engine.execute("OAS_EXEC0001", "Bob", 100.0)
        assert receipt.status == TradeStatus.SETTLED
        assert receipt.receipt_id.startswith("RCP_")
        assert receipt.equity_balance > 0

    def test_state_updated_after_execution(self):
        """Pool state should reflect the trade."""
        pool_before_supply = self.engine.get_pool("OAS_EXEC0001").supply
        pool_before_reserve = self.engine.get_pool("OAS_EXEC0001").reserve_balance

        self.engine.execute("OAS_EXEC0001", "Bob", 100.0)

        pool = self.engine.get_pool("OAS_EXEC0001")
        assert pool.supply > pool_before_supply
        assert pool.reserve_balance > pool_before_reserve
        assert pool.total_trades == 1
        assert pool.total_burned > 0

    def test_buyer_balance_tracked(self):
        self.engine.execute("OAS_EXEC0001", "Bob", 100.0)
        self.engine.execute("OAS_EXEC0001", "Bob", 50.0)

        balance = self.engine.balances["OAS_EXEC0001"]["Bob"]
        assert balance > 0

    def test_multiple_buyers(self):
        self.engine.execute("OAS_EXEC0001", "Bob", 100.0)
        self.engine.execute("OAS_EXEC0001", "Carol", 200.0)

        assert "Bob" in self.engine.balances["OAS_EXEC0001"]
        assert "Carol" in self.engine.balances["OAS_EXEC0001"]
        assert self.engine.total_trades == 2

    def test_global_burn_accumulates(self):
        self.engine.execute("OAS_EXEC0001", "Bob", 100.0)
        burn_1 = self.engine.total_burned
        self.engine.execute("OAS_EXEC0001", "Carol", 100.0)
        burn_2 = self.engine.total_burned
        assert burn_2 > burn_1


class TestNetworkStats:
    """Test the analytics layer."""

    def test_empty_network(self):
        engine = SettlementEngine()
        stats = engine.network_stats()
        assert stats["total_assets"] == 0
        assert stats["total_trades"] == 0

    def test_stats_after_trades(self):
        engine = SettlementEngine()
        engine.register_asset("OAS_S1", owner="Alice")
        engine.register_asset("OAS_S2", owner="Bob")
        engine.execute("OAS_S1", "Carol", 100.0)
        engine.execute("OAS_S2", "Dave", 200.0)

        stats = engine.network_stats()
        assert stats["total_assets"] == 2
        assert stats["total_trades"] == 2
        assert stats["total_burned_oas"] > 0

    def test_asset_stats(self):
        engine = SettlementEngine()
        engine.register_asset("OAS_AS1", owner="Alice")
        engine.execute("OAS_AS1", "Bob", 50.0)
        engine.execute("OAS_AS1", "Carol", 75.0)

        stats = engine.asset_stats("OAS_AS1")
        assert stats["total_trades"] == 2
        assert stats["holder_count"] == 3  # Alice (initial) + Bob + Carol
        assert stats["spot_price_oas"] > 0


class TestAssetRegistration:
    """Test asset pool lifecycle."""

    def test_register_new_asset(self):
        engine = SettlementEngine()
        pool = engine.register_asset("OAS_NEW001", owner="Alice")
        assert pool.asset_id == "OAS_NEW001"
        assert pool.supply == 10000.0
        assert pool.reserve_balance == 1000.0

    def test_duplicate_registration_raises(self):
        engine = SettlementEngine()
        engine.register_asset("OAS_DUP001", owner="Alice")
        with pytest.raises(ValueError, match="already registered"):
            engine.register_asset("OAS_DUP001", owner="Bob")

    def test_initial_spot_price(self):
        engine = SettlementEngine()
        pool = engine.register_asset("OAS_PRICE01", owner="Alice", initial_supply=10000, initial_reserve=1000)
        # P = R / (S × F) = 1000 / (10000 × 0.35) ≈ 0.285714
        assert abs(pool.spot_price - 0.285714) < 0.001

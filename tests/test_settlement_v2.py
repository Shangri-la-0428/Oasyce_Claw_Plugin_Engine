"""Tests for settlement engine v2: buyer collateral, free assets, disputes."""
import pytest
from oasyce_plugin.services.settlement.engine import (
    SettlementConfig,
    SettlementEngine,
    PriceModel,
)


@pytest.fixture
def engine():
    return SettlementEngine()


class TestFreeAssets:
    def test_register_free_asset(self, engine):
        pool = engine.register_asset("FREE_001", "alice", price_model="free")
        assert pool.price_model == "free"
        assert pool.supply == 0
        assert pool.reserve_balance == 0

    def test_free_asset_no_purchase(self, engine):
        engine.register_asset("FREE_001", "alice", price_model="free")
        with pytest.raises(ValueError, match="free"):
            engine.quote("FREE_001", 100)

    def test_free_asset_not_in_balances(self, engine):
        engine.register_asset("FREE_001", "alice", price_model="free")
        assert "FREE_001" not in engine.balances


class TestBuyerCollateral:
    def test_collateral_locked_on_purchase(self, engine):
        engine.register_asset("ASSET_001", "alice")
        receipt = engine.execute("ASSET_001", "bob", 100)
        assert receipt.status.value == "SETTLED"
        assert engine.collaterals["ASSET_001"]["bob"] == pytest.approx(10.0, rel=0.01)

    def test_collateral_accumulates(self, engine):
        engine.register_asset("ASSET_001", "alice")
        engine.execute("ASSET_001", "bob", 100)
        engine.execute("ASSET_001", "bob", 100)
        assert engine.collaterals["ASSET_001"]["bob"] == pytest.approx(20.0, rel=0.01)


class TestBuyerSlashing:
    def test_slash_full(self, engine):
        engine.register_asset("ASSET_001", "alice")
        engine.execute("ASSET_001", "bob", 100)
        result = engine.slash_buyer("ASSET_001", "bob", reason="data_leak", slash_pct=1.0)
        assert result["collateral_burned"] == pytest.approx(10.0, rel=0.01)
        assert result["shares_frozen"] is True
        assert result["banned"] is True
        assert "bob" in engine.banned

    def test_slash_partial(self, engine):
        engine.register_asset("ASSET_001", "alice")
        engine.execute("ASSET_001", "bob", 100)
        result = engine.slash_buyer("ASSET_001", "bob", reason="license_violation", slash_pct=0.5)
        assert result["collateral_remaining"] == pytest.approx(5.0, rel=0.01)
        assert result["banned"] is False

    def test_banned_buyer_cannot_buy(self, engine):
        engine.register_asset("ASSET_001", "alice")
        engine.execute("ASSET_001", "bob", 100)
        engine.slash_buyer("ASSET_001", "bob", slash_pct=1.0)
        receipt = engine.execute("ASSET_001", "bob", 50)
        assert receipt.status.value == "FAILED"
        assert "banned" in receipt.error

    def test_slash_no_collateral_raises(self, engine):
        engine.register_asset("ASSET_001", "alice")
        with pytest.raises(ValueError, match="no collateral"):
            engine.slash_buyer("ASSET_001", "bob")


class TestDispute:
    def test_file_dispute(self, engine):
        engine.register_asset("ASSET_001", "alice")
        dispute = engine.file_dispute("ASSET_001", "charlie", "git_commit", "abc123")
        assert dispute["status"] == "pending"
        assert dispute["current_owner"] == "alice"
        assert dispute["challenger"] == "charlie"

    def test_resolve_upheld(self, engine):
        engine.register_asset("ASSET_001", "alice")
        engine.execute("ASSET_001", "bob", 100)
        dispute = engine.file_dispute("ASSET_001", "charlie", "git_commit", "abc123")
        result = engine.resolve_dispute(dispute["dispute_id"], upheld=True)
        assert result["result"] == "upheld"
        assert result["new_owner"] == "charlie"
        assert result["old_owner_banned"] is True
        # Verify ownership transferred
        pool = engine.get_pool("ASSET_001")
        assert pool.owner == "charlie"
        assert "alice" in engine.banned

    def test_resolve_rejected(self, engine):
        engine.register_asset("ASSET_001", "alice")
        dispute = engine.file_dispute("ASSET_001", "charlie", "git_commit", "abc123")
        burned_before = engine.total_burned
        result = engine.resolve_dispute(dispute["dispute_id"], upheld=False)
        assert result["result"] == "rejected"
        assert result["challenger_stake_burned"] == 1000.0
        assert engine.total_burned == burned_before + 1000.0

    def test_banned_cannot_dispute(self, engine):
        engine.register_asset("ASSET_001", "alice")
        engine.banned.add("evil")
        with pytest.raises(ValueError, match="banned"):
            engine.file_dispute("ASSET_001", "evil", "git_commit", "abc")

    def test_banned_cannot_register(self, engine):
        engine.banned.add("evil")
        with pytest.raises(ValueError, match="banned"):
            engine.register_asset("ASSET_002", "evil")

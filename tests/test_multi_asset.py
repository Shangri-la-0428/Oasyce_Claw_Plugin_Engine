"""
Tests for Phase 3 multi-asset support.

Covers:
- Asset type registration (valid, duplicate, invalid)
- Multi-asset balance management (credit, debit, get)
- Cross-asset transfers
- Per-asset-type validation isolation
- OAS native asset backward compatibility
- Edge cases (zero balance, overdraft, self-transfer)
- ConsensusEngine facade integration
- Resource dataclass
"""

import pytest

from oasyce_plugin.consensus import ConsensusEngine
from oasyce_plugin.consensus.core.types import (
    AssetType,
    Resource,
    Operation,
    OperationType,
    KNOWN_ASSET_TYPES,
    ASSET_DECIMALS,
    OAS_DECIMALS,
    to_units,
    from_units,
)
from oasyce_plugin.consensus.assets.registry import AssetDefinition, AssetRegistry
from oasyce_plugin.consensus.assets.balances import MultiAssetBalance


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    e = ConsensusEngine(db_path=":memory:")
    yield e
    e.close()


@pytest.fixture
def registry():
    return AssetRegistry()


# ══════════════════════════════════════════════════════════════════════
#  1. Asset Registry
# ══════════════════════════════════════════════════════════════════════


class TestAssetRegistry:
    """Asset type registration tests."""

    def test_oas_pre_registered(self, registry):
        """OAS is always pre-registered as native."""
        info = registry.get_asset_info("OAS")
        assert info is not None
        assert info.is_native is True
        assert info.decimals == 8
        assert info.name == "Oasyce Token"

    def test_register_new_asset(self, registry):
        """Register a new asset type successfully."""
        defn = AssetDefinition(
            asset_type="USDC", name="USD Coin", decimals=6, issuer="issuer_addr"
        )
        result = registry.register_asset(defn)
        assert result["ok"] is True
        assert result["asset_type"] == "USDC"
        info = registry.get_asset_info("USDC")
        assert info.name == "USD Coin"
        assert info.decimals == 6
        assert info.issuer == "issuer_addr"

    def test_register_duplicate_fails(self, registry):
        """Registering the same asset type twice fails."""
        defn = AssetDefinition(
            asset_type="USDC", name="USD Coin", decimals=6, issuer="a"
        )
        result1 = registry.register_asset(defn)
        assert result1["ok"] is True
        result2 = registry.register_asset(defn)
        assert result2["ok"] is False
        assert "already registered" in result2["error"]

    def test_register_oas_duplicate_fails(self, registry):
        """Cannot re-register native OAS."""
        defn = AssetDefinition(
            asset_type="OAS", name="Fake", decimals=8, issuer="x"
        )
        result = registry.register_asset(defn)
        assert result["ok"] is False

    def test_register_empty_type_fails(self, registry):
        """Empty asset_type is rejected."""
        defn = AssetDefinition(asset_type="", name="Empty", decimals=0, issuer="x")
        result = registry.register_asset(defn)
        assert result["ok"] is False

    def test_register_invalid_decimals(self, registry):
        """Decimals outside 0-18 are rejected."""
        defn = AssetDefinition(
            asset_type="BAD", name="Bad", decimals=19, issuer="x"
        )
        result = registry.register_asset(defn)
        assert result["ok"] is False
        defn2 = AssetDefinition(
            asset_type="BAD2", name="Bad2", decimals=-1, issuer="x"
        )
        result2 = registry.register_asset(defn2)
        assert result2["ok"] is False

    def test_is_registered(self, registry):
        assert registry.is_registered("OAS") is True
        assert registry.is_registered("NONEXIST") is False

    def test_list_assets(self, registry):
        """list_assets returns at least OAS."""
        assets = registry.list_assets()
        assert len(assets) >= 1
        types = [a.asset_type for a in assets]
        assert "OAS" in types

    def test_to_dict_list(self, registry):
        dicts = registry.to_dict_list()
        assert isinstance(dicts, list)
        assert dicts[0]["asset_type"] == "OAS"
        assert "name" in dicts[0]

    def test_get_unknown_returns_none(self, registry):
        assert registry.get_asset_info("FAKE") is None

    def test_register_data_credit(self, registry):
        defn = AssetDefinition(
            asset_type="DATA_CREDIT", name="Data Credit", decimals=0, issuer="sys"
        )
        result = registry.register_asset(defn)
        assert result["ok"] is True

    def test_register_capability_token(self, registry):
        defn = AssetDefinition(
            asset_type="CAPABILITY_TOKEN", name="Cap Token", decimals=0, issuer="sys"
        )
        result = registry.register_asset(defn)
        assert result["ok"] is True


# ══════════════════════════════════════════════════════════════════════
#  2. Multi-Asset Balance Management
# ══════════════════════════════════════════════════════════════════════


class TestMultiAssetBalance:
    """Balance CRUD operations."""

    def test_initial_balance_zero(self, engine):
        assert engine.get_balance("addr1", "OAS") == 0

    def test_credit_and_read(self, engine):
        new_bal = engine.credit_balance("addr1", "OAS", 1000)
        assert new_bal == 1000
        assert engine.get_balance("addr1", "OAS") == 1000

    def test_multiple_credits(self, engine):
        engine.credit_balance("addr1", "OAS", 500)
        engine.credit_balance("addr1", "OAS", 300)
        assert engine.get_balance("addr1", "OAS") == 800

    def test_debit(self, engine):
        engine.credit_balance("addr1", "OAS", 1000)
        remaining = engine.state.balances.debit("addr1", "OAS", 400)
        assert remaining == 600

    def test_debit_overdraft_fails(self, engine):
        engine.credit_balance("addr1", "OAS", 100)
        with pytest.raises(ValueError, match="insufficient"):
            engine.state.balances.debit("addr1", "OAS", 200)

    def test_debit_zero_balance(self, engine):
        with pytest.raises(ValueError, match="insufficient"):
            engine.state.balances.debit("addr1", "OAS", 1)

    def test_credit_negative_fails(self, engine):
        with pytest.raises(ValueError, match="non-negative"):
            engine.state.balances.credit("addr1", "OAS", -100)

    def test_multi_asset_isolation(self, engine):
        """Balances for different asset types are independent."""
        engine.credit_balance("addr1", "OAS", 1000)
        engine.credit_balance("addr1", "USDC", 500)
        assert engine.get_balance("addr1", "OAS") == 1000
        assert engine.get_balance("addr1", "USDC") == 500

    def test_get_all_balances(self, engine):
        engine.credit_balance("addr1", "OAS", 1000)
        engine.credit_balance("addr1", "USDC", 500)
        balances = engine.get_all_balances("addr1")
        assert balances == {"OAS": 1000, "USDC": 500}

    def test_get_all_balances_empty(self, engine):
        balances = engine.get_all_balances("nobody")
        assert balances == {}

    def test_total_supply(self, engine):
        engine.credit_balance("a", "OAS", 1000)
        engine.credit_balance("b", "OAS", 2000)
        supply = engine.state.balances.get_total_supply("OAS")
        assert supply == 3000

    def test_total_supply_empty(self, engine):
        assert engine.state.balances.get_total_supply("NONEXIST") == 0


# ══════════════════════════════════════════════════════════════════════
#  3. Transfers (via balance layer)
# ══════════════════════════════════════════════════════════════════════


class TestBalanceTransfer:
    """Direct balance-layer transfer tests."""

    def test_basic_transfer(self, engine):
        engine.credit_balance("alice", "OAS", 1000)
        result = engine.state.balances.transfer("alice", "bob", "OAS", 400)
        assert result["ok"] is True
        assert engine.get_balance("alice", "OAS") == 600
        assert engine.get_balance("bob", "OAS") == 400

    def test_transfer_overdraft_fails(self, engine):
        engine.credit_balance("alice", "OAS", 100)
        result = engine.state.balances.transfer("alice", "bob", "OAS", 200)
        assert result["ok"] is False
        assert "insufficient" in result["error"]

    def test_transfer_zero_fails(self, engine):
        result = engine.state.balances.transfer("alice", "bob", "OAS", 0)
        assert result["ok"] is False

    def test_transfer_negative_fails(self, engine):
        result = engine.state.balances.transfer("alice", "bob", "OAS", -1)
        assert result["ok"] is False

    def test_transfer_to_self_fails(self, engine):
        engine.credit_balance("alice", "OAS", 1000)
        result = engine.state.balances.transfer("alice", "alice", "OAS", 100)
        assert result["ok"] is False
        assert "self" in result["error"]

    def test_transfer_usdc(self, engine):
        """Transfer a non-OAS asset type."""
        engine.credit_balance("alice", "USDC", 5000)
        result = engine.state.balances.transfer("alice", "bob", "USDC", 2000)
        assert result["ok"] is True
        assert result["asset_type"] == "USDC"
        assert engine.get_balance("alice", "USDC") == 3000
        assert engine.get_balance("bob", "USDC") == 2000

    def test_transfer_does_not_affect_other_assets(self, engine):
        """Transferring OAS doesn't change USDC balance."""
        engine.credit_balance("alice", "OAS", 1000)
        engine.credit_balance("alice", "USDC", 500)
        engine.state.balances.transfer("alice", "bob", "OAS", 300)
        assert engine.get_balance("alice", "USDC") == 500

    def test_transfer_history(self, engine):
        engine.credit_balance("alice", "OAS", 1000)
        engine.state.balances.transfer("alice", "bob", "OAS", 300)
        engine.state.balances.transfer("alice", "bob", "OAS", 200)
        history = engine.state.balances.get_transfer_history("alice")
        assert len(history) == 2


# ══════════════════════════════════════════════════════════════════════
#  4. Transfers via ConsensusEngine (operation pipeline)
# ══════════════════════════════════════════════════════════════════════


class TestEngineTransfer:
    """Transfer via the apply_operation state machine."""

    def test_engine_transfer_oas(self, engine):
        engine.credit_balance("alice", "OAS", to_units(10))
        result = engine.transfer_asset("alice", "bob", "OAS", to_units(3))
        assert result["ok"] is True
        assert engine.get_balance("alice", "OAS") == to_units(7)
        assert engine.get_balance("bob", "OAS") == to_units(3)

    def test_engine_transfer_unregistered_asset_fails(self, engine):
        """Transfer of unregistered asset type fails validation."""
        engine.credit_balance("alice", "FAKE", 1000)
        result = engine.transfer_asset("alice", "bob", "FAKE", 500)
        assert result["ok"] is False
        assert "unknown asset type" in result["error"]

    def test_engine_transfer_insufficient_balance(self, engine):
        result = engine.transfer_asset("alice", "bob", "OAS", 1)
        assert result["ok"] is False
        assert "insufficient" in result["error"]

    def test_engine_transfer_to_self(self, engine):
        engine.credit_balance("alice", "OAS", 1000)
        result = engine.transfer_asset("alice", "alice", "OAS", 100)
        assert result["ok"] is False

    def test_engine_transfer_missing_addresses(self, engine):
        """Missing from/to addresses fail validation."""
        op = Operation(
            op_type=OperationType.TRANSFER,
            validator_id="",
            amount=100,
            asset_type="OAS",
            from_addr="",
            to_addr="bob",
        )
        result = engine.apply(op)
        assert result["ok"] is False
        assert "from_addr" in result["error"]

    def test_engine_transfer_registered_custom_asset(self, engine):
        """Register custom asset, credit, then transfer."""
        reg = engine.register_asset_type("USDC", "USD Coin", 6, "admin")
        assert reg["ok"] is True
        engine.credit_balance("alice", "USDC", 1_000_000)
        result = engine.transfer_asset("alice", "bob", "USDC", 500_000)
        assert result["ok"] is True
        assert engine.get_balance("alice", "USDC") == 500_000
        assert engine.get_balance("bob", "USDC") == 500_000


# ══════════════════════════════════════════════════════════════════════
#  5. Asset Registration via Engine
# ══════════════════════════════════════════════════════════════════════


class TestEngineAssetRegistration:
    """Register asset types through the operation pipeline."""

    def test_register_via_engine(self, engine):
        result = engine.register_asset_type("USDC", "USD Coin", 6, "admin")
        assert result["ok"] is True
        info = engine.asset_registry.get_asset_info("USDC")
        assert info.name == "USD Coin"
        assert info.decimals == 6

    def test_register_duplicate_via_engine(self, engine):
        engine.register_asset_type("USDC", "USD Coin", 6, "admin")
        result = engine.register_asset_type("USDC", "Another", 6, "admin2")
        assert result["ok"] is False
        assert "already registered" in result["error"]

    def test_register_oas_via_engine_fails(self, engine):
        result = engine.register_asset_type("OAS", "Fake", 8, "x")
        assert result["ok"] is False

    def test_register_without_issuer_fails(self, engine):
        """from_addr (issuer) is required."""
        op = Operation(
            op_type=OperationType.REGISTER_ASSET,
            validator_id="",
            asset_type="NEW",
            reason="New Token",
            commission_rate=8,
            from_addr="",
        )
        result = engine.apply(op)
        assert result["ok"] is False
        assert "issuer" in result["error"]

    def test_register_data_credit_via_engine(self, engine):
        result = engine.register_asset_type("DATA_CREDIT", "Data Credit", 0, "sys")
        assert result["ok"] is True
        assert engine.asset_registry.is_registered("DATA_CREDIT")

    def test_register_capability_token_via_engine(self, engine):
        result = engine.register_asset_type(
            "CAPABILITY_TOKEN", "Capability Token", 0, "sys"
        )
        assert result["ok"] is True

    def test_list_asset_types(self, engine):
        engine.register_asset_type("USDC", "USD Coin", 6, "admin")
        assets = engine.list_asset_types()
        types = [a["asset_type"] for a in assets]
        assert "OAS" in types
        assert "USDC" in types


# ══════════════════════════════════════════════════════════════════════
#  6. OAS Backward Compatibility
# ══════════════════════════════════════════════════════════════════════


class TestOASBackwardCompat:
    """Ensure existing OAS consensus logic is unaffected."""

    def test_oas_validator_register_still_works(self, engine):
        result = engine.register_validator("val1", to_units(100), 1000, block_height=1)
        assert result["ok"] is True

    def test_oas_delegate_still_works(self, engine):
        engine.register_validator("val1", to_units(100), 1000, block_height=1)
        result = engine.delegate("del1", "val1", to_units(50), block_height=2)
        assert result["ok"] is True

    def test_oas_is_default_asset_type(self):
        """Operation default asset_type is OAS."""
        op = Operation(op_type=OperationType.REGISTER, validator_id="v1", amount=100)
        assert op.asset_type == "OAS"

    def test_oas_decimals_unchanged(self):
        assert OAS_DECIMALS == 10 ** 8

    def test_to_from_units_unchanged(self):
        assert to_units(1.0) == 100_000_000
        assert from_units(100_000_000) == 1.0


# ══════════════════════════════════════════════════════════════════════
#  7. Resource Dataclass
# ══════════════════════════════════════════════════════════════════════


class TestResource:
    """Resource frozen dataclass tests."""

    def test_create_resource(self):
        r = Resource(type="asset", id="OAS", amount=100)
        assert r.type == "asset"
        assert r.id == "OAS"
        assert r.amount == 100
        assert r.asset_type == "OAS"
        assert r.metadata == {}

    def test_resource_with_asset_type(self):
        r = Resource(type="asset", id="USDC", amount=500, asset_type="USDC")
        assert r.asset_type == "USDC"

    def test_resource_frozen(self):
        r = Resource(type="asset", id="OAS", amount=100)
        with pytest.raises(AttributeError):
            r.amount = 200

    def test_resource_with_metadata(self):
        r = Resource(
            type="right", id="GPT4_INFERENCE", amount=1,
            asset_type="CAPABILITY_TOKEN",
            metadata={"model": "gpt-4"},
        )
        assert r.metadata["model"] == "gpt-4"


# ══════════════════════════════════════════════════════════════════════
#  8. Constants and Type System
# ══════════════════════════════════════════════════════════════════════


class TestConstants:
    def test_known_asset_types(self):
        assert "OAS" in KNOWN_ASSET_TYPES
        assert "USDC" in KNOWN_ASSET_TYPES
        assert "DATA_CREDIT" in KNOWN_ASSET_TYPES
        assert "CAPABILITY_TOKEN" in KNOWN_ASSET_TYPES

    def test_asset_decimals(self):
        assert ASSET_DECIMALS["OAS"] == 8
        assert ASSET_DECIMALS["USDC"] == 6
        assert ASSET_DECIMALS["DATA_CREDIT"] == 0

    def test_operation_type_transfer(self):
        assert OperationType.TRANSFER.value == "transfer"

    def test_operation_type_register_asset(self):
        assert OperationType.REGISTER_ASSET.value == "register_asset"


# ══════════════════════════════════════════════════════════════════════
#  9. Validation Isolation
# ══════════════════════════════════════════════════════════════════════


class TestValidationIsolation:
    """Per-asset-type validation does not cross-contaminate."""

    def test_oas_transfer_does_not_affect_usdc(self, engine):
        engine.register_asset_type("USDC", "USD Coin", 6, "admin")
        engine.credit_balance("alice", "OAS", 1000)
        engine.credit_balance("alice", "USDC", 500)
        # Transfer OAS
        engine.transfer_asset("alice", "bob", "OAS", 300)
        # USDC balance unchanged
        assert engine.get_balance("alice", "USDC") == 500
        # Can still transfer USDC
        result = engine.transfer_asset("alice", "bob", "USDC", 200)
        assert result["ok"] is True

    def test_overdraft_one_asset_doesnt_block_another(self, engine):
        engine.register_asset_type("USDC", "USD Coin", 6, "admin")
        engine.credit_balance("alice", "OAS", 100)
        engine.credit_balance("alice", "USDC", 1000)
        # OAS overdraft
        fail = engine.transfer_asset("alice", "bob", "OAS", 200)
        assert fail["ok"] is False
        # USDC still works
        ok = engine.transfer_asset("alice", "bob", "USDC", 500)
        assert ok["ok"] is True


# ══════════════════════════════════════════════════════════════════════
#  10. Edge Cases
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_transfer_exact_balance(self, engine):
        """Transfer entire balance succeeds."""
        engine.credit_balance("alice", "OAS", 1000)
        result = engine.transfer_asset("alice", "bob", "OAS", 1000)
        assert result["ok"] is True
        assert engine.get_balance("alice", "OAS") == 0
        assert engine.get_balance("bob", "OAS") == 1000

    def test_credit_zero(self, engine):
        """Credit zero is a no-op but succeeds."""
        result = engine.credit_balance("alice", "OAS", 0)
        assert result == 0

    def test_multiple_asset_types_same_address(self, engine):
        """An address can hold many asset types."""
        engine.register_asset_type("USDC", "USD Coin", 6, "admin")
        engine.register_asset_type("DATA_CREDIT", "DC", 0, "admin")
        engine.credit_balance("alice", "OAS", 1000)
        engine.credit_balance("alice", "USDC", 2000)
        engine.credit_balance("alice", "DATA_CREDIT", 50)
        balances = engine.get_all_balances("alice")
        assert len(balances) == 3
        assert balances["OAS"] == 1000
        assert balances["USDC"] == 2000
        assert balances["DATA_CREDIT"] == 50

    def test_large_amount_transfer(self, engine):
        """Large integer amounts work correctly (no float)."""
        big = 10 ** 18
        engine.credit_balance("alice", "OAS", big)
        result = engine.transfer_asset("alice", "bob", "OAS", big)
        assert result["ok"] is True
        assert engine.get_balance("bob", "OAS") == big

    def test_sequential_transfers(self, engine):
        """Multiple sequential transfers maintain correct state."""
        engine.credit_balance("alice", "OAS", 1000)
        engine.transfer_asset("alice", "bob", "OAS", 300)
        engine.transfer_asset("bob", "carol", "OAS", 100)
        engine.transfer_asset("carol", "alice", "OAS", 50)
        assert engine.get_balance("alice", "OAS") == 750
        assert engine.get_balance("bob", "OAS") == 200
        assert engine.get_balance("carol", "OAS") == 50

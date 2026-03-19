"""Tests for oasyce.bridge.core_bridge integration with oasyce."""

import os
import time
import pytest

CHAIN_AVAILABLE = os.getenv("OASYCE_CHAIN_URL") is not None

try:
    from oasyce.bridge.core_bridge import (
        bridge_buy,
        bridge_get_shares,
        bridge_quote,
        bridge_register,
        bridge_stake,
        metadata_to_capture_pack,
        reset_engine,
    )

    HAS_CORE = True
except ImportError:
    HAS_CORE = False


pytestmark = pytest.mark.skipif(
    not HAS_CORE or not CHAIN_AVAILABLE,
    reason="Requires running oasyce-chain (set OASYCE_CHAIN_URL)",
)


@pytest.fixture(autouse=True)
def _fresh_protocol():
    """Reset the cached protocol before each test for isolation."""
    reset_engine()
    yield
    reset_engine()


def _signed_metadata() -> dict:
    """Return a minimal signed metadata dict resembling plugin output."""
    return {
        "asset_id": "OAS_AABBCCDD",
        "filename": "test.jpg",
        "owner": "alice",
        "tags": ["Core"],
        "timestamp": int(time.time()),
        "file_hash": "b" * 64,
        "popc_signature": "deadbeef",
    }


# -- metadata_to_capture_pack ------------------------------------------------


class TestMetadataToCapturePack:
    def test_converts_with_unix_timestamp(self):
        md = _signed_metadata()
        pack = metadata_to_capture_pack(md)
        assert pack.media_hash == "b" * 64
        assert pack.device_signature == "deadbeef"
        assert pack.source == "camera"
        # ISO timestamp should be parseable
        pack.parsed_timestamp()

    def test_converts_without_timestamp(self):
        md = _signed_metadata()
        del md["timestamp"]
        pack = metadata_to_capture_pack(md)
        # Should fall back to now()
        pack.parsed_timestamp()

    def test_defaults_for_missing_fields(self):
        pack = metadata_to_capture_pack({})
        assert pack.media_hash == "0" * 64
        assert pack.device_signature == "deadbeef"


# -- bridge_register ---------------------------------------------------------


class TestBridgeRegister:
    def test_successful_register(self):
        result = bridge_register(_signed_metadata())
        assert result["valid"] is True
        assert result["core_asset_id"] is not None

    def test_register_uses_owner_as_creator(self):
        result = bridge_register(_signed_metadata(), creator="bob")
        assert result["valid"] is True

    def test_register_returns_reason_for_camera(self):
        result = bridge_register(_signed_metadata())
        # camera source → reason is None (full public)
        assert result["reason"] is None


# -- bridge_quote -------------------------------------------------------------


class TestBridgeQuote:
    def test_quote_for_registered_asset(self):
        reg = bridge_register(_signed_metadata())
        asset_id = reg["core_asset_id"]

        quote = bridge_quote(asset_id)
        assert "error" not in quote
        assert quote["price_oas"] > 0
        assert quote["supply"] == 0  # first quote, asset supply is 0

    def test_quote_not_found(self):
        result = bridge_quote("nonexistent_id")
        assert "error" in result


# -- bridge_buy ---------------------------------------------------------------


class TestBridgeBuy:
    def test_buy_success(self):
        reg = bridge_register(_signed_metadata())
        asset_id = reg["core_asset_id"]

        result = bridge_buy(asset_id, buyer="bob")
        assert result["settled"] is True
        assert result["price_oas"] > 0
        assert result["tx_id"] is not None
        assert "split" in result
        assert result["split"]["creator"] > 0

    def test_buy_increases_price(self):
        reg = bridge_register(_signed_metadata())
        asset_id = reg["core_asset_id"]

        r1 = bridge_buy(asset_id, buyer="bob")
        r2 = bridge_buy(asset_id, buyer="carol")
        assert r2["price_oas"] > r1["price_oas"]

    def test_buy_not_found(self):
        result = bridge_buy("nonexistent_id", buyer="bob")
        assert "error" in result


# -- bridge_stake / bridge_get_shares ----------------------------------------


class TestBridgeStakeAndShares:
    def test_stake_returns_total(self):
        total = bridge_stake("validator_1", 150.0)
        assert total == 150.0

    def test_stake_accumulates(self):
        bridge_stake("validator_1", 100.0)
        total = bridge_stake("validator_1", 50.0)
        assert total == 150.0

    def test_get_shares_empty_for_unknown_owner(self):
        holdings = bridge_get_shares("nobody")
        assert holdings == []

    def test_get_shares_after_buy(self):
        reg = bridge_register(_signed_metadata())
        asset_id = reg["core_asset_id"]
        bridge_buy(asset_id, buyer="alice")

        holdings = bridge_get_shares("alice")
        assert len(holdings) > 0


# -- end-to-end: register → quote → buy → quote again ------------------------


class TestEndToEnd:
    def test_full_pipeline(self):
        # 1. Register
        reg = bridge_register(_signed_metadata())
        assert reg["valid"]
        aid = reg["core_asset_id"]

        # 2. Quote (asset supply=0)
        q1 = bridge_quote(aid)
        assert q1["supply"] == 0

        # 3. Buy
        buy = bridge_buy(aid, buyer="dave")
        assert buy["settled"]

        # 4. Quote again (asset supply=1, Bancor price higher)
        q2 = bridge_quote(aid)
        assert q2["supply"] == 1
        assert q2["price_oas"] > q1["price_oas"]

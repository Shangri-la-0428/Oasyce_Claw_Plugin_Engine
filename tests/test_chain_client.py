"""Tests for the Oasyce Chain RPC Client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from oasyce.chain_client import ChainClient, ChainClientError, OasyceClient


# ======================================================================
# ChainClient — initialisation
# ======================================================================


class TestChainClientInit:
    def test_default_urls(self):
        client = ChainClient()
        assert client.rest_url == "http://localhost:1317"
        assert client.grpc_url == "localhost:9090"

    def test_custom_urls(self):
        client = ChainClient(
            rest_url="http://mynode:1317/",
            grpc_url="mynode:9090",
        )
        # Trailing slash should be stripped.
        assert client.rest_url == "http://mynode:1317"
        assert client.grpc_url == "mynode:9090"

    def test_custom_timeout(self):
        client = ChainClient(timeout=30)
        assert client.timeout == 30


# ======================================================================
# ChainClient — connectivity
# ======================================================================


class TestChainClientConnectivity:
    def test_is_connected_returns_false_when_chain_down(self):
        """When the chain is not running, is_connected() should return False."""
        client = ChainClient(rest_url="http://127.0.0.1:19999")
        assert client.is_connected() is False

    @patch("oasyce.chain_client.requests.get")
    def test_is_connected_returns_true_on_200(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        client = ChainClient()
        assert client.is_connected() is True

    @patch("oasyce.chain_client.requests.get")
    def test_is_connected_returns_false_on_non_200(self, mock_get):
        mock_get.return_value = MagicMock(status_code=503)
        client = ChainClient()
        assert client.is_connected() is False


# ======================================================================
# ChainClient — query methods raise when chain is down
# ======================================================================


class TestChainClientQueriesDown:
    """All query methods should raise ChainClientError when the chain is unreachable."""

    @pytest.fixture()
    def client(self):
        return ChainClient(rest_url="http://127.0.0.1:19999", timeout=1)

    def test_get_escrow_raises(self, client):
        with pytest.raises(ChainClientError):
            client.get_escrow("escrow-1")

    def test_get_bonding_curve_price_raises(self, client):
        with pytest.raises(ChainClientError):
            client.get_bonding_curve_price("asset-1")

    def test_get_capability_raises(self, client):
        with pytest.raises(ChainClientError):
            client.get_capability("cap-1")

    def test_list_capabilities_raises(self, client):
        with pytest.raises(ChainClientError):
            client.list_capabilities()

    def test_get_earnings_raises(self, client):
        with pytest.raises(ChainClientError):
            client.get_earnings("oasyce1provider")

    def test_get_data_asset_raises(self, client):
        with pytest.raises(ChainClientError):
            client.get_data_asset("asset-1")

    def test_list_data_assets_raises(self, client):
        with pytest.raises(ChainClientError):
            client.list_data_assets()

    def test_get_reputation_raises(self, client):
        with pytest.raises(ChainClientError):
            client.get_reputation("oasyce1addr")

    def test_get_balance_raises(self, client):
        with pytest.raises(ChainClientError):
            client.get_balance("oasyce1addr")

    def test_get_account_raises(self, client):
        with pytest.raises(ChainClientError):
            client.get_account("oasyce1addr")


# ======================================================================
# ChainClient — query methods with mocked responses
# ======================================================================


class TestChainClientQueriesMocked:
    @patch("oasyce.chain_client.requests.get")
    def test_get_escrow_returns_json(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"escrow": {"id": "e1", "status": "active"}},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        client = ChainClient()
        result = client.get_escrow("e1")
        assert result["escrow"]["id"] == "e1"

    @patch("oasyce.chain_client.requests.get")
    def test_list_capabilities_with_tag(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"capabilities": [{"id": "c1", "name": "test"}]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        client = ChainClient()
        result = client.list_capabilities(tag="nlp")
        assert len(result["capabilities"]) == 1
        # Verify the tag was passed as a query param.
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs.get("params", {}).get("tag") == "nlp"

    @patch("oasyce.chain_client.requests.get")
    def test_list_capabilities_by_provider(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"capabilities": []},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        client = ChainClient()
        client.list_capabilities(provider="oasyce1prov")
        url = mock_get.call_args[0][0]
        assert "/provider/oasyce1prov" in url

    @patch("oasyce.chain_client.requests.get")
    def test_get_balance(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"balances": [{"denom": "uoas", "amount": "1000000"}]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        client = ChainClient()
        result = client.get_balance("oasyce1addr")
        assert result["balances"][0]["denom"] == "uoas"

    @patch("oasyce.chain_client.requests.get")
    def test_get_reputation(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"address": "oasyce1addr", "total_score": "450"},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        client = ChainClient()
        result = client.get_reputation("oasyce1addr")
        assert result["total_score"] == "450"


# ======================================================================
# ChainClient — transaction methods (unsigned tx shape)
# ======================================================================


class TestChainClientTransactions:
    def test_build_tx_body_shape(self):
        client = ChainClient()
        body = client._build_tx_body(
            "/oasyce.settlement.v1.MsgCreateEscrow",
            {"creator": "oasyce1a", "provider": "oasyce1b"},
        )
        assert "tx" in body
        msgs = body["tx"]["body"]["messages"]
        assert len(msgs) == 1
        assert msgs[0]["@type"] == "/oasyce.settlement.v1.MsgCreateEscrow"
        assert msgs[0]["creator"] == "oasyce1a"
        assert body["mode"] == "BROADCAST_MODE_SYNC"


# ======================================================================
# OasyceClient — fallback behaviour
# ======================================================================


class TestOasyceClientFallback:
    def test_detects_chain_unavailable(self):
        """When no chain is running, OasyceClient should not be in chain mode."""
        client = OasyceClient(rest_url="http://127.0.0.1:19999")
        assert client.is_chain_mode is False

    @patch("oasyce.chain_client.requests.get")
    def test_detects_chain_available(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200)
        client = OasyceClient()
        assert client.is_chain_mode is True

    def test_refresh_connection(self):
        client = OasyceClient(rest_url="http://127.0.0.1:19999")
        # First call caches the result.
        assert client.is_chain_mode is False
        # refresh_connection re-checks.
        assert client.refresh_connection() is False

    @patch("oasyce.chain_client.requests.get")
    def test_list_capabilities_uses_chain(self, mock_get):
        """When chain is up, list_capabilities should call the chain."""
        # First call: is_connected check.
        # Second call: the actual query.
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"capabilities": [{"id": "c1"}]},
        )
        mock_get.return_value.raise_for_status = MagicMock()
        client = OasyceClient()
        result = client.list_capabilities()
        assert result == [{"id": "c1"}]

    def test_list_capabilities_falls_back_to_local(self):
        """When chain is down, list_capabilities should fall back to local engine."""
        client = OasyceClient(rest_url="http://127.0.0.1:19999")

        # Inject a mock local engine.
        mock_engine = MagicMock()
        mock_engine.list_capabilities.return_value = [{"id": "local-1", "name": "local"}]
        client._local_engine = mock_engine

        result = client.list_capabilities(tag="nlp")
        assert result == [{"id": "local-1", "name": "local"}]
        mock_engine.list_capabilities.assert_called_once_with(tag="nlp", provider=None)

    def test_get_balance_falls_back(self):
        """Balance query should fall back when chain is down."""
        client = OasyceClient(rest_url="http://127.0.0.1:19999")
        mock_engine = MagicMock()
        mock_engine.get_balance.return_value = {"balances": []}
        client._local_engine = mock_engine

        result = client.get_balance("oasyce1addr")
        assert result == {"balances": []}

    def test_null_engine_raises(self):
        """When local engine is also unavailable, operations should raise."""
        client = OasyceClient(rest_url="http://127.0.0.1:19999")

        # Force _NullEngine by making the import fail.
        with patch("oasyce.chain_client.OasyceClient._get_local_engine") as mock_gle:
            from oasyce.chain_client import _NullEngine

            mock_gle.return_value = _NullEngine()
            with pytest.raises(ChainClientError, match="unavailable"):
                client.list_capabilities()

    def test_direct_chain_access(self):
        """The .chain property should expose the underlying ChainClient."""
        client = OasyceClient()
        assert isinstance(client.chain, ChainClient)

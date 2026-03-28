"""Tests for the Oasyce Chain RPC Client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from oasyce.chain_client import ChainClient, ChainClientError, OasyceClient


# ======================================================================
# ChainClient — initialisation
# ======================================================================


class TestChainClientInit:
    def test_default_urls(self):
        client = ChainClient()
        assert client.rest_url == "http://localhost:1317"
        assert client.grpc_url == "localhost:9090"

    def test_testnet_defaults_and_chain_from_env(self, monkeypatch):
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "testnet")
        monkeypatch.setenv("OASYCE_CHAIN_FROM", "e2e-agent")

        client = ChainClient()

        assert client.rest_url == "http://47.93.32.88:1317"
        assert client.rpc_url == "http://47.93.32.88:26657"
        assert client.chain_id == "oasyce-testnet-1"
        assert client.default_from == "e2e-agent"

    def test_managed_chain_from_used_when_env_missing(self, monkeypatch, tmp_path):
        from oasyce import update_manager

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.delenv("OASYCE_CHAIN_FROM", raising=False)
        update_manager.write_managed_install_state(chain_signer_name="managed-agent")

        client = ChainClient()

        assert client.default_from == "managed-agent"

    def test_custom_urls(self):
        client = ChainClient(
            rest_url="http://mynode:1317/",
            rpc_url="http://mynode:26657/",
            grpc_url="mynode:9090",
        )
        # Trailing slash should be stripped.
        assert client.rest_url == "http://mynode:1317"
        assert client.rpc_url == "http://mynode:26657"
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

    @patch("oasyce.chain_client.requests.get")
    def test_get_agent_profile(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "address": "oasyce1addr",
                "shareholdings": [{"asset_id": "DATA_1", "shares": "100"}],
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()
        client = ChainClient()
        result = client.get_agent_profile("oasyce1addr")
        assert result["address"] == "oasyce1addr"
        assert result["shareholdings"][0]["asset_id"] == "DATA_1"

    @patch("oasyce.chain_client.requests.get")
    def test_get_includes_response_body_on_http_error(self, mock_get):
        response = MagicMock()
        response.text = '{"message":"bonding curve state not found"}'
        response.status_code = 500
        response.raise_for_status.side_effect = requests.HTTPError(
            "500 Server Error", response=response
        )
        mock_get.return_value = response

        client = ChainClient()
        with pytest.raises(ChainClientError, match="bonding curve state not found"):
            client.get_bonding_curve_price("asset-1")


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

    def test_strict_mode_raises_when_chain_is_down(self):
        client = OasyceClient(rest_url="http://127.0.0.1:19999")
        with pytest.raises(ChainClientError, match="fallback is disabled"):
            client.list_capabilities()

    def test_list_capabilities_falls_back_to_local(self):
        """When chain is down, list_capabilities should fall back to local engine."""
        client = OasyceClient(
            rest_url="http://127.0.0.1:19999",
            allow_local_fallback=True,
        )

        # Inject a mock local engine.
        mock_engine = MagicMock()
        mock_engine.list_capabilities.return_value = [{"id": "local-1", "name": "local"}]
        client._local_engine = mock_engine

        result = client.list_capabilities(tag="nlp")
        assert result == [{"id": "local-1", "name": "local"}]
        mock_engine.list_capabilities.assert_called_once_with(tag="nlp", provider=None)

    def test_get_balance_falls_back(self):
        """Balance query should fall back when chain is down."""
        client = OasyceClient(
            rest_url="http://127.0.0.1:19999",
            allow_local_fallback=True,
        )
        mock_engine = MagicMock()
        mock_engine.get_balance.return_value = {"balances": []}
        client._local_engine = mock_engine

        result = client.get_balance("oasyce1addr")
        assert result == {"balances": []}

    def test_null_engine_raises(self):
        """When local engine is also unavailable, operations should raise."""
        client = OasyceClient(
            rest_url="http://127.0.0.1:19999",
            allow_local_fallback=True,
        )

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


# ======================================================================
# ChainClient — invocation lifecycle transactions (CLI-based)
# ======================================================================


class TestInvocationTransactions:
    """Tests for complete/fail/claim/dispute invocation methods."""

    @pytest.fixture()
    def client(self):
        c = ChainClient(default_from="provider1", fees="10000uoas")
        # Inject a fake oasyced binary path so has_cli is True.
        c._oasyced = "/usr/local/bin/oasyced"
        return c

    @patch("oasyce.chain_client.subprocess.run")
    def test_complete_invocation_builds_correct_command(self, mock_run, client):
        """complete_invocation should call oasyced with correct args."""
        mock_run.return_value = MagicMock(
            stdout='{"txhash": "ABC123"}',
            stderr="",
            returncode=0,
        )
        client.complete_invocation("inv-42", "sha256:deadbeef")

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/oasyced"
        assert "tx" in cmd
        assert "oasyce_capability" in cmd
        assert "complete-invocation" in cmd
        assert "inv-42" in cmd
        assert "sha256:deadbeef" in cmd
        assert "--from" in cmd

    @patch("oasyce.chain_client.subprocess.run")
    def test_default_from_precedes_business_actor_for_cli_signing(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout='{"txhash": "ABC123"}',
            stderr="",
            returncode=0,
        )
        client = ChainClient(default_from="e2e-agent", fees="10000uoas")
        client._oasyced = "/usr/local/bin/oasyced"

        client.register_data_asset(
            owner="wallet-address-not-key-name",
            name="demo",
            description="demo",
            content_hash="a" * 64,
        )

        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--from") + 1] == "e2e-agent"
        assert "wallet-address-not-key-name" not in cmd
        assert cmd[cmd.index("--node") + 1] == client.rpc_url
        assert "--fees" in cmd
        assert "10000uoas" in cmd
        assert "--yes" in cmd

    @patch("oasyce.chain_client.subprocess.run")
    def test_fail_invocation_builds_correct_command(self, mock_run, client):
        """fail_invocation should call oasyced with correct args."""
        mock_run.return_value = MagicMock(
            stdout='{"txhash": "FAIL1"}',
            stderr="",
            returncode=0,
        )
        client.fail_invocation("inv-99")

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/oasyced"
        assert "tx" in cmd
        assert "oasyce_capability" in cmd
        assert "fail-invocation" in cmd
        assert "inv-99" in cmd
        assert "--from" in cmd
        assert "provider1" in cmd
        assert "--fees" in cmd
        assert "10000uoas" in cmd
        assert "--yes" in cmd

    @patch("oasyce.chain_client.subprocess.run")
    def test_claim_invocation_builds_correct_command(self, mock_run, client):
        """claim_invocation should call oasyced with correct args."""
        mock_run.return_value = MagicMock(
            stdout='{"txhash": "CLAIM1"}',
            stderr="",
            returncode=0,
        )
        client.claim_invocation("inv-55")

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/oasyced"
        assert "tx" in cmd
        assert "oasyce_capability" in cmd
        assert "claim-invocation" in cmd
        assert "inv-55" in cmd
        assert "--from" in cmd
        assert "provider1" in cmd
        assert "--fees" in cmd
        assert "10000uoas" in cmd
        assert "--yes" in cmd

    @patch("oasyce.chain_client.subprocess.run")
    def test_dispute_invocation_builds_correct_command(self, mock_run, client):
        """dispute_invocation should call oasyced with correct args including reason."""
        mock_run.return_value = MagicMock(
            stdout='{"txhash": "DISP1"}',
            stderr="",
            returncode=0,
        )
        client.dispute_invocation("inv-77", "output is garbage")

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/oasyced"
        assert "tx" in cmd
        assert "oasyce_capability" in cmd
        assert "dispute-invocation" in cmd
        assert "inv-77" in cmd
        assert "output is garbage" in cmd
        assert "--from" in cmd
        assert "provider1" in cmd
        assert "--fees" in cmd
        assert "10000uoas" in cmd
        assert "--yes" in cmd

    @patch("oasyce.chain_client.subprocess.run")
    def test_dispute_invocation_requires_reason(self, mock_run, client):
        """dispute_invocation with an empty reason should still pass the empty
        string to the CLI (the chain validates it). We verify the arg is present."""
        mock_run.return_value = MagicMock(
            stdout='{"txhash": "DISP2"}',
            stderr="",
            returncode=0,
        )
        client.dispute_invocation("inv-78", "")

        cmd = mock_run.call_args[0][0]
        # The reason arg (empty string) should be in the command list right after
        # the invocation ID.
        inv_idx = cmd.index("inv-78")
        assert cmd[inv_idx + 1] == ""


# ======================================================================
# ChainClient — get_access_level (REST query)
# ======================================================================


class TestGetAccessLevel:
    @patch("oasyce.chain_client.requests.get")
    def test_get_access_level_returns_data(self, mock_get):
        """get_access_level should return parsed JSON from the chain REST API."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "access_level": "L2",
                "equity_bps": 520,
                "shares": "5200",
                "total_shares": "100000",
            },
        )
        mock_get.return_value.raise_for_status = MagicMock()
        client = ChainClient()
        result = client.get_access_level("asset-abc", "oasyce1holder")

        assert result["access_level"] == "L2"
        assert result["equity_bps"] == 520
        # Verify the URL was constructed correctly.
        url = mock_get.call_args[0][0]
        assert "/oasyce/datarights/v1/access_level/asset-abc/oasyce1holder" in url

    def test_get_access_level_chain_down(self):
        """get_access_level should raise ChainClientError when the chain is down."""
        client = ChainClient(rest_url="http://127.0.0.1:19999", timeout=1)
        with pytest.raises(ChainClientError):
            client.get_access_level("asset-abc", "oasyce1holder")


# ======================================================================
# ChainClient — default fee value
# ======================================================================


class TestDefaultFee:
    def test_default_fee_is_10000uoas(self):
        """The default fee attribute should be '10000uoas'."""
        client = ChainClient()
        assert client.fees == "10000uoas"


# ======================================================================
# ChainClient — no-CLI path (has_cli=False → ChainClientError)
# ======================================================================


class TestInvocationNoCli:
    """When oasyced binary is not found, invocation methods raise ChainClientError."""

    def test_complete_invocation_no_cli(self):
        client = ChainClient()
        client._oasyced = None
        with pytest.raises(ChainClientError, match="CLI binary required"):
            client.complete_invocation("inv-1", "hash123")

    def test_fail_invocation_no_cli(self):
        client = ChainClient()
        client._oasyced = None
        with pytest.raises(ChainClientError, match="CLI binary required"):
            client.fail_invocation("inv-1")

    def test_claim_invocation_no_cli(self):
        client = ChainClient()
        client._oasyced = None
        with pytest.raises(ChainClientError, match="CLI binary required"):
            client.claim_invocation("inv-1")

    def test_dispute_invocation_no_cli(self):
        client = ChainClient()
        client._oasyced = None
        with pytest.raises(ChainClientError, match="CLI binary required"):
            client.dispute_invocation("inv-1", "bad output")


# ======================================================================
# ChainClient — subprocess returns empty output (error propagation)
# ======================================================================


class TestInvocationSubprocessError:
    """When oasyced returns no output, _run_cli raises ChainClientError."""

    @pytest.fixture
    def client(self):
        c = ChainClient()
        c._from_address = "provider1"
        c._oasyced = "/usr/local/bin/oasyced"
        return c

    @patch("oasyce.chain_client.subprocess.run")
    def test_complete_invocation_empty_output(self, mock_run, client):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=1)
        with pytest.raises(ChainClientError, match="no output"):
            client.complete_invocation("inv-1", "hash" * 8)

    @patch("oasyce.chain_client.subprocess.run")
    def test_claim_invocation_empty_output(self, mock_run, client):
        mock_run.return_value = MagicMock(stdout="", stderr="", returncode=1)
        with pytest.raises(ChainClientError, match="no output"):
            client.claim_invocation("inv-1")

    @patch("oasyce.chain_client.subprocess.run")
    def test_run_cli_raises_on_nonzero_with_error_output(self, mock_run, client):
        mock_run.return_value = MagicMock(
            stdout='{"Error": "key not found"}',
            stderr="",
            returncode=1,
        )
        with pytest.raises(ChainClientError, match="key not found"):
            client.register_data_asset(
                owner="alice",
                name="demo",
                description="demo",
                content_hash="a" * 64,
            )

    @patch("oasyce.chain_client.subprocess.run")
    def test_query_cli_uses_rpc_node(self, mock_run, client):
        mock_run.return_value = MagicMock(
            stdout='{"account": {"address": "oasyce1abc"}}',
            stderr="",
            returncode=0,
        )

        client._query_cli(["query", "auth", "account", "oasyce1abc"])

        cmd = mock_run.call_args[0][0]
        assert cmd[cmd.index("--node") + 1] == client.rpc_url


# ======================================================================
# ChainClient — complete_invocation usage_report parameter
# ======================================================================


class TestCompleteInvocationUsageReport:
    """Tests that the --usage-report flag is correctly included/excluded."""

    @pytest.fixture()
    def client(self):
        c = ChainClient(default_from="provider1", fees="10000uoas")
        c._oasyced = "/usr/local/bin/oasyced"
        return c

    @patch("oasyce.chain_client.subprocess.run")
    def test_usage_report_included_when_provided(self, mock_run, client):
        """--usage-report should appear in the CLI args when usage_report is given."""
        mock_run.return_value = MagicMock(
            stdout='{"txhash": "UR1"}',
            stderr="",
            returncode=0,
        )
        client.complete_invocation(
            "inv-100", "sha256:aabbccdd", usage_report="tokens:42,latency_ms:120"
        )

        cmd = mock_run.call_args[0][0]
        assert "--usage-report" in cmd
        ur_idx = cmd.index("--usage-report")
        assert cmd[ur_idx + 1] == "tokens:42,latency_ms:120"

    @patch("oasyce.chain_client.subprocess.run")
    def test_usage_report_excluded_when_none(self, mock_run, client):
        """--usage-report should NOT appear when usage_report is None (default)."""
        mock_run.return_value = MagicMock(
            stdout='{"txhash": "UR2"}',
            stderr="",
            returncode=0,
        )
        client.complete_invocation("inv-101", "sha256:11223344")

        cmd = mock_run.call_args[0][0]
        assert "--usage-report" not in cmd

    @patch("oasyce.chain_client.subprocess.run")
    def test_usage_report_excluded_when_empty_string(self, mock_run, client):
        """--usage-report should NOT appear when usage_report is an empty string."""
        mock_run.return_value = MagicMock(
            stdout='{"txhash": "UR3"}',
            stderr="",
            returncode=0,
        )
        client.complete_invocation("inv-102", "sha256:deadbeef", usage_report="")

        cmd = mock_run.call_args[0][0]
        assert "--usage-report" not in cmd

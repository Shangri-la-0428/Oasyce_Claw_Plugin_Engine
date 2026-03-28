"""
Comprehensive CLI test suite for the `oas` command.

Tests CLI argument parsing, --json output formatting, missing-argument errors,
and invalid-argument handling.  All service/facade layers are mocked — we are
testing the CLI shell, not business logic.
"""

from __future__ import annotations

import json
import os
import sys
import types
from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("OASYCE_REQUIRE_SIGNATURES", "0")

from oasyce.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class ServiceResult:
    """Mirror of oasyce.services.facade.ServiceResult for test mocks."""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


def run_cli(*argv: str):
    """Run the CLI with the given argv and capture stdout/stderr/exit_code.

    Returns (exit_code, stdout, stderr).
    """
    old_argv = sys.argv
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    sys.stdout = StringIO()
    sys.stderr = StringIO()
    exit_code = 0

    try:
        sys.argv = ["oas"] + list(argv)
        main()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
    finally:
        stdout = sys.stdout.getvalue()
        stderr = sys.stderr.getvalue()
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    return exit_code, stdout, stderr


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _suppress_update_check():
    """Prevent the background update check from running during tests."""
    with patch("oasyce.cli._maybe_check_for_update"), patch("oasyce.cli._maybe_auto_update"):
        yield


# ═══════════════════════════════════════════════════════════════════════════
# 1. Top-level / help / no-command
# ═══════════════════════════════════════════════════════════════════════════


class TestTopLevel:
    """Tests for running `oas` with no subcommand or with --help."""

    def test_no_command_shows_help_or_welcome(self):
        """Running `oas` without a subcommand exits 0."""
        code, out, err = run_cli()
        assert code == 0

    def test_help_flag(self):
        code, out, err = run_cli("--help")
        assert code == 0
        assert "Oasyce" in out

    def test_unknown_command(self):
        """An unrecognised subcommand should produce a non-zero exit."""
        code, out, err = run_cli("nonexistent_command_xyz")
        assert code != 0


class TestBootstrapUpdate:
    def test_update_check_reports_oasyce_and_odv(self):
        with patch(
            "oasyce.cli._check_package_updates",
            return_value=[
                {
                    "name": "oasyce",
                    "current": "2.3.0",
                    "latest": "2.4.0",
                    "installed": True,
                    "up_to_date": False,
                },
                {
                    "name": "odv",
                    "current": "0.2.0",
                    "latest": "0.3.0",
                    "installed": True,
                    "up_to_date": False,
                },
            ],
        ):
            code, out, err = run_cli("update", "--check", "--json")

        assert code == 0
        payload = json.loads(out)
        assert payload["current"] == "2.3.0"
        assert payload["latest"] == "2.4.0"
        assert payload["up_to_date"] is False
        assert payload["packages"][1]["name"] == "odv"
        assert "odv" in payload["upgrade_command"]

    def test_update_uses_eager_upgrade_strategy(self):
        completed = types.SimpleNamespace(returncode=0, stderr="")
        with patch(
            "oasyce.cli._check_package_updates",
            side_effect=[
                [
                    {
                        "name": "oasyce",
                        "current": "2.3.0",
                        "latest": "2.4.0",
                        "installed": True,
                        "up_to_date": False,
                    },
                    {
                        "name": "odv",
                        "current": "0.2.0",
                        "latest": "0.3.0",
                        "installed": True,
                        "up_to_date": False,
                    },
                ],
                [
                    {
                        "name": "oasyce",
                        "current": "2.4.0",
                        "latest": "2.4.0",
                        "installed": True,
                        "up_to_date": True,
                    },
                    {
                        "name": "odv",
                        "current": "0.3.0",
                        "latest": "0.3.0",
                        "installed": True,
                        "up_to_date": True,
                    },
                ],
            ],
        ), patch("oasyce.cli._upgrade_managed_packages", return_value=completed) as mock_upgrade:
            code, out, err = run_cli("update", "--json")

        assert code == 0
        assert mock_upgrade.called
        payload = json.loads(out)
        assert payload["upgraded"] is True
        assert payload["packages"][1]["current"] == "0.3.0"

    @patch("oasyce.identity.Wallet")
    def test_bootstrap_json_auto_creates_wallet_and_checks_datavault(self, mock_wallet_cls):
        mock_wallet_cls.get_address.return_value = None
        mock_wallet_cls.create.return_value = types.SimpleNamespace(address="wallet-new")

        with patch(
            "oasyce.cli._check_package_updates",
            return_value=[
                {
                    "name": "oasyce",
                    "current": "2.3.0",
                    "latest": "2.3.0",
                    "installed": True,
                    "up_to_date": True,
                },
                {
                    "name": "odv",
                    "current": "0.2.0",
                    "latest": "0.2.0",
                    "installed": True,
                    "up_to_date": True,
                },
            ],
        ), patch("oasyce.cli.importlib.util.find_spec", return_value=object()), patch(
            "oasyce.cli.shutil.which", return_value="/usr/local/bin/datavault"
        ):
            code, out, err = run_cli("bootstrap", "--json")

        assert code == 0
        payload = json.loads(out)
        assert payload["ok"] is True
        assert payload["wallet_created"] is True
        assert payload["wallet_address"] == "wallet-new"
        assert payload["datavault_module"] is True
        assert payload["datavault_cli"] is True
        assert payload["ready"] is True
        assert payload["auto_update_enabled"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 2. Data Asset commands: register, search, quote, buy, sell, shares
# ═══════════════════════════════════════════════════════════════════════════


class TestRegister:
    """Tests for `oas register`."""

    @patch("oasyce.services.facade.OasyceServiceFacade")
    @patch("oasyce.identity.Wallet")
    def test_register_success_json(self, mock_wallet_cls, mock_facade_cls, tmp_path):
        mock_wallet_cls.get_address.return_value = "oas1testaddr"
        facade = mock_facade_cls.return_value
        facade.register.return_value = ServiceResult(
            success=True,
            data={
                "asset_id": "OAS_ABCD1234",
                "owner": "oas1testaddr",
                "filename": "data.csv",
                "tags": ["test"],
                "rights_type": "original",
            },
        )
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")

        code, out, err = run_cli("register", str(f), "--tags", "test", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["asset_id"] == "OAS_ABCD1234"

    @patch("oasyce.services.facade.OasyceServiceFacade")
    @patch("oasyce.identity.Wallet")
    def test_register_success_human(self, mock_wallet_cls, mock_facade_cls, tmp_path):
        mock_wallet_cls.get_address.return_value = "oas1testaddr"
        facade = mock_facade_cls.return_value
        facade.register.return_value = ServiceResult(
            success=True,
            data={
                "asset_id": "OAS_ABCD1234",
                "owner": "oas1testaddr",
                "filename": "data.csv",
                "tags": ["test"],
                "rights_type": "original",
            },
        )
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")

        code, out, err = run_cli("register", str(f), "--tags", "test")
        assert code == 0
        assert "OAS_ABCD1234" in out

    @patch("oasyce.services.facade.OasyceServiceFacade")
    @patch("oasyce.identity.Wallet")
    def test_register_failure_json(self, mock_wallet_cls, mock_facade_cls, tmp_path):
        mock_wallet_cls.get_address.return_value = "oas1testaddr"
        facade = mock_facade_cls.return_value
        facade.register.return_value = ServiceResult(success=False, error="file too large")

        f = tmp_path / "big.bin"
        f.write_bytes(b"\x00" * 16)

        code, out, err = run_cli("register", str(f), "--json")
        assert code == 1
        parsed = json.loads(out)
        assert parsed["ok"] is False
        assert "file too large" in parsed["error"]

    def test_register_missing_file_arg(self):
        """Omitting the required positional <file> argument -> error."""
        code, out, err = run_cli("register")
        assert code != 0

    @patch("oasyce.services.facade.OasyceServiceFacade")
    @patch("oasyce.identity.Wallet")
    def test_register_free_flag(self, mock_wallet_cls, mock_facade_cls, tmp_path):
        mock_wallet_cls.get_address.return_value = "addr"
        facade = mock_facade_cls.return_value
        facade.register.return_value = ServiceResult(
            success=True,
            data={"asset_id": "OAS_FREE", "owner": "addr", "filename": "f.txt", "tags": []},
        )
        f = tmp_path / "f.txt"
        f.write_text("free")

        code, out, err = run_cli("register", str(f), "--free")
        assert code == 0
        # Facade should be called with price_model="free"
        call_kwargs = facade.register.call_args
        assert (
            call_kwargs[1]["price_model"] == "free"
            or call_kwargs.kwargs.get("price_model") == "free"
        )

    @patch("oasyce.services.facade.OasyceServiceFacade")
    @patch("oasyce.identity.Wallet")
    def test_register_rights_type_choices(self, mock_wallet_cls, mock_facade_cls, tmp_path):
        """Invalid --rights-type should fail."""
        mock_wallet_cls.get_address.return_value = "addr"
        f = tmp_path / "f.txt"
        f.write_text("data")

        code, out, err = run_cli("register", str(f), "--rights-type", "INVALID")
        assert code != 0


class TestSearch:
    """Tests for `oas search`."""

    @patch("oasyce.cli.OasyceSkills")
    def test_search_json(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        skills.search_data_skill.return_value = [
            {"asset_id": "OAS_A", "filename": "a.csv", "owner": "alice"},
        ]

        code, out, err = run_cli("search", "nlp", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert len(parsed) == 1
        assert parsed[0]["asset_id"] == "OAS_A"

    @patch("oasyce.cli.OasyceSkills")
    def test_search_empty(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        skills.search_data_skill.return_value = []

        code, out, err = run_cli("search", "nonexistent")
        assert code == 0
        assert "No assets found" in out

    def test_search_missing_tag(self):
        code, out, err = run_cli("search")
        assert code != 0


class TestQuote:
    """Tests for `oas quote`."""

    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_quote_json(self, mock_facade_cls):
        facade = mock_facade_cls.return_value
        facade.quote.return_value = ServiceResult(
            success=True,
            data={
                "payment_oas": 10.0,
                "equity_minted": 3.162,
                "spot_price_before": 1.0,
                "spot_price_after": 1.5,
                "price_impact_pct": 0.05,
                "protocol_fee": 0.07,
            },
        )

        code, out, err = run_cli("quote", "OAS_TEST123", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert "payment_oas" in parsed

    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_quote_failure(self, mock_facade_cls):
        facade = mock_facade_cls.return_value
        facade.quote.return_value = ServiceResult(success=False, error="asset not found")

        code, out, err = run_cli("quote", "NONEXISTENT", "--json")
        assert code == 1
        parsed = json.loads(out)
        assert parsed["ok"] is False

    def test_quote_missing_asset_id(self):
        code, out, err = run_cli("quote")
        assert code != 0


class TestBuy:
    """Tests for `oas buy`."""

    @patch("oasyce.services.facade.OasyceServiceFacade")
    @patch("oasyce.identity.Wallet")
    def test_buy_json(self, mock_wallet_cls, mock_facade_cls):
        mock_wallet_cls.get_address.return_value = "bob"
        facade = mock_facade_cls.return_value
        facade.buy.return_value = ServiceResult(
            success=True,
            data={
                "buyer": "bob",
                "receipt_id": "R_001",
                "quote": {"equity_minted": 3.0, "protocol_fee": 0.07},
            },
        )

        code, out, err = run_cli("buy", "OAS_TEST", "--buyer", "bob", "--amount", "10.0", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["receipt_id"] == "R_001"

    @patch("oasyce.services.facade.OasyceServiceFacade")
    @patch("oasyce.identity.Wallet")
    def test_buy_failure(self, mock_wallet_cls, mock_facade_cls):
        mock_wallet_cls.get_address.return_value = "bob"
        facade = mock_facade_cls.return_value
        facade.buy.return_value = ServiceResult(success=False, error="insufficient balance")

        code, out, err = run_cli("buy", "OAS_X", "--json")
        assert code == 1

    def test_buy_missing_asset_id(self):
        code, out, err = run_cli("buy")
        assert code != 0


class TestSell:
    """Tests for `oas sell`."""

    @patch("oasyce.services.facade.OasyceServiceFacade")
    @patch("oasyce.identity.Wallet")
    def test_sell_json(self, mock_wallet_cls, mock_facade_cls):
        mock_wallet_cls.get_address.return_value = "alice"
        facade = mock_facade_cls.return_value
        facade.sell.return_value = ServiceResult(
            success=True,
            data={"seller": "alice", "payout_oas": 4.75, "receipt_id": "R_002"},
        )

        code, out, err = run_cli(
            "sell", "OAS_TEST", "--seller", "alice", "--tokens", "5.0", "--json"
        )
        assert code == 0
        parsed = json.loads(out)
        assert parsed["payout_oas"] == 4.75

    def test_sell_missing_tokens(self):
        """--tokens is required."""
        code, out, err = run_cli("sell", "OAS_TEST")
        assert code != 0


class TestShares:
    """Tests for `oas shares`."""

    @patch("oasyce.bridge.core_bridge.bridge_get_shares")
    def test_shares_json(self, mock_get_shares):
        Holding = types.SimpleNamespace
        mock_get_shares.return_value = [
            Holding(asset_id="OAS_A", shares=10.0, acquired_price=1.5),
        ]

        code, out, err = run_cli("shares", "alice", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert len(parsed) == 1
        assert parsed[0]["asset_id"] == "OAS_A"

    @patch("oasyce.bridge.core_bridge.bridge_get_shares")
    def test_shares_empty(self, mock_get_shares):
        mock_get_shares.return_value = []

        code, out, err = run_cli("shares", "nobody")
        assert code == 0
        assert "No shares found" in out

    def test_shares_missing_owner(self):
        code, out, err = run_cli("shares")
        assert code != 0


# ═══════════════════════════════════════════════════════════════════════════
# 3. Pricing commands: price, price-factors
# ═══════════════════════════════════════════════════════════════════════════


class TestPrice:
    """Tests for `oas price` and `oas price-factors`."""

    @patch("oasyce.services.pricing.DatasetPricingCurve")
    def test_price_json(self, mock_curve_cls):
        curve = mock_curve_cls.return_value
        curve.calculate_price.return_value = {
            "base_price": 1.0,
            "final_price": 1.234,
            "demand_factor": 1.1,
            "scarcity_factor": 1.05,
            "quality_factor": 1.0,
            "freshness_factor": 1.0,
        }

        code, out, err = run_cli("price", "OAS_TEST", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["final_price"] == 1.234

    @patch("oasyce.services.pricing.DatasetPricingCurve")
    def test_price_factors_json(self, mock_curve_cls):
        curve = mock_curve_cls.return_value
        curve.calculate_price.return_value = {
            "base_price": 1.0,
            "final_price": 2.0,
            "demand_factor": 1.5,
            "scarcity_factor": 1.2,
            "quality_factor": 1.1,
            "freshness_factor": 1.0,
        }

        code, out, err = run_cli("price-factors", "OAS_TEST", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["demand_factor"] == 1.5


# ═══════════════════════════════════════════════════════════════════════════
# 4. Dispute & Resolution
# ═══════════════════════════════════════════════════════════════════════════


class TestDispute:
    """Tests for `oas dispute`."""

    @patch("oasyce.storage.ledger.Ledger")
    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_dispute_json(self, mock_facade_cls, mock_ledger_cls):
        facade = mock_facade_cls.return_value
        facade.dispute.return_value = ServiceResult(
            success=True,
            data={"dispute_id": "DIS_001", "state": "open", "arbitrators": []},
        )

        code, out, err = run_cli("dispute", "OAS_BAD", "--reason", "plagiarised content", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["dispute_id"] == "DIS_001"

    @patch("oasyce.storage.ledger.Ledger")
    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_dispute_failure(self, mock_facade_cls, mock_ledger_cls):
        facade = mock_facade_cls.return_value
        facade.dispute.return_value = ServiceResult(success=False, error="already disputed")

        code, out, err = run_cli("dispute", "OAS_BAD", "--reason", "dup", "--json")
        assert code == 1
        parsed = json.loads(out)
        assert parsed["ok"] is False

    def test_dispute_missing_reason(self):
        """--reason is required."""
        code, out, err = run_cli("dispute", "OAS_X")
        assert code != 0


class TestResolve:
    """Tests for `oas resolve`."""

    @patch("oasyce.storage.ledger.Ledger")
    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_resolve_json(self, mock_facade_cls, mock_ledger_cls):
        facade = mock_facade_cls.return_value
        facade.resolve_dispute.return_value = ServiceResult(
            success=True,
            data={
                "dispute_id": "DIS_001",
                "outcome": "consumer",
                "consumer_refunded": True,
                "slash_amount": 5.0,
            },
        )

        code, out, err = run_cli(
            "resolve", "OAS_X", "--remedy", "delist", "--dispute-id", "DIS_001", "--json"
        )
        assert code == 0
        parsed = json.loads(out)
        assert parsed["outcome"] == "consumer"

    def test_resolve_missing_remedy(self):
        code, out, err = run_cli("resolve", "OAS_X")
        assert code != 0

    def test_resolve_invalid_remedy(self):
        code, out, err = run_cli("resolve", "OAS_X", "--remedy", "invalid_remedy")
        assert code != 0


class TestDelist:
    """Tests for `oas delist`."""

    @patch("oasyce.storage.ledger.Ledger")
    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_delist_json(self, mock_facade_cls, mock_ledger_cls):
        facade = mock_facade_cls.return_value
        facade.delist_asset.return_value = ServiceResult(
            success=True, data={"asset_id": "OAS_X", "status": "delisted"}
        )

        code, out, err = run_cli("delist", "OAS_X", "--owner", "alice", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["status"] == "delisted"

    def test_delist_missing_owner(self):
        code, out, err = run_cli("delist", "OAS_X")
        assert code != 0


class TestJuryVote:
    """Tests for `oas jury-vote`."""

    @patch("oasyce.storage.ledger.Ledger")
    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_jury_vote_uphold_json(self, mock_facade_cls, mock_ledger_cls):
        facade = mock_facade_cls.return_value
        facade.jury_vote.return_value = ServiceResult(success=True, data={"recorded": True})

        code, out, err = run_cli(
            "jury-vote", "DIS_001", "--verdict", "uphold", "--juror", "charlie", "--json"
        )
        assert code == 0
        parsed = json.loads(out)
        assert parsed["recorded"] is True

    @patch("oasyce.storage.ledger.Ledger")
    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_jury_vote_reject_json(self, mock_facade_cls, mock_ledger_cls):
        facade = mock_facade_cls.return_value
        facade.jury_vote.return_value = ServiceResult(success=True, data={"recorded": True})

        code, out, err = run_cli(
            "jury-vote", "DIS_001", "--verdict", "reject", "--juror", "dave", "--json"
        )
        assert code == 0

    def test_jury_vote_invalid_verdict(self):
        code, out, err = run_cli("jury-vote", "DIS_001", "--verdict", "maybe", "--juror", "x")
        assert code != 0

    def test_jury_vote_missing_juror(self):
        code, out, err = run_cli("jury-vote", "DIS_001", "--verdict", "uphold")
        assert code != 0


# ═══════════════════════════════════════════════════════════════════════════
# 5. Capability Marketplace
# ═══════════════════════════════════════════════════════════════════════════


class TestCapabilityRegister:
    """Tests for `oas capability register`."""

    @patch("oasyce.cli._get_delivery_protocol")
    def test_capability_register_json(self, mock_proto):
        reg = MagicMock()
        reg.register.return_value = {"ok": True, "capability_id": "CAP_001"}
        reg.close = MagicMock()
        mock_proto.return_value = (MagicMock(), reg, MagicMock())

        code, out, err = run_cli(
            "capability",
            "register",
            "--name",
            "Translate",
            "--endpoint",
            "https://api.example.com/tr",
            "--price",
            "0.5",
            "--tags",
            "nlp,translation",
            "--json",
        )
        assert code == 0
        parsed = json.loads(out)
        assert parsed["capability_id"] == "CAP_001"

    def test_capability_register_missing_name(self):
        code, out, err = run_cli("capability", "register", "--endpoint", "https://x.com/api")
        assert code != 0

    def test_capability_register_missing_endpoint(self):
        code, out, err = run_cli("capability", "register", "--name", "Foo")
        assert code != 0


class TestCapabilityList:
    """Tests for `oas capability list`."""

    @patch("oasyce.cli._get_delivery_protocol")
    def test_capability_list_json(self, mock_proto):
        ep = MagicMock()
        ep.to_dict.return_value = {
            "capability_id": "CAP_001",
            "name": "Translate",
            "price_per_call": 50000000,
        }
        reg = MagicMock()
        reg.list_active.return_value = [ep]
        reg.close = MagicMock()
        mock_proto.return_value = (MagicMock(), reg, MagicMock())

        code, out, err = run_cli("capability", "list", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert len(parsed) == 1

    @patch("oasyce.cli._get_delivery_protocol")
    def test_capability_list_empty(self, mock_proto):
        reg = MagicMock()
        reg.list_active.return_value = []
        reg.close = MagicMock()
        mock_proto.return_value = (MagicMock(), reg, MagicMock())

        code, out, err = run_cli("capability", "list")
        assert code == 0
        assert "No active capabilities" in out


class TestCapabilityInvoke:
    """Tests for `oas capability invoke`."""

    @patch("oasyce.cli._get_delivery_protocol")
    def test_invoke_json(self, mock_proto):
        protocol = MagicMock()
        protocol.invoke.return_value = {
            "ok": True,
            "invocation_id": "INV_001",
            "latency_ms": 120,
            "amount": 50000000,
            "provider_earned": 46500000,
            "protocol_fee": 1500000,
            "output": {"result": "hello"},
        }
        protocol.close = MagicMock()
        reg = MagicMock()
        reg.close = MagicMock()
        escrow = MagicMock()
        escrow.close = MagicMock()
        mock_proto.return_value = (protocol, reg, escrow)

        code, out, err = run_cli(
            "capability",
            "invoke",
            "CAP_001",
            "--input",
            '{"text":"hi"}',
            "--json",
        )
        assert code == 0
        parsed = json.loads(out)
        assert parsed["invocation_id"] == "INV_001"


class TestCapabilityEarnings:
    """Tests for `oas capability earnings`."""

    @patch("oasyce.cli._get_delivery_protocol")
    def test_earnings_provider_json(self, mock_proto):
        protocol = MagicMock()
        protocol.provider_earnings.return_value = {
            "total_earned": 500000000,
            "total_calls": 10,
            "success_rate": 0.9,
        }
        protocol.close = MagicMock()
        reg = MagicMock()
        reg.close = MagicMock()
        escrow = MagicMock()
        escrow.close = MagicMock()
        mock_proto.return_value = (protocol, reg, escrow)

        code, out, err = run_cli("capability", "earnings", "--provider", "alice", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["total_calls"] == 10

    @patch("oasyce.cli._get_delivery_protocol")
    def test_earnings_no_flag(self, mock_proto):
        """Must specify --provider or --consumer."""
        protocol = MagicMock()
        protocol.close = MagicMock()
        reg = MagicMock()
        reg.close = MagicMock()
        escrow = MagicMock()
        escrow.close = MagicMock()
        mock_proto.return_value = (protocol, reg, escrow)

        code, out, err = run_cli("capability", "earnings")
        assert code == 1
        assert "provider" in err.lower() or "consumer" in err.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 6. Task Market (AHRP)
# ═══════════════════════════════════════════════════════════════════════════


class TestTaskPost:

    @patch("oasyce.cli._get_task_facade")
    def test_task_post_json(self, mock_facade_fn):
        facade = MagicMock()
        facade.post_task.return_value = ServiceResult(
            success=True,
            data={
                "task_id": "TASK_001",
                "requester_id": "alice",
                "budget": 50.0,
                "selection_strategy": "weighted_score",
                "status": "open",
            },
        )
        mock_facade_fn.return_value = facade

        code, out, err = run_cli(
            "task",
            "post",
            "--requester",
            "alice",
            "--description",
            "Translate EN->FR",
            "--budget",
            "50",
            "--json",
        )
        assert code == 0
        parsed = json.loads(out)
        assert parsed["task_id"] == "TASK_001"

    def test_task_post_missing_requester(self):
        code, out, err = run_cli("task", "post", "--description", "x", "--budget", "10")
        assert code != 0

    def test_task_post_missing_budget(self):
        code, out, err = run_cli("task", "post", "--requester", "alice", "--description", "x")
        assert code != 0


class TestTaskList:

    @patch("oasyce.cli._get_task_facade")
    def test_task_list_json(self, mock_facade_fn):
        facade = MagicMock()
        facade.query_tasks.return_value = ServiceResult(
            success=True,
            data=[
                {
                    "task_id": "T1",
                    "budget": 10.0,
                    "status": "open",
                    "bids": [],
                    "description": "Task one",
                },
            ],
        )
        mock_facade_fn.return_value = facade

        code, out, err = run_cli("task", "list", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert len(parsed) == 1

    @patch("oasyce.cli._get_task_facade")
    def test_task_list_empty(self, mock_facade_fn):
        facade = MagicMock()
        facade.query_tasks.return_value = ServiceResult(success=True, data=[])
        mock_facade_fn.return_value = facade

        code, out, err = run_cli("task", "list")
        assert code == 0
        assert "No open tasks" in out


class TestTaskBid:

    @patch("oasyce.cli._get_task_facade")
    def test_bid_json(self, mock_facade_fn):
        facade = MagicMock()
        facade.submit_task_bid.return_value = ServiceResult(
            success=True,
            data={"bid_id": "BID_001", "agent_id": "bob", "price": 30.0},
        )
        mock_facade_fn.return_value = facade

        code, out, err = run_cli(
            "task",
            "bid",
            "TASK_001",
            "--agent",
            "bob",
            "--price",
            "30",
            "--json",
        )
        assert code == 0
        parsed = json.loads(out)
        assert parsed["bid_id"] == "BID_001"

    def test_bid_missing_agent(self):
        code, out, err = run_cli("task", "bid", "T1", "--price", "10")
        assert code != 0

    def test_bid_missing_price(self):
        code, out, err = run_cli("task", "bid", "T1", "--agent", "bob")
        assert code != 0


class TestTaskSelect:

    @patch("oasyce.cli._get_task_facade")
    def test_select_json(self, mock_facade_fn):
        facade = MagicMock()
        facade.select_task_winner.return_value = ServiceResult(
            success=True,
            data={"agent_id": "bob", "bid_id": "BID_001", "price": 30.0},
        )
        mock_facade_fn.return_value = facade

        code, out, err = run_cli("task", "select", "TASK_001", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["agent_id"] == "bob"


class TestTaskComplete:

    @patch("oasyce.cli._get_task_facade")
    def test_complete_json(self, mock_facade_fn):
        facade = MagicMock()
        facade.complete_task.return_value = ServiceResult(
            success=True, data={"task_id": "T1", "status": "completed"}
        )
        mock_facade_fn.return_value = facade

        code, out, err = run_cli("task", "complete", "T1", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["status"] == "completed"


class TestTaskCancel:

    @patch("oasyce.cli._get_task_facade")
    def test_cancel_json(self, mock_facade_fn):
        facade = MagicMock()
        facade.cancel_task.return_value = ServiceResult(
            success=True, data={"task_id": "T1", "status": "cancelled"}
        )
        mock_facade_fn.return_value = facade

        code, out, err = run_cli("task", "cancel", "T1", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["status"] == "cancelled"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Reputation
# ═══════════════════════════════════════════════════════════════════════════


class TestReputation:

    @patch("oasyce.cli.OasyceSkills")
    def test_reputation_check_json(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        skills.check_reputation_skill.return_value = {
            "reputation": 8.5,
            "bond_discount": 0.85,
        }

        code, out, err = run_cli("reputation", "check", "alice", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["reputation"] == 8.5

    @patch("oasyce.cli.OasyceSkills")
    def test_reputation_update_json(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        rep_mock = MagicMock()
        rep_mock.update.return_value = 9.0
        skills.access_provider = MagicMock()
        skills.access_provider.reputation = rep_mock

        code, out, err = run_cli("reputation", "update", "alice", "--success", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["reputation"] == 9.0

    def test_reputation_no_subcommand(self):
        """Running `oas reputation` without a subcommand should show help."""
        code, out, err = run_cli("reputation")
        assert code == 0


# ═══════════════════════════════════════════════════════════════════════════
# 8. Access Control
# ═══════════════════════════════════════════════════════════════════════════


class TestAccess:

    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_access_buy_json(self, mock_facade_cls):
        facade = mock_facade_cls.return_value
        facade.access_buy.return_value = ServiceResult(
            success=True,
            data={
                "asset_id": "OAS_X",
                "buyer": "bob",
                "level": "L1",
                "bond_oas": 5.0,
                "lock_days": 30,
            },
        )

        code, out, err = run_cli(
            "access", "buy", "OAS_X", "--agent", "bob", "--level", "L1", "--json"
        )
        assert code == 0
        parsed = json.loads(out)
        assert parsed["level"] == "L1"

    def test_access_buy_missing_level(self):
        code, out, err = run_cli("access", "buy", "OAS_X", "--agent", "bob")
        assert code != 0

    def test_access_buy_invalid_level(self):
        code, out, err = run_cli("access", "buy", "OAS_X", "--agent", "bob", "--level", "L9")
        assert code != 0

    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_access_quote_json(self, mock_facade_cls):
        facade = mock_facade_cls.return_value
        facade.access_quote.return_value = ServiceResult(
            success=True,
            data={
                "asset_id": "OAS_X",
                "reputation": 8.0,
                "levels": [
                    {
                        "level": "L0",
                        "name": "Query",
                        "available": True,
                        "bond_oas": 1.0,
                        "lock_days": 7,
                    },
                ],
            },
        )

        code, out, err = run_cli("access", "quote", "OAS_X", "--agent", "bob", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["levels"][0]["level"] == "L0"

    @patch("oasyce.cli.OasyceSkills")
    def test_access_query_json(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        skills.query_data_skill.return_value = {
            "success": True,
            "bond_required": 1.0,
            "data": {"rows": 100},
        }

        code, out, err = run_cli("access", "query", "OAS_X", "--agent", "bob", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["success"] is True

    def test_access_no_subcommand(self):
        code, out, err = run_cli("access")
        assert code == 0

    @patch("oasyce.cli.OasyceSkills")
    def test_access_compute_json(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        skills.compute_data_skill.return_value = {
            "success": True,
            "bond_required": 10.0,
            "data": {"result": 42},
        }

        code, out, err = run_cli(
            "access", "compute", "OAS_X", "--agent", "bob", "--code", "len(data)", "--json"
        )
        assert code == 0
        parsed = json.loads(out)
        assert parsed["data"]["result"] == 42


# ═══════════════════════════════════════════════════════════════════════════
# 9. Agent Scheduler
# ═══════════════════════════════════════════════════════════════════════════


class TestAgent:

    @patch("oasyce.cli._get_agent_scheduler")
    def test_agent_start_json(self, mock_sched_fn):
        sched = MagicMock()
        sched.status.return_value = {
            "running": True,
            "config": {"interval_hours": 24, "scan_paths": []},
        }
        mock_sched_fn.return_value = sched

        code, out, err = run_cli("agent", "start", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["running"] is True

    @patch("oasyce.cli._get_agent_scheduler")
    def test_agent_stop_json(self, mock_sched_fn):
        sched = MagicMock()
        sched.status.return_value = {"running": False}
        mock_sched_fn.return_value = sched

        code, out, err = run_cli("agent", "stop", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["running"] is False

    @patch("oasyce.cli._get_agent_scheduler")
    def test_agent_status_json(self, mock_sched_fn):
        sched = MagicMock()
        sched.status.return_value = {
            "running": False,
            "last_run": None,
            "next_run": None,
            "total_runs": 0,
            "total_registered": 0,
            "total_errors": 0,
            "last_result": None,
            "config": {"interval_hours": 24, "scan_paths": []},
        }
        mock_sched_fn.return_value = sched

        code, out, err = run_cli("agent", "status", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["total_runs"] == 0

    @patch("oasyce.cli._get_agent_scheduler")
    def test_agent_run_json(self, mock_sched_fn):
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {
            "scan_count": 5,
            "register_count": 2,
            "trade_count": 0,
            "duration_ms": 350,
            "errors": [],
        }
        sched = MagicMock()
        sched.run_once.return_value = result_obj
        mock_sched_fn.return_value = sched

        code, out, err = run_cli("agent", "run", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["scan_count"] == 5

    @patch("oasyce.cli._get_agent_scheduler")
    def test_agent_config_json(self, mock_sched_fn):
        from unittest.mock import PropertyMock

        config_obj = MagicMock()
        config_obj.to_dict.return_value = {
            "enabled": True,
            "interval_hours": 12,
            "scan_paths": ["/tmp/data"],
            "auto_register": True,
            "auto_trade": False,
            "trade_tags": [],
            "trade_max_spend": 10.0,
        }
        config_obj.interval_hours = 24
        config_obj.scan_paths = []
        config_obj.auto_trade = False
        config_obj.trade_tags = []
        config_obj.trade_max_spend = 10.0

        sched = MagicMock()
        sched.get_config.return_value = config_obj
        mock_sched_fn.return_value = sched

        code, out, err = run_cli("agent", "config", "--interval", "12", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert "interval_hours" in parsed

    def test_agent_no_subcommand(self):
        code, out, err = run_cli("agent")
        assert code == 0


# ═══════════════════════════════════════════════════════════════════════════
# 10. Node commands
# ═══════════════════════════════════════════════════════════════════════════


class TestNode:

    @patch("oasyce.config.load_or_create_node_identity")
    @patch("oasyce.storage.ledger.Ledger")
    def test_node_info_json(self, mock_ledger_cls, mock_identity):
        mock_identity.return_value = ("privhex", "abcdef1234567890" * 4)
        ledger = mock_ledger_cls.return_value
        ledger.get_chain_height.return_value = 42

        code, out, err = run_cli("node", "info", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert "node_id" in parsed
        assert parsed["chain_height"] == 42

    @patch("oasyce.config.reset_node_identity")
    def test_node_reset_identity_json(self, mock_reset):
        mock_reset.return_value = ("privhex", "newid" * 8)

        code, out, err = run_cli("node", "reset-identity", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert "node_id" in parsed

    def test_node_no_subcommand(self):
        code, out, err = run_cli("node")
        assert code == 0


# ═══════════════════════════════════════════════════════════════════════════
# 11. Fingerprint commands
# ═══════════════════════════════════════════════════════════════════════════


class TestFingerprint:

    @patch("oasyce.fingerprint.registry.FingerprintRegistry")
    @patch("oasyce.storage.ledger.Ledger")
    @patch("oasyce.fingerprint.engine.FingerprintEngine")
    @patch("oasyce.crypto.keys.load_or_create_keypair")
    def test_fingerprint_embed_json(
        self, mock_keys, mock_engine_cls, mock_ledger_cls, mock_registry_cls, tmp_path
    ):
        mock_keys.return_value = ("privhex", "pubhex")
        engine = mock_engine_cls.return_value
        engine.generate_fingerprint.return_value = "abcdef0123456789" * 4
        engine.embed_text.return_value = "watermarked text content"
        registry = mock_registry_cls.return_value
        ledger = mock_ledger_cls.return_value

        f = tmp_path / "doc.txt"
        f.write_text("original text content")

        code, out, err = run_cli("fingerprint", "embed", str(f), "--caller", "bob", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert "fingerprint" in parsed
        assert parsed["caller_id"] == "bob"

    @patch("oasyce.fingerprint.engine.FingerprintEngine")
    def test_fingerprint_extract_not_found(self, mock_engine_cls, tmp_path):
        mock_engine_cls.extract_binary.return_value = None
        mock_engine_cls.extract_text.return_value = None

        f = tmp_path / "plain.txt"
        f.write_text("no watermark here")

        code, out, err = run_cli("fingerprint", "extract", str(f), "--json")
        assert code == 1
        parsed = json.loads(out)
        assert parsed["fingerprint"] is None

    @patch("oasyce.fingerprint.registry.FingerprintRegistry")
    @patch("oasyce.storage.ledger.Ledger")
    def test_fingerprint_trace_json(self, mock_ledger_cls, mock_registry_cls):
        registry = mock_registry_cls.return_value
        registry.trace_fingerprint.return_value = {
            "fingerprint": "abcdef",
            "caller_id": "bob",
            "asset_id": "OAS_X",
            "timestamp": 1700000000,
        }
        ledger = mock_ledger_cls.return_value

        code, out, err = run_cli("fingerprint", "trace", "abcdef", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["caller_id"] == "bob"

    @patch("oasyce.fingerprint.registry.FingerprintRegistry")
    @patch("oasyce.storage.ledger.Ledger")
    def test_fingerprint_trace_not_found(self, mock_ledger_cls, mock_registry_cls):
        registry = mock_registry_cls.return_value
        registry.trace_fingerprint.return_value = None
        ledger = mock_ledger_cls.return_value

        code, out, err = run_cli("fingerprint", "trace", "deadbeef", "--json")
        assert code == 1
        parsed = json.loads(out)
        assert parsed["found"] is False

    def test_fingerprint_no_subcommand(self):
        code, out, err = run_cli("fingerprint")
        assert code == 0


# ═══════════════════════════════════════════════════════════════════════════
# 12. Info / Diagnostics
# ═══════════════════════════════════════════════════════════════════════════


class TestInfo:

    def test_info_json(self):
        code, out, err = run_cli("info", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert "project" in parsed
        assert "version" in parsed
        assert "beta_onboarding" in parsed

    def test_info_section_economics(self):
        code, out, err = run_cli("info", "--section", "economics")
        assert code == 0

    def test_info_section_beta(self):
        code, out, err = run_cli("info", "--section", "beta")
        assert code == 0
        assert "register" in out.lower()
        assert "quote" in out.lower()
        assert "buy" in out.lower()

    def test_info_section_invalid(self):
        code, out, err = run_cli("info", "--section", "nonexistent_section")
        assert code != 0


# ═══════════════════════════════════════════════════════════════════════════
# 13. Leakage commands
# ═══════════════════════════════════════════════════════════════════════════


class TestLeakage:

    @patch("oasyce.cli.OasyceSkills")
    def test_leakage_check_json(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        skills.check_leakage_budget_skill.return_value = {
            "budget": 100.0,
            "used": 30.0,
            "remaining": 70.0,
            "queries": 5,
            "exhausted": False,
        }

        code, out, err = run_cli("leakage", "check", "bob", "OAS_X", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["remaining"] == 70.0

    @patch("oasyce.cli.OasyceSkills")
    def test_leakage_reset_json(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        skills.access_provider = MagicMock()
        skills.access_provider.leakage = MagicMock()
        skills.access_provider.leakage.reset_budget.return_value = {"ok": True}

        code, out, err = run_cli("leakage", "reset", "bob", "OAS_X", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["ok"] is True

    def test_leakage_no_subcommand(self):
        code, out, err = run_cli("leakage")
        assert code == 0


# ═══════════════════════════════════════════════════════════════════════════
# 14. Subcommand group help (no subcommand -> show help, exit 0)
# ═══════════════════════════════════════════════════════════════════════════


class TestSubcommandGroupHelp:
    """All command groups should print help and exit 0 when no sub given."""

    @pytest.mark.parametrize(
        "group",
        [
            "node",
            "fingerprint",
            "access",
            "reputation",
            "contribution",
            "leakage",
            "sandbox",
            "testnet",
            "keys",
            "cache",
            "agent",
            "task",
        ],
    )
    def test_group_no_subcommand_shows_help(self, group):
        code, out, err = run_cli(group)
        assert code == 0


class TestTestnetCli:
    def test_testnet_group_help_marks_local_simulation(self):
        code, out, err = run_cli("testnet")
        assert code == 0
        assert "local sandbox" in out.lower()

    def test_testnet_status_json_marks_local_simulation(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        code, out, err = run_cli("--json", "testnet", "status")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["mode"] == "LOCAL_SIMULATION"
        assert parsed["network"] == "sandbox"

    def test_sandbox_status_json_marks_local_simulation(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        code, out, err = run_cli("--json", "sandbox", "status")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["mode"] == "LOCAL_SIMULATION"
        assert parsed["network"] == "sandbox"


class TestDoctor:
    @patch("requests.get")
    @patch("shutil.which", return_value="/usr/local/bin/datavault")
    @patch("oasyce.cli._import_optional_module")
    @patch("oasyce.update_manager.read_managed_install_state")
    @patch("oasyce.identity.Wallet.exists", return_value=True)
    def test_public_beta_doctor_json_success(
        self,
        mock_wallet_exists,
        mock_managed_state,
        mock_import_module,
        mock_which,
        mock_requests_get,
        monkeypatch,
    ):
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "testnet")
        mock_managed_state.return_value = {
            "auto_update": True,
            "installed_via_bootstrap": True,
        }

        health = MagicMock()
        health.json.return_value = {"status": "ok", "chain_id": "oasyce-testnet-1"}
        health.raise_for_status.return_value = None
        params = MagicMock()
        params.json.return_value = {
            "params": {"airdrop_amount": {"amount": "1"}, "pow_difficulty": 16}
        }
        params.raise_for_status.return_value = None
        mock_requests_get.side_effect = [health, params]

        code, out, err = run_cli("doctor", "--public-beta", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["scope"] == "public_beta"
        assert parsed["status"] == "ok"
        assert parsed["errors"] == 0
        names = {item["name"] for item in parsed["checks"]}
        assert "Network mode" in names
        assert "Strict chain mode" in names
        assert "Public chain health" in names

    @patch("requests.get")
    @patch("shutil.which", return_value=None)
    @patch("oasyce.cli._import_optional_module", side_effect=ImportError("missing datavault"))
    @patch("oasyce.update_manager.read_managed_install_state", return_value={"auto_update": False})
    @patch("oasyce.identity.Wallet.exists", return_value=False)
    def test_public_beta_doctor_json_failure(
        self,
        mock_wallet_exists,
        mock_managed_state,
        mock_import_module,
        mock_which,
        mock_requests_get,
        monkeypatch,
    ):
        monkeypatch.delenv("OASYCE_NETWORK_MODE", raising=False)
        mock_requests_get.side_effect = RuntimeError("offline")

        code, out, err = run_cli("doctor", "--public-beta", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["scope"] == "public_beta"
        assert parsed["status"] == "error"
        assert parsed["errors"] >= 1
        details = {item["name"]: item["detail"] for item in parsed["checks"]}
        assert "Set OASYCE_NETWORK_MODE=testnet" in details["Network mode"]
        assert "Run `oas bootstrap`" in details["Managed install"]


# ═══════════════════════════════════════════════════════════════════════════
# 15. Feedback command
# ═══════════════════════════════════════════════════════════════════════════


class TestFeedback:

    @patch("oasyce.cli.Config")
    def test_feedback_direct_db_json(self, mock_config_cls, tmp_path):
        """Feedback should fall back to local DB when server is unreachable."""
        cfg = MagicMock()
        cfg.data_dir = str(tmp_path)
        mock_config_cls.from_env.return_value = cfg

        code, out, err = run_cli("feedback", "This is a bug report", "--type", "bug", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed.get("ok") is True or "feedback_id" in parsed

    def test_feedback_empty_message(self):
        """Empty message should produce an error."""
        code, out, err = run_cli("feedback", "", "--json")
        assert code == 1
        parsed = json.loads(out)
        assert parsed["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 16. Parametric: --json flag produces valid JSON across many commands
# ═══════════════════════════════════════════════════════════════════════════


class TestJsonOutputFormat:
    """Ensure various commands with --json produce parseable JSON on stdout."""

    @patch("oasyce.services.facade.OasyceServiceFacade")
    @patch("oasyce.identity.Wallet")
    def test_register_json_is_valid(self, mock_wallet_cls, mock_facade_cls, tmp_path):
        mock_wallet_cls.get_address.return_value = "addr"
        facade = mock_facade_cls.return_value
        facade.register.return_value = ServiceResult(
            success=True,
            data={"asset_id": "OAS_J", "owner": "addr", "filename": "f", "tags": []},
        )
        f = tmp_path / "f.csv"
        f.write_text("a\n1\n")

        code, out, err = run_cli("register", str(f), "--json")
        assert code == 0
        json.loads(out)  # must not raise

    @patch("oasyce.services.facade.OasyceServiceFacade")
    def test_quote_json_is_valid(self, mock_facade_cls):
        facade = mock_facade_cls.return_value
        facade.quote.return_value = ServiceResult(success=True, data={"payment_oas": 10.0})

        code, out, err = run_cli("quote", "OAS_X", "--json")
        assert code == 0
        json.loads(out)

    def test_info_json_is_valid(self):
        code, out, err = run_cli("info", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert isinstance(parsed, dict)


class TestSupport:

    @patch("oasyce.client.Oasyce")
    def test_support_beta_json(self, mock_client_cls):
        client = mock_client_cls.return_value
        client.support_beta.return_value = {
            "ok": True,
            "events": [{"event": "buy.failed"}],
            "failures": [{"event": "buy.failed"}],
            "transactions": [{"tx_id": "tx-1"}],
        }

        code, out, err = run_cli("support", "beta", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["ok"] is True
        assert parsed["events"][0]["event"] == "buy.failed"


# ═══════════════════════════════════════════════════════════════════════════
# 17. Contribution commands
# ═══════════════════════════════════════════════════════════════════════════


class TestContribution:

    def test_contribution_no_subcommand(self):
        code, out, err = run_cli("contribution")
        assert code == 0

    @patch("oasyce.services.contribution.ContributionEngine")
    def test_contribution_prove_json(self, mock_engine_cls, tmp_path):
        cert = MagicMock()
        cert.to_dict.return_value = {
            "content_hash": "abc123",
            "source_type": "manual",
            "creator_key": "pk1",
            "timestamp": 1700000000,
            "semantic_fingerprint": [0.1, 0.2, 0.3],
        }
        engine = mock_engine_cls.return_value
        engine.generate_proof.return_value = cert

        f = tmp_path / "data.txt"
        f.write_text("some data")

        code, out, err = run_cli("contribution", "prove", str(f), "--creator", "pk1", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["content_hash"] == "abc123"


# ═══════════════════════════════════════════════════════════════════════════
# 18. Discover command
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscover:

    @patch("oasyce.services.discovery.SkillDiscoveryEngine")
    def test_discover_json(self, mock_discovery_cls):
        candidate = MagicMock()
        candidate.capability_id = "CAP_01"
        candidate.name = "Translate"
        candidate.provider = "alice"
        candidate.tags = ["nlp"]
        candidate.final_score = 0.95
        candidate.intent_score = 0.9
        candidate.trust_score = 0.8
        candidate.economic_score = 0.7
        candidate.base_price = 0.5

        engine = mock_discovery_cls.return_value
        engine.discover.return_value = [candidate]

        code, out, err = run_cli("discover", "--intents", "translate", "--tags", "nlp", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert len(parsed) == 1
        assert parsed[0]["capability_id"] == "CAP_01"

    @patch("oasyce.services.discovery.SkillDiscoveryEngine")
    def test_discover_empty(self, mock_discovery_cls):
        engine = mock_discovery_cls.return_value
        engine.discover.return_value = []

        code, out, err = run_cli("discover", "--intents", "nonexistent")
        assert code == 0
        assert "No capabilities found" in out


# ═══════════════════════════════════════════════════════════════════════════
# 19. Asset info / validate
# ═══════════════════════════════════════════════════════════════════════════


class TestAssetInfo:

    @patch("oasyce.cli.OasyceSkills")
    def test_asset_info_json(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        skills.get_asset_standard_skill.return_value = {
            "identity": {
                "asset_id": "OAS_X",
                "creator": "alice",
                "created_at": 1700000000,
                "version": "1.0",
                "namespace": "oasyce",
            },
            "metadata": {
                "title": "Test",
                "tags": ["ai"],
                "file_size_bytes": 1024,
                "description": "",
                "category": "",
            },
            "access_policy": {
                "risk_level": "public",
                "max_access_level": "L3",
                "price_model": "bonding_curve",
                "license_type": "proprietary",
            },
            "compute_interface": {
                "supported_operations": [],
                "runtime": "python3",
                "max_compute_seconds": 300,
                "memory_limit_mb": 1024,
            },
            "provenance": {
                "popc_signature": None,
                "certificate_issuer": None,
                "parent_assets": [],
                "fingerprint_id": None,
                "semantic_vector": None,
            },
        }

        code, out, err = run_cli("asset-info", "OAS_X", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["identity"]["asset_id"] == "OAS_X"

    @patch("oasyce.cli.OasyceSkills")
    def test_asset_validate_json(self, mock_skills_cls):
        skills = mock_skills_cls.return_value
        skills.validate_asset_standard_skill.return_value = {
            "valid": True,
            "errors": [],
        }

        code, out, err = run_cli("asset-validate", "OAS_X", "--json")
        assert code == 0
        parsed = json.loads(out)
        assert parsed["valid"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 20. Unit conversion helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestUnitConversion:
    """Test the from_units / to_units helpers."""

    def test_from_units(self):
        from oasyce.cli import from_units, OAS_DECIMALS

        assert from_units(OAS_DECIMALS) == 1.0
        assert from_units(0) == 0.0

    def test_to_units(self):
        from oasyce.cli import to_units, OAS_DECIMALS

        assert to_units(1.0) == OAS_DECIMALS
        assert to_units(0.0) == 0

    def test_roundtrip(self):
        from oasyce.cli import from_units, to_units

        assert from_units(to_units(3.14)) == pytest.approx(3.14, abs=1e-8)

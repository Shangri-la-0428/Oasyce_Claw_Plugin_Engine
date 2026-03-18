"""
Tests for testnet mode: faucet, onboarding, config isolation.
"""

import os
import shutil
import tempfile
import time
from unittest.mock import patch

import pytest

from oasyce_plugin.config import (
    MAINNET_ECONOMICS,
    TESTNET_ECONOMICS,
    TESTNET_NETWORK_CONFIG,
    NetworkMode,
    get_data_dir,
    get_economics,
)
from oasyce_plugin.consensus.core.types import to_units
from oasyce_plugin.services.faucet import Faucet
from oasyce_plugin.services.testnet import TestnetOnboarding


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="oasyce_testnet_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ── Faucet tests ─────────────────────────────────────────────────────


class TestFaucetClaim:
    def test_faucet_claim(self, tmp_dir):
        """First claim succeeds with expected amount."""
        faucet = Faucet(tmp_dir)
        result = faucet.claim("addr-a")

        assert result["success"] is True
        assert result["amount"] == Faucet.TESTNET_DRIP
        assert result["balance"] == Faucet.TESTNET_DRIP
        assert result["error"] is None

    def test_faucet_cooldown(self, tmp_dir):
        """Second claim within cooldown is rejected."""
        faucet = Faucet(tmp_dir)
        faucet.claim("addr-a")

        result = faucet.claim("addr-a")
        assert result["success"] is False
        assert result["amount"] == 0.0
        assert "Cooldown" in result["error"]

    def test_faucet_cooldown_expires(self, tmp_dir):
        """Claim succeeds after cooldown expires (simulated via time mock)."""
        faucet = Faucet(tmp_dir)
        base = time.time()

        with patch("oasyce_plugin.services.faucet.time") as mock_time:
            mock_time.time.return_value = base
            faucet.claim("addr-a")

            mock_time.time.return_value = base + Faucet.COOLDOWN + 1
            result = faucet.claim("addr-a")
            assert result["success"] is True
            assert result["balance"] == Faucet.TESTNET_DRIP * 2

    def test_faucet_multiple_addresses(self, tmp_dir):
        """Different addresses have independent cooldowns."""
        faucet = Faucet(tmp_dir)

        r1 = faucet.claim("addr-a")
        r2 = faucet.claim("addr-b")

        assert r1["success"] is True
        assert r2["success"] is True

        # addr-a in cooldown, addr-b still independent
        r3 = faucet.claim("addr-a")
        assert r3["success"] is False

    def test_faucet_balance(self, tmp_dir):
        """Balance reflects claims correctly."""
        faucet = Faucet(tmp_dir)
        assert faucet.balance("addr-x") == 0.0

        faucet.claim("addr-x")
        assert faucet.balance("addr-x") == Faucet.TESTNET_DRIP

    def test_faucet_persistence(self, tmp_dir):
        """Faucet state persists across instances."""
        faucet1 = Faucet(tmp_dir)
        faucet1.claim("addr-a")

        faucet2 = Faucet(tmp_dir)
        assert faucet2.balance("addr-a") == Faucet.TESTNET_DRIP

        # Cooldown also persists
        result = faucet2.claim("addr-a")
        assert result["success"] is False

    def test_faucet_reset(self, tmp_dir):
        """Reset clears all faucet state."""
        faucet = Faucet(tmp_dir)
        faucet.claim("addr-a")
        assert faucet.balance("addr-a") == Faucet.TESTNET_DRIP

        faucet.reset()
        assert faucet.balance("addr-a") == 0.0

    def test_faucet_no_now_parameter(self, tmp_dir):
        """claim() does not accept a 'now' parameter — timestamp is internal."""
        faucet = Faucet(tmp_dir)
        import inspect
        sig = inspect.signature(faucet.claim)
        assert "now" not in sig.parameters

    def test_faucet_lifetime_claim_limit(self, tmp_dir):
        """Per-address lifetime claim limit is enforced."""
        faucet = Faucet(tmp_dir)
        base = time.time()

        with patch("oasyce_plugin.services.faucet.time") as mock_time:
            for i in range(Faucet.MAX_CLAIMS_PER_ADDRESS):
                mock_time.time.return_value = base + i * (Faucet.COOLDOWN + 1)
                result = faucet.claim("addr-a")
                assert result["success"] is True

            # Next claim should fail even after cooldown
            mock_time.time.return_value = base + Faucet.MAX_CLAIMS_PER_ADDRESS * (Faucet.COOLDOWN + 1)
            result = faucet.claim("addr-a")
            assert result["success"] is False
            assert "Lifetime claim limit" in result["error"]

    def test_faucet_total_supply_cap(self, tmp_dir):
        """Total supply cap prevents unlimited minting."""
        faucet = Faucet(tmp_dir)
        # Set total_claimed to just under the cap
        faucet._total_claimed = Faucet.MAX_TOTAL_SUPPLY - Faucet.TESTNET_DRIP + 1

        result = faucet.claim("addr-cap")
        assert result["success"] is False
        assert "supply exhausted" in result["error"]

    def test_faucet_total_supply_tracks(self, tmp_dir):
        """Total claimed amount is tracked across claims."""
        faucet = Faucet(tmp_dir)
        assert faucet.total_claimed == 0.0

        faucet.claim("addr-a")
        assert faucet.total_claimed == Faucet.TESTNET_DRIP

        faucet.claim("addr-b")
        assert faucet.total_claimed == Faucet.TESTNET_DRIP * 2


# ── Onboarding tests ────────────────────────────────────────────────


class TestOnboarding:
    def test_onboarding_flow(self, tmp_dir):
        """Full onboarding: faucet + sample asset + stake."""
        onboarding = TestnetOnboarding(tmp_dir)
        result = onboarding.onboard("addr-new")

        # Faucet should succeed
        assert result["faucet_result"]["success"] is True
        assert result["faucet_result"]["amount"] == Faucet.TESTNET_DRIP

        # Sample asset should be created
        assert result["sample_asset"]["asset_id"].startswith("OAS_TEST_")
        assert result["sample_asset"]["creator"] == "addr-new"

        # Summary: 1 simulation label + steps
        assert len(result["summary"]) >= 3
        assert "LOCAL SIMULATION" in result["summary"][0]
        assert result["mode"] == "LOCAL_SIMULATION"

    def test_onboarding_faucet_cooldown(self, tmp_dir):
        """Second onboarding skips faucet but still registers asset."""
        onboarding = TestnetOnboarding(tmp_dir)
        onboarding.onboard("addr-a")

        result = onboarding.onboard("addr-a")
        assert result["faucet_result"]["success"] is False
        assert result["sample_asset"] is not None


# ── Config tests ─────────────────────────────────────────────────────


class TestTestnetConfig:
    def test_testnet_config(self):
        """Testnet economics parameters are correct."""
        assert TESTNET_ECONOMICS["block_reward"] == to_units(40)
        assert TESTNET_ECONOMICS["min_stake"] == to_units(100)
        assert TESTNET_ECONOMICS["agent_stake"] == to_units(1)
        assert TESTNET_ECONOMICS["halving_interval"] == 10000

    def test_testnet_economics_differ_from_mainnet(self):
        """Testnet and mainnet economics are different."""
        assert TESTNET_ECONOMICS["block_reward"] != MAINNET_ECONOMICS["block_reward"]
        assert TESTNET_ECONOMICS["min_stake"] != MAINNET_ECONOMICS["min_stake"]
        assert TESTNET_ECONOMICS["halving_interval"] != MAINNET_ECONOMICS["halving_interval"]

        # Testnet should be more generous
        assert TESTNET_ECONOMICS["block_reward"] > MAINNET_ECONOMICS["block_reward"]
        assert TESTNET_ECONOMICS["min_stake"] < MAINNET_ECONOMICS["min_stake"]

    def test_network_mode_enum(self):
        """NetworkMode enum values."""
        assert NetworkMode.MAINNET == "mainnet"
        assert NetworkMode.TESTNET == "testnet"
        assert NetworkMode.LOCAL == "local"

    def test_testnet_port(self):
        """Testnet uses different port from mainnet default."""
        assert TESTNET_NETWORK_CONFIG.listen_port == 9528

    def test_data_dir_isolation(self):
        """Testnet and mainnet use different data directories."""
        mainnet_dir = get_data_dir(NetworkMode.MAINNET)
        testnet_dir = get_data_dir(NetworkMode.TESTNET)
        assert mainnet_dir != testnet_dir
        assert "oasyce-testnet" in testnet_dir
        assert "oasyce-testnet" not in mainnet_dir

    def test_get_economics(self):
        """get_economics returns correct params for each mode."""
        main_econ = get_economics(NetworkMode.MAINNET)
        test_econ = get_economics(NetworkMode.TESTNET)
        assert main_econ["min_stake"] == to_units(10000)
        assert test_econ["min_stake"] == to_units(100)

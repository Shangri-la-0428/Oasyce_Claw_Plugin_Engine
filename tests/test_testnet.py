"""
Tests for testnet mode: faucet, onboarding, config isolation.
"""

import os
import shutil
import tempfile
import time

import pytest

from oasyce_plugin.config import (
    MAINNET_ECONOMICS,
    TESTNET_ECONOMICS,
    TESTNET_NETWORK_CONFIG,
    NetworkMode,
    get_data_dir,
    get_economics,
)
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
        result = faucet.claim("node-a", now=1000.0)

        assert result["success"] is True
        assert result["amount"] == Faucet.TESTNET_DRIP
        assert result["balance"] == Faucet.TESTNET_DRIP
        assert result["error"] is None

    def test_faucet_cooldown(self, tmp_dir):
        """Second claim within cooldown is rejected."""
        faucet = Faucet(tmp_dir)
        faucet.claim("node-a", now=1000.0)

        result = faucet.claim("node-a", now=1000.0 + 100)
        assert result["success"] is False
        assert result["amount"] == 0.0
        assert "Cooldown" in result["error"]

    def test_faucet_cooldown_expires(self, tmp_dir):
        """Claim succeeds after cooldown expires."""
        faucet = Faucet(tmp_dir)
        faucet.claim("node-a", now=1000.0)

        after_cooldown = 1000.0 + Faucet.COOLDOWN + 1
        result = faucet.claim("node-a", now=after_cooldown)
        assert result["success"] is True
        assert result["balance"] == Faucet.TESTNET_DRIP * 2

    def test_faucet_multiple_nodes(self, tmp_dir):
        """Different nodes have independent cooldowns."""
        faucet = Faucet(tmp_dir)
        now = 5000.0

        r1 = faucet.claim("node-a", now=now)
        r2 = faucet.claim("node-b", now=now)

        assert r1["success"] is True
        assert r2["success"] is True

        # node-a in cooldown, node-b still independent
        r3 = faucet.claim("node-a", now=now + 10)
        assert r3["success"] is False

    def test_faucet_balance(self, tmp_dir):
        """Balance reflects claims correctly."""
        faucet = Faucet(tmp_dir)
        assert faucet.balance("node-x") == 0.0

        faucet.claim("node-x", now=1000.0)
        assert faucet.balance("node-x") == Faucet.TESTNET_DRIP

    def test_faucet_persistence(self, tmp_dir):
        """Faucet state persists across instances."""
        faucet1 = Faucet(tmp_dir)
        faucet1.claim("node-a", now=1000.0)

        faucet2 = Faucet(tmp_dir)
        assert faucet2.balance("node-a") == Faucet.TESTNET_DRIP

        # Cooldown also persists
        result = faucet2.claim("node-a", now=1000.0 + 50)
        assert result["success"] is False

    def test_faucet_reset(self, tmp_dir):
        """Reset clears all faucet state."""
        faucet = Faucet(tmp_dir)
        faucet.claim("node-a", now=1000.0)
        assert faucet.balance("node-a") == Faucet.TESTNET_DRIP

        faucet.reset()
        assert faucet.balance("node-a") == 0.0


# ── Onboarding tests ────────────────────────────────────────────────


class TestOnboarding:
    def test_onboarding_flow(self, tmp_dir):
        """Full onboarding: faucet + sample asset + stake."""
        onboarding = TestnetOnboarding(tmp_dir)
        result = onboarding.onboard("node-new", now=1000.0)

        # Faucet should succeed
        assert result["faucet_result"]["success"] is True
        assert result["faucet_result"]["amount"] == Faucet.TESTNET_DRIP

        # Sample asset should be created
        assert result["sample_asset"]["asset_id"].startswith("OAS_TEST_")
        assert result["sample_asset"]["creator"] == "node-new"

        # Should have enough to stake (10000 >= 100)
        assert result["stake_result"]["staked"] is True
        assert result["stake_result"]["amount"] == TESTNET_ECONOMICS["min_stake"]

        # Summary: 1 simulation label + 3 steps
        assert len(result["summary"]) == 4
        assert "LOCAL SIMULATION" in result["summary"][0]
        assert result["mode"] == "LOCAL_SIMULATION"

    def test_onboarding_faucet_cooldown(self, tmp_dir):
        """Second onboarding skips faucet but still registers + stakes."""
        onboarding = TestnetOnboarding(tmp_dir)
        onboarding.onboard("node-a", now=1000.0)

        result = onboarding.onboard("node-a", now=1000.0 + 100)
        assert result["faucet_result"]["success"] is False
        assert result["sample_asset"] is not None
        # Still has enough from first claim
        assert result["stake_result"]["staked"] is True


# ── Config tests ─────────────────────────────────────────────────────


class TestTestnetConfig:
    def test_testnet_config(self):
        """Testnet economics parameters are correct."""
        assert TESTNET_ECONOMICS["block_reward"] == 40.0
        assert TESTNET_ECONOMICS["min_stake"] == 100.0
        assert TESTNET_ECONOMICS["agent_stake"] == 1.0
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
        assert main_econ["min_stake"] == 10000.0
        assert test_econ["min_stake"] == 100.0

"""Tests for network mode security configuration."""

import pytest

from oasyce.config import (
    MAINNET_SECURITY,
    TESTNET_SECURITY,
    LOCAL_SECURITY,
    NetworkMode,
    get_network_mode,
    get_security,
)


class TestSecurityConfig:
    def test_mainnet_requires_signatures(self):
        sec = get_security(NetworkMode.MAINNET)
        assert sec["require_signatures"] is True
        assert sec["verify_identity"] is True
        assert sec["allow_local_fallback"] is False

    def test_testnet_fails_closed(self):
        sec = get_security(NetworkMode.TESTNET)
        assert sec["require_signatures"] is False
        assert sec["verify_identity"] is False
        assert sec["allow_local_fallback"] is False

    def test_local_relaxed(self):
        sec = get_security(NetworkMode.LOCAL)
        assert sec["require_signatures"] is False
        assert sec["allow_local_fallback"] is True


class TestGetNetworkMode:
    def test_default_is_local(self, monkeypatch):
        monkeypatch.delenv("OASYCE_NETWORK_MODE", raising=False)
        assert get_network_mode() == NetworkMode.LOCAL

    def test_mainnet(self, monkeypatch):
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "mainnet")
        assert get_network_mode() == NetworkMode.MAINNET

    def test_testnet(self, monkeypatch):
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "testnet")
        assert get_network_mode() == NetworkMode.TESTNET

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "MAINNET")
        assert get_network_mode() == NetworkMode.MAINNET

    def test_unknown_falls_to_local(self, monkeypatch):
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "garbage")
        assert get_network_mode() == NetworkMode.LOCAL


class TestFacadeSecurityIntegration:
    def test_mainnet_facade_enforces_identity(self, monkeypatch):
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "mainnet")
        from oasyce.services.facade import OasyceServiceFacade

        facade = OasyceServiceFacade()
        assert facade._verify_identity is True
        assert facade._allow_local_fallback is False

    def test_local_facade_permissive(self, monkeypatch):
        monkeypatch.delenv("OASYCE_NETWORK_MODE", raising=False)
        monkeypatch.delenv("OASYCE_STRICT_CHAIN", raising=False)
        from oasyce.services.facade import OasyceServiceFacade

        facade = OasyceServiceFacade()
        assert facade._verify_identity is False
        assert facade._allow_local_fallback is True

    def test_testnet_facade_is_strict_by_default(self, monkeypatch):
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "testnet")
        monkeypatch.delenv("OASYCE_STRICT_CHAIN", raising=False)
        from oasyce.services.facade import OasyceServiceFacade

        facade = OasyceServiceFacade()
        assert facade._allow_local_fallback is False

    def test_explicit_override_honored(self, monkeypatch):
        """Explicit verify_identity=True overrides even local mode."""
        monkeypatch.delenv("OASYCE_NETWORK_MODE", raising=False)
        from oasyce.services.facade import OasyceServiceFacade

        facade = OasyceServiceFacade(verify_identity=True)
        assert facade._verify_identity is True

    def test_strict_chain_env_overrides_mode(self, monkeypatch):
        """OASYCE_STRICT_CHAIN=1 disables fallback even in testnet mode."""
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "testnet")
        monkeypatch.setenv("OASYCE_STRICT_CHAIN", "1")
        from oasyce.services.facade import OasyceServiceFacade

        facade = OasyceServiceFacade()
        assert facade._allow_local_fallback is False


class TestMainnetBlocksUnsigned:
    def test_buy_rejected_without_signature(self, monkeypatch):
        """Mainnet mode rejects buy without valid signature."""
        monkeypatch.setenv("OASYCE_NETWORK_MODE", "mainnet")
        from oasyce.services.facade import OasyceServiceFacade

        facade = OasyceServiceFacade(allow_local_fallback=True)
        se = facade._get_settlement()
        se.register_asset("AUTH_BUY", "creator", initial_reserve=100.0)

        result = facade.buy("AUTH_BUY", "buyer", 10.0)
        assert not result.success
        assert "identity" in result.error.lower() or "signature" in result.error.lower()

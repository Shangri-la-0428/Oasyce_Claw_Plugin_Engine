"""
Tests for oasyce_plugin.identity — Wallet identity module.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from oasyce_plugin.identity import Wallet, _load_or_create_encryption_key


@pytest.fixture
def tmp_wallet(tmp_path):
    """Provide a temporary wallet path and a fixed passphrase."""
    wallet_path = tmp_path / "wallet.json"
    passphrase = "test-passphrase-for-ci"
    return wallet_path, passphrase


class TestWalletExists:
    def test_exists_false_when_no_file(self, tmp_path):
        wallet_path = tmp_path / "wallet.json"
        assert Wallet.exists(wallet_path) is False

    def test_exists_true_after_create(self, tmp_wallet):
        wallet_path, passphrase = tmp_wallet
        Wallet.create(wallet_path=wallet_path, passphrase=passphrase)
        assert Wallet.exists(wallet_path) is True


class TestWalletCreate:
    def test_create_returns_wallet(self, tmp_wallet):
        wallet_path, passphrase = tmp_wallet
        wallet = Wallet.create(wallet_path=wallet_path, passphrase=passphrase)
        assert isinstance(wallet, Wallet)
        assert len(wallet.address) == 64  # 32 bytes hex = 64 chars

    def test_create_persists_file(self, tmp_wallet):
        wallet_path, passphrase = tmp_wallet
        Wallet.create(wallet_path=wallet_path, passphrase=passphrase)
        assert wallet_path.is_file()

        data = json.loads(wallet_path.read_text())
        assert "version" in data
        assert "public_key" in data
        assert "encrypted_private_key" in data

    def test_create_file_permissions(self, tmp_wallet):
        wallet_path, passphrase = tmp_wallet
        Wallet.create(wallet_path=wallet_path, passphrase=passphrase)
        mode = os.stat(wallet_path).st_mode & 0o777
        assert mode == 0o600


class TestWalletLoad:
    def test_load_recovers_same_address(self, tmp_wallet):
        wallet_path, passphrase = tmp_wallet
        created = Wallet.create(wallet_path=wallet_path, passphrase=passphrase)
        loaded = Wallet.load(wallet_path=wallet_path, passphrase=passphrase)
        assert loaded.address == created.address

    def test_load_recovers_private_key(self, tmp_wallet):
        wallet_path, passphrase = tmp_wallet
        created = Wallet.create(wallet_path=wallet_path, passphrase=passphrase)
        loaded = Wallet.load(wallet_path=wallet_path, passphrase=passphrase)
        assert loaded.private_key_hex == created.private_key_hex

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Wallet.load(wallet_path=tmp_path / "nope.json", passphrase="x")

    def test_load_wrong_passphrase_raises(self, tmp_wallet):
        wallet_path, passphrase = tmp_wallet
        Wallet.create(wallet_path=wallet_path, passphrase=passphrase)
        with pytest.raises(Exception):
            Wallet.load(wallet_path=wallet_path, passphrase="wrong-passphrase")


class TestAddressDeterminism:
    def test_address_is_deterministic_across_loads(self, tmp_wallet):
        """Loading the same wallet multiple times yields the same address."""
        wallet_path, passphrase = tmp_wallet
        created = Wallet.create(wallet_path=wallet_path, passphrase=passphrase)
        addr1 = Wallet.load(wallet_path=wallet_path, passphrase=passphrase).address
        addr2 = Wallet.load(wallet_path=wallet_path, passphrase=passphrase).address
        assert addr1 == addr2 == created.address

    def test_different_wallets_have_different_addresses(self, tmp_path):
        """Two independently created wallets should have distinct addresses."""
        w1 = Wallet.create(wallet_path=tmp_path / "w1.json", passphrase="p1")
        w2 = Wallet.create(wallet_path=tmp_path / "w2.json", passphrase="p2")
        assert w1.address != w2.address


class TestGetAddress:
    def test_get_address_returns_none_when_no_wallet(self, tmp_path):
        assert Wallet.get_address(tmp_path / "nope.json") is None

    def test_get_address_returns_pubkey_without_decryption(self, tmp_wallet):
        wallet_path, passphrase = tmp_wallet
        created = Wallet.create(wallet_path=wallet_path, passphrase=passphrase)
        # get_address does not need the passphrase
        addr = Wallet.get_address(wallet_path)
        assert addr == created.address

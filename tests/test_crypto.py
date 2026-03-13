"""Tests for Ed25519 crypto module."""

import os
import pytest
from oasyce_plugin.crypto import generate_keypair, load_or_create_keypair, sign, verify


class TestGenerateKeypair:
    def test_returns_hex_strings(self):
        priv, pub = generate_keypair()
        assert isinstance(priv, str)
        assert isinstance(pub, str)
        # Ed25519 private key = 32 bytes = 64 hex chars
        assert len(priv) == 64
        # Ed25519 public key = 32 bytes = 64 hex chars
        assert len(pub) == 64

    def test_keys_are_valid_hex(self):
        priv, pub = generate_keypair()
        bytes.fromhex(priv)
        bytes.fromhex(pub)

    def test_each_call_produces_unique_keys(self):
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        assert priv1 != priv2
        assert pub1 != pub2


class TestLoadOrCreateKeypair:
    def test_creates_keys_when_missing(self, tmp_path):
        key_dir = str(tmp_path / "keys")
        priv, pub = load_or_create_keypair(key_dir)
        assert len(priv) == 64
        assert len(pub) == 64
        assert (tmp_path / "keys" / "private.key").exists()
        assert (tmp_path / "keys" / "public.key").exists()

    def test_loads_existing_keys(self, tmp_path):
        key_dir = str(tmp_path / "keys")
        priv1, pub1 = load_or_create_keypair(key_dir)
        priv2, pub2 = load_or_create_keypair(key_dir)
        assert priv1 == priv2
        assert pub1 == pub2


class TestSignAndVerify:
    def test_sign_verify_roundtrip(self):
        priv, pub = generate_keypair()
        message = b"hello oasyce"
        sig = sign(message, priv)
        assert verify(message, sig, pub)

    def test_wrong_message_fails(self):
        priv, pub = generate_keypair()
        sig = sign(b"correct message", priv)
        assert not verify(b"wrong message", sig, pub)

    def test_wrong_key_fails(self):
        priv1, pub1 = generate_keypair()
        _, pub2 = generate_keypair()
        sig = sign(b"test", priv1)
        assert not verify(b"test", sig, pub2)

    def test_tampered_signature_fails(self):
        priv, pub = generate_keypair()
        sig = sign(b"data", priv)
        # Flip one hex char
        tampered = sig[:-1] + ("0" if sig[-1] != "0" else "1")
        assert not verify(b"data", tampered, pub)

    def test_signature_is_hex_string(self):
        priv, _ = generate_keypair()
        sig = sign(b"msg", priv)
        assert isinstance(sig, str)
        bytes.fromhex(sig)
        # Ed25519 signature = 64 bytes = 128 hex chars
        assert len(sig) == 128

"""
Tests for Ed25519 signature verification on consensus Operations.

Covers: keypair generation, serialization, signing, verification,
tamper detection, replay protection, CLI key management, and
integration with the consensus engine.
"""

import json
import os
import time
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

from oasyce_plugin.crypto.keys import generate_keypair, load_or_create_keypair, sign, verify
from oasyce_plugin.consensus.core.types import Operation, OperationType, to_units
from oasyce_plugin.consensus.core.signature import (
    serialize_operation,
    sign_operation,
    verify_signature,
    operation_hash,
)
from oasyce_plugin.consensus.core.validation import (
    _validate_signature,
    _require_signatures,
    validate_operation,
)
from oasyce_plugin.consensus import ConsensusEngine


# ── Helpers ────────────────────────────────────────────────────────

def _make_engine(tmp_path=None):
    """Create an in-memory ConsensusEngine for testing."""
    db = str(tmp_path / "test.db") if tmp_path else None
    return ConsensusEngine(db_path=db)


def _make_op(**kwargs):
    """Create a test operation with sensible defaults."""
    defaults = dict(
        op_type=OperationType.REGISTER,
        validator_id="val_test_001",
        amount=to_units(200),
        commission_rate=1000,
    )
    defaults.update(kwargs)
    return Operation(**defaults)


def _signed_op(op, priv_hex, pub_hex):
    """Sign an operation and return it with sender/signature/timestamp."""
    ts = int(time.time())
    unsigned = replace(op, sender=pub_hex, timestamp=ts, signature="")
    sig = sign_operation(unsigned, priv_hex)
    return replace(unsigned, signature=sig)


# ── 1. Keypair generation ─────────────────────────────────────────

class TestKeypairGeneration:
    def test_generate_keypair_returns_hex_strings(self):
        priv, pub = generate_keypair()
        assert isinstance(priv, str) and isinstance(pub, str)
        bytes.fromhex(priv)
        bytes.fromhex(pub)

    def test_keypair_lengths(self):
        priv, pub = generate_keypair()
        assert len(bytes.fromhex(priv)) == 32
        assert len(bytes.fromhex(pub)) == 32

    def test_keypairs_are_unique(self):
        k1 = generate_keypair()
        k2 = generate_keypair()
        assert k1 != k2

    def test_load_or_create_keypair_creates_files(self, tmp_path):
        key_dir = str(tmp_path / "keys")
        priv, pub = load_or_create_keypair(key_dir)
        assert (tmp_path / "keys" / "private.key").exists()
        assert (tmp_path / "keys" / "public.key").exists()

    def test_load_or_create_keypair_idempotent(self, tmp_path):
        key_dir = str(tmp_path / "keys")
        k1 = load_or_create_keypair(key_dir)
        k2 = load_or_create_keypair(key_dir)
        assert k1 == k2

    def test_encrypted_keypair(self, tmp_path):
        key_dir = str(tmp_path / "keys")
        priv, pub = load_or_create_keypair(key_dir, passphrase="test123")
        assert (tmp_path / "keys" / "private.key.enc").exists()
        # Reload with same passphrase
        priv2, pub2 = load_or_create_keypair(key_dir, passphrase="test123")
        assert priv == priv2 and pub == pub2

    def test_key_file_permissions(self, tmp_path):
        key_dir = str(tmp_path / "keys")
        load_or_create_keypair(key_dir)
        priv_file = tmp_path / "keys" / "private.key"
        mode = priv_file.stat().st_mode & 0o777
        assert mode == 0o600


# ── 2. Operation serialization ────────────────────────────────────

class TestSerialization:
    def test_serialize_is_deterministic(self):
        op = _make_op()
        assert serialize_operation(op) == serialize_operation(op)

    def test_serialize_excludes_signature_and_sender(self):
        op = _make_op(signature="deadbeef", sender="cafe0000")
        raw = serialize_operation(op)
        payload = json.loads(raw)
        assert "signature" not in payload
        assert "sender" not in payload

    def test_serialize_includes_timestamp(self):
        op = _make_op(timestamp=1234567890)
        payload = json.loads(serialize_operation(op))
        assert payload["timestamp"] == 1234567890

    def test_different_ops_different_serialization(self):
        op1 = _make_op(amount=100)
        op2 = _make_op(amount=200)
        assert serialize_operation(op1) != serialize_operation(op2)

    def test_serialize_sorted_keys(self):
        op = _make_op()
        payload = json.loads(serialize_operation(op))
        keys = list(payload.keys())
        assert keys == sorted(keys)


# ── 3. Signing and verification ───────────────────────────────────

class TestSignAndVerify:
    def test_sign_and_verify_roundtrip(self):
        priv, pub = generate_keypair()
        op = _make_op()
        sig = sign_operation(op, priv)
        assert verify_signature(op, sig, pub)

    def test_wrong_key_fails(self):
        priv1, pub1 = generate_keypair()
        _priv2, pub2 = generate_keypair()
        op = _make_op()
        sig = sign_operation(op, priv1)
        assert not verify_signature(op, sig, pub2)

    def test_tampered_amount_fails(self):
        priv, pub = generate_keypair()
        op = _make_op(amount=100)
        sig = sign_operation(op, priv)
        tampered = replace(op, amount=999)
        assert not verify_signature(tampered, sig, pub)

    def test_tampered_validator_id_fails(self):
        priv, pub = generate_keypair()
        op = _make_op(validator_id="v1")
        sig = sign_operation(op, priv)
        tampered = replace(op, validator_id="v2")
        assert not verify_signature(tampered, sig, pub)

    def test_tampered_op_type_fails(self):
        priv, pub = generate_keypair()
        op = _make_op(op_type=OperationType.DELEGATE, validator_id="v1", amount=100)
        sig = sign_operation(op, priv)
        tampered = replace(op, op_type=OperationType.UNDELEGATE)
        assert not verify_signature(tampered, sig, pub)

    def test_tampered_timestamp_fails(self):
        priv, pub = generate_keypair()
        op = _make_op(timestamp=1000)
        sig = sign_operation(op, priv)
        tampered = replace(op, timestamp=2000)
        assert not verify_signature(tampered, sig, pub)

    def test_empty_signature_fails(self):
        _, pub = generate_keypair()
        op = _make_op()
        assert not verify_signature(op, "", pub)

    def test_empty_public_key_fails(self):
        priv, _ = generate_keypair()
        op = _make_op()
        sig = sign_operation(op, priv)
        assert not verify_signature(op, sig, "")

    def test_invalid_hex_signature_fails(self):
        _, pub = generate_keypair()
        op = _make_op()
        assert not verify_signature(op, "not_hex", pub)

    def test_truncated_signature_fails(self):
        priv, pub = generate_keypair()
        op = _make_op()
        sig = sign_operation(op, priv)
        assert not verify_signature(op, sig[:32], pub)

    def test_sign_operation_returns_hex(self):
        priv, _ = generate_keypair()
        sig = sign_operation(_make_op(), priv)
        bytes.fromhex(sig)
        assert len(bytes.fromhex(sig)) == 64  # Ed25519 sig is 64 bytes


# ── 4. Operation hash ─────────────────────────────────────────────

class TestOperationHash:
    def test_hash_deterministic(self):
        op = _make_op()
        assert operation_hash(op) == operation_hash(op)

    def test_different_ops_different_hash(self):
        op1 = _make_op(amount=100)
        op2 = _make_op(amount=200)
        assert operation_hash(op1) != operation_hash(op2)

    def test_hash_is_sha256_hex(self):
        h = operation_hash(_make_op())
        assert len(h) == 64
        bytes.fromhex(h)


# ── 5. Validation layer ──────────────────────────────────────────

class TestValidateSignature:
    def test_no_signature_required_by_default(self):
        """Without REQUIRE_SIGNATURES, unsigned ops pass."""
        op = _make_op()
        ok, err = _validate_signature(op)
        assert ok and err == ""

    def test_system_ops_bypass_signature(self):
        """SLASH and REWARD bypass signature even when required."""
        with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
            slash_op = _make_op(op_type=OperationType.SLASH)
            ok, _ = _validate_signature(slash_op)
            assert ok

            reward_op = _make_op(op_type=OperationType.REWARD)
            ok, _ = _validate_signature(reward_op)
            assert ok

    def test_missing_sender_rejected(self):
        with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
            op = _make_op(signature="aabb", sender="")
            ok, err = _validate_signature(op)
            assert not ok and "sender" in err

    def test_missing_signature_rejected(self):
        with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
            op = _make_op(sender="aabb", signature="")
            ok, err = _validate_signature(op)
            assert not ok and "signature" in err

    def test_invalid_signature_rejected(self):
        with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
            priv, pub = generate_keypair()
            op = _make_op(sender=pub, signature="aa" * 64, timestamp=int(time.time()))
            ok, err = _validate_signature(op)
            assert not ok and "invalid signature" in err

    def test_valid_signature_accepted(self):
        with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
            priv, pub = generate_keypair()
            op = _make_op(timestamp=int(time.time()))
            op = _signed_op(op, priv, pub)
            ok, err = _validate_signature(op)
            assert ok and err == ""

    def test_zero_timestamp_rejected(self):
        with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
            priv, pub = generate_keypair()
            # Manually craft with timestamp=0
            op = _make_op(sender=pub, timestamp=0, signature="")
            sig = sign_operation(op, priv)
            op = replace(op, signature=sig)
            ok, err = _validate_signature(op)
            assert not ok and "timestamp" in err


# ── 6. Replay protection ─────────────────────────────────────────

class TestReplayProtection:
    def test_same_op_different_timestamps(self):
        """Two operations with same content but different timestamps
        produce different signatures (because timestamp is in payload)."""
        priv, pub = generate_keypair()
        op1 = _make_op(timestamp=1000)
        op2 = _make_op(timestamp=2000)
        sig1 = sign_operation(op1, priv)
        sig2 = sign_operation(op2, priv)
        assert sig1 != sig2

    def test_replayed_signature_invalid_for_different_timestamp(self):
        priv, pub = generate_keypair()
        op = _make_op(timestamp=1000)
        sig = sign_operation(op, priv)
        # Replay with new timestamp
        replayed = replace(op, timestamp=2000)
        assert not verify_signature(replayed, sig, pub)


# ── 7. ConsensusEngine.sign_op ────────────────────────────────────

class TestEngineSignOp:
    def test_sign_op_fills_fields(self):
        engine = _make_engine()
        try:
            priv, pub = generate_keypair()
            op = _make_op()
            signed = engine.sign_op(op, priv, pub)
            assert signed.sender == pub
            assert signed.signature != ""
            assert signed.timestamp > 0
        finally:
            engine.close()

    def test_sign_op_produces_valid_signature(self):
        engine = _make_engine()
        try:
            priv, pub = generate_keypair()
            op = _make_op()
            signed = engine.sign_op(op, priv, pub)
            assert verify_signature(signed, signed.signature, signed.sender)
        finally:
            engine.close()

    def test_sign_op_immutability(self):
        """Original op is not modified (frozen dataclass)."""
        engine = _make_engine()
        try:
            priv, pub = generate_keypair()
            op = _make_op()
            signed = engine.sign_op(op, priv, pub)
            assert op.signature == ""
            assert op.sender == ""
            assert signed.signature != ""
        finally:
            engine.close()


# ── 8. Integration: signed ops through engine ─────────────────────

class TestSignedIntegration:
    def test_unsigned_register_works_by_default(self, tmp_path):
        """Without REQUIRE_SIGNATURES, unsigned ops still work."""
        engine = _make_engine(tmp_path)
        try:
            result = engine.register_validator("v1", to_units(200), 1000)
            assert result["ok"]
        finally:
            engine.close()

    def test_signed_register_works(self, tmp_path):
        """Signed operations work regardless of REQUIRE_SIGNATURES."""
        engine = _make_engine(tmp_path)
        try:
            priv, pub = generate_keypair()
            op = Operation(
                op_type=OperationType.REGISTER,
                validator_id="v_signed",
                amount=to_units(200),
                commission_rate=1000,
            )
            signed = engine.sign_op(op, priv, pub)
            result = engine.apply(signed)
            assert result["ok"]
        finally:
            engine.close()

    def test_signed_delegate_works(self, tmp_path):
        engine = _make_engine(tmp_path)
        try:
            priv, pub = generate_keypair()
            # Register first
            engine.register_validator("v1", to_units(200), 1000)
            # Signed delegate
            op = Operation(
                op_type=OperationType.DELEGATE,
                validator_id="v1",
                amount=to_units(50),
                from_addr="delegator1",
            )
            signed = engine.sign_op(op, priv, pub)
            result = engine.apply(signed)
            assert result["ok"]
        finally:
            engine.close()

    def test_enforced_unsigned_rejected(self, tmp_path):
        """With REQUIRE_SIGNATURES=True, unsigned ops are rejected."""
        engine = _make_engine(tmp_path)
        try:
            with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
                op = Operation(
                    op_type=OperationType.REGISTER,
                    validator_id="v_unsigned",
                    amount=to_units(200),
                    commission_rate=1000,
                )
                result = engine.apply(op)
                assert not result["ok"]
                assert "sender" in result["error"] or "signature" in result["error"]
        finally:
            engine.close()

    def test_enforced_signed_accepted(self, tmp_path):
        """With REQUIRE_SIGNATURES=True, properly signed ops pass."""
        engine = _make_engine(tmp_path)
        try:
            with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
                priv, pub = generate_keypair()
                op = Operation(
                    op_type=OperationType.REGISTER,
                    validator_id="v_signed_enforced",
                    amount=to_units(200),
                    commission_rate=1000,
                )
                signed = engine.sign_op(op, priv, pub)
                result = engine.apply(signed)
                assert result["ok"]
        finally:
            engine.close()

    def test_enforced_bad_signature_rejected(self, tmp_path):
        """With REQUIRE_SIGNATURES=True, bad signatures are rejected."""
        engine = _make_engine(tmp_path)
        try:
            with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
                priv, pub = generate_keypair()
                op = Operation(
                    op_type=OperationType.REGISTER,
                    validator_id="v_bad_sig",
                    amount=to_units(200),
                    commission_rate=1000,
                    sender=pub,
                    signature="aa" * 64,
                    timestamp=int(time.time()),
                )
                result = engine.apply(op)
                assert not result["ok"]
                assert "invalid signature" in result["error"]
        finally:
            engine.close()

    def test_enforced_tampered_op_rejected(self, tmp_path):
        """Sign an op then tamper with amount — must be rejected."""
        engine = _make_engine(tmp_path)
        try:
            with mock.patch("oasyce_plugin.consensus.core.validation._require_signatures", return_value=True):
                priv, pub = generate_keypair()
                op = Operation(
                    op_type=OperationType.REGISTER,
                    validator_id="v_tamper",
                    amount=to_units(200),
                    commission_rate=1000,
                )
                signed = engine.sign_op(op, priv, pub)
                tampered = replace(signed, amount=to_units(999))
                result = engine.apply(tampered)
                assert not result["ok"]
                assert "invalid signature" in result["error"]
        finally:
            engine.close()


# ── 9. CLI key management ─────────────────────────────────────────

class TestCLIKeyManagement:
    def test_cmd_keys_generate(self, tmp_path):
        from oasyce_plugin.cli import cmd_keys_generate
        with mock.patch("oasyce_plugin.cli.Config") as MockConfig:
            MockConfig.from_env.return_value.data_dir = str(tmp_path)
            args = mock.MagicMock()
            args.json = False
            args.force = False
            args.passphrase = None
            cmd_keys_generate(args)
            assert (tmp_path / "keys" / "public.key").exists()
            assert (tmp_path / "keys" / "private.key").exists()

    def test_cmd_keys_generate_no_overwrite(self, tmp_path, capsys):
        from oasyce_plugin.cli import cmd_keys_generate
        with mock.patch("oasyce_plugin.cli.Config") as MockConfig:
            MockConfig.from_env.return_value.data_dir = str(tmp_path)
            args = mock.MagicMock()
            args.json = False
            args.force = False
            args.passphrase = None
            cmd_keys_generate(args)  # first
            cmd_keys_generate(args)  # second should warn
            out = capsys.readouterr().out
            assert "already exist" in out

    def test_cmd_keys_generate_force(self, tmp_path):
        from oasyce_plugin.cli import cmd_keys_generate
        with mock.patch("oasyce_plugin.cli.Config") as MockConfig:
            MockConfig.from_env.return_value.data_dir = str(tmp_path)
            args = mock.MagicMock()
            args.json = False
            args.force = False
            args.passphrase = None
            cmd_keys_generate(args)
            pub1 = (tmp_path / "keys" / "public.key").read_text().strip()

            args.force = True
            cmd_keys_generate(args)
            pub2 = (tmp_path / "keys" / "public.key").read_text().strip()
            assert pub1 != pub2

    def test_cmd_keys_show(self, tmp_path, capsys):
        from oasyce_plugin.cli import cmd_keys_generate, cmd_keys_show
        with mock.patch("oasyce_plugin.cli.Config") as MockConfig:
            MockConfig.from_env.return_value.data_dir = str(tmp_path)
            gen_args = mock.MagicMock()
            gen_args.json = False
            gen_args.force = False
            gen_args.passphrase = None
            cmd_keys_generate(gen_args)

            show_args = mock.MagicMock()
            show_args.json = False
            cmd_keys_show(show_args)
            out = capsys.readouterr().out
            assert "Public key:" in out

    def test_cmd_keys_show_no_keys(self, tmp_path, capsys):
        from oasyce_plugin.cli import cmd_keys_show
        with mock.patch("oasyce_plugin.cli.Config") as MockConfig:
            MockConfig.from_env.return_value.data_dir = str(tmp_path)
            args = mock.MagicMock()
            args.json = False
            cmd_keys_show(args)
            out = capsys.readouterr().out
            assert "No keys found" in out

    def test_cmd_keys_generate_json(self, tmp_path, capsys):
        from oasyce_plugin.cli import cmd_keys_generate
        with mock.patch("oasyce_plugin.cli.Config") as MockConfig:
            MockConfig.from_env.return_value.data_dir = str(tmp_path)
            args = mock.MagicMock()
            args.json = True
            args.force = False
            args.passphrase = None
            cmd_keys_generate(args)
            out = capsys.readouterr().out
            data = json.loads(out)
            assert data["ok"]
            assert "public_key" in data

    def test_cmd_keys_show_json(self, tmp_path, capsys):
        from oasyce_plugin.cli import cmd_keys_generate, cmd_keys_show
        with mock.patch("oasyce_plugin.cli.Config") as MockConfig:
            MockConfig.from_env.return_value.data_dir = str(tmp_path)
            gen_args = mock.MagicMock()
            gen_args.json = True
            gen_args.force = False
            gen_args.passphrase = None
            cmd_keys_generate(gen_args)

            show_args = mock.MagicMock()
            show_args.json = True
            cmd_keys_show(show_args)
            out = capsys.readouterr().out
            # Last JSON output is from show
            lines = [l for l in out.strip().split("\n") if l.startswith("{")]
            data = json.loads(lines[-1])
            assert data["ok"]
            assert "public_key" in data


# ── 10. Low-level crypto round-trip ──────────────────────────────

class TestCryptoRoundTrip:
    def test_sign_verify_raw(self):
        priv, pub = generate_keypair()
        msg = b"hello consensus"
        sig = sign(msg, priv)
        assert verify(msg, sig, pub)

    def test_sign_verify_raw_wrong_message(self):
        priv, pub = generate_keypair()
        sig = sign(b"msg1", priv)
        assert not verify(b"msg2", sig, pub)


# ── 11. Edge cases ────────────────────────────────────────────────

class TestEdgeCases:
    def test_operation_with_all_empty_fields(self):
        """Minimal operation can be serialized and signed."""
        priv, pub = generate_keypair()
        op = Operation(op_type=OperationType.REGISTER, validator_id="")
        sig = sign_operation(op, priv)
        assert verify_signature(op, sig, pub)

    def test_operation_with_unicode_reason(self):
        priv, pub = generate_keypair()
        op = _make_op(reason="数据权利争议 — 需要仲裁")
        sig = sign_operation(op, priv)
        assert verify_signature(op, sig, pub)

    def test_operation_with_long_chain_id(self):
        priv, pub = generate_keypair()
        op = _make_op(chain_id="oasyce-mainnet-v2-" + "x" * 200)
        sig = sign_operation(op, priv)
        assert verify_signature(op, sig, pub)

    def test_signature_performance(self):
        """Signature verification should complete in < 1ms per op."""
        priv, pub = generate_keypair()
        op = _make_op()
        sig = sign_operation(op, priv)

        start = time.perf_counter()
        iterations = 100
        for _ in range(iterations):
            verify_signature(op, sig, pub)
        elapsed = (time.perf_counter() - start) / iterations
        assert elapsed < 0.001, f"verify_signature took {elapsed*1000:.2f}ms (>1ms)"

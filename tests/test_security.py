"""
Tests for security hardening: key encryption, feedback persistence, PoPC naming.
"""

import hashlib
import os
import shutil
import sqlite3
import tempfile
import threading

import pytest

from oasyce.crypto.keys import (
    generate_keypair,
    load_or_create_keypair,
    sign,
    verify,
)
from oasyce.engines.core_engines import CertificateEngine, MetadataEngine, DataEngine
from oasyce.services.discovery.feedback import ExecutionRecord, FeedbackStore

# Check if we're using the built-in (hardened) Ledger or oasyce_core's
try:
    from oasyce.storage.ledger import Ledger as _Ledger

    _has_builtin_ledger = hasattr(_Ledger, "attempt_reorg")
except ImportError:
    _has_builtin_ledger = False

_builtin_only = pytest.mark.skipif(
    not _has_builtin_ledger,
    reason="Requires built-in Ledger with reorg support",
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="oasyce_sec_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def memory_ledger():
    from oasyce.storage.ledger import Ledger

    return Ledger(db_path=":memory:")


# ── Chain Reorg Validation (built-in only) ────────────────────────────


@_builtin_only
class TestChainReorgValidation:
    def test_reorg_rejects_broken_chain(self, memory_ledger):
        """attempt_reorg rejects chains with broken prev_hash links."""
        memory_ledger.record_tx("test", asset_id="a1")
        memory_ledger.create_block()

        broken_chain = [
            {
                "block_number": 0,
                "block_hash": "aaa",
                "prev_hash": "0" * 64,
                "merkle_root": "x",
                "timestamp": "2024-01-01",
                "tx_count": 0,
            },
            {
                "block_number": 1,
                "block_hash": "bbb",
                "prev_hash": "WRONG",
                "merkle_root": "y",
                "timestamp": "2024-01-02",
                "tx_count": 0,
            },
            {
                "block_number": 2,
                "block_hash": "ccc",
                "prev_hash": "bbb",
                "merkle_root": "z",
                "timestamp": "2024-01-03",
                "tx_count": 0,
            },
        ]
        assert memory_ledger.attempt_reorg(broken_chain) is False

    def test_reorg_accepts_valid_chain(self, memory_ledger):
        """attempt_reorg accepts a valid longer chain."""
        memory_ledger.record_tx("test", asset_id="a1")
        memory_ledger.create_block()

        valid_chain = [
            {
                "block_number": 0,
                "block_hash": "aaa",
                "prev_hash": "0" * 64,
                "merkle_root": "x",
                "timestamp": "2024-01-01",
                "tx_count": 0,
            },
            {
                "block_number": 1,
                "block_hash": "bbb",
                "prev_hash": "aaa",
                "merkle_root": "y",
                "timestamp": "2024-01-02",
                "tx_count": 0,
            },
            {
                "block_number": 2,
                "block_hash": "ccc",
                "prev_hash": "bbb",
                "merkle_root": "z",
                "timestamp": "2024-01-03",
                "tx_count": 0,
            },
        ]
        assert memory_ledger.attempt_reorg(valid_chain) is True
        assert memory_ledger.get_chain_height() == 3


# ── Thread-Safe Ledger (built-in only) ───────────────────────────────


@_builtin_only
class TestThreadSafeLedger:
    def test_concurrent_writes(self, memory_ledger):
        """Multiple threads can write transactions without errors."""
        errors = []

        def writer(n):
            try:
                for i in range(20):
                    memory_ledger.record_tx("test", asset_id=f"asset_{n}_{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert memory_ledger.count_transactions() == 100

    def test_concurrent_read_write(self, memory_ledger):
        """Reads and writes can happen concurrently."""
        errors = []
        stop = threading.Event()

        def writer():
            try:
                for i in range(50):
                    memory_ledger.record_tx("test", asset_id=f"asset_{i}")
            except Exception as e:
                errors.append(e)
            finally:
                stop.set()

        def reader():
            try:
                while not stop.is_set():
                    memory_ledger.count_transactions()
                    memory_ledger.get_pending_transactions()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == []


# ── LIKE Escaping (built-in only) ────────────────────────────────────


@_builtin_only
class TestLikeEscaping:
    def test_search_escapes_percent(self, memory_ledger):
        """LIKE wildcards in search queries are escaped."""
        memory_ledger.register_asset("a1", "owner1", "hash1", {"tags": ["100% safe"]})
        memory_ledger.register_asset("a2", "owner2", "hash2", {"tags": ["hello"]})

        results = memory_ledger.search_assets("100%")
        assert len(results) == 1
        assert results[0]["asset_id"] == "a1"

    def test_search_escapes_underscore(self, memory_ledger):
        """Single-char wildcard _ is escaped in search."""
        memory_ledger.register_asset("a_b", "owner", "hash1", {"name": "a_b"})
        memory_ledger.register_asset("acb", "owner", "hash2", {"name": "acb"})

        results = memory_ledger.search_assets("a_b")
        assert any(r["asset_id"] == "a_b" for r in results)


# ── Key Encryption ───────────────────────────────────────────────────


class TestKeyEncryption:
    def test_plaintext_backward_compat(self, tmp_dir):
        """Without passphrase, keys stored as plaintext hex."""
        key_dir = os.path.join(tmp_dir, "keys")
        priv, pub = load_or_create_keypair(key_dir)
        priv_file = os.path.join(key_dir, "private.key")
        assert os.path.exists(priv_file)
        assert open(priv_file).read().strip() == priv

    def test_encrypted_roundtrip(self, tmp_dir):
        """Keys encrypted with passphrase can be decrypted."""
        key_dir = os.path.join(tmp_dir, "keys_enc")
        priv1, pub1 = load_or_create_keypair(key_dir, passphrase="test123")

        enc_file = os.path.join(key_dir, "private.key.enc")
        assert os.path.exists(enc_file)
        plain_file = os.path.join(key_dir, "private.key")
        assert not os.path.exists(plain_file)

        priv2, pub2 = load_or_create_keypair(key_dir, passphrase="test123")
        assert priv1 == priv2
        assert pub1 == pub2

    def test_wrong_passphrase_fails(self, tmp_dir):
        """Wrong passphrase raises an error."""
        key_dir = os.path.join(tmp_dir, "keys_wrong")
        load_or_create_keypair(key_dir, passphrase="correct")
        with pytest.raises(Exception):
            load_or_create_keypair(key_dir, passphrase="wrong")

    def test_file_permissions(self, tmp_dir):
        """Key files have restricted permissions."""
        key_dir = os.path.join(tmp_dir, "keys_perm")
        load_or_create_keypair(key_dir)
        priv_file = os.path.join(key_dir, "private.key")
        mode = os.stat(priv_file).st_mode & 0o777
        assert mode == 0o600

    def test_encrypted_key_can_sign(self, tmp_dir):
        """Keys from encrypted storage produce valid signatures."""
        key_dir = os.path.join(tmp_dir, "keys_sign")
        priv, pub = load_or_create_keypair(key_dir, passphrase="mypass")
        msg = b"hello world"
        sig = sign(msg, priv)
        assert verify(msg, sig, pub)


# ── FeedbackStore Persistence ────────────────────────────────────────


class TestFeedbackPersistence:
    def test_in_memory_default(self):
        """Default FeedbackStore is in-memory."""
        fs = FeedbackStore()
        fs.record(ExecutionRecord(skill_id="s1", success=True, latency_ms=100, caller_rating=4.0))
        assert fs.learned_trust("s1") is not None

    def test_sqlite_persistence(self, tmp_dir):
        """FeedbackStore persists to SQLite and survives restart."""
        db_path = os.path.join(tmp_dir, "feedback.db")

        fs1 = FeedbackStore(db_path=db_path)
        fs1.record(ExecutionRecord(skill_id="s1", success=True, latency_ms=100, caller_rating=5.0))
        fs1.record(ExecutionRecord(skill_id="s1", success=False, latency_ms=200, caller_rating=1.0))
        trust1 = fs1.learned_trust("s1")
        stats1 = fs1.stats("s1")

        fs2 = FeedbackStore(db_path=db_path)
        trust2 = fs2.learned_trust("s1")
        stats2 = fs2.stats("s1")

        assert stats2["total"] == 2
        assert stats2["successes"] == 1
        assert abs(trust1 - trust2) < 0.01

    def test_sqlite_eviction(self, tmp_dir):
        """Eviction removes oldest records from both memory and DB."""
        db_path = os.path.join(tmp_dir, "feedback_evict.db")
        fs = FeedbackStore(db_path=db_path)

        for i in range(FeedbackStore.MAX_RECORDS_PER_SKILL + 50):
            fs.record(
                ExecutionRecord(
                    skill_id="s1",
                    success=True,
                    latency_ms=10,
                    caller_rating=4.0,
                    timestamp=1000 + i,
                )
            )

        stats = fs.stats("s1")
        assert stats["total"] == FeedbackStore.MAX_RECORDS_PER_SKILL

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM feedback_records WHERE skill_id='s1'"
        ).fetchone()[0]
        conn.close()
        assert count == FeedbackStore.MAX_RECORDS_PER_SKILL


# ── PoPC Naming ──────────────────────────────────────────────────────


class TestPoPCNaming:
    def test_certificate_type_is_digital_signature(self, tmp_dir):
        """PoPC certificate correctly identifies as digital_signature."""
        test_file = os.path.join(tmp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test data")

        priv, pub = generate_keypair()
        scan = DataEngine.scan_data(test_file)
        meta = MetadataEngine.generate_metadata(scan.data, ["test"], "alice")
        cert = CertificateEngine.create_popc_certificate(
            meta.data, signing_key=priv, key_id="mykey123"
        )

        assert cert.ok
        assert cert.data["certificate_type"] == "digital_signature"
        assert cert.data["certificate_issuer"] == "oasyce_node_mykey123"
        assert "Hardware" not in cert.data["certificate_issuer"]

    def test_certificate_issuer_uses_key_id(self, tmp_dir):
        """Certificate issuer is derived from key_id, not hardcoded."""
        test_file = os.path.join(tmp_dir, "test2.txt")
        with open(test_file, "w") as f:
            f.write("data")

        priv, pub = generate_keypair()
        scan = DataEngine.scan_data(test_file)
        meta = MetadataEngine.generate_metadata(scan.data, ["test"], "bob")
        cert = CertificateEngine.create_popc_certificate(
            meta.data, signing_key=priv, key_id="abcdef1234567890"
        )

        assert cert.data["certificate_issuer"] == "oasyce_node_abcdef12"

    def test_certificate_verifies_after_rename(self, tmp_dir):
        """Renamed certificate fields don't break signature verification."""
        test_file = os.path.join(tmp_dir, "test3.txt")
        with open(test_file, "w") as f:
            f.write("verify me")

        priv, pub = generate_keypair()
        scan = DataEngine.scan_data(test_file)
        meta = MetadataEngine.generate_metadata(scan.data, ["test"], "charlie")
        cert = CertificateEngine.create_popc_certificate(
            meta.data, signing_key=priv, key_id="testkey"
        )
        assert cert.ok

        # Verify the certificate
        verify_result = CertificateEngine.verify_popc_certificate(cert.data, signing_key=pub)
        assert verify_result.ok
        assert verify_result.data is True


# ── Block Signatures in Ledger (built-in only) ───────────────────────


@_builtin_only
class TestBlockSignatures:
    def test_create_signed_block(self, memory_ledger):
        """create_block with validator key produces signed block."""
        priv, pub = generate_keypair()
        memory_ledger.record_tx("test", asset_id="a1")
        block = memory_ledger.create_block(validator_key=priv, validator_pubkey=pub)

        assert block is not None
        assert "validator_signature" in block
        assert block["validator_pubkey"] == pub

        block_data = (
            f"{block['block_number']}{block['prev_hash']}{block['merkle_root']}{block['timestamp']}"
        )
        assert verify(block_data.encode(), block["validator_signature"], pub)

    def test_create_unsigned_block(self, memory_ledger):
        """create_block without validator key still works."""
        memory_ledger.record_tx("test", asset_id="a1")
        block = memory_ledger.create_block()
        assert block is not None
        assert block.get("validator_signature") is None

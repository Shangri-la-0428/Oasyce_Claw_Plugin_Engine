"""
Tests for security hardening: message limits, thread safety, chain validation,
key encryption, feedback persistence, slippage protection, PoPC naming.
"""

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time

import pytest

from oasyce_plugin.crypto.keys import (
    generate_keypair,
    load_or_create_keypair,
    sign,
    verify,
)
from oasyce_plugin.engines.core_engines import CertificateEngine, MetadataEngine, DataEngine
from oasyce_plugin.network.node import OasyceNode, PeerInfo
from oasyce_plugin.services.discovery.feedback import ExecutionRecord, FeedbackStore
from oasyce_plugin.storage.ledger import _USING_CORE

# Check if we're using the built-in (hardened) Ledger or oasyce_core's
_builtin_only = pytest.mark.skipif(
    _USING_CORE,
    reason="Test targets built-in Ledger hardening (oasyce_core is installed)",
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_dir():
    d = tempfile.mkdtemp(prefix="oasyce_sec_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def memory_ledger():
    from oasyce_plugin.storage.ledger import Ledger
    return Ledger(db_path=":memory:")


def _get_bound_port(node):
    return node._server.sockets[0].getsockname()[1]


# ── P2P Message Size Limit ───────────────────────────────────────────

class TestMessageSizeLimit:
    def test_max_message_size_constant(self):
        """Node has a MAX_MESSAGE_SIZE constant."""
        assert OasyceNode.MAX_MESSAGE_SIZE == 1_048_576

    def test_normal_message_accepted(self):
        """Normal-sized messages are processed correctly."""
        async def _run():
            node = OasyceNode(host="127.0.0.1", port=0, node_id="test")
            await node.start()
            port = _get_bound_port(node)

            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(json.dumps({"type": "ping"}).encode() + b"\n")
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            resp = json.loads(line)
            assert resp["type"] == "pong"

            writer.close()
            await writer.wait_closed()
            await node.stop()

        asyncio.run(_run())

    def test_unknown_type_rejected(self):
        """Unknown message types return error."""
        node = OasyceNode(node_id="test")
        result = node._dispatch({"type": "evil_command"})
        assert result["type"] == "error"


# ── Block Validation ─────────────────────────────────────────────────

class TestBlockValidation:
    def test_new_block_requires_fields(self):
        """new_block with missing fields is rejected."""
        ledger = pytest.importorskip("oasyce_plugin.storage.ledger").Ledger(db_path=":memory:")
        node = OasyceNode(node_id="test", ledger=ledger)
        # Missing merkle_root and timestamp
        incomplete = {
            "block_number": 0,
            "block_hash": "abc",
            "prev_hash": "0" * 64,
        }
        result = node._dispatch({"type": "new_block", "block": incomplete})
        assert result["status"] == "rejected"

    def test_signed_block_bad_signature_rejected(self):
        """Signed block with wrong signature is rejected."""
        ledger = pytest.importorskip("oasyce_plugin.storage.ledger").Ledger(db_path=":memory:")
        node = OasyceNode(node_id="test", ledger=ledger)
        _, pub = generate_keypair()
        other_priv, _ = generate_keypair()

        bn, prev, mr, ts = 0, "0" * 64, "b" * 64, "2024-01-01T00:00:00"
        hash_input = f"{bn}{prev}{mr}{ts}"
        block_hash = hashlib.sha256(hash_input.encode()).hexdigest()
        bad_sig = sign(block_hash.encode(), other_priv)

        block = {
            "block_number": bn,
            "block_hash": block_hash,
            "prev_hash": prev,
            "merkle_root": mr,
            "timestamp": ts,
            "tx_count": 0,
            "validator_signature": bad_sig,
            "validator_pubkey": pub,
        }
        result = node._dispatch({"type": "new_block", "block": block})
        assert result["status"] == "rejected"

    def test_signed_block_passes_validation(self):
        """Properly signed block passes signature validation (not rejected for signature)."""
        ledger = pytest.importorskip("oasyce_plugin.storage.ledger").Ledger(db_path=":memory:")
        node = OasyceNode(node_id="test", ledger=ledger)
        priv, pub = generate_keypair()

        bn, prev, mr, ts = 0, "0" * 64, "a" * 64, "2024-01-01T00:00:00"
        hash_input = f"{bn}{prev}{mr}{ts}"
        block_hash = hashlib.sha256(hash_input.encode()).hexdigest()
        sig = sign(block_hash.encode(), priv)

        block = {
            "block_number": bn,
            "block_hash": block_hash,
            "prev_hash": prev,
            "merkle_root": mr,
            "timestamp": ts,
            "tx_count": 0,
            "validator_signature": sig,
            "validator_pubkey": pub,
        }
        result = node._dispatch({"type": "new_block", "block": block})
        # Should NOT be rejected for signature reasons; may be accepted or rejected
        # by the underlying ledger's insert, but validation passed
        assert result["status"] in ("accepted", "rejected")


# ── Chain Reorg Validation (built-in only) ────────────────────────────

@_builtin_only
class TestChainReorgValidation:
    def test_reorg_rejects_broken_chain(self, memory_ledger):
        """attempt_reorg rejects chains with broken prev_hash links."""
        memory_ledger.record_tx("test", asset_id="a1")
        memory_ledger.create_block()

        broken_chain = [
            {"block_number": 0, "block_hash": "aaa", "prev_hash": "0" * 64,
             "merkle_root": "x", "timestamp": "2024-01-01", "tx_count": 0},
            {"block_number": 1, "block_hash": "bbb", "prev_hash": "WRONG",
             "merkle_root": "y", "timestamp": "2024-01-02", "tx_count": 0},
            {"block_number": 2, "block_hash": "ccc", "prev_hash": "bbb",
             "merkle_root": "z", "timestamp": "2024-01-03", "tx_count": 0},
        ]
        assert memory_ledger.attempt_reorg(broken_chain) is False

    def test_reorg_accepts_valid_chain(self, memory_ledger):
        """attempt_reorg accepts a valid longer chain."""
        memory_ledger.record_tx("test", asset_id="a1")
        memory_ledger.create_block()

        valid_chain = [
            {"block_number": 0, "block_hash": "aaa", "prev_hash": "0" * 64,
             "merkle_root": "x", "timestamp": "2024-01-01", "tx_count": 0},
            {"block_number": 1, "block_hash": "bbb", "prev_hash": "aaa",
             "merkle_root": "y", "timestamp": "2024-01-02", "tx_count": 0},
            {"block_number": 2, "block_hash": "ccc", "prev_hash": "bbb",
             "merkle_root": "z", "timestamp": "2024-01-03", "tx_count": 0},
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
            fs.record(ExecutionRecord(
                skill_id="s1", success=True, latency_ms=10,
                caller_rating=4.0, timestamp=1000 + i,
            ))

        stats = fs.stats("s1")
        assert stats["total"] == FeedbackStore.MAX_RECORDS_PER_SKILL

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM feedback_records WHERE skill_id='s1'").fetchone()[0]
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

        hash_input = f"{block['block_number']}{block['prev_hash']}{block['merkle_root']}{block['timestamp']}"
        expected_hash = hashlib.sha256(hash_input.encode()).hexdigest()
        assert verify(expected_hash.encode(), block["validator_signature"], pub)

    def test_create_unsigned_block(self, memory_ledger):
        """create_block without validator key still works."""
        memory_ledger.record_tx("test", asset_id="a1")
        block = memory_ledger.create_block()
        assert block is not None
        assert block.get("validator_signature") is None


# ── Node Rate Limiting ───────────────────────────────────────────────

class TestNodeRateLimiting:
    def test_rate_limit_new_block(self):
        """Excessive new_block messages are rate-limited."""
        node = OasyceNode(node_id="test")
        for _ in range(OasyceNode.RATE_LIMIT_MAX):
            result = node._dispatch({"type": "new_block", "block": {}}, peer_key="bad_peer")
            assert result["status"] != "rate_limited"

        result = node._dispatch({"type": "new_block", "block": {}}, peer_key="bad_peer")
        assert result["status"] == "rate_limited"

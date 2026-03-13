"""Tests for block structure — transactions packed into blocks forming a chain."""

import hashlib

import pytest

from oasyce_plugin.crypto.merkle import merkle_root
from oasyce_plugin.storage.ledger import Ledger


@pytest.fixture
def ledger():
    db = Ledger(":memory:")
    yield db
    db.close()


# ── Merkle Root ──────────────────────────────────────────────────────────


class TestMerkleRoot:
    def test_empty_list(self):
        assert merkle_root([]) == "0" * 64

    def test_single_tx(self):
        tx = "abc123"
        expected = hashlib.sha256(tx.encode()).hexdigest()
        # Single leaf — root equals the leaf hash
        assert merkle_root([tx]) == expected

    def test_two_txs(self):
        a = hashlib.sha256(b"tx1").hexdigest()
        b = hashlib.sha256(b"tx2").hexdigest()
        expected = hashlib.sha256((a + b).encode()).hexdigest()
        assert merkle_root(["tx1", "tx2"]) == expected

    def test_odd_duplicates_last(self):
        """Three leaves: the third is duplicated to make four."""
        a = hashlib.sha256(b"t1").hexdigest()
        b = hashlib.sha256(b"t2").hexdigest()
        c = hashlib.sha256(b"t3").hexdigest()
        ab = hashlib.sha256((a + b).encode()).hexdigest()
        cc = hashlib.sha256((c + c).encode()).hexdigest()
        expected = hashlib.sha256((ab + cc).encode()).hexdigest()
        assert merkle_root(["t1", "t2", "t3"]) == expected

    def test_deterministic(self):
        ids = ["aa", "bb", "cc", "dd"]
        assert merkle_root(ids) == merkle_root(ids)


# ── Genesis Block ────────────────────────────────────────────────────────


class TestGenesisBlock:
    def test_genesis_prev_hash_all_zeros(self, ledger):
        ledger.record_tx("REGISTER", asset_id="asset-1", from_addr="alice")
        block = ledger.create_block()
        assert block is not None
        assert block["block_number"] == 0
        assert block["prev_hash"] == "0" * 64

    def test_genesis_contains_tx(self, ledger):
        tx_id = ledger.record_tx("REGISTER", asset_id="asset-1")
        block = ledger.create_block()
        assert tx_id in block["tx_ids"]
        assert block["tx_count"] == 1


# ── Multi-Block Chain ───────────────────────────────────────────────────


class TestChainLinkage:
    def test_second_block_links_to_genesis(self, ledger):
        ledger.record_tx("REGISTER", asset_id="a1")
        b0 = ledger.create_block()

        ledger.record_tx("BUY", asset_id="a1", from_addr="bob", amount=10.0)
        b1 = ledger.create_block()

        assert b1["prev_hash"] == b0["block_hash"]
        assert b1["block_number"] == 1

    def test_chain_height(self, ledger):
        assert ledger.get_chain_height() == 0
        ledger.record_tx("REGISTER", asset_id="a1")
        ledger.create_block()
        assert ledger.get_chain_height() == 1
        ledger.record_tx("BUY", asset_id="a1")
        ledger.create_block()
        assert ledger.get_chain_height() == 2

    def test_get_latest_block(self, ledger):
        assert ledger.get_latest_block() is None
        ledger.record_tx("REGISTER", asset_id="a1")
        ledger.create_block()
        ledger.record_tx("BUY", asset_id="a1")
        b1 = ledger.create_block()
        latest = ledger.get_latest_block()
        assert latest["block_number"] == b1["block_number"]
        assert latest["block_hash"] == b1["block_hash"]


# ── Merkle Root in Blocks ───────────────────────────────────────────────


class TestBlockMerkle:
    def test_block_merkle_matches_tx_ids(self, ledger):
        tx1 = ledger.record_tx("REGISTER", asset_id="a1")
        tx2 = ledger.record_tx("BUY", asset_id="a1", amount=5.0)
        block = ledger.create_block()
        assert block["merkle_root"] == merkle_root([tx1, tx2])


# ── Chain Verification ──────────────────────────────────────────────────


class TestVerifyChain:
    def test_empty_chain_is_valid(self, ledger):
        assert ledger.verify_chain() is True

    def test_single_block_valid(self, ledger):
        ledger.record_tx("REGISTER", asset_id="a1")
        ledger.create_block()
        assert ledger.verify_chain() is True

    def test_multi_block_valid(self, ledger):
        for i in range(5):
            ledger.record_tx("TX", asset_id=f"a{i}")
            ledger.create_block()
        assert ledger.verify_chain() is True

    def test_tampered_hash_detected(self, ledger):
        ledger.record_tx("REGISTER", asset_id="a1")
        ledger.create_block()
        # Tamper with block_hash
        ledger._conn.execute(
            "UPDATE blocks SET block_hash = 'deadbeef' WHERE block_number = 0"
        )
        assert ledger.verify_chain() is False

    def test_tampered_prev_hash_detected(self, ledger):
        ledger.record_tx("REGISTER", asset_id="a1")
        ledger.create_block()
        ledger.record_tx("BUY", asset_id="a1")
        ledger.create_block()
        # Tamper with prev_hash of block 1
        ledger._conn.execute(
            "UPDATE blocks SET prev_hash = 'badc0de' WHERE block_number = 1"
        )
        assert ledger.verify_chain() is False


# ── Empty Pool ──────────────────────────────────────────────────────────


class TestNoOpBlock:
    def test_no_pending_tx_returns_none(self, ledger):
        assert ledger.create_block() is None

    def test_already_packed_not_repacked(self, ledger):
        ledger.record_tx("REGISTER", asset_id="a1")
        ledger.create_block()
        # All transactions are now packed — second call returns None
        assert ledger.create_block() is None


# ── get_block ───────────────────────────────────────────────────────────


class TestGetBlock:
    def test_get_existing_block(self, ledger):
        ledger.record_tx("REGISTER", asset_id="a1")
        ledger.create_block()
        b = ledger.get_block(0)
        assert b is not None
        assert b["block_number"] == 0

    def test_get_nonexistent_block(self, ledger):
        assert ledger.get_block(999) is None

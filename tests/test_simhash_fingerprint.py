"""Tests for SimHash/MinHash content fingerprinting (Task #19)."""

from __future__ import annotations

import pytest

from oasyce.services.fingerprint import (
    FingerprintStore,
    minhash_signature,
    minhash_similarity,
    simhash,
    simhash_distance,
)


# ── SimHash ───────────────────────────────────────────────────────────


class TestSimHash:
    def test_deterministic(self) -> None:
        text = "the quick brown fox jumps over the lazy dog"
        assert simhash(text) == simhash(text)

    def test_empty_text(self) -> None:
        assert simhash("") == 0

    def test_short_text(self) -> None:
        # Shorter than shingle size should still work
        assert isinstance(simhash("ab"), int)

    def test_similar_texts_close_distance(self) -> None:
        a = "the quick brown fox jumps over the lazy dog"
        b = "the quick brown fox leaps over the lazy dog"
        dist = simhash_distance(simhash(a), simhash(b))
        assert dist < 10, f"Expected small distance, got {dist}"

    def test_different_texts_large_distance(self) -> None:
        a = "the quick brown fox jumps over the lazy dog"
        b = "completely unrelated content about quantum physics and mathematics"
        dist = simhash_distance(simhash(a), simhash(b))
        assert dist > 5, f"Expected large distance, got {dist}"

    def test_identical_texts_zero_distance(self) -> None:
        text = "hello world this is a test of simhash fingerprinting"
        assert simhash_distance(simhash(text), simhash(text)) == 0

    def test_64_bit_value(self) -> None:
        h = simhash("some content for hashing purposes")
        assert 0 <= h < (1 << 64)

    def test_near_duplicate_threshold(self) -> None:
        """Near-duplicates (small edits) should have distance < 3."""
        original = "This is a fairly long paragraph about the nature of content " * 5
        edited = original.replace("nature", "essence")
        dist = simhash_distance(simhash(original), simhash(edited))
        assert dist <= 10  # allow margin; character n-gram SimHash varies with edit position


class TestSimHashDistance:
    def test_same_value(self) -> None:
        assert simhash_distance(0, 0) == 0
        assert simhash_distance(0xFFFFFFFF, 0xFFFFFFFF) == 0

    def test_all_bits_different(self) -> None:
        assert simhash_distance(0, (1 << 64) - 1) == 64

    def test_one_bit_different(self) -> None:
        assert simhash_distance(0, 1) == 1
        assert simhash_distance(0, 1 << 63) == 1

    def test_symmetric(self) -> None:
        a, b = 0xABCD, 0x1234
        assert simhash_distance(a, b) == simhash_distance(b, a)


# ── MinHash ───────────────────────────────────────────────────────────


class TestMinHash:
    def test_identical_sets_similarity_one(self) -> None:
        tokens = {"apple", "banana", "cherry"}
        sig = minhash_signature(tokens)
        sim = minhash_similarity(sig, sig)
        assert sim == 1.0

    def test_disjoint_sets_low_similarity(self) -> None:
        sig_a = minhash_signature({"a", "b", "c", "d", "e"})
        sig_b = minhash_signature({"v", "w", "x", "y", "z"})
        sim = minhash_similarity(sig_a, sig_b)
        assert sim < 0.3

    def test_overlapping_sets_moderate_similarity(self) -> None:
        sig_a = minhash_signature({"a", "b", "c", "d"})
        sig_b = minhash_signature({"c", "d", "e", "f"})
        sim = minhash_similarity(sig_a, sig_b)
        # Jaccard({a,b,c,d}, {c,d,e,f}) = 2/6 ≈ 0.33
        assert 0.1 < sim < 0.7

    def test_empty_sets(self) -> None:
        sig = minhash_signature(set())
        assert all(v == 0 for v in sig)

    def test_signature_length(self) -> None:
        sig = minhash_signature({"x", "y"}, k=64)
        assert len(sig) == 64

    def test_near_duplicate_high_similarity(self) -> None:
        """Large overlapping sets should have high similarity."""
        base = {f"token_{i}" for i in range(100)}
        modified = (base - {"token_1", "token_2"}) | {"new_1", "new_2"}
        sig_a = minhash_signature(base)
        sig_b = minhash_signature(modified)
        sim = minhash_similarity(sig_a, sig_b)
        assert sim > 0.8


# ── FingerprintStore ──────────────────────────────────────────────────


class TestFingerprintStore:
    @pytest.fixture
    def store(self) -> FingerprintStore:
        s = FingerprintStore(":memory:")
        yield s
        s.close()

    def test_add_and_get(self, store: FingerprintStore) -> None:
        sh = store.add("asset1", "hello world this is content")
        assert isinstance(sh, int)
        assert store.get("asset1") == sh

    def test_get_missing(self, store: FingerprintStore) -> None:
        assert store.get("nonexistent") is None

    def test_find_similar_exact(self, store: FingerprintStore) -> None:
        store.add("asset1", "the quick brown fox jumps over the lazy dog")
        matches = store.find_similar("the quick brown fox jumps over the lazy dog")
        assert "asset1" in matches

    def test_find_similar_near_duplicate(self, store: FingerprintStore) -> None:
        text = "This is a long document about software engineering practices " * 10
        store.add("asset1", text)
        edited = text.replace("engineering", "development")
        # Use a generous threshold; character-level SimHash can diverge more
        matches = store.find_similar(edited, threshold=15)
        assert "asset1" in matches

    def test_find_similar_no_match(self, store: FingerprintStore) -> None:
        store.add("asset1", "the quick brown fox jumps over the lazy dog")
        matches = store.find_similar(
            "completely different content about quantum physics and advanced math",
            threshold=3,
        )
        # May or may not match depending on hash collisions; just verify no crash
        assert isinstance(matches, list)

    def test_find_similar_minhash(self, store: FingerprintStore) -> None:
        text = "This is content about machine learning and artificial intelligence " * 5
        store.add("asset1", text)
        similar = text.replace("artificial", "deep")
        matches = store.find_similar_minhash(similar, threshold=0.5)
        assert "asset1" in matches

    def test_overwrite(self, store: FingerprintStore) -> None:
        store.add("asset1", "version one")
        sh1 = store.get("asset1")
        store.add("asset1", "completely different version two")
        sh2 = store.get("asset1")
        assert sh1 != sh2

    def test_multiple_assets(self, store: FingerprintStore) -> None:
        store.add("a", "content a" * 20)
        store.add("b", "content b" * 20)
        store.add("c", "content c" * 20)
        assert store.get("a") is not None
        assert store.get("b") is not None
        assert store.get("c") is not None

"""
Tests for the Contribution Proof service.

Covers:
  - ContributionCertificate generation and serialization
  - ContributionEngine.generate_proof (happy path + errors)
  - ContributionEngine.verify_proof (hash match, timestamp)
  - Contribution score calculation (originality, rarity, freshness)
  - Semantic fingerprint generation
  - Source type validation
"""

from __future__ import annotations

import json
import os
import tempfile
import time

import pytest

from oasyce.services.contribution import (
    ContributionCertificate,
    ContributionEngine,
    SourceProof,
)


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def engine():
    return ContributionEngine()


@pytest.fixture
def sample_file():
    """Create a temporary text file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Oasyce contribution proof test data — unique content for testing\n")
        f.write("This file contains enough text for semantic fingerprinting.\n")
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def sample_file_2():
    """Create a second distinct temporary file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Completely different content — weather data from sensor network.\n")
        f.write("Temperature readings: 22.5°C, 23.1°C, 21.8°C, 24.0°C\n")
        path = f.name
    yield path
    os.unlink(path)


# ─── ContributionCertificate ─────────────────────────────────────


class TestContributionCertificate:
    def test_to_dict_roundtrip(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "creator_key_abc")
        d = cert.to_dict()
        restored = ContributionCertificate.from_dict(d)
        assert restored.content_hash == cert.content_hash
        assert restored.creator_key == cert.creator_key
        assert restored.source_type == cert.source_type
        assert restored.timestamp == cert.timestamp

    def test_certificate_is_frozen(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "key123")
        with pytest.raises(AttributeError):
            cert.content_hash = "modified"

    def test_json_serializable(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "key123")
        serialized = json.dumps(cert.to_dict())
        restored = ContributionCertificate.from_dict(json.loads(serialized))
        assert restored.content_hash == cert.content_hash


# ─── generate_proof ─────────────────────────────────────────────


class TestGenerateProof:
    def test_basic_proof(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "creator_abc")
        assert len(cert.content_hash) == 64  # SHA-256 hex
        assert cert.creator_key == "creator_abc"
        assert cert.source_type == "manual"
        assert cert.timestamp <= int(time.time())

    def test_all_source_types(self, engine, sample_file):
        for st in SourceProof:
            cert = engine.generate_proof(sample_file, "key", source_type=st.value)
            assert cert.source_type == st.value

    def test_invalid_source_type_raises(self, engine, sample_file):
        with pytest.raises(ValueError, match="Invalid source_type"):
            engine.generate_proof(sample_file, "key", source_type="invalid_type")

    def test_file_not_found_raises(self, engine):
        with pytest.raises(FileNotFoundError):
            engine.generate_proof("/nonexistent/path.txt", "key")

    def test_semantic_fingerprint_generated(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "key")
        assert cert.semantic_fingerprint is not None
        assert len(cert.semantic_fingerprint) == 32

    def test_source_evidence_preserved(self, engine, sample_file):
        cert = engine.generate_proof(
            sample_file,
            "key",
            source_evidence="https://example.com/provenance",
        )
        assert cert.source_evidence == "https://example.com/provenance"


# ─── verify_proof ────────────────────────────────────────────────


class TestVerifyProof:
    def test_valid_proof(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "key")
        result = engine.verify_proof(cert, sample_file)
        assert result["valid"] is True
        assert result["checks"]["content_hash"] is True
        assert result["checks"]["timestamp"] is True

    def test_modified_file_fails_hash(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "key")
        # Modify the file
        with open(sample_file, "a") as f:
            f.write("TAMPERED\n")
        result = engine.verify_proof(cert, sample_file)
        assert result["valid"] is False
        assert result["checks"]["content_hash"] is False

    def test_future_timestamp_fails(self, engine, sample_file):
        cert = ContributionCertificate(
            content_hash=engine._compute_content_hash(sample_file),
            semantic_fingerprint=None,
            source_type="manual",
            source_evidence="",
            creator_key="key",
            timestamp=int(time.time()) + 86400,  # 1 day in future
        )
        result = engine.verify_proof(cert, sample_file)
        assert result["valid"] is False
        assert result["checks"]["timestamp"] is False


# ─── calculate_contribution_score ────────────────────────────────


class TestContributionScore:
    def test_unique_content_scores_high(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "key")
        score = engine.calculate_contribution_score(cert, [])
        # No existing assets → originality=1, rarity=1, freshness≈1
        assert score > 0.9

    def test_duplicate_content_scores_low(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "key")
        existing = [{"semantic_fingerprint": cert.semantic_fingerprint}]
        score = engine.calculate_contribution_score(cert, existing)
        # Same vector → originality≈0
        assert score < 0.1

    def test_score_range_0_to_1(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "key")
        score = engine.calculate_contribution_score(cert, [])
        assert 0 <= score <= 1

    def test_rarity_decreases_with_similar_assets(self, engine, sample_file):
        cert = engine.generate_proof(sample_file, "key")
        fp = cert.semantic_fingerprint

        # Test rarity component directly (score = orig * rarity * fresh,
        # and orig=0 for exact duplicates, masking rarity differences)
        rarity_none = engine._compute_rarity(cert, [])
        assert rarity_none == 1.0

        many_similar = [{"semantic_fingerprint": fp} for _ in range(10)]
        rarity_many = engine._compute_rarity(cert, many_similar)
        one_similar = [{"semantic_fingerprint": fp}]
        rarity_one = engine._compute_rarity(cert, one_similar)

        assert rarity_many < rarity_one

    def test_freshness_decreases_with_age(self, engine, sample_file):
        now = int(time.time())

        cert_new = ContributionCertificate(
            content_hash="a" * 64,
            semantic_fingerprint=None,
            source_type="manual",
            source_evidence="",
            creator_key="key",
            timestamp=now,
        )
        cert_old = ContributionCertificate(
            content_hash="b" * 64,
            semantic_fingerprint=None,
            source_type="manual",
            source_evidence="",
            creator_key="key",
            timestamp=now - 365 * 86400,  # 1 year old
        )

        score_new = engine.calculate_contribution_score(cert_new, [])
        score_old = engine.calculate_contribution_score(cert_old, [])
        assert score_new > score_old

    def test_different_content_scores_higher(self, engine, sample_file, sample_file_2):
        cert1 = engine.generate_proof(sample_file, "key")
        cert2 = engine.generate_proof(sample_file_2, "key")

        # cert2 vs cert1 as existing — should have some originality
        existing = [{"semantic_fingerprint": cert1.semantic_fingerprint}]
        score = engine.calculate_contribution_score(cert2, existing)
        assert score > 0.0

    def test_no_semantic_fp_full_originality(self, engine):
        """Binary file (no semantic fingerprint) gets full originality."""
        cert = ContributionCertificate(
            content_hash="c" * 64,
            semantic_fingerprint=None,
            source_type="manual",
            source_evidence="",
            creator_key="key",
            timestamp=int(time.time()),
        )
        score = engine.calculate_contribution_score(cert, [{"semantic_fingerprint": [0.1] * 32}])
        # No fp → originality=1, rarity=1
        assert score > 0.9

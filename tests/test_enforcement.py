"""
Tests for enforcement system — fingerprint scanning, infringement detection,
bounty hunting, crawlers, and CLI commands.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from oasyce_plugin.consensus.enforcement import (
    EnforcementEngine,
    FingerprintScanner,
    InfringementDetector,
    BountyHunter,
    Evidence,
    EvidenceStatus,
    DisputeVerdict,
    FingerprintResult,
    InfringementReport,
    InfringementType,
    ScanResult,
    SeverityLevel,
    BountyInfo,
    EnforcementCase,
)
from oasyce_plugin.consensus.enforcement.types import (
    BOUNTY_REWARD_BPS,
    FALSE_REPORT_SLASH_BPS,
)
from oasyce_plugin.consensus.enforcement.fingerprint_scanner import (
    _content_hash,
    _fingerprint_hash,
    _extract_watermark,
    _compute_similarity,
    EXACT_MATCH_THRESHOLD,
    HIGH_SIMILARITY_THRESHOLD,
    MEDIUM_SIMILARITY_THRESHOLD,
    INFRINGEMENT_THRESHOLD,
)
from oasyce_plugin.consensus.enforcement.infringement_detector import (
    _classify_infringement,
    _assess_severity,
    _generate_report_id,
    DAMAGE_RATES,
)
from oasyce_plugin.consensus.enforcement.crawlers.base import (
    BaseCrawler,
    RateLimiter,
    compute_content_hash,
    compute_fingerprint,
)
from oasyce_plugin.consensus.enforcement.crawlers import (
    GitHubCrawler,
    TwitterCrawler,
    ZhihuCrawler,
    GeneralCrawler,
)
from oasyce_plugin.consensus.core.types import to_units, from_units, apply_rate_bps


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def scanner():
    return FingerprintScanner()


@pytest.fixture
def detector(scanner):
    return InfringementDetector(scanner)


@pytest.fixture
def bounty(scanner, detector):
    return BountyHunter(scanner, detector)


@pytest.fixture
def engine():
    return EnforcementEngine()


def _make_content(text: str) -> bytes:
    return text.encode("utf-8")


def _make_watermarked(text: str, wm_payload: str) -> bytes:
    return f"{text}OASYCE_WM:{wm_payload}:WM_END".encode("utf-8")


def _fp(content: str) -> str:
    """Helper to compute fingerprint for test content."""
    data = content.encode("utf-8")
    normalized = data.strip()
    inner = hashlib.sha256(normalized).digest()
    return hashlib.sha256(inner).hexdigest()


def _make_scan_result(
    content: str,
    platform: str = "github",
    url: str = "https://example.com/stolen",
) -> ScanResult:
    """Create a ScanResult from content for testing."""
    data = content.encode("utf-8")
    return ScanResult(
        platform=platform,
        url=url,
        content_hash=hashlib.sha256(data).hexdigest(),
        fingerprint=_fp(content),
        similarity_score=0,
        title="test",
        author="attacker",
        timestamp=int(time.time()),
        raw_snippet=content[:500],
    )


# ── FingerprintScanner Tests ─────────────────────────────────────────


class TestContentHash:
    def test_deterministic(self):
        assert _content_hash(b"hello") == _content_hash(b"hello")

    def test_different_content(self):
        assert _content_hash(b"hello") != _content_hash(b"world")

    def test_sha256_format(self):
        h = _content_hash(b"test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestFingerprintHash:
    def test_deterministic(self):
        assert _fingerprint_hash(b"hello") == _fingerprint_hash(b"hello")

    def test_strips_whitespace(self):
        assert _fingerprint_hash(b"  hello  ") == _fingerprint_hash(b"hello")

    def test_different_from_content_hash(self):
        data = b"test data"
        assert _fingerprint_hash(data) != _content_hash(data)


class TestWatermark:
    def test_extract_present(self):
        data = b"some content OASYCE_WM:abc123:WM_END more content"
        assert _extract_watermark(data) == "abc123"

    def test_extract_missing(self):
        assert _extract_watermark(b"no watermark here") is None

    def test_extract_incomplete_start(self):
        assert _extract_watermark(b"OASYCE_WM:abc123") is None

    def test_extract_incomplete_end(self):
        assert _extract_watermark(b"abc:WM_END") is None

    def test_extract_empty_payload(self):
        assert _extract_watermark(b"OASYCE_WM::WM_END") == ""


class TestSimilarity:
    def test_exact_match(self):
        assert _compute_similarity("abc123", "abc123") == 10000

    def test_no_match(self):
        # Completely different hex chars
        a = "0" * 64
        b = "f" * 64
        assert _compute_similarity(a, b) == 0

    def test_partial_match(self):
        a = "abcdef1234567890" * 4
        b = "abcdef0000000000" * 4
        score = _compute_similarity(a, b)
        assert 0 < score < 10000

    def test_empty_strings(self):
        assert _compute_similarity("", "") == 0
        assert _compute_similarity("abc", "") == 0


class TestFingerprintScanner:
    def test_scan_bytes(self, scanner):
        result = scanner.scan_content(b"hello world")
        assert isinstance(result, FingerprintResult)
        assert result.fingerprint
        assert result.content_hash
        assert result.content_size == 11
        assert result.similarity_score == 10000

    def test_scan_string(self, scanner):
        result = scanner.scan_content("hello world")
        assert result.content_size == 11

    def test_scan_watermarked(self, scanner):
        data = _make_watermarked("content", "asset_xyz")
        result = scanner.scan_content(data)
        assert result.watermark_found is True
        assert result.watermark_data == "asset_xyz"

    def test_scan_no_watermark(self, scanner):
        result = scanner.scan_content(b"plain content")
        assert result.watermark_found is False

    def test_register_and_verify(self, scanner):
        fp = _fp("my asset content")
        scanner.register_fingerprint("asset_1", fp)
        assert scanner.verify_ownership(fp, "asset_1") is True

    def test_verify_wrong_asset(self, scanner):
        fp = _fp("my asset content")
        scanner.register_fingerprint("asset_1", fp)
        assert scanner.verify_ownership(fp, "asset_2") is False

    def test_verify_unregistered(self, scanner):
        assert scanner.verify_ownership("somefp", "unknown") is False

    def test_find_owner_exact(self, scanner):
        fp = _fp("unique content")
        scanner.register_fingerprint("asset_A", fp)
        assert scanner.find_owner(fp) == "asset_A"

    def test_find_owner_none(self, scanner):
        assert scanner.find_owner("nonexistent") is None

    def test_compare_fingerprints(self, scanner):
        fp = _fp("same content")
        assert scanner.compare_fingerprints(fp, fp) == 10000

    def test_scan_platform_no_crawler(self, scanner):
        with pytest.raises(ValueError, match="No crawler"):
            scanner.scan_platform("github", "https://github.com/test")


# ── InfringementDetector Tests ───────────────────────────────────────


class TestClassification:
    def test_below_threshold(self):
        assert _classify_infringement(4000, False, False) is None

    def test_exact_copy(self):
        result = _classify_infringement(9500, True, False)
        assert result == InfringementType.UNAUTHORIZED_DISTRIBUTION

    def test_exact_with_watermark_removed(self):
        result = _classify_infringement(9600, False, True)
        assert result == InfringementType.CONTENT_TAMPERING

    def test_high_similarity(self):
        result = _classify_infringement(8500, True, False)
        assert result == InfringementType.CONTENT_TAMPERING

    def test_medium_similarity(self):
        result = _classify_infringement(6000, True, False)
        assert result == InfringementType.LICENSE_VIOLATION


class TestSeverityAssessment:
    def test_critical(self):
        assert _assess_severity(InfringementType.UNAUTHORIZED_DISTRIBUTION, 9500) == SeverityLevel.CRITICAL

    def test_high_unauthorized(self):
        assert _assess_severity(InfringementType.UNAUTHORIZED_DISTRIBUTION, 8000) == SeverityLevel.HIGH

    def test_high_tampering(self):
        assert _assess_severity(InfringementType.CONTENT_TAMPERING, 8500) == SeverityLevel.HIGH

    def test_medium_license(self):
        assert _assess_severity(InfringementType.LICENSE_VIOLATION, 8500) == SeverityLevel.MEDIUM

    def test_low_license(self):
        assert _assess_severity(InfringementType.LICENSE_VIOLATION, 6000) == SeverityLevel.LOW


class TestInfringementDetector:
    def test_register_and_detect_exact(self, detector):
        content = "original valuable content"
        fp = _fp(content)
        detector.register_asset("asset_1", fp, value=to_units(1000))

        scan = _make_scan_result(content, url="https://pirate.com/stolen")
        reports = detector.detect_infringement("asset_1", [scan])
        assert len(reports) == 1
        assert reports[0].infringement_type == InfringementType.UNAUTHORIZED_DISTRIBUTION

    def test_no_infringement_below_threshold(self, detector):
        fp = _fp("original content")
        detector.register_asset("asset_1", fp)

        scan = _make_scan_result("completely different content")
        reports = detector.detect_infringement("asset_1", [scan])
        assert len(reports) == 0

    def test_whitelist_skipped(self, detector):
        content = "whitelisted content"
        fp = _fp(content)
        detector.register_asset("asset_1", fp)
        detector.whitelist("asset_1", "https://authorized.com/page")

        scan = _make_scan_result(content, url="https://authorized.com/page")
        reports = detector.detect_infringement("asset_1", [scan])
        assert len(reports) == 0

    def test_unregistered_asset(self, detector):
        scan = _make_scan_result("some content")
        reports = detector.detect_infringement("nonexistent", [scan])
        assert len(reports) == 0

    def test_damage_calculation(self, detector):
        value = to_units(1000)
        low_dmg = detector.calculate_damages_from_severity(SeverityLevel.LOW, value)
        high_dmg = detector.calculate_damages_from_severity(SeverityLevel.HIGH, value)
        critical_dmg = detector.calculate_damages_from_severity(SeverityLevel.CRITICAL, value)
        assert low_dmg < high_dmg < critical_dmg
        # Low = 1% of 1000 OAS = 10 OAS
        assert low_dmg == apply_rate_bps(value, DAMAGE_RATES["low"])

    def test_detect_all(self, detector):
        content = "shared content"
        fp = _fp(content)
        detector.register_asset("asset_A", fp)

        scan = _make_scan_result(content)
        reports = detector.detect_all([scan])
        assert len(reports) == 1
        assert reports[0].asset_id == "asset_A"

    def test_report_id_deterministic(self):
        id1 = _generate_report_id("asset_1", "https://example.com")
        id2 = _generate_report_id("asset_1", "https://example.com")
        assert id1 == id2

    def test_report_id_unique(self):
        id1 = _generate_report_id("asset_1", "https://a.com")
        id2 = _generate_report_id("asset_1", "https://b.com")
        assert id1 != id2


# ── BountyHunter Tests ───────────────────────────────────────────────


class TestBountyHunter:
    def _setup_asset(self, bounty):
        content = "protected content"
        fp = _fp(content)
        bounty.scanner.register_fingerprint("asset_1", fp)
        bounty.set_bounty_pool("asset_1", to_units(10000))
        return fp

    def _make_evidence(self, fp, url="https://pirate.com"):
        return Evidence(
            asset_id="asset_1",
            reporter="hunter_001",
            infringement_type=InfringementType.UNAUTHORIZED_DISTRIBUTION,
            platform="web",
            url=url,
            content_hash="deadbeef" * 8,
            fingerprint=fp,
            similarity_score=9500,
            description="found stolen copy",
            timestamp=int(time.time()),
        )

    def test_submit_evidence_success(self, bounty):
        fp = self._setup_asset(bounty)
        evidence = self._make_evidence(fp)
        dispute_id = bounty.submit_evidence("asset_1", evidence)
        assert dispute_id
        assert len(dispute_id) == 16

    def test_submit_missing_fields(self, bounty):
        self._setup_asset(bounty)
        with pytest.raises(ValueError, match="asset_id"):
            bounty.submit_evidence("asset_1", Evidence(
                asset_id="", reporter="x", infringement_type=InfringementType.UNAUTHORIZED_DISTRIBUTION,
                platform="web", url="u", content_hash="h", fingerprint="f",
                similarity_score=9000, timestamp=1,
            ))

    def test_submit_missing_url(self, bounty):
        self._setup_asset(bounty)
        with pytest.raises(ValueError, match="URL"):
            bounty.submit_evidence("asset_1", Evidence(
                asset_id="asset_1", reporter="x",
                infringement_type=InfringementType.UNAUTHORIZED_DISTRIBUTION,
                platform="web", url="", content_hash="h", fingerprint="f",
                similarity_score=9000, timestamp=1,
            ))

    def test_submit_missing_reporter(self, bounty):
        self._setup_asset(bounty)
        with pytest.raises(ValueError, match="reporter"):
            bounty.submit_evidence("asset_1", Evidence(
                asset_id="asset_1", reporter="",
                infringement_type=InfringementType.UNAUTHORIZED_DISTRIBUTION,
                platform="web", url="u", content_hash="h", fingerprint="f",
                similarity_score=9000, timestamp=1,
            ))

    def test_submit_unregistered_asset(self, bounty):
        with pytest.raises(ValueError, match="not registered"):
            bounty.submit_evidence("nonexistent", Evidence(
                asset_id="nonexistent", reporter="x",
                infringement_type=InfringementType.UNAUTHORIZED_DISTRIBUTION,
                platform="web", url="u", content_hash="h", fingerprint="f",
                similarity_score=9000, timestamp=1,
            ))

    def test_submit_low_similarity(self, bounty):
        self._setup_asset(bounty)
        with pytest.raises(ValueError, match="Similarity too low"):
            bounty.submit_evidence("asset_1", Evidence(
                asset_id="asset_1", reporter="x",
                infringement_type=InfringementType.UNAUTHORIZED_DISTRIBUTION,
                platform="web", url="u", content_hash="h",
                fingerprint="0000" * 16,  # won't match
                similarity_score=0, timestamp=1,
            ))

    def test_submit_duplicate(self, bounty):
        fp = self._setup_asset(bounty)
        evidence = self._make_evidence(fp)
        bounty.submit_evidence("asset_1", evidence)
        with pytest.raises(ValueError, match="Duplicate"):
            bounty.submit_evidence("asset_1", evidence)

    def test_review_case(self, bounty):
        fp = self._setup_asset(bounty)
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        result = bounty.review_case(dispute_id)
        assert result["ok"] is True
        assert result["status"] == "under_review"

    def test_review_nonexistent(self, bounty):
        result = bounty.review_case("nonexistent")
        assert result["ok"] is False

    def test_resolve_guilty(self, bounty):
        fp = self._setup_asset(bounty)
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        result = bounty.resolve_case(dispute_id, DisputeVerdict.GUILTY, damages=to_units(500))
        assert result["ok"] is True
        assert result["verdict"] == "guilty"
        assert result["bounty_amount"] > 0

    def test_resolve_innocent(self, bounty):
        fp = self._setup_asset(bounty)
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        bounty.set_reporter_stake("hunter_001", to_units(1000))
        result = bounty.resolve_case(dispute_id, DisputeVerdict.INNOCENT)
        assert result["ok"] is True
        assert result["verdict"] == "innocent"
        assert result["reporter_slashed"] > 0

    def test_resolve_already_resolved(self, bounty):
        fp = self._setup_asset(bounty)
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        bounty.resolve_case(dispute_id, DisputeVerdict.GUILTY, damages=to_units(100))
        result = bounty.resolve_case(dispute_id, DisputeVerdict.GUILTY)
        assert result["ok"] is False

    def test_claim_bounty_success(self, bounty):
        fp = self._setup_asset(bounty)
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        bounty.resolve_case(dispute_id, DisputeVerdict.GUILTY, damages=to_units(500))
        payout = bounty.claim_bounty(dispute_id)
        assert payout > 0

    def test_claim_bounty_innocent(self, bounty):
        fp = self._setup_asset(bounty)
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        bounty.resolve_case(dispute_id, DisputeVerdict.INNOCENT)
        with pytest.raises(ValueError, match="Cannot claim"):
            bounty.claim_bounty(dispute_id)

    def test_claim_bounty_nonexistent(self, bounty):
        with pytest.raises(ValueError, match="not found"):
            bounty.claim_bounty("nonexistent")

    def test_double_claim_prevented(self, bounty):
        fp = self._setup_asset(bounty)
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        bounty.resolve_case(dispute_id, DisputeVerdict.GUILTY, damages=to_units(500))
        bounty.claim_bounty(dispute_id)
        with pytest.raises(ValueError, match="No bounty"):
            bounty.claim_bounty(dispute_id)

    def test_bounty_pool_deduction(self, bounty):
        fp = self._setup_asset(bounty)
        initial_pool = bounty._bounty_pools["asset_1"]
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        bounty.resolve_case(dispute_id, DisputeVerdict.GUILTY, damages=to_units(500))
        payout = bounty.claim_bounty(dispute_id)
        assert bounty._bounty_pools["asset_1"] == initial_pool - payout

    def test_get_bounty_info(self, bounty):
        self._setup_asset(bounty)
        info = bounty.get_bounty_info("asset_1")
        assert isinstance(info, BountyInfo)
        assert info.asset_id == "asset_1"
        assert info.total_bounty_pool == to_units(10000)

    def test_get_case(self, bounty):
        fp = self._setup_asset(bounty)
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        case = bounty.get_case(dispute_id)
        assert isinstance(case, EnforcementCase)
        assert case.asset_id == "asset_1"

    def test_list_cases_all(self, bounty):
        fp = self._setup_asset(bounty)
        bounty.submit_evidence("asset_1", self._make_evidence(fp, url="https://a.com"))
        bounty.submit_evidence("asset_1", self._make_evidence(fp, url="https://b.com"))
        cases = bounty.list_cases()
        assert len(cases) == 2

    def test_list_cases_filter_status(self, bounty):
        fp = self._setup_asset(bounty)
        dispute_id = bounty.submit_evidence("asset_1", self._make_evidence(fp))
        bounty.resolve_case(dispute_id, DisputeVerdict.GUILTY, damages=to_units(100))
        pending = bounty.list_cases(status=EvidenceStatus.PENDING)
        resolved = bounty.list_cases(status=EvidenceStatus.RESOLVED)
        assert len(pending) == 0
        assert len(resolved) == 1

    def test_list_cases_filter_asset(self, bounty):
        fp = self._setup_asset(bounty)
        bounty.submit_evidence("asset_1", self._make_evidence(fp))
        cases = bounty.list_cases(asset_id="asset_1")
        assert len(cases) == 1
        cases = bounty.list_cases(asset_id="nonexistent")
        assert len(cases) == 0


# ── Crawler Tests ────────────────────────────────────────────────────


class TestRateLimiter:
    def test_first_request_immediate(self):
        limiter = RateLimiter(min_interval=0.0)
        assert limiter.can_proceed() is True

    def test_rate_limit_blocks(self):
        limiter = RateLimiter(min_interval=100.0)
        limiter.wait()  # first call
        assert limiter.can_proceed() is False


class TestBaseCrawlerUtils:
    def test_compute_content_hash(self):
        h = compute_content_hash("hello")
        assert len(h) == 64

    def test_compute_fingerprint(self):
        fp = compute_fingerprint("hello")
        assert len(fp) == 64
        assert fp != compute_content_hash("hello")

    def test_compute_fingerprint_bytes(self):
        fp = compute_fingerprint(b"hello")
        assert len(fp) == 64


class TestGitHubCrawler:
    def test_crawl_with_mock(self):
        def mock_fetch(url):
            return {
                "owner": "testuser",
                "repo": "testrepo",
                "files": [
                    {"path": "README.md", "content": "# Hello World", "url": f"{url}/README.md", "size": 13},
                    {"path": "main.py", "content": "print('hello')", "url": f"{url}/main.py", "size": 14},
                ],
            }

        crawler = GitHubCrawler(rate_limit=0.0, fetch_fn=mock_fetch)
        results = crawler.crawl("https://github.com/testuser/testrepo")
        assert len(results) == 2
        assert results[0].platform == "github"
        assert results[0].title == "README.md"
        assert results[0].fingerprint

    def test_crawl_no_fetch_fn(self):
        crawler = GitHubCrawler(rate_limit=0.0)
        results = crawler.crawl("https://github.com/test/repo")
        assert results == []

    def test_crawl_robots_blocked(self):
        crawler = GitHubCrawler(rate_limit=0.0, fetch_fn=lambda u: {"files": []})
        crawler.set_robots_allowed("https://blocked.com", False)
        results = crawler.crawl("https://blocked.com")
        assert results == []

    def test_crawl_empty_files(self):
        crawler = GitHubCrawler(rate_limit=0.0, fetch_fn=lambda u: {"files": []})
        results = crawler.crawl("https://github.com/test/repo")
        assert results == []

    def test_crawl_skip_empty_content(self):
        def mock_fetch(url):
            return {"files": [{"path": "empty.txt", "content": "", "url": url}]}
        crawler = GitHubCrawler(rate_limit=0.0, fetch_fn=mock_fetch)
        results = crawler.crawl("https://github.com/test/repo")
        assert results == []


class TestTwitterCrawler:
    def test_crawl_with_mock(self):
        def mock_fetch(url):
            return {
                "tweets": [
                    {"id": "123", "text": "This is my original content!", "author": "user1", "url": url},
                ],
            }

        crawler = TwitterCrawler(rate_limit=0.0, fetch_fn=mock_fetch)
        results = crawler.crawl("https://twitter.com/user1/status/123")
        assert len(results) == 1
        assert results[0].platform == "twitter"

    def test_crawl_no_fetch(self):
        crawler = TwitterCrawler(rate_limit=0.0)
        assert crawler.crawl("https://twitter.com/test") == []


class TestZhihuCrawler:
    def test_crawl_with_mock(self):
        def mock_fetch(url):
            return {
                "articles": [
                    {"id": "456", "title": "Article", "content": "Zhihu article content", "author": "author1", "url": url},
                ],
            }

        crawler = ZhihuCrawler(rate_limit=0.0, fetch_fn=mock_fetch)
        results = crawler.crawl("https://zhuanlan.zhihu.com/p/123")
        assert len(results) == 1
        assert results[0].platform == "zhihu"

    def test_crawl_no_fetch(self):
        crawler = ZhihuCrawler(rate_limit=0.0)
        assert crawler.crawl("https://zhihu.com/question/123") == []


class TestGeneralCrawler:
    def test_crawl_single_page(self):
        def mock_fetch(url):
            return {"content": "Page content here", "title": "Test Page", "author": "admin"}

        crawler = GeneralCrawler(rate_limit=0.0, fetch_fn=mock_fetch)
        results = crawler.crawl("https://example.com/page")
        assert len(results) == 1
        assert results[0].platform == "web"

    def test_crawl_multiple_blocks(self):
        def mock_fetch(url):
            return {
                "blocks": [
                    {"content": "Block 1", "url": f"{url}#1"},
                    {"content": "Block 2", "url": f"{url}#2"},
                ],
            }

        crawler = GeneralCrawler(rate_limit=0.0, fetch_fn=mock_fetch)
        results = crawler.crawl("https://forum.com/thread")
        assert len(results) == 2

    def test_crawl_no_fetch(self):
        crawler = GeneralCrawler(rate_limit=0.0)
        assert crawler.crawl("https://example.com") == []

    def test_crawl_null_response(self):
        crawler = GeneralCrawler(rate_limit=0.0, fetch_fn=lambda u: None)
        assert crawler.crawl("https://example.com") == []


# ── EnforcementEngine Facade Tests ───────────────────────────────────


class TestEnforcementEngine:
    def test_register_and_scan(self, engine):
        content = "my valuable data"
        fp_result = engine.scan_content(content)
        engine.register_asset("asset_X", fp_result.fingerprint, value=to_units(500))

        # Verify ownership
        assert engine.scanner.verify_ownership(fp_result.fingerprint, "asset_X")

    def test_full_workflow(self, engine):
        """End-to-end: register, scan, detect, submit, resolve, claim."""
        # 1. Register asset
        content = "proprietary algorithm code v2"
        fp_result = engine.scan_content(content)
        engine.register_asset(
            "asset_algo", fp_result.fingerprint,
            value=to_units(5000), owner="creator_1",
        )
        engine.bounty.set_bounty_pool("asset_algo", to_units(1000))

        # 2. Mock crawler finds the same content elsewhere
        scan = _make_scan_result(content, platform="github", url="https://github.com/thief/repo")

        # 3. Detect infringement
        reports = engine.detect_infringement("asset_algo", [scan])
        assert len(reports) == 1
        assert reports[0].severity in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)

        # 4. Submit evidence
        evidence = Evidence(
            asset_id="asset_algo",
            reporter="bounty_hunter_1",
            infringement_type=reports[0].infringement_type,
            platform="github",
            url="https://github.com/thief/repo",
            content_hash=scan.content_hash,
            fingerprint=scan.fingerprint,
            similarity_score=reports[0].similarity_score,
            description="Found exact copy on GitHub",
            timestamp=int(time.time()),
        )
        dispute_id = engine.submit_evidence("asset_algo", evidence)
        assert dispute_id

        # 5. Resolve guilty
        result = engine.resolve_case(
            dispute_id, DisputeVerdict.GUILTY,
            damages=reports[0].damages_estimate,
        )
        assert result["ok"] is True
        assert result["bounty_amount"] > 0

        # 6. Claim bounty
        payout = engine.claim_bounty(dispute_id)
        assert payout > 0

        # 7. Verify case listed
        cases = engine.list_cases()
        assert len(cases) == 1
        assert cases[0].verdict == DisputeVerdict.GUILTY

    def test_whitelist_url(self, engine):
        content = "authorized content"
        fp = engine.scan_content(content).fingerprint
        engine.register_asset("asset_W", fp)
        engine.whitelist_url("asset_W", "https://partner.com/page")

        scan = _make_scan_result(content, url="https://partner.com/page")
        reports = engine.detect_infringement("asset_W", [scan])
        assert len(reports) == 0

    def test_bounty_info(self, engine):
        engine.register_asset("asset_B", "fp123")
        info = engine.get_bounty_info("asset_B")
        assert info.asset_id == "asset_B"
        assert info.active_cases == 0


# ── CLI Tests ────────────────────────────────────────────────────────


class TestCLI:
    def test_scan_content_cli(self, tmp_path):
        """Test enforcement scan-content command."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("CLI test content")

        result = subprocess.run(
            [sys.executable, "-m", "oasyce_plugin.cli",
             "enforcement", "scan-content", str(test_file), "--json"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "fingerprint" in data
        assert "content_hash" in data
        assert data["content_size"] == len("CLI test content")

    def test_scan_content_missing_file(self, tmp_path):
        """Test enforcement scan-content with missing file."""
        result = subprocess.run(
            [sys.executable, "-m", "oasyce_plugin.cli",
             "enforcement", "scan-content", "/nonexistent/file.txt"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0

    def test_bounty_info_cli(self):
        """Test enforcement bounty command."""
        result = subprocess.run(
            [sys.executable, "-m", "oasyce_plugin.cli",
             "enforcement", "bounty", "--asset", "test_asset", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["asset_id"] == "test_asset"

    def test_list_cases_cli(self):
        """Test enforcement list command."""
        result = subprocess.run(
            [sys.executable, "-m", "oasyce_plugin.cli",
             "enforcement", "list", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_enforcement_help(self):
        """Test enforcement subcommand help."""
        result = subprocess.run(
            [sys.executable, "-m", "oasyce_plugin.cli", "enforcement"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0


# ── Type Tests ───────────────────────────────────────────────────────


class TestTypes:
    def test_bounty_reward_bps(self):
        assert BOUNTY_REWARD_BPS["low"] == 500
        assert BOUNTY_REWARD_BPS["critical"] == 3000

    def test_false_report_slash(self):
        stake = to_units(1000)
        slash = apply_rate_bps(stake, FALSE_REPORT_SLASH_BPS)
        # 2% of 1000 = 20 OAS
        assert slash == to_units(20)

    def test_evidence_frozen(self):
        e = Evidence(
            asset_id="a", reporter="r",
            infringement_type=InfringementType.UNAUTHORIZED_DISTRIBUTION,
            platform="web", url="u", content_hash="h", fingerprint="f",
            similarity_score=9000, timestamp=1,
        )
        with pytest.raises(AttributeError):
            e.asset_id = "new"  # type: ignore

    def test_scan_result_frozen(self):
        sr = ScanResult(
            platform="web", url="u", content_hash="h",
            fingerprint="f", similarity_score=0,
        )
        with pytest.raises(AttributeError):
            sr.url = "new"  # type: ignore

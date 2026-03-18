"""
Enforcement — bounty hunter system for detecting and reporting infringements.

Public API:
    EnforcementEngine  — facade for all enforcement operations
    FingerprintScanner — content fingerprint extraction & verification
    InfringementDetector — infringement detection from scan results
    BountyHunter       — evidence submission, case management, bounty payout
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from oasyce_plugin.consensus.enforcement.types import (
    BountyInfo,
    DisputeVerdict,
    EnforcementCase,
    Evidence,
    EvidenceStatus,
    FingerprintResult,
    InfringementReport,
    InfringementType,
    ScanResult,
    SeverityLevel,
)
from oasyce_plugin.consensus.enforcement.fingerprint_scanner import FingerprintScanner
from oasyce_plugin.consensus.enforcement.infringement_detector import InfringementDetector
from oasyce_plugin.consensus.enforcement.bounty_hunter import BountyHunter
from oasyce_plugin.consensus.enforcement.crawlers.base import BaseCrawler


class EnforcementEngine:
    """Unified facade for enforcement operations.

    Composes FingerprintScanner, InfringementDetector, and BountyHunter
    into a single entry point.
    """

    def __init__(self) -> None:
        self.scanner = FingerprintScanner()
        self.detector = InfringementDetector(self.scanner)
        self.bounty = BountyHunter(self.scanner, self.detector)

    # ── Asset registration ────────────────────────────────────────────

    def register_asset(
        self,
        asset_id: str,
        fingerprint: str,
        value: int = 0,
        has_watermark: bool = False,
        owner: str = "",
    ) -> None:
        """Register an asset for monitoring."""
        self.detector.register_asset(
            asset_id, fingerprint, value, has_watermark, owner,
        )

    def whitelist_url(self, asset_id: str, url: str) -> None:
        """Mark a URL as authorized for an asset."""
        self.detector.whitelist(asset_id, url)

    # ── Scanning ──────────────────────────────────────────────────────

    def scan_content(self, content: bytes | str) -> FingerprintResult:
        """Scan local content for fingerprint."""
        return self.scanner.scan_content(content)

    def scan_platform(self, platform: str, url: str) -> List[ScanResult]:
        """Scan a platform URL."""
        return self.scanner.scan_platform(platform, url)

    def register_crawler(self, platform: str, crawler: BaseCrawler) -> None:
        """Register a platform crawler."""
        self.scanner.register_crawler(platform, crawler)

    # ── Detection ─────────────────────────────────────────────────────

    def detect_infringement(
        self,
        asset_id: str,
        scan_results: List[ScanResult],
    ) -> List[InfringementReport]:
        """Detect infringements for an asset."""
        return self.detector.detect_infringement(asset_id, scan_results)

    def detect_all(
        self,
        scan_results: List[ScanResult],
    ) -> List[InfringementReport]:
        """Detect infringements across all registered assets."""
        return self.detector.detect_all(scan_results)

    # ── Bounty hunting ────────────────────────────────────────────────

    def submit_evidence(self, asset_id: str, evidence: Evidence) -> str:
        """Submit infringement evidence. Returns dispute_id."""
        return self.bounty.submit_evidence(asset_id, evidence)

    def claim_bounty(self, dispute_id: str) -> int:
        """Claim bounty after guilty verdict. Returns payout amount."""
        return self.bounty.claim_bounty(dispute_id)

    def get_bounty_info(self, asset_id: str) -> BountyInfo:
        """Get bounty info for an asset."""
        return self.bounty.get_bounty_info(asset_id)

    def list_cases(
        self,
        status: Optional[EvidenceStatus] = None,
        asset_id: Optional[str] = None,
    ) -> List[EnforcementCase]:
        """List enforcement cases."""
        return self.bounty.list_cases(status=status, asset_id=asset_id)

    def resolve_case(
        self,
        dispute_id: str,
        verdict: DisputeVerdict,
        damages: int = 0,
    ) -> Dict[str, Any]:
        """Resolve a case with a verdict."""
        return self.bounty.resolve_case(dispute_id, verdict, damages)

    def get_case(self, dispute_id: str) -> Optional[EnforcementCase]:
        """Get a case by dispute_id."""
        return self.bounty.get_case(dispute_id)


__all__ = [
    "EnforcementEngine",
    "FingerprintScanner",
    "InfringementDetector",
    "BountyHunter",
    "BaseCrawler",
    "BountyInfo",
    "DisputeVerdict",
    "EnforcementCase",
    "Evidence",
    "EvidenceStatus",
    "FingerprintResult",
    "InfringementReport",
    "InfringementType",
    "ScanResult",
    "SeverityLevel",
]

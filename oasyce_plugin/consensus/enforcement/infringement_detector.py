"""
Infringement Detector — detects unauthorized use of registered assets.

Analyzes scan results against registered assets to identify infringements
such as unauthorized distribution, content tampering, and license violations.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional

from oasyce_plugin.consensus.enforcement.types import (
    InfringementReport,
    InfringementType,
    ScanResult,
    SeverityLevel,
)
from oasyce_plugin.consensus.enforcement.fingerprint_scanner import (
    FingerprintScanner,
    EXACT_MATCH_THRESHOLD,
    HIGH_SIMILARITY_THRESHOLD,
    MEDIUM_SIMILARITY_THRESHOLD,
)
from oasyce_plugin.consensus.core.types import apply_rate_bps, to_units


# Damage calculation rates in basis points
DAMAGE_RATES: Dict[str, int] = {
    "low": 100,        # 1% of asset value
    "medium": 500,     # 5%
    "high": 1000,      # 10%
    "critical": 2500,  # 25%
}

# Minimum similarity for infringement (basis points)
INFRINGEMENT_THRESHOLD = 5000  # 50% similarity


def _generate_report_id(asset_id: str, url: str) -> str:
    """Generate a deterministic report ID."""
    raw = f"{asset_id}:{url}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _classify_infringement(
    similarity: int,
    watermark_found: bool,
    original_has_watermark: bool,
) -> Optional[InfringementType]:
    """Classify the type of infringement based on evidence.

    Returns None if no infringement detected.
    """
    if similarity < INFRINGEMENT_THRESHOLD:
        return None

    if similarity >= EXACT_MATCH_THRESHOLD:
        # Exact copy — unauthorized distribution
        if original_has_watermark and not watermark_found:
            return InfringementType.CONTENT_TAMPERING
        return InfringementType.UNAUTHORIZED_DISTRIBUTION

    if similarity >= HIGH_SIMILARITY_THRESHOLD:
        # High similarity — likely unauthorized with modifications
        return InfringementType.CONTENT_TAMPERING

    # Medium similarity — possible license violation
    return InfringementType.LICENSE_VIOLATION


def _assess_severity(
    infringement_type: InfringementType,
    similarity: int,
) -> SeverityLevel:
    """Assess severity based on infringement type and similarity."""
    if infringement_type == InfringementType.UNAUTHORIZED_DISTRIBUTION:
        if similarity >= EXACT_MATCH_THRESHOLD:
            return SeverityLevel.CRITICAL
        return SeverityLevel.HIGH

    if infringement_type == InfringementType.CONTENT_TAMPERING:
        return SeverityLevel.HIGH

    if infringement_type == InfringementType.LICENSE_VIOLATION:
        if similarity >= HIGH_SIMILARITY_THRESHOLD:
            return SeverityLevel.MEDIUM
        return SeverityLevel.LOW

    return SeverityLevel.LOW


class InfringementDetector:
    """Detects infringements by comparing scan results against registered assets."""

    def __init__(self, scanner: FingerprintScanner) -> None:
        self.scanner = scanner
        # Whitelist: set of (asset_id, url) that are authorized
        self._whitelist: set = set()
        # Known asset metadata: asset_id -> {value, has_watermark, owner}
        self._asset_meta: Dict[str, Dict[str, Any]] = {}

    def register_asset(self, asset_id: str, fingerprint: str,
                       value: int = 0, has_watermark: bool = False,
                       owner: str = "") -> None:
        """Register an asset for infringement monitoring."""
        self.scanner.register_fingerprint(asset_id, fingerprint)
        self._asset_meta[asset_id] = {
            "value": value,
            "has_watermark": has_watermark,
            "owner": owner,
        }

    def whitelist(self, asset_id: str, url: str) -> None:
        """Whitelist a URL for an asset (authorized distribution)."""
        self._whitelist.add((asset_id, url))

    def is_whitelisted(self, asset_id: str, url: str) -> bool:
        """Check if a URL is whitelisted for an asset."""
        return (asset_id, url) in self._whitelist

    def detect_infringement(
        self,
        asset_id: str,
        scan_results: List[ScanResult],
    ) -> List[InfringementReport]:
        """Detect infringements from scan results for a specific asset.

        Filters out whitelisted URLs and results below similarity threshold.
        """
        meta = self._asset_meta.get(asset_id, {})
        original_has_watermark = meta.get("has_watermark", False)
        asset_value = meta.get("value", to_units(100))  # default 100 OAS

        registered_fp = self.scanner._registry.get(asset_id)
        if registered_fp is None:
            return []

        reports = []
        for sr in scan_results:
            # Skip whitelisted
            if self.is_whitelisted(asset_id, sr.url):
                continue

            similarity = self.scanner.compare_fingerprints(registered_fp, sr.fingerprint)

            # Classify
            infringement_type = _classify_infringement(
                similarity, sr.fingerprint != "", original_has_watermark,
            )
            if infringement_type is None:
                continue

            severity = _assess_severity(infringement_type, similarity)
            damages = self.calculate_damages_from_severity(severity, asset_value)
            report_id = _generate_report_id(asset_id, sr.url)

            reports.append(InfringementReport(
                report_id=report_id,
                asset_id=asset_id,
                infringement_type=infringement_type,
                severity=severity,
                scan_result=sr,
                similarity_score=similarity,
                damages_estimate=damages,
                description=(
                    f"{infringement_type.value} detected on {sr.platform} "
                    f"(similarity: {similarity / 100:.1f}%)"
                ),
            ))

        return reports

    def calculate_damages(self, infringement: InfringementReport) -> int:
        """Calculate damages for an infringement report."""
        meta = self._asset_meta.get(infringement.asset_id, {})
        asset_value = meta.get("value", to_units(100))
        return self.calculate_damages_from_severity(
            infringement.severity, asset_value,
        )

    def calculate_damages_from_severity(
        self,
        severity: SeverityLevel,
        asset_value: int,
    ) -> int:
        """Calculate damages based on severity and asset value."""
        rate = DAMAGE_RATES.get(severity.value, 100)
        return apply_rate_bps(asset_value, rate)

    def detect_all(
        self,
        scan_results: List[ScanResult],
    ) -> List[InfringementReport]:
        """Detect infringements across all registered assets."""
        all_reports = []
        for sr in scan_results:
            owner = self.scanner.find_owner(sr.fingerprint)
            if owner is not None:
                reports = self.detect_infringement(owner, [sr])
                all_reports.extend(reports)
        return all_reports

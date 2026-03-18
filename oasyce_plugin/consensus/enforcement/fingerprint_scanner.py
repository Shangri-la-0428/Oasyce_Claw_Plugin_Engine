"""
Fingerprint Scanner — content fingerprinting and watermark verification.

Extracts content fingerprints (SHA-256 based), detects embedded watermarks,
and scans platforms for matching content.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from oasyce_plugin.consensus.enforcement.types import (
    FingerprintResult,
    ScanResult,
)

if TYPE_CHECKING:
    from oasyce_plugin.consensus.enforcement.crawlers.base import BaseCrawler


# Similarity thresholds (basis points, 10000 = exact match)
EXACT_MATCH_THRESHOLD = 9500      # >= 95% = exact
HIGH_SIMILARITY_THRESHOLD = 8000  # >= 80% = high
MEDIUM_SIMILARITY_THRESHOLD = 5000  # >= 50% = medium
INFRINGEMENT_THRESHOLD = 5000       # minimum similarity for infringement


def _content_hash(data: bytes) -> str:
    """SHA-256 hash of raw content."""
    return hashlib.sha256(data).hexdigest()


def _fingerprint_hash(data: bytes) -> str:
    """Generate a content fingerprint.

    Uses a two-pass hash: first normalize, then SHA-256.
    This makes the fingerprint resilient to minor formatting changes.
    """
    # Normalize: strip whitespace variations for text content
    normalized = data.strip()
    # Double-hash for fingerprint distinction from content_hash
    inner = hashlib.sha256(normalized).digest()
    return hashlib.sha256(inner).hexdigest()


def _extract_watermark(data: bytes) -> Optional[str]:
    """Extract an embedded Oasyce watermark from content.

    Watermarks are embedded as a magic byte sequence:
    b'OASYCE_WM:' followed by hex payload until b':WM_END'
    """
    marker_start = b"OASYCE_WM:"
    marker_end = b":WM_END"
    start = data.find(marker_start)
    if start < 0:
        return None
    payload_start = start + len(marker_start)
    end = data.find(marker_end, payload_start)
    if end < 0:
        return None
    try:
        return data[payload_start:end].decode("ascii").strip()
    except (UnicodeDecodeError, ValueError):
        return None


def _compute_similarity(fp_a: str, fp_b: str) -> int:
    """Compute similarity between two fingerprints.

    Returns a score in basis points (0-10000).
    Exact match = 10000, completely different = 0.
    Uses character-level comparison of hex digests.
    """
    if not fp_a and not fp_b:
        return 0
    if fp_a == fp_b:
        return 10000
    if not fp_a or not fp_b:
        return 0
    # Normalize lengths
    min_len = min(len(fp_a), len(fp_b))
    if min_len == 0:
        return 0
    matches = sum(1 for a, b in zip(fp_a[:min_len], fp_b[:min_len]) if a == b)
    return (matches * 10000) // min_len


class FingerprintScanner:
    """Scans content for fingerprints and watermarks.

    Stores a registry of known fingerprints (asset_id -> fingerprint)
    for ownership verification.
    """

    def __init__(self) -> None:
        # In-memory registry: asset_id -> fingerprint hex
        self._registry: Dict[str, str] = {}
        # Reverse index: fingerprint -> asset_id
        self._reverse: Dict[str, str] = {}
        # Crawlers: platform -> crawler instance
        self._crawlers: Dict[str, BaseCrawler] = {}

    def register_fingerprint(self, asset_id: str, fingerprint: str) -> None:
        """Register a known fingerprint for an asset."""
        self._registry[asset_id] = fingerprint
        self._reverse[fingerprint] = asset_id

    def register_crawler(self, platform: str, crawler: "BaseCrawler") -> None:
        """Register a platform crawler."""
        self._crawlers[platform] = crawler

    def scan_content(self, content: bytes | str) -> FingerprintResult:
        """Scan content, extract fingerprint and watermark."""
        if isinstance(content, str):
            data = content.encode("utf-8")
        else:
            data = content

        fp = _fingerprint_hash(data)
        ch = _content_hash(data)
        wm = _extract_watermark(data)

        return FingerprintResult(
            fingerprint=fp,
            content_hash=ch,
            content_size=len(data),
            watermark_found=wm is not None,
            watermark_data=wm or "",
            similarity_score=10000,  # self-scan = exact
        )

    def verify_ownership(self, fingerprint: str, asset_id: str) -> bool:
        """Verify if a fingerprint belongs to a registered asset."""
        registered = self._registry.get(asset_id)
        if registered is None:
            return False
        return _compute_similarity(registered, fingerprint) >= EXACT_MATCH_THRESHOLD

    def find_owner(self, fingerprint: str) -> Optional[str]:
        """Find the asset_id that owns this fingerprint, if any."""
        # Exact match first
        if fingerprint in self._reverse:
            return self._reverse[fingerprint]
        # Fuzzy match
        best_score = 0
        best_asset = None
        for asset_id, reg_fp in self._registry.items():
            score = _compute_similarity(reg_fp, fingerprint)
            if score > best_score:
                best_score = score
                best_asset = asset_id
        if best_score >= HIGH_SIMILARITY_THRESHOLD:
            return best_asset
        return None

    def compare_fingerprints(self, fp_a: str, fp_b: str) -> int:
        """Compare two fingerprints. Returns similarity in basis points."""
        return _compute_similarity(fp_a, fp_b)

    def scan_platform(self, platform: str, url: str) -> List[ScanResult]:
        """Scan a public platform URL for content matching registered assets.

        Returns a list of ScanResult for each piece of content found.
        Requires a crawler registered for the given platform.
        """
        crawler = self._crawlers.get(platform)
        if crawler is None:
            raise ValueError(f"No crawler registered for platform: {platform}")
        return crawler.crawl(url)

    def scan_and_match(self, platform: str, url: str) -> List[Dict[str, Any]]:
        """Scan a platform and match found content against registered assets.

        Returns matches with asset_id and similarity score.
        """
        results = self.scan_platform(platform, url)
        matches = []
        for sr in results:
            owner = self.find_owner(sr.fingerprint)
            if owner is not None:
                registered_fp = self._registry.get(owner, "")
                similarity = _compute_similarity(registered_fp, sr.fingerprint)
                matches.append({
                    "asset_id": owner,
                    "scan_result": sr,
                    "similarity": similarity,
                })
        return matches

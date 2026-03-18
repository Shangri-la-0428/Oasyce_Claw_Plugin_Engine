"""
Base crawler — abstract interface and shared utilities for platform crawlers.

All crawlers must respect robots.txt and enforce rate limiting.
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from oasyce_plugin.consensus.enforcement.types import ScanResult


# Default rate limit: 1 request per second per platform
DEFAULT_RATE_LIMIT = 1.0  # seconds between requests


class RateLimiter:
    """Simple per-platform rate limiter."""

    def __init__(self, min_interval: float = DEFAULT_RATE_LIMIT) -> None:
        self.min_interval = min_interval
        self._last_request: float = 0.0

    def wait(self) -> None:
        """Block until rate limit allows next request."""
        now = time.time()
        elapsed = now - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.time()

    def can_proceed(self) -> bool:
        """Check if a request can proceed without blocking."""
        return (time.time() - self._last_request) >= self.min_interval


def compute_content_hash(content: str | bytes) -> str:
    """SHA-256 hash of content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def compute_fingerprint(content: str | bytes) -> str:
    """Compute a fingerprint from content (normalized double-hash)."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    normalized = content.strip()
    inner = hashlib.sha256(normalized).digest()
    return hashlib.sha256(inner).hexdigest()


class BaseCrawler(ABC):
    """Abstract base for platform crawlers.

    Subclasses implement `crawl()` to fetch and parse platform content.
    Rate limiting and robots.txt compliance are handled here.
    """

    platform: str = "unknown"

    def __init__(self, rate_limit: float = DEFAULT_RATE_LIMIT) -> None:
        self._limiter = RateLimiter(rate_limit)
        self._robots_cache: Dict[str, bool] = {}

    def check_robots_txt(self, url: str) -> bool:
        """Check robots.txt compliance for a URL.

        Returns True if crawling is allowed.
        Default implementation allows all — subclasses should override
        with actual robots.txt parsing for production use.
        """
        return self._robots_cache.get(url, True)

    def set_robots_allowed(self, url: str, allowed: bool) -> None:
        """Manually set robots.txt status for testing."""
        self._robots_cache[url] = allowed

    @abstractmethod
    def crawl(self, url: str) -> List[ScanResult]:
        """Crawl a URL and return scan results.

        Must be implemented by subclasses.
        Should call self._limiter.wait() before each HTTP request.
        Should call self.check_robots_txt() and skip blocked URLs.
        """
        ...

    def _make_scan_result(
        self,
        url: str,
        content: str,
        title: str = "",
        author: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ScanResult:
        """Helper to create a ScanResult from crawled content."""
        content_hash = compute_content_hash(content)
        fingerprint = compute_fingerprint(content)
        return ScanResult(
            platform=self.platform,
            url=url,
            content_hash=content_hash,
            fingerprint=fingerprint,
            similarity_score=0,  # computed later by scanner
            title=title,
            author=author,
            timestamp=int(time.time()),
            raw_snippet=content[:500],
            metadata=metadata or {},
        )

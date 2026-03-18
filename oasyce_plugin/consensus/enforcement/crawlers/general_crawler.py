"""
General Crawler — scan arbitrary web pages for content matching registered assets.

Respects robots.txt and rate limits.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from oasyce_plugin.consensus.enforcement.crawlers.base import BaseCrawler
from oasyce_plugin.consensus.enforcement.types import ScanResult


class GeneralCrawler(BaseCrawler):
    """Generic web page crawler.

    Fetches page content and extracts text for fingerprint comparison.
    """

    platform = "web"

    def __init__(
        self,
        rate_limit: float = 1.0,
        fetch_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    ) -> None:
        super().__init__(rate_limit)
        self._fetch_fn = fetch_fn

    def crawl(self, url: str) -> List[ScanResult]:
        """Crawl a generic web URL.

        Returns scan results for each content block found on the page.
        """
        if not self.check_robots_txt(url):
            return []

        self._limiter.wait()

        if self._fetch_fn is None:
            return []

        data = self._fetch_fn(url)
        if data is None:
            return []

        results = []

        # Single page content
        content = data.get("content", "")
        if content:
            sr = self._make_scan_result(
                url=url,
                content=content,
                title=data.get("title", ""),
                author=data.get("author", ""),
                metadata={
                    "content_type": data.get("content_type", "text/html"),
                    "status_code": data.get("status_code", 200),
                },
            )
            results.append(sr)

        # Multiple content blocks (e.g., forum posts)
        blocks = data.get("blocks", [])
        for block in blocks:
            block_content = block.get("content", "")
            if not block_content:
                continue
            block_url = block.get("url", url)
            sr = self._make_scan_result(
                url=block_url,
                content=block_content,
                title=block.get("title", ""),
                author=block.get("author", ""),
                metadata=block.get("metadata", {}),
            )
            results.append(sr)

        return results

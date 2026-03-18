"""
Zhihu Crawler — scan Zhihu articles/answers for content matching registered assets.

Respects robots.txt and API rate limits.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from oasyce_plugin.consensus.enforcement.crawlers.base import BaseCrawler
from oasyce_plugin.consensus.enforcement.types import ScanResult


class ZhihuCrawler(BaseCrawler):
    """Scans Zhihu for matching content.

    Supports scanning:
    - Articles (zhuanlan)
    - Answers
    - Question pages
    """

    platform = "zhihu"

    def __init__(
        self,
        rate_limit: float = 1.0,
        fetch_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    ) -> None:
        super().__init__(rate_limit)
        self._fetch_fn = fetch_fn

    def crawl(self, url: str) -> List[ScanResult]:
        """Crawl a Zhihu URL.

        Expects URL to article, answer, or question.
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
        articles = data.get("articles", [])
        for article in articles:
            content = article.get("content", "")
            if not content:
                continue
            article_url = article.get("url", url)
            sr = self._make_scan_result(
                url=article_url,
                content=content,
                title=article.get("title", ""),
                author=article.get("author", ""),
                metadata={
                    "article_id": article.get("id", ""),
                    "upvotes": article.get("upvotes", 0),
                    "comments": article.get("comments", 0),
                },
            )
            results.append(sr)

        return results

"""
Twitter Crawler — scan Twitter/X posts for content matching registered assets.

Respects robots.txt and API rate limits.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from oasyce_plugin.consensus.enforcement.crawlers.base import BaseCrawler
from oasyce_plugin.consensus.enforcement.types import ScanResult


class TwitterCrawler(BaseCrawler):
    """Scans Twitter/X for matching content.

    Supports scanning:
    - Individual tweet content
    - User timelines
    - Search results
    """

    platform = "twitter"

    def __init__(
        self,
        rate_limit: float = 1.0,
        fetch_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    ) -> None:
        super().__init__(rate_limit)
        self._fetch_fn = fetch_fn

    def crawl(self, url: str) -> List[ScanResult]:
        """Crawl a Twitter URL.

        Expects URL or search query.
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
        tweets = data.get("tweets", [])
        for tweet in tweets:
            content = tweet.get("text", "")
            if not content:
                continue
            tweet_url = tweet.get("url", url)
            sr = self._make_scan_result(
                url=tweet_url,
                content=content,
                title="",
                author=tweet.get("author", ""),
                metadata={
                    "tweet_id": tweet.get("id", ""),
                    "likes": tweet.get("likes", 0),
                    "retweets": tweet.get("retweets", 0),
                },
            )
            results.append(sr)

        return results

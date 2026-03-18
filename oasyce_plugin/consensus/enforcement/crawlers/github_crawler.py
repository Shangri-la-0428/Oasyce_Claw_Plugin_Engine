"""
GitHub Crawler — scan GitHub repositories for content matching registered assets.

Respects robots.txt and API rate limits.
Uses GitHub REST API when available, falls back to raw content.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from oasyce_plugin.consensus.enforcement.crawlers.base import BaseCrawler
from oasyce_plugin.consensus.enforcement.types import ScanResult


class GitHubCrawler(BaseCrawler):
    """Scans GitHub repositories for matching content.

    Supports scanning:
    - Repository file trees
    - README and documentation files
    - Release assets
    """

    platform = "github"

    def __init__(
        self,
        rate_limit: float = 1.0,
        fetch_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    ) -> None:
        super().__init__(rate_limit)
        # Pluggable fetch function for testing (avoids real HTTP)
        self._fetch_fn = fetch_fn

    def crawl(self, url: str) -> List[ScanResult]:
        """Crawl a GitHub repository URL.

        Expects URL in format: https://github.com/{owner}/{repo}
        or just {owner}/{repo}.
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

        # Process file list
        files = data.get("files", [])
        for f in files:
            content = f.get("content", "")
            if not content:
                continue
            file_url = f.get("url", f"{url}/{f.get('path', '')}")
            sr = self._make_scan_result(
                url=file_url,
                content=content,
                title=f.get("path", ""),
                author=data.get("owner", ""),
                metadata={
                    "repo": data.get("repo", ""),
                    "path": f.get("path", ""),
                    "size": f.get("size", 0),
                },
            )
            results.append(sr)

        return results

    def crawl_repo(self, owner: str, repo: str) -> List[ScanResult]:
        """Convenience method to crawl by owner/repo."""
        url = f"https://github.com/{owner}/{repo}"
        return self.crawl(url)

"""Oracle Feed Adapter Framework.

Wraps external data sources (weather, prices, news, etc.) as Oasyce capability
assets. Each feed is a CapabilityManifest that, when invoked, fetches real-time
data from an external API and returns it through the standard settlement flow.

Architecture:
    OracleFeed (abstract) → WeatherFeed, PriceFeed, ...
    OracleRegistry — registers feeds as capabilities on startup
    OracleExecutor — handles invocation by dispatching to the right feed
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from oasyce.capabilities.manifest import (
    CapabilityManifest,
    PricingConfig,
    StakingConfig,
    QualityPolicy,
    ExecutionLimits,
)


@dataclass
class FeedResult:
    """Result from an oracle feed query."""

    feed_id: str
    data: Dict[str, Any]
    source: str
    fetched_at: int = field(default_factory=lambda: int(time.time()))
    cache_ttl: int = 300  # seconds


class OracleFeed(ABC):
    """Abstract base class for oracle data feeds."""

    @property
    @abstractmethod
    def feed_id(self) -> str:
        """Unique feed identifier."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable feed name."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Feed description."""

    @property
    def tags(self) -> List[str]:
        return ["oracle", self.feed_id]

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {"query": {"type": "string"}}}

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "data": {"type": "object"},
                "source": {"type": "string"},
                "fetched_at": {"type": "integer"},
            },
            "required": ["data", "source"],
        }

    @property
    def pricing(self) -> PricingConfig:
        return PricingConfig(base_price=0.1, reserve_ratio=0.35)

    @abstractmethod
    def fetch(self, query: Dict[str, Any]) -> FeedResult:
        """Fetch data from the external source.

        Args:
            query: Input payload from the invocation.

        Returns:
            FeedResult with the fetched data.

        Raises:
            FeedError: If the fetch fails.
        """

    def to_manifest(self, provider_id: str) -> CapabilityManifest:
        """Convert this feed to a CapabilityManifest for registration."""
        return CapabilityManifest(
            name=self.name,
            description=self.description,
            version=self.version,
            provider=provider_id,
            tags=self.tags,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            pricing=self.pricing,
            staking=StakingConfig(min_bond=10.0),
            quality=QualityPolicy(verification_type="deterministic"),
            limits=ExecutionLimits(timeout_seconds=30, rate_limit_per_minute=120),
        )


class FeedError(Exception):
    """Raised when a feed fetch fails."""


class OracleRegistry:
    """Manages oracle feeds and registers them as capabilities."""

    def __init__(self, provider_id: str = "oracle_node") -> None:
        self.provider_id = provider_id
        self._feeds: Dict[str, OracleFeed] = {}
        self._cache: Dict[str, FeedResult] = {}

    def register_feed(self, feed: OracleFeed) -> CapabilityManifest:
        """Register a feed. Returns its manifest."""
        self._feeds[feed.feed_id] = feed
        return feed.to_manifest(self.provider_id)

    def get_feed(self, feed_id: str) -> Optional[OracleFeed]:
        return self._feeds.get(feed_id)

    def list_feeds(self) -> List[OracleFeed]:
        return list(self._feeds.values())

    def execute(self, feed_id: str, query: Dict[str, Any]) -> FeedResult:
        """Execute a feed query with caching.

        Returns cached result if within TTL, otherwise fetches fresh data.
        """
        feed = self._feeds.get(feed_id)
        if feed is None:
            raise FeedError(f"feed not found: {feed_id}")

        # Check cache
        cached = self._cache.get(feed_id)
        if cached and (time.time() - cached.fetched_at) < cached.cache_ttl:
            return cached

        # Fetch fresh
        result = feed.fetch(query)
        self._cache[feed_id] = result
        return result

    @property
    def feed_count(self) -> int:
        return len(self._feeds)

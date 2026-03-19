"""Tests for Oracle Feed Adapter Framework."""

from __future__ import annotations

import time
import pytest

from oasyce.oracle import (
    OracleFeed,
    OracleRegistry,
    FeedResult,
    FeedError,
)
from oasyce.oracle.feeds import RandomFeed, WeatherFeed, TimeFeed
from oasyce.capabilities.manifest import CapabilityManifest
from oasyce.capabilities.registry import CapabilityRegistry


# ── RandomFeed (deterministic, no network) ────────────────────────────


class TestRandomFeed:
    def test_basic_fetch(self):
        feed = RandomFeed()
        result = feed.fetch({"seed": "test", "count": 3})
        assert result.feed_id == "random"
        assert result.source == "deterministic_prng"
        assert len(result.data["values"]) == 3

    def test_deterministic(self):
        feed = RandomFeed()
        r1 = feed.fetch({"seed": "hello", "count": 5})
        r2 = feed.fetch({"seed": "hello", "count": 5})
        assert r1.data["values"] == r2.data["values"]

    def test_different_seeds(self):
        feed = RandomFeed()
        r1 = feed.fetch({"seed": "a"})
        r2 = feed.fetch({"seed": "b"})
        assert r1.data["values"] != r2.data["values"]

    def test_default_count(self):
        feed = RandomFeed()
        result = feed.fetch({})
        assert len(result.data["values"]) == 5

    def test_max_count_cap(self):
        feed = RandomFeed()
        result = feed.fetch({"count": 999})
        assert len(result.data["values"]) == 100

    def test_stats(self):
        feed = RandomFeed()
        result = feed.fetch({"seed": "stats", "count": 10})
        assert 0 < result.data["mean"] < 1
        assert result.data["sum"] == pytest.approx(sum(result.data["values"]), rel=1e-4)


# ── OracleRegistry ───────────────────────────────────────────────────


class TestOracleRegistry:
    def test_register_and_execute(self):
        reg = OracleRegistry(provider_id="test_oracle")
        feed = RandomFeed()
        manifest = reg.register_feed(feed)

        assert isinstance(manifest, CapabilityManifest)
        assert manifest.name == "Random Oracle (Test)"
        assert manifest.provider == "test_oracle"
        assert "oracle" in manifest.tags
        assert reg.feed_count == 1

    def test_execute(self):
        reg = OracleRegistry()
        reg.register_feed(RandomFeed())
        result = reg.execute("random", {"seed": "exec_test"})
        assert result.feed_id == "random"
        assert len(result.data["values"]) == 5

    def test_execute_not_found(self):
        reg = OracleRegistry()
        with pytest.raises(FeedError, match="feed not found"):
            reg.execute("nonexistent", {})

    def test_caching(self):
        reg = OracleRegistry()
        feed = RandomFeed()
        reg.register_feed(feed)

        # RandomFeed has cache_ttl=0, so no caching
        r1 = reg.execute("random", {"seed": "cache"})
        r2 = reg.execute("random", {"seed": "cache"})
        # Both should have same values (deterministic) but fresh fetches
        assert r1.data == r2.data

    def test_list_feeds(self):
        reg = OracleRegistry()
        reg.register_feed(RandomFeed())
        feeds = reg.list_feeds()
        assert len(feeds) == 1
        assert feeds[0].feed_id == "random"

    def test_get_feed(self):
        reg = OracleRegistry()
        reg.register_feed(RandomFeed())
        assert reg.get_feed("random") is not None
        assert reg.get_feed("nonexistent") is None


# ── Manifest Integration ─────────────────────────────────────────────


class TestManifestIntegration:
    """Verify oracle feeds produce valid manifests that can be registered."""

    def test_random_manifest_valid(self):
        feed = RandomFeed()
        manifest = feed.to_manifest("oracle_provider")
        errors = manifest.validate()
        assert errors == [], f"validation errors: {errors}"

    def test_weather_manifest_valid(self):
        feed = WeatherFeed()
        manifest = feed.to_manifest("oracle_provider")
        errors = manifest.validate()
        assert errors == []

    def test_time_manifest_valid(self):
        feed = TimeFeed()
        manifest = feed.to_manifest("oracle_provider")
        errors = manifest.validate()
        assert errors == []

    def test_register_in_capability_registry(self):
        """Oracle feeds can be registered in the main capability registry."""
        cap_reg = CapabilityRegistry()
        feeds = [RandomFeed(), WeatherFeed(), TimeFeed()]

        for feed in feeds:
            manifest = feed.to_manifest("oracle_node_1")
            cap_id = cap_reg.register(manifest)
            assert cap_id
            stored = cap_reg.get(cap_id)
            assert stored is not None
            assert stored.name == feed.name

    def test_search_by_oracle_tag(self):
        cap_reg = CapabilityRegistry()
        cap_reg.register(RandomFeed().to_manifest("o1"))
        cap_reg.register(WeatherFeed().to_manifest("o1"))

        results = cap_reg.search(query_tags=["oracle"])
        assert len(results) >= 2


# ── FeedResult ────────────────────────────────────────────────────────


class TestFeedResult:
    def test_dataclass(self):
        r = FeedResult(feed_id="test", data={"k": "v"}, source="src")
        assert r.feed_id == "test"
        assert r.cache_ttl == 300
        assert r.fetched_at > 0

    def test_custom_ttl(self):
        r = FeedResult(feed_id="t", data={}, source="s", cache_ttl=60)
        assert r.cache_ttl == 60


# ── Cache TTL ─────────────────────────────────────────────────────────


class TestCacheTTL:
    def test_weather_cache_respected(self):
        """WeatherFeed cache_ttl = 600s, RandomFeed = 0."""
        reg = OracleRegistry()
        reg.register_feed(RandomFeed())

        # Random: cache_ttl=0 → always fresh
        r1 = reg.execute("random", {"seed": "ttl"})
        r1_time = r1.fetched_at

        # Manually set cached result with future timestamp
        r1_copy = FeedResult(
            feed_id="random",
            data={"cached": True},
            source="test",
            fetched_at=int(time.time()),
            cache_ttl=3600,  # 1 hour
        )
        reg._cache["random"] = r1_copy

        # Should return cached version (within TTL)
        r2 = reg.execute("random", {"seed": "different"})
        assert r2.data == {"cached": True}

    def test_expired_cache_refreshes(self):
        reg = OracleRegistry()
        reg.register_feed(RandomFeed())

        # Set expired cache entry
        old = FeedResult(
            feed_id="random",
            data={"old": True},
            source="test",
            fetched_at=int(time.time()) - 9999,
            cache_ttl=1,
        )
        reg._cache["random"] = old

        # Should fetch fresh (cache expired)
        result = reg.execute("random", {"seed": "fresh"})
        assert "old" not in result.data
        assert "values" in result.data

"""Tests for internal oracle feeds (DataAssetFeed + AggregatorFeed)."""

from __future__ import annotations

import time
import pytest

from oasyce.oracle import OracleRegistry, FeedError
from oasyce.oracle.feeds import RandomFeed
from oasyce.oracle.internal import DataAssetFeed, AggregatorFeed


# ── Mock ledger ───────────────────────────────────────────────────────

MOCK_ASSETS = [
    {"asset_id": "A1", "owner": "alice", "tags": ["medical", "imaging"], "created_at": 1000},
    {"asset_id": "A2", "owner": "alice", "tags": ["medical", "lab"], "created_at": 2000},
    {"asset_id": "A3", "owner": "bob", "tags": ["sensor", "temperature"], "created_at": 3000},
    {"asset_id": "A4", "owner": "bob", "tags": ["sensor", "humidity"], "created_at": 4000},
    {"asset_id": "A5", "owner": "carol", "tags": ["creative", "photo"], "created_at": 5000},
]


def mock_query(filters):
    results = list(MOCK_ASSETS)
    if "tags" in filters:
        results = [a for a in results if set(filters["tags"]).issubset(set(a.get("tags", [])))]
    if "owner" in filters:
        results = [a for a in results if a["owner"] == filters["owner"]]
    if "created_after" in filters:
        results = [a for a in results if a["created_at"] > filters["created_after"]]
    if "created_before" in filters:
        results = [a for a in results if a["created_at"] < filters["created_before"]]
    limit = filters.get("limit", 10)
    return results[:limit]


def mock_get(asset_id):
    for a in MOCK_ASSETS:
        if a["asset_id"] == asset_id:
            return a
    return None


# ── DataAssetFeed tests ──────────────────────────────────────────────


class TestDataAssetFeed:
    @pytest.fixture
    def feed(self):
        return DataAssetFeed(query_fn=mock_query, get_fn=mock_get)

    def test_query_all(self, feed):
        result = feed.fetch({"action": "query"})
        assert result.data["count"] == 5
        assert result.source == "oasyce_ledger"

    def test_query_by_tags(self, feed):
        result = feed.fetch({"action": "query", "tags": ["medical"]})
        assert result.data["count"] == 2
        assert all("medical" in a["tags"] for a in result.data["assets"])

    def test_query_by_owner(self, feed):
        result = feed.fetch({"action": "query", "owner": "bob"})
        assert result.data["count"] == 2
        assert all(a["owner"] == "bob" for a in result.data["assets"])

    def test_query_by_time(self, feed):
        result = feed.fetch({"action": "query", "created_after": 2500})
        assert result.data["count"] == 3

    def test_query_limit(self, feed):
        result = feed.fetch({"action": "query", "limit": 2})
        assert result.data["count"] == 2

    def test_get_existing(self, feed):
        result = feed.fetch({"action": "get", "asset_id": "A3"})
        assert result.data["asset"]["owner"] == "bob"

    def test_get_not_found(self, feed):
        with pytest.raises(FeedError, match="asset not found"):
            feed.fetch({"action": "get", "asset_id": "NONEXISTENT"})

    def test_get_missing_id(self, feed):
        with pytest.raises(FeedError, match="asset_id required"):
            feed.fetch({"action": "get"})

    def test_count(self, feed):
        result = feed.fetch({"action": "count"})
        assert result.data["total"] == 5

    def test_count_filtered(self, feed):
        result = feed.fetch({"action": "count", "tags": ["sensor"]})
        assert result.data["total"] == 2

    def test_latest(self, feed):
        result = feed.fetch({"action": "latest", "limit": 3})
        assert result.data["count"] == 3
        # Should be sorted newest first
        timestamps = [a["created_at"] for a in result.data["assets"]]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_latest_filtered(self, feed):
        result = feed.fetch({"action": "latest", "owner": "alice"})
        assert result.data["count"] == 2

    def test_manifest_valid(self, feed):
        manifest = feed.to_manifest("oracle_self")
        errors = manifest.validate()
        assert errors == []
        assert "self-referential" in manifest.tags

    def test_default_action_is_query(self, feed):
        result = feed.fetch({})
        assert result.data["action"] == "query"


# ── AggregatorFeed tests ─────────────────────────────────────────────


class TestAggregatorFeed:
    @pytest.fixture
    def agg(self):
        return AggregatorFeed(
            {
                "random": RandomFeed(),
                "data_assets": DataAssetFeed(query_fn=mock_query, get_fn=mock_get),
            }
        )

    def test_multi_query(self, agg):
        result = agg.fetch(
            {
                "queries": {
                    "random": {"seed": "agg", "count": 3},
                    "data_assets": {"action": "count"},
                },
            }
        )
        assert result.data["feeds_queried"] == 2
        assert result.data["feeds_ok"] == 2
        assert result.data["feeds_failed"] == 0
        assert len(result.data["results"]["random"]["values"]) == 3
        assert result.data["results"]["data_assets"]["total"] == 5

    def test_partial_failure(self, agg):
        result = agg.fetch(
            {
                "queries": {
                    "random": {"seed": "ok"},
                    "nonexistent": {},
                },
            }
        )
        assert result.data["feeds_ok"] == 1
        assert result.data["feeds_failed"] == 1
        assert "nonexistent" in result.data["errors"]

    def test_empty_queries(self, agg):
        result = agg.fetch({"queries": {}})
        assert result.data["feeds_queried"] == 0

    def test_manifest_valid(self, agg):
        manifest = agg.to_manifest("agg_node")
        errors = manifest.validate()
        assert errors == []
        assert "aggregator" in manifest.tags

    def test_register_in_oracle_registry(self, agg):
        reg = OracleRegistry()
        manifest = reg.register_feed(agg)
        assert manifest.name == "Multi-Feed Aggregator"

        result = reg.execute(
            "aggregator",
            {
                "queries": {"random": {"seed": "reg_test"}},
            },
        )
        assert result.data["feeds_ok"] == 1

"""Internal Oracle — Oasyce registered data assets as oracle feeds.

The network itself is an oracle. Every registered data asset is a record of
the real world. This module bridges registered assets into the Oracle Feed
framework, so other agents can query Oasyce data through the same
capability invocation pipeline.

Flow:
    Agent registers photo → DataAssetFeed wraps it → Another agent invokes
    "query_assets" capability → Gets the data through escrow + settlement

This creates a self-reinforcing loop:
    More registrations → More oracle data → More invocations → More fees → More registrations
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from oasyce.oracle import OracleFeed, FeedResult, FeedError, PricingConfig


class DataAssetFeed(OracleFeed):
    """Oracle feed that reads from Oasyce's own registered data assets.

    Turns every registered asset into queryable oracle data.

    Parameters
    ----------
    query_fn : callable
        (filters: dict) → list of asset dicts from the ledger.
        Must support: tags, owner, created_after, created_before, limit.
    get_fn : callable
        (asset_id: str) → asset dict or None.
    """

    def __init__(
        self,
        query_fn: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
        get_fn: Callable[[str], Optional[Dict[str, Any]]],
    ) -> None:
        self._query = query_fn
        self._get = get_fn

    @property
    def feed_id(self) -> str:
        return "data_assets"

    @property
    def name(self) -> str:
        return "Oasyce Data Asset Oracle"

    @property
    def description(self) -> str:
        return (
            "Query registered data assets on the Oasyce network. "
            "Every registration is a record of the real world — "
            "the network itself is an oracle."
        )

    @property
    def tags(self) -> List[str]:
        return ["oracle", "data_assets", "internal", "self-referential"]

    @property
    def pricing(self) -> PricingConfig:
        return PricingConfig(base_price=0.05, reserve_ratio=0.35)

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["query", "get", "count", "latest"],
                    "description": "query=search, get=by ID, count=total, latest=newest N",
                },
                "asset_id": {"type": "string", "description": "For action=get"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags (AND logic)",
                },
                "owner": {"type": "string", "description": "Filter by owner"},
                "created_after": {"type": "integer", "description": "Unix timestamp"},
                "created_before": {"type": "integer", "description": "Unix timestamp"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
        }

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

    def fetch(self, query: Dict[str, Any]) -> FeedResult:
        action = query.get("action", "query")

        if action == "get":
            return self._fetch_get(query)
        elif action == "count":
            return self._fetch_count(query)
        elif action == "latest":
            return self._fetch_latest(query)
        else:  # query
            return self._fetch_query(query)

    def _fetch_query(self, query: Dict[str, Any]) -> FeedResult:
        filters = {
            k: query[k]
            for k in ("tags", "owner", "created_after", "created_before", "limit")
            if k in query
        }
        if "limit" not in filters:
            filters["limit"] = 10

        assets = self._query(filters)
        return FeedResult(
            feed_id=self.feed_id,
            data={
                "action": "query",
                "count": len(assets),
                "assets": assets,
                "filters": filters,
            },
            source="oasyce_ledger",
            cache_ttl=30,
        )

    def _fetch_get(self, query: Dict[str, Any]) -> FeedResult:
        asset_id = query.get("asset_id", "")
        if not asset_id:
            raise FeedError("asset_id required for action=get")

        asset = self._get(asset_id)
        if asset is None:
            raise FeedError(f"asset not found: {asset_id}")

        return FeedResult(
            feed_id=self.feed_id,
            data={"action": "get", "asset": asset},
            source="oasyce_ledger",
            cache_ttl=60,
        )

    def _fetch_count(self, query: Dict[str, Any]) -> FeedResult:
        filters = {
            k: query[k] for k in ("tags", "owner", "created_after", "created_before") if k in query
        }
        filters["limit"] = 999999  # get all for count
        assets = self._query(filters)
        return FeedResult(
            feed_id=self.feed_id,
            data={"action": "count", "total": len(assets), "filters": filters},
            source="oasyce_ledger",
            cache_ttl=30,
        )

    def _fetch_latest(self, query: Dict[str, Any]) -> FeedResult:
        limit = query.get("limit", 5)
        filters = {"limit": limit}
        if "tags" in query:
            filters["tags"] = query["tags"]
        if "owner" in query:
            filters["owner"] = query["owner"]

        assets = self._query(filters)
        # Sort by created_at desc (in case query_fn doesn't)
        assets.sort(key=lambda a: a.get("created_at", 0), reverse=True)
        assets = assets[:limit]

        return FeedResult(
            feed_id=self.feed_id,
            data={
                "action": "latest",
                "count": len(assets),
                "assets": assets,
            },
            source="oasyce_ledger",
            cache_ttl=30,
        )


class AggregatorFeed(OracleFeed):
    """Meta-oracle that aggregates multiple feeds into a single query.

    Useful for combining external + internal data in one invocation.
    Example: "Give me weather + latest 3 sensor readings + asset count"
    """

    def __init__(self, feeds: Dict[str, OracleFeed]) -> None:
        self._feeds = feeds

    @property
    def feed_id(self) -> str:
        return "aggregator"

    @property
    def name(self) -> str:
        return "Multi-Feed Aggregator"

    @property
    def description(self) -> str:
        feed_names = ", ".join(self._feeds.keys())
        return f"Aggregates multiple oracle feeds in a single query: {feed_names}"

    @property
    def tags(self) -> List[str]:
        return ["oracle", "aggregator", "multi-source"]

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "object",
                    "description": "Map of feed_id → query payload",
                    "additionalProperties": {"type": "object"},
                },
            },
            "required": ["queries"],
        }

    def fetch(self, query: Dict[str, Any]) -> FeedResult:
        queries = query.get("queries", {})
        results = {}
        errors = {}

        for feed_id, sub_query in queries.items():
            feed = self._feeds.get(feed_id)
            if feed is None:
                errors[feed_id] = f"feed not found: {feed_id}"
                continue
            try:
                result = feed.fetch(sub_query)
                results[feed_id] = result.data
            except FeedError as e:
                errors[feed_id] = str(e)

        return FeedResult(
            feed_id=self.feed_id,
            data={
                "results": results,
                "errors": errors,
                "feeds_queried": len(queries),
                "feeds_ok": len(results),
                "feeds_failed": len(errors),
            },
            source="aggregator",
            cache_ttl=0,
        )

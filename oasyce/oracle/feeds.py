"""Built-in oracle feeds — ready-to-use data sources.

These feeds require no API keys and use free public APIs:
  - WeatherFeed: wttr.in (no key needed)
  - TimeFeed: worldtimeapi.org (no key needed)
  - RandomFeed: deterministic PRNG (for testing)
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List
from urllib.request import urlopen, Request
from urllib.error import URLError

from oasyce.oracle import OracleFeed, FeedResult, FeedError, PricingConfig


class WeatherFeed(OracleFeed):
    """Real-time weather data from wttr.in (free, no API key)."""

    @property
    def feed_id(self) -> str:
        return "weather"

    @property
    def name(self) -> str:
        return "Weather Oracle"

    @property
    def description(self) -> str:
        return "Real-time weather data for any location worldwide. Source: wttr.in"

    @property
    def tags(self) -> List[str]:
        return ["oracle", "weather", "realtime"]

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City name or coordinates"},
            },
            "required": ["location"],
        }

    @property
    def output_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "data": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                        "temperature_c": {"type": "number"},
                        "humidity": {"type": "string"},
                        "description": {"type": "string"},
                        "wind_kmph": {"type": "string"},
                    },
                },
                "source": {"type": "string"},
                "fetched_at": {"type": "integer"},
            },
            "required": ["data", "source"],
        }

    def fetch(self, query: Dict[str, Any]) -> FeedResult:
        location = query.get("location", "Beijing")
        url = f"https://wttr.in/{location}?format=j1"
        try:
            req = Request(url, headers={"User-Agent": "oasyce-oracle/1.0"})
            resp = urlopen(req, timeout=10)
            data = json.loads(resp.read())

            current = data.get("current_condition", [{}])[0]
            area = data.get("nearest_area", [{}])[0]
            area_name = area.get("areaName", [{}])[0].get("value", location)

            return FeedResult(
                feed_id=self.feed_id,
                data={
                    "location": area_name,
                    "temperature_c": int(current.get("temp_C", 0)),
                    "humidity": current.get("humidity", ""),
                    "description": current.get("weatherDesc", [{}])[0].get("value", ""),
                    "wind_kmph": current.get("windspeedKmph", ""),
                    "feels_like_c": current.get("FeelsLikeC", ""),
                    "uv_index": current.get("uvIndex", ""),
                },
                source="wttr.in",
                cache_ttl=600,  # 10 min
            )
        except (URLError, OSError, json.JSONDecodeError, KeyError) as e:
            raise FeedError(f"weather fetch failed: {e}")


class TimeFeed(OracleFeed):
    """Current time for any timezone from worldtimeapi.org."""

    @property
    def feed_id(self) -> str:
        return "time"

    @property
    def name(self) -> str:
        return "World Time Oracle"

    @property
    def description(self) -> str:
        return "Current time for any timezone. Source: worldtimeapi.org"

    @property
    def tags(self) -> List[str]:
        return ["oracle", "time", "timezone"]

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "IANA timezone (e.g. Asia/Shanghai)"},
            },
            "required": ["timezone"],
        }

    def fetch(self, query: Dict[str, Any]) -> FeedResult:
        tz = query.get("timezone", "Asia/Shanghai")
        url = f"https://worldtimeapi.org/api/timezone/{tz}"
        try:
            req = Request(url, headers={"User-Agent": "oasyce-oracle/1.0"})
            resp = urlopen(req, timeout=10)
            data = json.loads(resp.read())
            return FeedResult(
                feed_id=self.feed_id,
                data={
                    "timezone": data.get("timezone", tz),
                    "datetime": data.get("datetime", ""),
                    "utc_offset": data.get("utc_offset", ""),
                    "day_of_week": data.get("day_of_week", 0),
                    "week_number": data.get("week_number", 0),
                },
                source="worldtimeapi.org",
                cache_ttl=60,  # 1 min
            )
        except (URLError, OSError, json.JSONDecodeError, KeyError) as e:
            raise FeedError(f"time fetch failed: {e}")


class RandomFeed(OracleFeed):
    """Deterministic pseudo-random oracle for testing.

    Given a seed, always returns the same "random" data.
    Useful for integration tests and demos without network access.
    """

    @property
    def feed_id(self) -> str:
        return "random"

    @property
    def name(self) -> str:
        return "Random Oracle (Test)"

    @property
    def description(self) -> str:
        return "Deterministic pseudo-random data feed for testing. No network required."

    @property
    def tags(self) -> List[str]:
        return ["oracle", "test", "random"]

    @property
    def pricing(self) -> PricingConfig:
        return PricingConfig(base_price=0.01, reserve_ratio=0.35)

    @property
    def input_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "seed": {"type": "string"},
                "count": {"type": "integer"},
            },
        }

    def fetch(self, query: Dict[str, Any]) -> FeedResult:
        seed = query.get("seed", "default")
        count = min(query.get("count", 5), 100)

        # Deterministic: same seed → same output
        values = []
        for i in range(count):
            h = hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()
            values.append(int(h[:8], 16) / 0xFFFFFFFF)

        return FeedResult(
            feed_id=self.feed_id,
            data={
                "seed": seed,
                "count": count,
                "values": [round(v, 6) for v in values],
                "sum": round(sum(values), 6),
                "mean": round(sum(values) / count, 6) if count > 0 else 0,
            },
            source="deterministic_prng",
            cache_ttl=0,  # no cache for random
        )

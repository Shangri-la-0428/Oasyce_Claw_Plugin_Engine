"""
OAS-Oracle: Oasyce Oracle Asset Standard

Defines the standard schema for oracle data feeds — external data sources
that bridge real-world information into the Oasyce network.

Core insight: "The network itself is an oracle." Every registered data asset
is a record of the real world. Oracle feeds formalize this into a standard
that enables:
  - Provider bonding (economic skin-in-the-game for data accuracy)
  - Quality metrics (latency, accuracy, uptime SLA)
  - Aggregation protocol (multi-source consensus for critical data)
  - Feed type registry (weather, price, event, sensor, internal)

Layer structure (extends OAS base):
  Layer 1 - Identity:  inherited from OAS (asset_id, creator, created_at)
  Layer 2 - Metadata:  inherited from OAS (title, tags, description)
  Layer 6 - Oracle:    feed type, provider bond, quality, aggregation
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── Feed Type Registry ──────────────────────────────────────────


class FeedType(str, enum.Enum):
    """Classification of oracle data feeds."""

    WEATHER = "weather"  # Meteorological data
    PRICE = "price"  # Asset/commodity/token prices
    TIME = "time"  # World clock / timezone
    EVENT = "event"  # Discrete events (releases, matches, etc.)
    SENSOR = "sensor"  # IoT / hardware sensor readings
    INTERNAL = "internal"  # Oasyce self-referential (DataAssetFeed)
    AGGREGATOR = "aggregator"  # Multi-feed composite
    CUSTOM = "custom"  # User-defined feed type


_FEED_TYPE_VALUES = {e.value for e in FeedType}


# ─── Freshness Tiers ─────────────────────────────────────────────


class FreshnessTier(str, enum.Enum):
    """How fresh the data must be to be considered valid."""

    REALTIME = "realtime"  # < 1 minute
    NEAR = "near"  # < 10 minutes
    PERIODIC = "periodic"  # < 1 hour
    DAILY = "daily"  # < 24 hours
    STATIC = "static"  # No freshness requirement


_FRESHNESS_TTL = {
    FreshnessTier.REALTIME: 60,
    FreshnessTier.NEAR: 600,
    FreshnessTier.PERIODIC: 3600,
    FreshnessTier.DAILY: 86400,
    FreshnessTier.STATIC: 0,
}


# ─── Provider Bonding ────────────────────────────────────────────


@dataclass
class OracleProviderBond:
    """Economic bonding requirements for oracle providers.

    Providers must stake OAS as a guarantee of data quality.
    Bond is slashed on quality violations (stale data, incorrect values,
    downtime exceeding SLA).

    Bond formula:
      bond = base_bond × feed_risk_factor × (1 - R/100)

    Where R is the provider's reputation score.
    """

    base_bond: float = 100.0  # Minimum OAS bond
    feed_risk_factor: float = 1.0  # Higher for price feeds, lower for weather
    slash_stale: float = 0.05  # 5% slash for stale data
    slash_incorrect: float = 0.20  # 20% slash for verifiably incorrect data
    slash_downtime: float = 0.10  # 10% slash for SLA breach
    cooldown_seconds: int = 3600  # 1 hour cooldown after slash before resuming


# ─── Quality Policy ──────────────────────────────────────────────


@dataclass
class OracleQualityMetrics:
    """Quality requirements and tracking for oracle feeds.

    These metrics determine whether a feed maintains its bond or gets slashed.
    """

    # SLA targets
    min_uptime_pct: float = 99.0  # Minimum uptime percentage
    max_latency_ms: int = 5000  # Maximum acceptable latency (ms)
    freshness: str = FreshnessTier.NEAR.value  # Required freshness tier

    # Verification
    verification_type: str = "deterministic"  # deterministic | consensus | signed
    min_consensus_sources: int = 1  # For consensus verification
    require_signed_payload: bool = False  # Require Ed25519 signature on data

    # Tracking (mutable, updated by the network)
    total_queries: int = 0
    successful_queries: int = 0
    avg_latency_ms: float = 0.0
    last_failure_at: Optional[int] = None

    @property
    def success_rate(self) -> float:
        """Query success rate as percentage."""
        if self.total_queries == 0:
            return 100.0
        return (self.successful_queries / self.total_queries) * 100.0

    @property
    def freshness_ttl(self) -> int:
        """Maximum allowed age of data in seconds."""
        try:
            return _FRESHNESS_TTL[FreshnessTier(self.freshness)]
        except (ValueError, KeyError):
            return 600  # Default 10 min


# ─── Pricing Model ───────────────────────────────────────────────


@dataclass
class OraclePricingModel:
    """Pricing configuration for oracle feed invocations.

    Supports per-call and subscription models.
    Fee split follows protocol standard: 60/20/15/5
    (provider/stakers/burn/treasury).
    """

    model: str = "per_call"  # per_call | subscription | free
    base_price_oas: float = 0.1  # OAS per invocation
    subscription_price_oas: float = 0.0  # OAS per subscription period
    subscription_period_days: int = 30
    reserve_ratio: float = 0.35  # Bonding curve reserve ratio
    bulk_discount_threshold: int = 100  # Calls/day for bulk pricing
    bulk_discount_pct: float = 0.20  # 20% discount above threshold


_VALID_PRICING_MODELS = {"per_call", "subscription", "free"}
_VALID_VERIFICATION_TYPES = {"deterministic", "consensus", "signed"}


# ─── Aggregation Protocol ────────────────────────────────────────


@dataclass
class AggregationConfig:
    """Configuration for multi-source oracle aggregation.

    When critical decisions depend on oracle data, a single source is
    a single point of failure. Aggregation combines multiple feeds
    with a consensus mechanism.
    """

    strategy: str = "median"  # median | mean | weighted | first_valid
    min_sources: int = 1  # Minimum sources required
    max_deviation_pct: float = 10.0  # Max deviation from median before outlier rejection
    timeout_per_source_ms: int = 5000
    fallback_on_failure: bool = True  # Return partial results if some sources fail

    def validate(self) -> List[str]:
        """Validate aggregation config."""
        errors: List[str] = []
        valid_strategies = {"median", "mean", "weighted", "first_valid"}
        if self.strategy not in valid_strategies:
            errors.append(f"strategy '{self.strategy}' must be one of {sorted(valid_strategies)}")
        if self.min_sources < 1:
            errors.append("min_sources must be >= 1")
        if self.max_deviation_pct <= 0:
            errors.append("max_deviation_pct must be > 0")
        return errors


# ─── Oracle Layer (composite) ────────────────────────────────────


@dataclass
class OracleLayer:
    """Layer 6: Oracle-specific properties for oracle assets.

    Combines feed classification, provider bonding, quality metrics,
    pricing, and aggregation into a single layer that extends the
    base OAS asset schema.
    """

    feed_type: str = FeedType.CUSTOM.value
    feed_uri: str = ""  # e.g. "oracle://weather/shanghai"
    provider_bond: OracleProviderBond = field(default_factory=OracleProviderBond)
    quality: OracleQualityMetrics = field(default_factory=OracleQualityMetrics)
    pricing: OraclePricingModel = field(default_factory=OraclePricingModel)
    aggregation: Optional[AggregationConfig] = None

    # Schema (inheritable from OracleFeed)
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)

    # Source feeds (for aggregator type)
    source_feed_ids: List[str] = field(default_factory=list)

    def validate(self) -> List[str]:
        """Validate the oracle layer. Returns list of error messages."""
        errors: List[str] = []

        if self.feed_type not in _FEED_TYPE_VALUES:
            errors.append(
                f"feed_type '{self.feed_type}' must be one of " f"{sorted(_FEED_TYPE_VALUES)}"
            )

        if self.pricing.model not in _VALID_PRICING_MODELS:
            errors.append(
                f"pricing.model '{self.pricing.model}' must be one of "
                f"{sorted(_VALID_PRICING_MODELS)}"
            )

        if self.quality.verification_type not in _VALID_VERIFICATION_TYPES:
            errors.append(
                f"quality.verification_type '{self.quality.verification_type}' "
                f"must be one of {sorted(_VALID_VERIFICATION_TYPES)}"
            )

        if self.feed_type == FeedType.AGGREGATOR.value:
            if not self.source_feed_ids:
                errors.append("aggregator feeds require source_feed_ids")
            if self.aggregation:
                errors.extend(self.aggregation.validate())

        if self.provider_bond.base_bond < 0:
            errors.append("provider_bond.base_bond must be >= 0")

        return errors


# ─── Feed Risk Factors ───────────────────────────────────────────

# Different feed types carry different risk profiles.
# Price feeds need higher bonds because incorrect prices can cause
# cascading financial losses.
FEED_RISK_FACTORS: Dict[str, float] = {
    FeedType.WEATHER.value: 0.5,  # Low risk — incorrect weather is annoying, not catastrophic
    FeedType.TIME.value: 0.3,  # Very low — easily verifiable
    FeedType.PRICE.value: 3.0,  # High — financial decisions depend on accuracy
    FeedType.EVENT.value: 2.0,  # Medium-high — triggers conditional actions
    FeedType.SENSOR.value: 1.5,  # Medium — depends on use case
    FeedType.INTERNAL.value: 0.5,  # Low — self-referential, already bonded at registration
    FeedType.AGGREGATOR.value: 1.0,  # Medium — inherits risk from sources
    FeedType.CUSTOM.value: 2.0,  # Default high — unknown risk profile
}


def recommended_bond(feed_type: str, base: float = 100.0) -> float:
    """Calculate recommended provider bond for a feed type.

    Args:
        feed_type: FeedType value string.
        base: Base bond amount in OAS.

    Returns:
        Recommended bond in OAS.
    """
    factor = FEED_RISK_FACTORS.get(feed_type, 2.0)
    return round(base * factor, 2)


__all__ = [
    "FeedType",
    "FreshnessTier",
    "OracleProviderBond",
    "OracleQualityMetrics",
    "OraclePricingModel",
    "AggregationConfig",
    "OracleLayer",
    "FEED_RISK_FACTORS",
    "recommended_bond",
]

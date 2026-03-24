"""
Capability Manifest — data structure and validation for capability assets.

A CapabilityManifest fully describes a callable agent service:
identity, schema, pricing, staking, quality policy, and execution limits.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ── Status lifecycle ──────────────────────────────────────────────────────────
VALID_STATUSES = {"active", "paused", "deprecated"}


# ── Sub-configs ───────────────────────────────────────────────────────────────


@dataclass
class PricingConfig:
    """Bonding curve pricing parameters."""

    base_price: float = 1.0  # initial price per call (OAS)
    reserve_ratio: float = 0.35  # Bancor CW
    protocol_fee_pct: float = 0.03  # 3%

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.base_price <= 0:
            errors.append("pricing.base_price must be > 0")
        if not (0 < self.reserve_ratio <= 1):
            errors.append("pricing.reserve_ratio must be in (0, 1]")
        if not (0 <= self.protocol_fee_pct < 1):
            errors.append("pricing.protocol_fee_pct must be in [0, 1)")
        return errors


@dataclass
class StakingConfig:
    """Provider staking / bond requirements."""

    min_bond: float = 100.0  # minimum OAS bond
    slash_timeout: float = 0.05  # 5%
    slash_invalid_output: float = 0.10
    slash_dispute_lost: float = 0.20
    slash_fraud: float = 1.00
    unbonding_period: int = 7 * 86400  # 7 days

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.min_bond < 0:
            errors.append("staking.min_bond must be >= 0")
        return errors


@dataclass
class QualityPolicy:
    """Quality assurance parameters."""

    verification_type: str = "optimistic"  # optimistic | deterministic | subjective
    dispute_window_seconds: int = 3600  # 1 hour
    min_jury_size: int = 3

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.verification_type not in {"optimistic", "deterministic", "subjective"}:
            errors.append(
                f"quality.verification_type '{self.verification_type}' "
                "must be one of: optimistic, deterministic, subjective"
            )
        if self.dispute_window_seconds <= 0:
            errors.append("quality.dispute_window_seconds must be > 0")
        return errors


@dataclass
class ExecutionLimits:
    """Runtime constraints for capability execution."""

    max_concurrent_calls: int = 10
    rate_limit_per_minute: int = 60
    timeout_seconds: int = 300
    max_input_size_bytes: int = 1_048_576  # 1 MB
    max_output_size_bytes: int = 10_485_760  # 10 MB

    def validate(self) -> List[str]:
        errors: List[str] = []
        if self.timeout_seconds <= 0:
            errors.append("limits.timeout_seconds must be > 0")
        if self.max_concurrent_calls <= 0:
            errors.append("limits.max_concurrent_calls must be > 0")
        return errors


# ── Main manifest ─────────────────────────────────────────────────────────────


def compute_capability_id(provider: str, name: str, version: str) -> str:
    """capability_id = sha256(provider + ':' + name + ':' + version)[:32]"""
    raw = f"{provider}:{name}:{version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


@dataclass
class CapabilityManifest:
    """Complete manifest for a capability asset.

    The capability_id is auto-computed from (provider, name, version)
    if not explicitly provided.
    """

    # Identity
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    provider: str = ""  # Ed25519 public key hex

    # Discovery
    tags: List[str] = field(default_factory=list)
    semantic_vector: Optional[List[float]] = None

    # Schema
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)

    # Economics
    pricing: PricingConfig = field(default_factory=PricingConfig)
    staking: StakingConfig = field(default_factory=StakingConfig)

    # Quality
    quality: QualityPolicy = field(default_factory=QualityPolicy)

    # Limits
    limits: ExecutionLimits = field(default_factory=ExecutionLimits)

    # Metadata
    created_at: int = 0
    updated_at: int = 0
    status: str = "active"

    # Computed
    capability_id: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = int(time.time())
        if not self.updated_at:
            self.updated_at = self.created_at
        if not self.capability_id and self.provider and self.name and self.version:
            self.capability_id = compute_capability_id(self.provider, self.name, self.version)

    def validate(self) -> List[str]:
        """Validate the manifest. Returns list of error messages (empty = valid)."""
        errors: List[str] = []

        # Required fields
        if not self.name:
            errors.append("name is required")
        if not self.provider:
            errors.append("provider is required")
        if not self.version:
            errors.append("version is required")

        # Schema validation (lightweight — just check dict with 'type' key)
        if not self.input_schema:
            errors.append("input_schema is required")
        elif not isinstance(self.input_schema, dict):
            errors.append("input_schema must be a dict")
        elif "type" not in self.input_schema:
            errors.append("input_schema must have a 'type' key")

        if not self.output_schema:
            errors.append("output_schema is required")
        elif not isinstance(self.output_schema, dict):
            errors.append("output_schema must be a dict")
        elif "type" not in self.output_schema:
            errors.append("output_schema must have a 'type' key")

        # Status
        if self.status not in VALID_STATUSES:
            errors.append(f"status '{self.status}' must be one of {sorted(VALID_STATUSES)}")

        # Sub-config validation
        errors.extend(self.pricing.validate())
        errors.extend(self.staking.validate())
        errors.extend(self.quality.validate())
        errors.extend(self.limits.validate())

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CapabilityManifest:
        """Deserialize from dictionary."""
        d = dict(data)
        # Unpack nested configs
        if "pricing" in d and isinstance(d["pricing"], dict):
            d["pricing"] = PricingConfig(**d["pricing"])
        if "staking" in d and isinstance(d["staking"], dict):
            d["staking"] = StakingConfig(**d["staking"])
        if "quality" in d and isinstance(d["quality"], dict):
            d["quality"] = QualityPolicy(**d["quality"])
        if "limits" in d and isinstance(d["limits"], dict):
            d["limits"] = ExecutionLimits(**d["limits"])
        return cls(**d)

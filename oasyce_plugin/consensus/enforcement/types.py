"""
Enforcement types — data models for fingerprint scanning, infringement detection, and bounty hunting.

All monetary values in integer units (1 OAS = 10^8 units).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class InfringementType(str, Enum):
    UNAUTHORIZED_DISTRIBUTION = "unauthorized_distribution"
    CONTENT_TAMPERING = "content_tampering"
    LICENSE_VIOLATION = "license_violation"
    ATTRIBUTION_MISSING = "attribution_missing"


class EvidenceStatus(str, Enum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class DisputeVerdict(str, Enum):
    GUILTY = "guilty"
    INNOCENT = "innocent"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class SeverityLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Bounty reward rates in basis points (out of 10000)
BOUNTY_REWARD_BPS: Dict[str, int] = {
    "low": 500,        # 5% of damages
    "medium": 1000,    # 10%
    "high": 2000,      # 20%
    "critical": 3000,  # 30%
}

# False report slash rate in basis points
FALSE_REPORT_SLASH_BPS: int = 200  # 2% of reporter's stake


@dataclass(frozen=True)
class FingerprintResult:
    """Result of scanning content for fingerprints/watermarks."""
    fingerprint: str          # hex-encoded fingerprint hash
    content_hash: str         # SHA-256 of original content
    content_size: int         # bytes
    watermark_found: bool
    watermark_data: str = ""  # extracted watermark payload
    similarity_score: int = 0  # 0-10000 basis points (10000 = exact match)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScanResult:
    """Result of scanning a platform for content."""
    platform: str             # e.g. "github", "twitter", "zhihu"
    url: str                  # where the content was found
    content_hash: str         # SHA-256 of found content
    fingerprint: str          # extracted fingerprint
    similarity_score: int     # 0-10000 basis points
    title: str = ""
    author: str = ""
    timestamp: int = 0        # unix timestamp when content was found
    raw_snippet: str = ""     # first 500 chars of content
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InfringementReport:
    """A detected infringement case."""
    report_id: str
    asset_id: str
    infringement_type: InfringementType
    severity: SeverityLevel
    scan_result: ScanResult
    similarity_score: int     # 0-10000 basis points
    damages_estimate: int     # integer units (OAS)
    description: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time()))


@dataclass(frozen=True)
class Evidence:
    """Evidence submitted by a bounty hunter."""
    asset_id: str
    reporter: str             # reporter's public key / address
    infringement_type: InfringementType
    platform: str
    url: str
    content_hash: str
    fingerprint: str
    similarity_score: int     # 0-10000 basis points
    description: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time()))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BountyInfo:
    """Bounty information for an asset."""
    asset_id: str
    total_bounty_pool: int    # integer units (OAS)
    active_cases: int
    resolved_cases: int
    total_paid_out: int       # integer units (OAS)
    reward_rates: Dict[str, int] = field(default_factory=lambda: dict(BOUNTY_REWARD_BPS))


@dataclass
class EnforcementCase:
    """An active enforcement case."""
    case_id: str
    dispute_id: str
    asset_id: str
    reporter: str
    evidence: Evidence
    status: EvidenceStatus = EvidenceStatus.PENDING
    verdict: Optional[DisputeVerdict] = None
    bounty_amount: int = 0    # integer units (OAS)
    created_at: int = field(default_factory=lambda: int(time.time()))
    resolved_at: Optional[int] = None
    damages: int = 0          # integer units (OAS)

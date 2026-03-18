"""
Bounty Hunter — submit evidence, claim bounties, manage enforcement cases.

Rewards honest reporters and slashes false reports.
All amounts in integer units (1 OAS = 10^8 units).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional

from oasyce_plugin.consensus.enforcement.types import (
    BountyInfo,
    BOUNTY_REWARD_BPS,
    DisputeVerdict,
    EnforcementCase,
    Evidence,
    EvidenceStatus,
    FALSE_REPORT_SLASH_BPS,
    InfringementType,
    SeverityLevel,
)
from oasyce_plugin.consensus.enforcement.infringement_detector import (
    InfringementDetector,
)
from oasyce_plugin.consensus.enforcement.fingerprint_scanner import (
    FingerprintScanner,
    INFRINGEMENT_THRESHOLD,
)
from oasyce_plugin.consensus.core.types import apply_rate_bps, to_units


def _generate_dispute_id(asset_id: str, reporter: str, url: str, ts: int) -> str:
    """Generate a unique dispute ID."""
    raw = f"{asset_id}:{reporter}:{url}:{ts}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _generate_case_id(dispute_id: str) -> str:
    """Generate a case ID from dispute ID."""
    raw = f"case:{dispute_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


class BountyHunter:
    """Manages bounty submissions, verification, and payouts.

    Integrates with FingerprintScanner and InfringementDetector
    to verify evidence before creating enforcement cases.
    """

    def __init__(
        self,
        scanner: FingerprintScanner,
        detector: InfringementDetector,
    ) -> None:
        self.scanner = scanner
        self.detector = detector
        # Active cases: case_id -> EnforcementCase
        self._cases: Dict[str, EnforcementCase] = {}
        # Dispute -> case mapping
        self._dispute_to_case: Dict[str, str] = {}
        # Bounty pools: asset_id -> total pool (integer units)
        self._bounty_pools: Dict[str, int] = {}
        # Total paid out: asset_id -> amount
        self._paid_out: Dict[str, int] = {}
        # Reporter stakes: reporter -> staked amount (for false report slashing)
        self._reporter_stakes: Dict[str, int] = {}

    def set_bounty_pool(self, asset_id: str, amount: int) -> None:
        """Set the bounty pool for an asset."""
        self._bounty_pools[asset_id] = amount

    def set_reporter_stake(self, reporter: str, amount: int) -> None:
        """Set the stake for a reporter (for false report slashing)."""
        self._reporter_stakes[reporter] = amount

    def submit_evidence(self, asset_id: str, evidence: Evidence) -> str:
        """Submit infringement evidence and create an enforcement case.

        Returns the dispute_id if evidence passes initial verification.
        Raises ValueError if evidence is insufficient.
        """
        # Validate evidence
        if not evidence.asset_id:
            raise ValueError("Evidence must include asset_id")
        if not evidence.url:
            raise ValueError("Evidence must include URL")
        if not evidence.content_hash:
            raise ValueError("Evidence must include content_hash")
        if not evidence.reporter:
            raise ValueError("Evidence must include reporter address")
        if evidence.timestamp <= 0:
            raise ValueError("Evidence must include valid timestamp")

        # Verify the fingerprint matches the registered asset
        registered_fp = self.scanner._registry.get(asset_id)
        if registered_fp is None:
            raise ValueError(f"Asset {asset_id} not registered for monitoring")

        # Check similarity
        similarity = self.scanner.compare_fingerprints(
            registered_fp, evidence.fingerprint,
        )
        if similarity < INFRINGEMENT_THRESHOLD:
            raise ValueError(
                f"Similarity too low ({similarity / 100:.1f}%) — "
                f"minimum {INFRINGEMENT_THRESHOLD / 100:.1f}% required"
            )

        # Check for duplicate submissions
        for case in self._cases.values():
            if (case.asset_id == asset_id and
                    case.evidence.url == evidence.url and
                    case.status not in (EvidenceStatus.REJECTED, EvidenceStatus.RESOLVED)):
                raise ValueError(
                    f"Duplicate submission — case {case.case_id} already exists"
                )

        # Create dispute and case
        ts = evidence.timestamp or int(time.time())
        dispute_id = _generate_dispute_id(asset_id, evidence.reporter, evidence.url, ts)
        case_id = _generate_case_id(dispute_id)

        case = EnforcementCase(
            case_id=case_id,
            dispute_id=dispute_id,
            asset_id=asset_id,
            reporter=evidence.reporter,
            evidence=evidence,
            status=EvidenceStatus.PENDING,
        )

        self._cases[case_id] = case
        self._dispute_to_case[dispute_id] = case_id

        return dispute_id

    def review_case(self, dispute_id: str) -> Dict[str, Any]:
        """Move a case to under_review status and perform automated checks."""
        case_id = self._dispute_to_case.get(dispute_id)
        if case_id is None:
            return {"ok": False, "error": "dispute not found"}

        case = self._cases[case_id]
        if case.status != EvidenceStatus.PENDING:
            return {"ok": False, "error": f"case is {case.status.value}, not pending"}

        case.status = EvidenceStatus.UNDER_REVIEW

        # Re-verify similarity
        registered_fp = self.scanner._registry.get(case.asset_id)
        if registered_fp is None:
            case.status = EvidenceStatus.REJECTED
            return {"ok": False, "error": "asset no longer registered"}

        similarity = self.scanner.compare_fingerprints(
            registered_fp, case.evidence.fingerprint,
        )

        return {
            "ok": True,
            "case_id": case_id,
            "dispute_id": dispute_id,
            "similarity": similarity,
            "status": case.status.value,
        }

    def resolve_case(
        self,
        dispute_id: str,
        verdict: DisputeVerdict,
        damages: int = 0,
    ) -> Dict[str, Any]:
        """Resolve a case with a verdict.

        If guilty: calculates bounty and marks for payout.
        If innocent/insufficient: may slash reporter for false report.
        """
        case_id = self._dispute_to_case.get(dispute_id)
        if case_id is None:
            return {"ok": False, "error": "dispute not found"}

        case = self._cases[case_id]
        if case.status == EvidenceStatus.RESOLVED:
            return {"ok": False, "error": "case already resolved"}

        case.verdict = verdict
        case.resolved_at = int(time.time())
        case.damages = damages

        result: Dict[str, Any] = {
            "ok": True,
            "case_id": case_id,
            "dispute_id": dispute_id,
            "verdict": verdict.value,
        }

        if verdict == DisputeVerdict.GUILTY:
            case.status = EvidenceStatus.VERIFIED
            # Calculate bounty based on severity
            severity = self._assess_severity(case)
            bounty_rate = BOUNTY_REWARD_BPS.get(severity.value, 500)
            bounty = apply_rate_bps(damages, bounty_rate) if damages > 0 else 0
            case.bounty_amount = bounty
            result["bounty_amount"] = bounty
            result["severity"] = severity.value
        else:
            case.status = EvidenceStatus.REJECTED
            # Slash reporter for false report
            reporter_stake = self._reporter_stakes.get(case.reporter, 0)
            slash_amount = apply_rate_bps(reporter_stake, FALSE_REPORT_SLASH_BPS)
            result["reporter_slashed"] = slash_amount
            result["reason"] = "false_report"

        case.status = EvidenceStatus.RESOLVED
        return result

    def claim_bounty(self, dispute_id: str, verdict: str = "") -> int:
        """Claim bounty after a guilty verdict.

        Returns the bounty amount in integer units.
        Raises ValueError if not eligible.
        """
        case_id = self._dispute_to_case.get(dispute_id)
        if case_id is None:
            raise ValueError("Dispute not found")

        case = self._cases[case_id]

        if case.verdict != DisputeVerdict.GUILTY:
            raise ValueError(
                f"Cannot claim bounty — verdict is "
                f"{case.verdict.value if case.verdict else 'pending'}"
            )

        if case.bounty_amount <= 0:
            raise ValueError("No bounty available for this case")

        # Check bounty pool
        pool = self._bounty_pools.get(case.asset_id, 0)
        payout = min(case.bounty_amount, pool)

        if payout > 0:
            self._bounty_pools[case.asset_id] = pool - payout
            self._paid_out[case.asset_id] = (
                self._paid_out.get(case.asset_id, 0) + payout
            )

        # Zero out to prevent double-claim
        case.bounty_amount = 0

        return payout

    def get_bounty_info(self, asset_id: str) -> BountyInfo:
        """Get bounty information for an asset."""
        active = sum(
            1 for c in self._cases.values()
            if c.asset_id == asset_id and c.status not in (
                EvidenceStatus.RESOLVED, EvidenceStatus.REJECTED,
            )
        )
        resolved = sum(
            1 for c in self._cases.values()
            if c.asset_id == asset_id and c.status == EvidenceStatus.RESOLVED
        )
        return BountyInfo(
            asset_id=asset_id,
            total_bounty_pool=self._bounty_pools.get(asset_id, 0),
            active_cases=active,
            resolved_cases=resolved,
            total_paid_out=self._paid_out.get(asset_id, 0),
        )

    def get_case(self, dispute_id: str) -> Optional[EnforcementCase]:
        """Get a case by dispute_id."""
        case_id = self._dispute_to_case.get(dispute_id)
        if case_id is None:
            return None
        return self._cases.get(case_id)

    def list_cases(
        self,
        status: Optional[EvidenceStatus] = None,
        asset_id: Optional[str] = None,
        reporter: Optional[str] = None,
    ) -> List[EnforcementCase]:
        """List enforcement cases with optional filters."""
        cases = list(self._cases.values())
        if status is not None:
            cases = [c for c in cases if c.status == status]
        if asset_id is not None:
            cases = [c for c in cases if c.asset_id == asset_id]
        if reporter is not None:
            cases = [c for c in cases if c.reporter == reporter]
        return sorted(cases, key=lambda c: c.created_at, reverse=True)

    def _assess_severity(self, case: EnforcementCase) -> SeverityLevel:
        """Assess severity of an enforcement case."""
        similarity = self.scanner.compare_fingerprints(
            self.scanner._registry.get(case.asset_id, ""),
            case.evidence.fingerprint,
        )
        if similarity >= 9500:
            return SeverityLevel.CRITICAL
        if similarity >= 8000:
            return SeverityLevel.HIGH
        if similarity >= 5000:
            return SeverityLevel.MEDIUM
        return SeverityLevel.LOW

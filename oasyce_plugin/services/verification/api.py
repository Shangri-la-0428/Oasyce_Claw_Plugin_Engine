"""
PoPC Verification API — FastAPI Service

Exposes the verification engine as HTTP endpoints for the Oasis app
and external validators to submit OTP payloads for verification.

Endpoints:
  POST /api/v1/verify          — Submit OTP payload for verification
  GET  /api/v1/verify/{id}     — Check verification status by asset ID
  GET  /api/v1/health          — Service health check
  GET  /api/v1/stats           — Verification statistics
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .engine import VerificationEngine
from .models import (
    CaptureSource,
    VerificationReport,
    VerificationStatus,
    VerifyRequest,
    VerifyResponse,
)

# ──────────────────────────────────────────────
# App factory
# ──────────────────────────────────────────────

def create_app(node_id: str = "Oasyce_Verification_Node_001") -> FastAPI:
    """Create and configure the FastAPI application."""
    
    app = FastAPI(
        title="Oasyce PoPC Verification Service",
        description=(
            "Proof of Physical Capture verification node. "
            "Validates OTP (Oasis Truth Protocol) payloads from the Oasis app."
        ),
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Tighten in production
        allow_methods=["*"],
        allow_headers=["*"],
    )

    engine = VerificationEngine(node_id=node_id)
    
    # In-memory store for verification results (replace with DB in production)
    verification_store: Dict[str, VerificationReport] = {}
    stats = {
        "total_requests": 0,
        "verified": 0,
        "rejected": 0,
        "disputed": 0,
        "started_at": int(time.time()),
    }

    # ──────────────────────────────────────────────
    # Routes
    # ──────────────────────────────────────────────

    @app.post("/api/v1/verify", response_model=VerifyResponse)
    async def verify_otp(request: VerifyRequest) -> VerifyResponse:
        """Submit an OTP payload for verification.
        
        The verification engine runs the full pipeline:
        1. Device attestation check
        2. Signature verification
        3. Sensor entropy analysis (for in-app captures)
        4. Temporal consistency check
        5. Geo plausibility check
        6. Capture source trust classification
        
        Returns a detailed verification report with individual check scores.
        """
        stats["total_requests"] += 1

        # Run verification
        report = engine.verify(request.otp)

        # Generate asset ID if verified
        if report.status == VerificationStatus.VERIFIED:
            asset_id = _generate_asset_id(request.otp.content_hash, request.otp.capture_timestamp)
            report.asset_id = asset_id
            stats["verified"] += 1
        elif report.status == VerificationStatus.REJECTED:
            stats["rejected"] += 1
        else:
            stats["disputed"] += 1

        # Store result
        if report.asset_id:
            verification_store[report.asset_id] = report

        return VerifyResponse(
            success=report.status == VerificationStatus.VERIFIED,
            report=report,
            message=_build_message(report),
        )

    @app.get("/api/v1/verify/{asset_id}")
    async def get_verification(asset_id: str) -> Dict[str, Any]:
        """Look up a verification report by asset ID."""
        report = verification_store.get(asset_id)
        if not report:
            raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
        return {"asset_id": asset_id, "report": report.model_dump()}

    @app.get("/api/v1/health")
    async def health() -> Dict[str, Any]:
        """Service health check."""
        return {
            "status": "healthy",
            "node_id": node_id,
            "uptime_s": int(time.time()) - stats["started_at"],
            "version": "1.0.0",
        }

    @app.get("/api/v1/stats")
    async def get_stats() -> Dict[str, Any]:
        """Verification statistics."""
        return {
            **stats,
            "uptime_s": int(time.time()) - stats["started_at"],
            "store_size": len(verification_store),
            "pass_rate": (
                round(stats["verified"] / stats["total_requests"] * 100, 1)
                if stats["total_requests"] > 0
                else 0
            ),
        }

    return app


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _generate_asset_id(content_hash: str, timestamp: int) -> str:
    """Generate deterministic asset ID from content hash + timestamp."""
    raw = f"{content_hash}:{timestamp}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:8].upper()
    return f"OAS_{digest}"


def _build_message(report: VerificationReport) -> str:
    """Build a human-readable message from the verification report."""
    if report.status == VerificationStatus.VERIFIED:
        msg = f"✅ Verified with score {report.overall_score:.2f}"
        if report.can_be_public:
            msg += " — eligible for public pool"
        else:
            msg += " — restricted (private/friends only)"
        return msg
    elif report.status == VerificationStatus.DISPUTED:
        return f"⚠️ Disputed (score {report.overall_score:.2f}) — manual review required"
    else:
        return f"❌ Rejected (score {report.overall_score:.2f}): {report.rejection_reason or 'Unknown'}"


# ──────────────────────────────────────────────
# Default app instance
# ──────────────────────────────────────────────

app = create_app()

"""
PoPC Verification Service — Data Models

Defines the Pydantic models for the PoPC (Proof of Physical Capture) verification
pipeline. These models represent the OTP (Oasis Truth Protocol) data packet that
flows from device → verification node → registry.

Architecture:
  Device captures → signs OTP packet → submits to /verify endpoint
  Verification node checks: certificate chain + ECDSA signature + gyro vector + timestamp
  Returns: VERIFIED | REJECTED | DISPUTED with detailed attestation report
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class VerificationStatus(str, Enum):
    """Asset verification state machine."""

    PROOF_PENDING = "PROOF_PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    DISPUTED = "DISPUTED"


class DeviceAttestation(BaseModel):
    """Hardware-level device identity and TEE attestation."""

    device_id: str = Field(
        ..., description="Unique device identifier (e.g., iOS IDFV or Android ID)"
    )
    platform: str = Field(..., pattern=r"^(ios|android)$", description="Device platform")
    tee_type: str = Field(..., description="TEE type: secure_enclave (iOS) or keystore (Android)")
    certificate_chain: List[str] = Field(
        default_factory=list, description="X.509 certificate chain from device TEE, base64 encoded"
    )
    attestation_token: Optional[str] = Field(
        None, description="Platform attestation token (Apple DeviceCheck / Android SafetyNet)"
    )


class SensorVector(BaseModel):
    """Gyroscope micro-jitter vector — anti-screen-capture defense.

    Real physical cameras produce chaotic micro-vibrations during capture.
    Screen recordings or injected images have unnaturally smooth or periodic patterns.
    We analyze the jitter entropy to distinguish physical capture from replay.
    """

    gyro_x: List[float] = Field(
        ..., min_length=10, description="Gyroscope X-axis samples during capture"
    )
    gyro_y: List[float] = Field(
        ..., min_length=10, description="Gyroscope Y-axis samples during capture"
    )
    gyro_z: List[float] = Field(
        ..., min_length=10, description="Gyroscope Z-axis samples during capture"
    )
    accel_magnitude: Optional[List[float]] = Field(
        None, description="Accelerometer magnitude samples"
    )
    sample_rate_hz: float = Field(default=100.0, gt=0, description="Sensor sampling rate")
    capture_duration_ms: int = Field(..., gt=0, description="Duration of sensor recording in ms")


class GeoProof(BaseModel):
    """GPS + timestamp proof of location during capture."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude_m: Optional[float] = None
    accuracy_m: float = Field(..., gt=0, le=1000, description="GPS accuracy in meters")
    timestamp: int = Field(..., description="Unix timestamp at capture moment")
    timezone_offset: Optional[int] = Field(None, description="UTC offset in minutes")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: int) -> int:
        now = int(time.time())
        # Reject timestamps from the future or older than 24 hours
        if v > now + 60:
            raise ValueError("Timestamp is in the future")
        if v < now - 86400:
            raise ValueError("Timestamp is older than 24 hours")
        return v


class CaptureSource(str, Enum):
    """How the data was captured — determines trust level."""

    IN_APP_CAMERA = "in_app_camera"  # Captured via Oasis app's native camera → full trust
    ALBUM_IMPORT = "album_import"  # Imported from photo album → restricted (no public)
    EXTERNAL_UPLOAD = "external_upload"  # Uploaded from desktop → lowest trust


class OTPPayload(BaseModel):
    """Oasis Truth Protocol (OTP) packet — the fundamental unit of truth.

    This is what the Oasis app submits when a user captures content.
    It bundles the content hash with physical proofs for verification.
    """

    # Content identity
    content_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$", description="SHA-256 of raw content")
    content_type: str = Field(..., pattern=r"^(image|video|audio|document)$")
    file_size_bytes: int = Field(..., gt=0)

    # Capture provenance
    capture_source: CaptureSource
    capture_timestamp: int = Field(..., description="Unix timestamp of capture")

    # Physical proofs
    device: DeviceAttestation
    geo: GeoProof
    sensor: Optional[SensorVector] = Field(None, description="Required for in_app_camera captures")

    # Cryptographic binding
    signature: str = Field(
        ..., description="ECDSA signature over (content_hash + timestamp + geo_hash)"
    )
    public_key: str = Field(..., description="Device public key (from TEE)")

    # Protocol metadata
    otp_version: str = Field(default="1.0.0")
    app_version: str = Field(..., description="Oasis app version that generated this packet")

    @field_validator("capture_source")
    @classmethod
    def validate_sensor_for_camera(cls, v: CaptureSource, info) -> CaptureSource:
        # Note: sensor requirement is checked at the service level, not here
        return v


class VerificationCheck(BaseModel):
    """Individual verification check result."""

    check_name: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    details: str = ""


class VerificationReport(BaseModel):
    """Complete verification attestation report."""

    asset_id: Optional[str] = Field(None, description="Assigned asset ID if verified")
    status: VerificationStatus
    overall_score: float = Field(ge=0.0, le=1.0)
    checks: List[VerificationCheck] = []

    # Trust metadata
    trust_level: str = Field(default="unknown", description="FULL | RESTRICTED | UNTRUSTED")
    can_be_public: bool = Field(
        default=False, description="Whether this asset can enter the public pool"
    )

    # Timestamps
    submitted_at: int = Field(default_factory=lambda: int(time.time()))
    verified_at: Optional[int] = None

    # Verification node identity
    verifier_node_id: str = Field(default="Oasyce_Verification_Node_001")

    # Detailed rejection reason (if rejected)
    rejection_reason: Optional[str] = None


class VerifyRequest(BaseModel):
    """API request to verify an OTP payload."""

    otp: OTPPayload
    owner: str = Field(..., min_length=1, description="Asset owner identifier")
    tags: List[str] = Field(default_factory=list)


class VerifyResponse(BaseModel):
    """API response from verification."""

    success: bool
    report: VerificationReport
    message: str = ""

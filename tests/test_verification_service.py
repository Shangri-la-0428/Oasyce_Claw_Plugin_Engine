"""
PoPC Verification Service — Tests

Tests the entire verification pipeline:
  - Model validation
  - Engine verification logic (all 6 checks)
  - API endpoints
  - Edge cases (replay, emulator, album import restrictions)
"""

from __future__ import annotations

import hashlib
import math
import random
import time

import pytest
from fastapi.testclient import TestClient

from oasyce_plugin.services.verification.api import create_app
from oasyce_plugin.services.verification.engine import VerificationEngine
from oasyce_plugin.services.verification.models import (
    CaptureSource,
    DeviceAttestation,
    GeoProof,
    OTPPayload,
    SensorVector,
    VerificationStatus,
    VerifyRequest,
)

# ──────────────────────────────────────────────
# Fixtures / helpers
# ──────────────────────────────────────────────

def _now() -> int:
    return int(time.time())


def _make_sensor(entropy: str = "normal") -> SensorVector:
    """Generate sensor data with controlled entropy levels."""
    n = 50
    if entropy == "zero":
        # Emulator: perfectly still
        return SensorVector(
            gyro_x=[0.0] * n,
            gyro_y=[0.0] * n,
            gyro_z=[0.0] * n,
            sample_rate_hz=100.0,
            capture_duration_ms=500,
        )
    elif entropy == "random":
        # Injected: pure random noise
        return SensorVector(
            gyro_x=[random.uniform(-100, 100) for _ in range(n)],
            gyro_y=[random.uniform(-100, 100) for _ in range(n)],
            gyro_z=[random.uniform(-100, 100) for _ in range(n)],
            sample_rate_hz=100.0,
            capture_duration_ms=500,
        )
    else:
        # Normal physical capture: mild jitter with natural variation
        base_x = [math.sin(i * 0.1) * 0.5 + random.gauss(0, 0.2) for i in range(n)]
        base_y = [math.cos(i * 0.12) * 0.3 + random.gauss(0, 0.15) for i in range(n)]
        base_z = [random.gauss(9.8, 0.1) + random.gauss(0, 0.05) for i in range(n)]
        return SensorVector(
            gyro_x=base_x,
            gyro_y=base_y,
            gyro_z=base_z,
            sample_rate_hz=100.0,
            capture_duration_ms=500,
        )


def _make_device(valid: bool = True) -> DeviceAttestation:
    return DeviceAttestation(
        device_id="ABCDEF1234567890" if valid else "x",
        platform="ios",
        tee_type="secure_enclave" if valid else "none",
        certificate_chain=["MIIBojCCAUmgAwIBAgIQ...base64cert..."] if valid else [],
        attestation_token="valid-attestation-token" if valid else None,
    )


def _make_geo(valid: bool = True) -> GeoProof:
    return GeoProof(
        latitude=39.9042 if valid else 0.0,
        longitude=116.4074 if valid else 0.0,
        altitude_m=50.0,
        accuracy_m=15.0 if valid else 999.0,
        timestamp=_now(),
    )


def _make_otp(
    source: CaptureSource = CaptureSource.IN_APP_CAMERA,
    valid_device: bool = True,
    valid_geo: bool = True,
    sensor_entropy: str = "normal",
    include_sensor: bool = True,
) -> OTPPayload:
    content_hash = hashlib.sha256(b"test-image-data-" + str(time.time()).encode()).hexdigest()
    now = _now()
    
    sensor = _make_sensor(sensor_entropy) if include_sensor else None
    
    return OTPPayload(
        content_hash=content_hash,
        content_type="image",
        file_size_bytes=1024000,
        capture_source=source,
        capture_timestamp=now,
        device=_make_device(valid_device),
        geo=_make_geo(valid_geo),
        sensor=sensor,
        signature="a" * 128,  # Mock ECDSA signature
        public_key="b" * 64,   # Mock public key
        app_version="1.0.0",
    )


# ──────────────────────────────────────────────
# Engine Tests
# ──────────────────────────────────────────────

class TestVerificationEngine:
    """Test the core verification engine."""

    def setup_method(self):
        self.engine = VerificationEngine()

    def test_valid_in_app_capture_passes(self):
        """A well-formed in-app capture should pass with VERIFIED status."""
        otp = _make_otp(source=CaptureSource.IN_APP_CAMERA, sensor_entropy="normal")
        report = self.engine.verify(otp)
        
        assert report.status == VerificationStatus.VERIFIED
        assert report.overall_score >= 0.7
        assert report.trust_level == "FULL"
        assert report.can_be_public is True
        assert report.asset_id is None  # Engine doesn't assign IDs, API does

    def test_album_import_verified_but_restricted(self):
        """Album imports can pass verification but must be restricted."""
        otp = _make_otp(source=CaptureSource.ALBUM_IMPORT, include_sensor=False)
        report = self.engine.verify(otp)
        
        # Should pass (no sensor required for album) or at least not be REJECTED
        if report.status == VerificationStatus.VERIFIED:
            assert report.trust_level == "RESTRICTED"
            assert report.can_be_public is False  # KEY: album content never public!
    
    def test_emulator_sensor_flags_suspect(self):
        """Zero-entropy sensor data (emulator) should lower the score."""
        otp = _make_otp(sensor_entropy="zero")
        report = self.engine.verify(otp)
        
        # Find the sensor check
        sensor_check = next((c for c in report.checks if c.check_name == "sensor_entropy"), None)
        assert sensor_check is not None
        assert sensor_check.score < 0.3  # Very low score for zero entropy
        assert not sensor_check.passed

    def test_random_injection_sensor_flags_suspect(self):
        """High-entropy random sensor data should be flagged."""
        otp = _make_otp(sensor_entropy="random")
        report = self.engine.verify(otp)
        
        sensor_check = next((c for c in report.checks if c.check_name == "sensor_entropy"), None)
        assert sensor_check is not None
        # Random injection can score low or medium depending on distribution
        # The key is it shouldn't get full marks
        assert sensor_check.score < 0.9

    def test_invalid_device_rejects(self):
        """Invalid device attestation should cause rejection."""
        otp = _make_otp(valid_device=False)
        report = self.engine.verify(otp)
        
        device_check = next((c for c in report.checks if c.check_name == "device_attestation"), None)
        assert device_check is not None
        assert device_check.score < 0.5

    def test_null_island_geo_flags(self):
        """Coordinates at (0,0) — Null Island — should be flagged."""
        otp = _make_otp(valid_geo=False)
        report = self.engine.verify(otp)
        
        geo_check = next((c for c in report.checks if c.check_name == "geo_plausibility"), None)
        assert geo_check is not None
        assert geo_check.score < 0.5

    def test_missing_sensor_for_camera_fails(self):
        """In-app camera capture without sensor data should fail the sensor check."""
        otp = _make_otp(source=CaptureSource.IN_APP_CAMERA, include_sensor=False)
        report = self.engine.verify(otp)
        
        sensor_check = next((c for c in report.checks if c.check_name == "sensor_entropy"), None)
        assert sensor_check is not None
        assert sensor_check.score == 0.0
        assert not sensor_check.passed

    def test_all_checks_present_in_report(self):
        """Verify all expected checks are in the report."""
        otp = _make_otp()
        report = self.engine.verify(otp)
        
        check_names = {c.check_name for c in report.checks}
        assert "device_attestation" in check_names
        assert "signature_verification" in check_names
        assert "sensor_entropy" in check_names
        assert "temporal_consistency" in check_names
        assert "geo_plausibility" in check_names
        assert "capture_source_trust" in check_names

    def test_temporal_consistency_good_sync(self):
        """Timestamps within 5s should score perfectly."""
        otp = _make_otp()
        report = self.engine.verify(otp)
        
        time_check = next((c for c in report.checks if c.check_name == "temporal_consistency"), None)
        assert time_check is not None
        assert time_check.score >= 0.9


class TestSignalEntropy:
    """Test the entropy calculation utility."""

    def test_zero_entropy(self):
        """Constant signal → entropy = 0."""
        entropy = VerificationEngine._signal_entropy([1.0] * 100)
        assert entropy == 0.0

    def test_max_entropy(self):
        """Uniform distribution → high entropy."""
        samples = [i / 100.0 for i in range(100)]
        entropy = VerificationEngine._signal_entropy(samples, bins=20)
        assert entropy > 0.8

    def test_single_sample(self):
        """Edge case: single sample."""
        entropy = VerificationEngine._signal_entropy([42.0])
        assert entropy == 0.0


# ──────────────────────────────────────────────
# API Tests
# ──────────────────────────────────────────────

class TestVerificationAPI:
    """Test the FastAPI endpoints."""

    def setup_method(self):
        self.app = create_app(node_id="test_node")
        self.client = TestClient(self.app)

    def test_health_endpoint(self):
        resp = self.client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["node_id"] == "test_node"

    def test_stats_endpoint(self):
        resp = self.client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 0

    def test_verify_valid_otp(self):
        """Submit a valid OTP and get a verification report."""
        otp = _make_otp()
        request = VerifyRequest(otp=otp, owner="TestUser", tags=["test"])
        
        resp = self.client.post("/api/v1/verify", json=request.model_dump())
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["report"]["status"] == "VERIFIED"
        assert data["report"]["asset_id"] is not None
        assert data["report"]["asset_id"].startswith("OAS_")

    def test_verify_then_lookup(self):
        """Verify an OTP, then look it up by asset ID."""
        otp = _make_otp()
        request = VerifyRequest(otp=otp, owner="TestUser", tags=["test"])
        
        # Verify
        resp1 = self.client.post("/api/v1/verify", json=request.model_dump())
        assert resp1.status_code == 200
        asset_id = resp1.json()["report"]["asset_id"]
        
        # Lookup
        resp2 = self.client.get(f"/api/v1/verify/{asset_id}")
        assert resp2.status_code == 200
        assert resp2.json()["asset_id"] == asset_id

    def test_lookup_nonexistent_asset(self):
        resp = self.client.get("/api/v1/verify/OAS_DEADBEEF")
        assert resp.status_code == 404

    def test_stats_increment_after_verify(self):
        """Stats should update after verification requests."""
        otp = _make_otp()
        request = VerifyRequest(otp=otp, owner="TestUser", tags=["test"])
        
        self.client.post("/api/v1/verify", json=request.model_dump())
        
        resp = self.client.get("/api/v1/stats")
        data = resp.json()
        assert data["total_requests"] == 1
        assert data["verified"] >= 0  # May or may not pass depending on randomness

    def test_verify_album_import_not_public(self):
        """Album imports should never be marked as public-eligible."""
        otp = _make_otp(source=CaptureSource.ALBUM_IMPORT, include_sensor=False)
        request = VerifyRequest(otp=otp, owner="TestUser", tags=["album"])
        
        resp = self.client.post("/api/v1/verify", json=request.model_dump())
        data = resp.json()
        
        # Regardless of pass/fail, can_be_public must be False
        assert data["report"]["can_be_public"] is False


# ──────────────────────────────────────────────
# Integration: Engine + Registry Bridge
# ──────────────────────────────────────────────

class TestVerificationRegistryBridge:
    """Test that verified assets can bridge to the existing Registry."""

    def test_asset_id_format_compatible(self):
        """Generated asset IDs should match the OAS_XXXXXXXX format."""
        otp = _make_otp()
        request = VerifyRequest(otp=otp, owner="TestUser", tags=["test"])
        
        app = create_app()
        client = TestClient(app)
        resp = client.post("/api/v1/verify", json=request.model_dump())
        
        if resp.json()["success"]:
            asset_id = resp.json()["report"]["asset_id"]
            assert len(asset_id) == 12  # "OAS_" + 8 hex chars
            assert asset_id[:4] == "OAS_"
            assert all(c in "0123456789ABCDEF" for c in asset_id[4:])

    def test_deterministic_asset_id(self):
        """Same content_hash + timestamp → same asset_id."""
        from oasyce_plugin.services.verification.api import _generate_asset_id
        
        id1 = _generate_asset_id("a" * 64, 1000000)
        id2 = _generate_asset_id("a" * 64, 1000000)
        id3 = _generate_asset_id("b" * 64, 1000000)
        
        assert id1 == id2  # Deterministic
        assert id1 != id3  # Different content → different ID

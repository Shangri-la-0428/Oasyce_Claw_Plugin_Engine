"""
PoPC Verification Engine

Implements the multi-layer verification pipeline:
  L1: Device certificate chain validation (TEE attestation)
  L2: Cryptographic signature verification (ECDSA over content+timestamp+geo)
  L3: Sensor entropy analysis (micro-jitter chaos detection)
  L4: Temporal & spatial consistency checks
  L5: Capture source trust classification

Design principle: fail-open for individual checks (score-based),
but fail-closed for the overall verdict (threshold-based).
"""

from __future__ import annotations

import hashlib
import hmac
import math
import statistics
import time
from typing import List, Optional, Tuple

from .models import (
    CaptureSource,
    GeoProof,
    OTPPayload,
    SensorVector,
    VerificationCheck,
    VerificationReport,
    VerificationStatus,
)


# Thresholds
OVERALL_PASS_THRESHOLD = 0.70  # Minimum overall score to pass verification
SENSOR_ENTROPY_MIN = 0.3  # Minimum normalized entropy for micro-jitter
TIMESTAMP_DRIFT_MAX_S = 300  # Max allowed drift between capture and geo timestamps
GEO_ACCURACY_IDEAL_M = 50.0  # Ideal GPS accuracy
CERTIFICATE_CHAIN_MIN_LENGTH = 1  # Minimum cert chain depth


class VerificationEngine:
    """Stateless verification engine. Each call processes one OTP payload."""

    def __init__(self, node_id: str = "Oasyce_Verification_Node_001"):
        self.node_id = node_id

    def verify(self, otp: OTPPayload) -> VerificationReport:
        """Run the full verification pipeline on an OTP payload.

        Returns a VerificationReport with individual check scores and overall verdict.
        """
        checks: List[VerificationCheck] = []

        # L1: Device attestation
        checks.append(self._check_device_attestation(otp))

        # L2: Signature verification
        checks.append(self._check_signature(otp))

        # L3: Sensor entropy (only for in-app captures)
        if otp.capture_source == CaptureSource.IN_APP_CAMERA:
            if otp.sensor is not None:
                checks.append(self._check_sensor_entropy(otp.sensor))
            else:
                checks.append(
                    VerificationCheck(
                        check_name="sensor_entropy",
                        passed=False,
                        score=0.0,
                        details="In-app camera capture requires sensor data",
                    )
                )

        # L4: Temporal consistency
        checks.append(self._check_temporal_consistency(otp))

        # L5: Geo plausibility
        checks.append(self._check_geo_plausibility(otp.geo))

        # L6: Capture source trust classification
        source_check = self._check_capture_source(otp.capture_source)
        checks.append(source_check)

        # Calculate overall score (weighted average)
        overall_score = self._calculate_overall_score(checks)

        # Determine verdict
        status, trust_level, can_be_public = self._determine_verdict(
            overall_score, otp.capture_source, checks
        )

        rejection_reason = None
        if status == VerificationStatus.REJECTED:
            failed = [c for c in checks if not c.passed]
            if failed:
                rejection_reason = "; ".join(f"{c.check_name}: {c.details}" for c in failed)

        return VerificationReport(
            status=status,
            overall_score=round(overall_score, 4),
            checks=checks,
            trust_level=trust_level,
            can_be_public=can_be_public,
            submitted_at=int(time.time()),
            verified_at=int(time.time()) if status == VerificationStatus.VERIFIED else None,
            verifier_node_id=self.node_id,
            rejection_reason=rejection_reason,
        )

    # ──────────────────────────────────────────────
    # Individual verification checks
    # ──────────────────────────────────────────────

    def _check_device_attestation(self, otp: OTPPayload) -> VerificationCheck:
        """L1: Validate device certificate chain and TEE attestation.

        In production, this would:
        1. Parse X.509 certs and verify chain to known Apple/Google root CAs
        2. Validate DeviceCheck / SafetyNet tokens via platform APIs
        3. Check device_id against known-compromised device list

        Current: Mock validation that checks structural integrity.
        """
        device = otp.device
        score = 0.0
        details_parts = []

        # Check certificate chain exists and has minimum depth
        if len(device.certificate_chain) >= CERTIFICATE_CHAIN_MIN_LENGTH:
            score += 0.3
            details_parts.append(f"cert_chain_depth={len(device.certificate_chain)}")
        else:
            details_parts.append("cert_chain too shallow")

        # Check TEE type matches platform
        valid_tee = {
            "ios": ["secure_enclave", "sep"],
            "android": ["keystore", "strongbox", "tee"],
        }
        if device.tee_type.lower() in valid_tee.get(device.platform, []):
            score += 0.3
            details_parts.append(f"tee_valid={device.tee_type}")
        else:
            details_parts.append(f"tee_mismatch: {device.tee_type} on {device.platform}")

        # Check attestation token exists
        if device.attestation_token:
            score += 0.2
            details_parts.append("attestation_token_present")
        else:
            score += 0.05
            details_parts.append("no_attestation_token")

        # Device ID format check
        if device.device_id and len(device.device_id) >= 8:
            score += 0.2
            details_parts.append("device_id_valid")
        else:
            details_parts.append("device_id_invalid")

        return VerificationCheck(
            check_name="device_attestation",
            passed=score >= 0.6,
            score=min(score, 1.0),
            details="; ".join(details_parts),
        )

    def _check_signature(self, otp: OTPPayload) -> VerificationCheck:
        """L2: Verify ECDSA signature over content binding.

        In production, this would:
        1. Reconstruct the signed payload: content_hash + timestamp + geo_hash
        2. Verify ECDSA signature using the device's public key
        3. Cross-check public key against the certificate chain

        Current: Mock that verifies structural integrity of signature fields.
        """
        score = 0.0
        details_parts = []

        # Check signature format (hex string, reasonable length for ECDSA)
        sig = otp.signature
        if sig and len(sig) >= 64:
            score += 0.4
            details_parts.append(f"sig_length={len(sig)}")
        else:
            details_parts.append("signature_too_short")

        # Check public key presence
        if otp.public_key and len(otp.public_key) >= 32:
            score += 0.3
            details_parts.append("pubkey_present")
        else:
            details_parts.append("pubkey_missing_or_short")

        # Verify content_hash is properly formed
        if otp.content_hash and len(otp.content_hash) == 64:
            score += 0.3
            details_parts.append("content_hash_valid")
        else:
            details_parts.append("content_hash_invalid")

        # In production: actual ECDSA verify would happen here
        # ecdsa.verify(otp.public_key, otp.signature, payload_hash)

        return VerificationCheck(
            check_name="signature_verification",
            passed=score >= 0.7,
            score=min(score, 1.0),
            details="; ".join(details_parts),
        )

    def _check_sensor_entropy(self, sensor: SensorVector) -> VerificationCheck:
        """L3: Analyze gyroscope micro-jitter entropy.

        Physical cameras produce chaotic vibration patterns during capture.
        Screen captures, emulators, or injected data have:
        - Zero variance (perfectly still)
        - Periodic patterns (emulator noise)
        - Unnaturally high variance (random injection)

        We measure Shannon entropy of the sensor signal to detect anomalies.
        """
        score = 0.0
        details_parts = []

        try:
            # Calculate per-axis statistics
            entropies = []
            for axis_name, samples in [
                ("x", sensor.gyro_x),
                ("y", sensor.gyro_y),
                ("z", sensor.gyro_z),
            ]:
                if len(samples) < 10:
                    details_parts.append(f"{axis_name}_insufficient_samples")
                    continue

                std = statistics.stdev(samples)
                entropy = self._signal_entropy(samples)
                entropies.append(entropy)
                details_parts.append(f"{axis_name}_std={std:.4f}_entropy={entropy:.4f}")

            if not entropies:
                return VerificationCheck(
                    check_name="sensor_entropy",
                    passed=False,
                    score=0.0,
                    details="Insufficient sensor data",
                )

            avg_entropy = statistics.mean(entropies)

            # Score based on entropy range
            if avg_entropy < 0.05:
                # Too still — likely emulator or static injection
                score = 0.1
                details_parts.append("SUSPECT: near-zero entropy (emulator?)")
            elif avg_entropy < SENSOR_ENTROPY_MIN:
                # Suspiciously low
                score = 0.4
                details_parts.append("LOW entropy")
            elif avg_entropy > 0.85:
                # Unnaturally high — random noise injection
                # Physical cameras don't produce uniform-distribution jitter
                score = 0.3
                details_parts.append("SUSPECT: entropy too high (random injection?)")
            else:
                # Healthy physical capture range
                score = 0.8 + (0.2 * min(avg_entropy / 0.7, 1.0))
                details_parts.append("HEALTHY entropy range")

            # Check capture duration is reasonable
            if 100 <= sensor.capture_duration_ms <= 30000:
                score = min(score + 0.05, 1.0)
            else:
                score = max(score - 0.1, 0.0)
                details_parts.append(f"unusual_duration={sensor.capture_duration_ms}ms")

        except Exception as e:
            return VerificationCheck(
                check_name="sensor_entropy",
                passed=False,
                score=0.0,
                details=f"Analysis error: {str(e)}",
            )

        return VerificationCheck(
            check_name="sensor_entropy",
            passed=score >= 0.6,
            score=round(min(score, 1.0), 4),
            details="; ".join(details_parts),
        )

    def _check_temporal_consistency(self, otp: OTPPayload) -> VerificationCheck:
        """L4: Check timestamp consistency between capture and geo proof."""
        score = 0.0
        details_parts = []

        drift = abs(otp.capture_timestamp - otp.geo.timestamp)
        details_parts.append(f"drift={drift}s")

        if drift <= 5:
            score = 1.0
            details_parts.append("excellent_sync")
        elif drift <= 30:
            score = 0.9
            details_parts.append("good_sync")
        elif drift <= TIMESTAMP_DRIFT_MAX_S:
            score = 0.7 - (0.3 * drift / TIMESTAMP_DRIFT_MAX_S)
            details_parts.append("acceptable_drift")
        else:
            score = 0.1
            details_parts.append("EXCESSIVE drift — possible replay")

        # Check freshness (how old is this submission?)
        age = int(time.time()) - otp.capture_timestamp
        details_parts.append(f"age={age}s")
        if age < 0:
            score = 0.0
            details_parts.append("FUTURE timestamp")
        elif age > 86400:
            score *= 0.5
            details_parts.append("STALE: >24h old")

        return VerificationCheck(
            check_name="temporal_consistency",
            passed=score >= 0.5,
            score=round(min(score, 1.0), 4),
            details="; ".join(details_parts),
        )

    def _check_geo_plausibility(self, geo: GeoProof) -> VerificationCheck:
        """L5: Check GPS coordinates are plausible."""
        score = 0.0
        details_parts = []

        # Basic range check (already enforced by Pydantic, but double-check)
        if -90 <= geo.latitude <= 90 and -180 <= geo.longitude <= 180:
            score += 0.4
            details_parts.append(f"coords=({geo.latitude:.4f},{geo.longitude:.4f})")
        else:
            return VerificationCheck(
                check_name="geo_plausibility",
                passed=False,
                score=0.0,
                details="Invalid coordinates",
            )

        # Check if coordinates are on land (simplified — reject 0,0 which is Atlantic Ocean)
        if abs(geo.latitude) < 0.01 and abs(geo.longitude) < 0.01:
            score = 0.1
            details_parts.append("SUSPECT: null island (0,0)")
        else:
            score += 0.2

        # GPS accuracy score
        if geo.accuracy_m <= GEO_ACCURACY_IDEAL_M:
            score += 0.3
            details_parts.append(f"accuracy={geo.accuracy_m}m (good)")
        elif geo.accuracy_m <= 200:
            score += 0.2
            details_parts.append(f"accuracy={geo.accuracy_m}m (ok)")
        else:
            score += 0.05
            details_parts.append(f"accuracy={geo.accuracy_m}m (poor)")

        # Altitude sanity (-500m to 9000m covers submarines to Everest)
        if geo.altitude_m is not None:
            if -500 <= geo.altitude_m <= 9000:
                score += 0.1
                details_parts.append(f"alt={geo.altitude_m}m")
            else:
                details_parts.append(f"SUSPECT: altitude={geo.altitude_m}m")

        return VerificationCheck(
            check_name="geo_plausibility",
            passed=score >= 0.5,
            score=round(min(score, 1.0), 4),
            details="; ".join(details_parts),
        )

    def _check_capture_source(self, source: CaptureSource) -> VerificationCheck:
        """L6: Classify trust level based on capture source."""
        trust_map = {
            CaptureSource.IN_APP_CAMERA: (1.0, "FULL trust — in-app native capture"),
            CaptureSource.ALBUM_IMPORT: (0.5, "RESTRICTED — album import, no public"),
            CaptureSource.EXTERNAL_UPLOAD: (0.3, "LOW trust — external upload"),
        }
        score, details = trust_map.get(source, (0.0, "Unknown source"))

        return VerificationCheck(
            check_name="capture_source_trust",
            passed=True,  # Always passes, but affects overall score
            score=score,
            details=details,
        )

    # ──────────────────────────────────────────────
    # Scoring & verdict
    # ──────────────────────────────────────────────

    def _calculate_overall_score(self, checks: List[VerificationCheck]) -> float:
        """Weighted average of all check scores."""
        weights = {
            "device_attestation": 0.25,
            "signature_verification": 0.25,
            "sensor_entropy": 0.20,
            "temporal_consistency": 0.15,
            "geo_plausibility": 0.10,
            "capture_source_trust": 0.05,
        }
        total_weight = 0.0
        weighted_sum = 0.0
        for check in checks:
            w = weights.get(check.check_name, 0.1)
            weighted_sum += check.score * w
            total_weight += w

        if total_weight == 0:
            return 0.0
        return weighted_sum / total_weight

    def _determine_verdict(
        self,
        overall_score: float,
        capture_source: CaptureSource,
        checks: List[VerificationCheck],
    ) -> Tuple[VerificationStatus, str, bool]:
        """Determine final verification status, trust level, and public eligibility."""

        # Hard failures — any critical check with score 0 triggers rejection
        critical_checks = {"device_attestation", "signature_verification"}
        for check in checks:
            if check.check_name in critical_checks and check.score < 0.3:
                return VerificationStatus.REJECTED, "UNTRUSTED", False

        # Score-based verdict
        if overall_score >= OVERALL_PASS_THRESHOLD:
            # Determine trust level & public eligibility
            if capture_source == CaptureSource.IN_APP_CAMERA:
                return VerificationStatus.VERIFIED, "FULL", True
            elif capture_source == CaptureSource.ALBUM_IMPORT:
                return VerificationStatus.VERIFIED, "RESTRICTED", False  # Album → never public
            else:
                return VerificationStatus.VERIFIED, "RESTRICTED", False
        elif overall_score >= 0.5:
            return VerificationStatus.DISPUTED, "RESTRICTED", False
        else:
            return VerificationStatus.REJECTED, "UNTRUSTED", False

    # ──────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────

    @staticmethod
    def _signal_entropy(samples: List[float], bins: int = 20) -> float:
        """Calculate normalized Shannon entropy of a sensor signal.

        Returns value between 0 (deterministic) and 1 (maximum entropy).
        """
        if len(samples) < 2:
            return 0.0

        # Histogram-based entropy
        min_val = min(samples)
        max_val = max(samples)
        if max_val == min_val:
            return 0.0  # All values identical

        bin_width = (max_val - min_val) / bins
        counts = [0] * bins
        for s in samples:
            idx = min(int((s - min_val) / bin_width), bins - 1)
            counts[idx] += 1

        n = len(samples)
        entropy = 0.0
        for c in counts:
            if c > 0:
                p = c / n
                entropy -= p * math.log2(p)

        # Normalize to [0, 1]
        max_entropy = math.log2(bins)
        return entropy / max_entropy if max_entropy > 0 else 0.0

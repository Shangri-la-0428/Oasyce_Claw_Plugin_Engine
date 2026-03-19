from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from oasyce.interfaces.verifier import IVerifier, VerifyResult
from oasyce.models.capture_pack import CapturePack

_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_MAX_FUTURE = timedelta(minutes=5)
_MAX_AGE = timedelta(days=30)


class MockVerifier(IVerifier):
    def verify(self, pack: CapturePack) -> VerifyResult:
        # timestamp range check
        try:
            ts = pack.parsed_timestamp()
        except (ValueError, TypeError):
            return VerifyResult(False, "invalid timestamp format")

        now = datetime.now(timezone.utc)
        if ts > now + _MAX_FUTURE:
            return VerifyResult(False, "timestamp is too far in the future")
        if ts < now - _MAX_AGE:
            return VerifyResult(False, "timestamp is older than 30 days")

        # hash format checks
        if not _HEX64_RE.match(pack.gps_hash):
            return VerifyResult(False, "gps_hash must be 64-char hex")
        if not _HEX64_RE.match(pack.media_hash):
            return VerifyResult(False, "media_hash must be 64-char hex")
        if not _HEX_RE.match(pack.device_signature):
            return VerifyResult(False, "device_signature must be hex")

        # source policy: album → private_only (we mark it but still pass)
        if pack.source == "album":
            return VerifyResult(True, "private_only")

        return VerifyResult(True)

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal


@dataclass(frozen=True)
class CapturePack:
    """A capture submission from a creator device."""

    timestamp: str  # ISO 8601
    gps_hash: str  # hex, 64 chars
    device_signature: str  # hex
    media_hash: str  # hex, 64 chars
    source: Literal["camera", "album"]

    def parsed_timestamp(self) -> datetime:
        return datetime.fromisoformat(self.timestamp).astimezone(timezone.utc)

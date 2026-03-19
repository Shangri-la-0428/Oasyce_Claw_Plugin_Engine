from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from oasyce.models.capture_pack import CapturePack


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    reason: Optional[str] = None


class IVerifier(ABC):
    @abstractmethod
    def verify(self, pack: CapturePack) -> VerifyResult: ...

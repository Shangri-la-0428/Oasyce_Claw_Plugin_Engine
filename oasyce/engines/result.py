from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Result(Generic[T]):
    ok: bool
    data: Optional[T] = None
    error: Optional[str] = None
    code: Optional[str] = None

    def unwrap(self) -> T:
        if not self.ok:
            raise RuntimeError(self.error or "Unknown error")
        return self.data  # type: ignore[return-value]


def ok(data: T) -> Result[T]:
    return Result(ok=True, data=data)


def err(message: str, code: Optional[str] = None) -> Result[T]:
    return Result(ok=False, error=message, code=code)

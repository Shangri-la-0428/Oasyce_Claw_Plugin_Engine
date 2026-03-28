from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class BuyReplay:
    status: int
    ok: bool
    state: str
    retryable: bool
    response: Dict[str, Any]
    original_trace_id: Optional[str] = None


@dataclass
class BuyLookup:
    kind: str
    replay: Optional[BuyReplay] = None


class BuyRuntime:
    """In-memory runtime state for buy idempotency and cooldown semantics."""

    def __init__(
        self,
        cooldown_seconds: int = 30,
        idempotency_ttl_seconds: int = 24 * 3600,
        *,
        cooldowns: Optional[Dict[Tuple[str, str], float]] = None,
        idempotency_cache: Optional[Dict[str, Dict[str, Any]]] = None,
        lock: Optional[threading.Lock] = None,
    ):
        self._cooldown_seconds = cooldown_seconds
        self._idempotency_ttl_seconds = idempotency_ttl_seconds
        self._cooldowns = cooldowns if cooldowns is not None else {}
        self._idempotency_cache = idempotency_cache if idempotency_cache is not None else {}
        self._lock = lock if lock is not None else threading.Lock()

    def cooldown_remaining(self, buyer: str, asset_id: str, now: Optional[float] = None) -> int:
        current = now if now is not None else time.time()
        with self._lock:
            last_buy = self._cooldowns.get((buyer, asset_id), 0.0)
        remaining = int(self._cooldown_seconds - (current - last_buy))
        return remaining if remaining > 0 else 0

    def lookup_idempotency(
        self,
        idempotency_key: str,
        request_fingerprint: str,
        now: Optional[float] = None,
    ) -> BuyLookup:
        current = now if now is not None else time.time()
        with self._lock:
            self._prune_stale(current)
            cached = self._idempotency_cache.get(idempotency_key)
        if not cached:
            return BuyLookup(kind="miss")
        if cached.get("request_fingerprint") != request_fingerprint:
            return BuyLookup(kind="conflict")
        return BuyLookup(
            kind="replay",
            replay=BuyReplay(
                status=int(cached.get("status", 200)),
                ok=bool(cached.get("ok", True)),
                state=str(cached.get("state", "success")),
                retryable=bool(cached.get("retryable", False)),
                response=dict(cached.get("response", {})),
                original_trace_id=cached.get("original_trace_id"),
            ),
        )

    def record_success(
        self,
        *,
        buyer: str,
        asset_id: str,
        idempotency_key: str,
        request_fingerprint: str,
        response: Dict[str, Any],
        trace_id: Optional[str],
        status: int = 200,
        ok: bool = True,
        state: str = "success",
        retryable: bool = False,
        now: Optional[float] = None,
    ) -> None:
        current = now if now is not None else time.time()
        with self._lock:
            self._cooldowns[(buyer, asset_id)] = current
            self._prune_stale(current)
            self._idempotency_cache[idempotency_key] = {
                "request_fingerprint": request_fingerprint,
                "status": status,
                "ok": ok,
                "state": state,
                "retryable": retryable,
                "response": dict(response),
                "created_at": current,
                "original_trace_id": trace_id,
            }

    def _prune_stale(self, now: float) -> None:
        cutoff = now - self._idempotency_ttl_seconds
        stale = [
            key
            for key, entry in self._idempotency_cache.items()
            if entry.get("created_at", 0) < cutoff
        ]
        for key in stale:
            self._idempotency_cache.pop(key, None)

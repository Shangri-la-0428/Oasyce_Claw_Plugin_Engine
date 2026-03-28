from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Optional


class BetaSupportStore:
    """Small in-memory store for recent beta core-flow events."""

    def __init__(self, max_events: int = 200):
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self._lock = threading.Lock()

    def record(
        self,
        event: str,
        trace_id: Optional[str],
        level: str,
        fields: Optional[Dict[str, Any]] = None,
        *,
        now: Optional[float] = None,
    ) -> None:
        entry = {
            "event": event,
            "trace_id": trace_id or "",
            "level": level,
            "timestamp": now if now is not None else time.time(),
            "fields": dict(fields or {}),
        }
        with self._lock:
            self._events.append(entry)

    def snapshot(self, limit: int = 20) -> Dict[str, Any]:
        with self._lock:
            events = list(self._events)
        events = list(reversed(events[-max(limit, 0) :]))
        failures = [
            event
            for event in events
            if event["level"] in {"warning", "error"} or event["event"].endswith(".failed")
        ]
        return {
            "events": events,
            "failures": failures,
        }


_STORE: Optional[BetaSupportStore] = None
_STORE_LOCK = threading.Lock()


def get_beta_support_store() -> BetaSupportStore:
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                _STORE = BetaSupportStore()
    return _STORE

"""
Server middleware — API key authentication and rate limiting.

Mainnet security:
  - Write endpoints require API key (OASYCE_API_KEY env var)
  - Read endpoints are open (public data)
  - Rate limiting per IP: reads 100/min, writes 20/min
"""

from __future__ import annotations

import os
import time
import threading
from collections import defaultdict
from typing import Callable, Dict, Optional, Set, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# ── Rate limiter ─────────────────────────────────────────────────────

class RateLimiter:
    """Token bucket rate limiter per IP address."""

    def __init__(self, rate: int, window_seconds: int = 60):
        self._rate = rate  # max requests per window
        self._window = window_seconds
        self._requests: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Return True if request is allowed, False if rate-limited."""
        now = time.time()
        cutoff = now - self._window

        with self._lock:
            # Prune old entries
            self._requests[key] = [
                t for t in self._requests[key] if t > cutoff
            ]
            if len(self._requests[key]) >= self._rate:
                return False
            self._requests[key].append(now)
            return True

    def remaining(self, key: str) -> int:
        """Requests remaining in current window."""
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            current = [t for t in self._requests[key] if t > cutoff]
            return max(0, self._rate - len(current))


# ── Read-only paths (no auth required) ───────────────────────────────

READ_PATHS: Set[str] = {
    "/health", "/status", "/metrics", "/docs", "/openapi.json",
}

READ_PREFIXES: Tuple[str, ...] = (
    "/v1/bonding_curve/",
    "/v1/escrow/",
    "/explorer/",
)


def _is_read_only(method: str, path: str) -> bool:
    """Determine if a request is read-only (no auth needed)."""
    if method == "GET":
        return True
    if path in READ_PATHS:
        return True
    # POST to read prefixes is a write (e.g., /v1/escrow/create)
    return False


# ── API Key Auth Middleware ──────────────────────────────────────────

class APIKeyMiddleware(BaseHTTPMiddleware):
    """Require API key for write endpoints when enabled.

    Set OASYCE_API_KEY to enable. Reads are always open.
    """

    def __init__(self, app, api_key: Optional[str] = None):
        super().__init__(app)
        self._api_key = api_key or os.environ.get("OASYCE_API_KEY", "")

    async def dispatch(self, request: Request, call_next: Callable):
        if not self._api_key:
            # No API key configured — skip auth
            return await call_next(request)

        if _is_read_only(request.method, request.url.path):
            return await call_next(request)

        # Check API key in header
        provided = request.headers.get("X-API-Key", "")
        if provided != self._api_key:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or missing API key"},
            )

        return await call_next(request)


# ── Rate Limit Middleware ────────────────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """IP-based rate limiting: reads 100/min, writes 20/min."""

    def __init__(
        self,
        app,
        read_rate: int = 100,
        write_rate: int = 20,
        window_seconds: int = 60,
    ):
        super().__init__(app)
        self._read_limiter = RateLimiter(read_rate, window_seconds)
        self._write_limiter = RateLimiter(write_rate, window_seconds)

    async def dispatch(self, request: Request, call_next: Callable):
        client_ip = request.client.host if request.client else "unknown"

        if _is_read_only(request.method, request.url.path):
            limiter = self._read_limiter
        else:
            limiter = self._write_limiter

        if not limiter.allow(client_ip):
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": "60"},
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(limiter.remaining(client_ip))
        return response

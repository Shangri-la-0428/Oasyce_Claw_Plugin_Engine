"""
Invocation Gateway — proxies capability calls to provider endpoints.

The gateway:
  1. Retrieves the provider's decrypted API key from the registry
  2. Calls the provider's endpoint with the consumer's input
  3. Measures latency and captures the response
  4. Never exposes the API key to the consumer

Supports both synchronous (HTTP POST) and timeout-protected calls.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from oasyce.services.capability_delivery.registry import EndpointRegistry


# ── SSRF protection ──────────────────────────────────────────────

_BLOCKED_HOSTNAMES = frozenset({"localhost"})


def _validate_endpoint_url(url: str) -> bool:
    """Return True if *url* is safe to call, False if it targets a
    private/internal/link-local address or uses a non-HTTP(S) scheme.

    Rejects:
      - Non-HTTP(S) schemes (ftp://, file://, etc.)
      - localhost, 127.0.0.1, 0.0.0.0, ::1
      - Private IP ranges: 10.x.x.x, 172.16-31.x.x, 192.168.x.x
      - Link-local: 169.254.x.x
      - Cloud metadata endpoint: 169.254.169.254
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        return False

    host = parsed.hostname
    if not host:
        return False

    # Blocked literal hostnames
    if host.lower() in _BLOCKED_HOSTNAMES:
        return False

    # Try to parse as IP address
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal — allow (DNS names other than "localhost" are OK)
        return True

    # Reject loopback, private, reserved, and link-local addresses
    if addr.is_loopback:  # 127.0.0.0/8, ::1
        return False
    if addr.is_private:  # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
        return False
    if addr.is_reserved:
        return False
    if addr.is_link_local:  # 169.254.0.0/16
        return False

    return True


def _resolve_and_validate(url: str) -> bool:
    """Resolve the hostname in *url* via DNS and check that the resolved IP
    is not private/internal.  This defends against DNS rebinding attacks where
    a name that pointed to a public IP at registration time is later rebound
    to an internal IP.

    Returns True if the resolved address is safe, False otherwise.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    host = parsed.hostname
    if not host:
        return False

    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, OSError):
        return False

    for family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        if addr.is_loopback or addr.is_private or addr.is_reserved or addr.is_link_local:
            return False

    return True


@dataclass
class InvocationResult:
    """Result of a single capability invocation."""

    success: bool
    output: Dict[str, Any]  # response payload (or error details)
    latency_ms: float  # round-trip time
    status_code: int = 200  # HTTP status
    error: str = ""  # error message if failed

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "success": self.success,
            "output": self.output,
            "latency_ms": self.latency_ms,
            "status_code": self.status_code,
        }
        if self.error:
            d["error"] = self.error
        return d


_DEFAULT_RATE_LIMIT = 60  # calls per minute


class InvocationGateway:
    """Proxies capability invocations to provider HTTP endpoints.

    Usage:
        gateway = InvocationGateway(registry)
        result = gateway.invoke("CAP_ABC123", {"text": "hello"})
    """

    def __init__(
        self,
        registry: EndpointRegistry,
        timeout: float = 30.0,
        max_retries: int = 0,
        allow_private: bool = False,
    ):
        self._registry = registry
        self._timeout = timeout
        self._max_retries = max_retries
        self._allow_private = allow_private
        self._call_timestamps: Dict[str, list] = {}  # capability_id -> [timestamps]

    def _check_rate_limit(self, capability_id: str, rate_limit: int) -> bool:
        """Return True if the call is within rate limit, False if exceeded.

        Cleans up timestamps older than 60 seconds as a side effect.
        """
        limit = rate_limit if rate_limit > 0 else _DEFAULT_RATE_LIMIT
        now = time.monotonic()
        window = 60.0  # 1 minute

        if capability_id not in self._call_timestamps:
            self._call_timestamps[capability_id] = []

        # Clean up old timestamps (only keep last 60 seconds)
        timestamps = self._call_timestamps[capability_id]
        cutoff = now - window
        self._call_timestamps[capability_id] = [t for t in timestamps if t > cutoff]
        timestamps = self._call_timestamps[capability_id]

        if len(timestamps) >= limit:
            return False

        timestamps.append(now)
        return True

    def invoke(
        self, capability_id: str, input_payload: Dict[str, Any], consumer_id: str = ""
    ) -> InvocationResult:
        """Invoke a capability endpoint.

        Args:
            capability_id: The capability to invoke.
            input_payload: JSON-serializable request body.
            consumer_id: Who is making the call (for logging).

        Returns:
            InvocationResult with success/failure, output, and latency.
        """
        # Look up endpoint
        endpoint = self._registry.get(capability_id)
        if not endpoint:
            return InvocationResult(
                success=False,
                output={},
                latency_ms=0,
                error=f"capability not found: {capability_id}",
            )

        if endpoint.status != "active":
            return InvocationResult(
                success=False,
                output={},
                latency_ms=0,
                error=f"capability is {endpoint.status}",
            )

        # Rate limit enforcement
        if not self._check_rate_limit(capability_id, endpoint.rate_limit):
            return InvocationResult(
                success=False,
                output={"ok": False, "error": "rate limit exceeded"},
                latency_ms=0,
                error="rate limit exceeded",
            )

        # SSRF protection: reject private/internal endpoints
        if not self._allow_private and not _validate_endpoint_url(endpoint.endpoint_url):
            return InvocationResult(
                success=False,
                output={
                    "ok": False,
                    "error": "endpoint URL blocked: private/internal address not allowed",
                },
                latency_ms=0,
                error="endpoint URL blocked: private/internal address not allowed",
            )

        # DNS rebinding protection: resolve hostname and validate the resolved
        # IP is not private/internal (second layer after registration-time check).
        if not self._allow_private and not _resolve_and_validate(endpoint.endpoint_url):
            return InvocationResult(
                success=False,
                output={
                    "ok": False,
                    "error": "endpoint URL blocked: DNS resolved to private/internal address",
                },
                latency_ms=0,
                error="endpoint URL blocked: DNS resolved to private/internal address",
            )

        # Get decrypted API key
        api_key = self._registry.get_api_key(capability_id)

        # Build request
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "Oasyce-Gateway/1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = json.dumps(input_payload).encode()

        # Call with retries
        last_error = ""
        last_status = 0
        latency = 0.0
        for attempt in range(1 + self._max_retries):
            t0 = time.monotonic()
            try:
                req = Request(
                    endpoint.endpoint_url,
                    data=body,
                    headers=headers,
                    method="POST",
                )
                with urlopen(req, timeout=self._timeout) as resp:
                    latency = (time.monotonic() - t0) * 1000
                    resp_body = resp.read().decode()
                    try:
                        output = json.loads(resp_body)
                    except json.JSONDecodeError:
                        output = {"raw": resp_body}

                    return InvocationResult(
                        success=True,
                        output=output,
                        latency_ms=round(latency, 2),
                        status_code=resp.status,
                    )

            except HTTPError as e:
                latency = (time.monotonic() - t0) * 1000
                last_status = e.code
                try:
                    err_body = e.read().decode()
                except Exception:
                    err_body = str(e)
                last_error = err_body
                if e.code < 500:
                    # Client error — don't retry
                    return InvocationResult(
                        success=False,
                        output={"error": err_body},
                        latency_ms=round(latency, 2),
                        status_code=e.code,
                        error=f"HTTP {e.code}",
                    )
                # Server error — may retry

            except URLError as e:
                latency = (time.monotonic() - t0) * 1000
                last_error = str(e.reason)

            except Exception as e:
                latency = (time.monotonic() - t0) * 1000
                last_error = str(e)

        # All retries exhausted
        return InvocationResult(
            success=False,
            output={"error": last_error},
            latency_ms=round(latency, 2),
            status_code=last_status or 0,
            error=f"invocation failed after {1 + self._max_retries} attempts: {last_error}",
        )

    def health_check(self, capability_id: str) -> Dict[str, Any]:
        """Quick health check — invoke with empty payload, expect any response."""
        result = self.invoke(capability_id, {"_health_check": True})
        return {
            "capability_id": capability_id,
            "reachable": result.success or result.status_code < 500,
            "latency_ms": result.latency_ms,
            "status_code": result.status_code,
        }

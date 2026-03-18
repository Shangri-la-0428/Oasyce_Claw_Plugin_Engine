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
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from oasyce_plugin.services.capability_delivery.registry import EndpointRegistry


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
    if addr.is_loopback:          # 127.0.0.0/8, ::1
        return False
    if addr.is_private:           # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
        return False
    if addr.is_reserved:
        return False
    if addr.is_link_local:        # 169.254.0.0/16
        return False

    return True


@dataclass
class InvocationResult:
    """Result of a single capability invocation."""
    success: bool
    output: Dict[str, Any]       # response payload (or error details)
    latency_ms: float            # round-trip time
    status_code: int = 200       # HTTP status
    error: str = ""              # error message if failed

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


class InvocationGateway:
    """Proxies capability invocations to provider HTTP endpoints.

    Usage:
        gateway = InvocationGateway(registry)
        result = gateway.invoke("CAP_ABC123", {"text": "hello"})
    """

    def __init__(self, registry: EndpointRegistry,
                 timeout: float = 30.0,
                 max_retries: int = 0,
                 allow_private: bool = False):
        self._registry = registry
        self._timeout = timeout
        self._max_retries = max_retries
        self._allow_private = allow_private

    def invoke(self, capability_id: str,
               input_payload: Dict[str, Any],
               consumer_id: str = "") -> InvocationResult:
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
                success=False, output={}, latency_ms=0,
                error=f"capability not found: {capability_id}",
            )

        if endpoint.status != "active":
            return InvocationResult(
                success=False, output={}, latency_ms=0,
                error=f"capability is {endpoint.status}",
            )

        # SSRF protection: reject private/internal endpoints
        if not self._allow_private and not _validate_endpoint_url(endpoint.endpoint_url):
            return InvocationResult(
                success=False,
                output={"ok": False, "error": "endpoint URL blocked: private/internal address not allowed"},
                latency_ms=0,
                error="endpoint URL blocked: private/internal address not allowed",
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

"""
Offline detection for Oasyce network connectivity.

Monitors connectivity to bootstrap nodes and DNS, reporting
online/degraded/offline status with hysteresis to avoid flapping.
"""

from __future__ import annotations

import socket
import time
import threading
from typing import Optional


# Connectivity thresholds
DEGRADED_THRESHOLD = 2    # consecutive failures before degraded
OFFLINE_THRESHOLD = 5     # consecutive failures before offline
RECOVERY_THRESHOLD = 2    # consecutive successes to recover from offline

# Default check targets
DEFAULT_DNS_HOST = "dns.google"
DEFAULT_DNS_PORT = 53
DEFAULT_TIMEOUT = 3  # seconds


class OfflineDetector:
    """Detects network connectivity status via lightweight probes.

    Status transitions:
        online  → degraded  (after DEGRADED_THRESHOLD consecutive failures)
        degraded → offline  (after OFFLINE_THRESHOLD consecutive failures)
        offline → degraded  (after 1 success)
        degraded → online   (after RECOVERY_THRESHOLD consecutive successes)
    """

    def __init__(
        self,
        check_interval: int = 30,
        bootstrap_host: Optional[str] = None,
        bootstrap_port: int = 8000,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.check_interval = check_interval
        self.bootstrap_host = bootstrap_host
        self.bootstrap_port = bootstrap_port
        self.timeout = timeout

        self._is_online = True
        self._status = "online"
        self.last_check: float = 0
        self.consecutive_failures: int = 0
        self.consecutive_successes: int = 0
        self._lock = threading.Lock()
        self._callbacks: list = []

    @property
    def is_online(self) -> bool:
        return self._status == "online"

    def check_connectivity(self) -> bool:
        """Check network connectivity. Returns True if reachable."""
        now = time.time()
        reachable = False

        # Try bootstrap node first if configured
        if self.bootstrap_host:
            reachable = self._probe_tcp(self.bootstrap_host, self.bootstrap_port)

        # Fallback to DNS check
        if not reachable:
            reachable = self._probe_tcp(DEFAULT_DNS_HOST, DEFAULT_DNS_PORT)

        with self._lock:
            self.last_check = now
            old_status = self._status

            if reachable:
                self.consecutive_failures = 0
                self.consecutive_successes += 1
                if self._status == "offline" and self.consecutive_successes >= 1:
                    self._status = "degraded"
                elif self._status == "degraded" and self.consecutive_successes >= RECOVERY_THRESHOLD:
                    self._status = "online"
                elif self._status == "online":
                    pass  # stay online
            else:
                self.consecutive_successes = 0
                self.consecutive_failures += 1
                if self.consecutive_failures >= OFFLINE_THRESHOLD:
                    self._status = "offline"
                elif self.consecutive_failures >= DEGRADED_THRESHOLD:
                    self._status = "degraded"

            if self._status != old_status:
                self._notify(old_status, self._status)

        return reachable

    def get_status(self) -> str:
        """Return current status: online/degraded/offline."""
        return self._status

    def get_info(self) -> dict:
        """Return detailed connectivity info."""
        with self._lock:
            return {
                "status": self._status,
                "last_check": self.last_check,
                "consecutive_failures": self.consecutive_failures,
                "consecutive_successes": self.consecutive_successes,
                "check_interval": self.check_interval,
                "bootstrap_host": self.bootstrap_host,
            }

    def on_status_change(self, callback):
        """Register callback(old_status, new_status) for status transitions."""
        self._callbacks.append(callback)

    def force_status(self, status: str):
        """Force a status (for testing). Must be online/degraded/offline."""
        if status not in ("online", "degraded", "offline"):
            raise ValueError(f"Invalid status: {status}")
        with self._lock:
            old = self._status
            self._status = status
            if old != status:
                self._notify(old, status)

    def _probe_tcp(self, host: str, port: int) -> bool:
        """Try to open a TCP connection. Returns True on success."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((host, port))
            sock.close()
            return True
        except (socket.error, OSError):
            return False

    def _notify(self, old_status: str, new_status: str):
        """Fire status change callbacks."""
        for cb in self._callbacks:
            try:
                cb(old_status, new_status)
            except Exception:
                pass

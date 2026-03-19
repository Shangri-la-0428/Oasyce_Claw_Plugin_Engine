"""Cloudflare Worker client for P2P bootstrap discovery.

This module handles:
1. Registering this node as a seed (if auto_seed=True)
2. Fetching seed nodes from Worker on startup
3. Sending heartbeats to keep registration alive
4. Local peer caching to reduce Worker requests
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

DEFAULT_CACHE_FILE = os.path.expanduser("~/.oasyce/known_peers.json")
HEARTBEAT_INTERVAL_SECONDS = 300  # 5 minutes
REGISTER_TIMEOUT = 5.0
FETCH_TIMEOUT = 5.0


class WorkerClient:
    """Client for Cloudflare Worker bootstrap discovery service."""

    def __init__(
        self,
        worker_url: str,
        node_ip: Optional[str] = None,
        node_port: int = 9527,
        node_id: Optional[str] = None,
        cache_file: str = DEFAULT_CACHE_FILE,
    ) -> None:
        self.worker_url = worker_url.rstrip("/")
        self.node_ip = node_ip
        self.node_port = node_port
        self.node_id = node_id
        self.cache_file = Path(cache_file)
        self.last_heartbeat = 0.0
        self.is_registered = False

    # ── Public API ──────────────────────────────────────────────────

    def load_cached_peers(self) -> List[str]:
        """Load peers from local cache file."""
        if not self.cache_file.exists():
            return []
        try:
            data = json.loads(self.cache_file.read_text())
            peers = data.get("peers", [])
            timestamp = data.get("timestamp", 0)
            # Cache valid for 24 hours
            if time.time() - timestamp < 86400:
                logger.info("Loaded %d peers from cache", len(peers))
                return peers
            else:
                logger.info("Cache expired, ignoring")
                return []
        except Exception as e:
            logger.debug("Failed to load cache: %s", e)
            return []

    def save_cached_peers(self, peers: List[str]) -> None:
        """Save peers to local cache file."""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "peers": peers,
                "timestamp": time.time(),
            }
            self.cache_file.write_text(json.dumps(data, indent=2))
            logger.debug("Saved %d peers to cache", len(peers))
        except Exception as e:
            logger.debug("Failed to save cache: %s", e)

    def fetch_seeds(self) -> List[Dict[str, Any]]:
        """Fetch seed nodes from Worker. Returns list of seed info dicts."""
        url = f"{self.worker_url}/seeds"
        try:
            req = urllib.request.Request(
                url,
                method="GET",
                headers={"User-Agent": "Oasyce-Node/1.0"},
            )
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                if resp.status == 200:
                    seeds = json.loads(resp.read().decode())
                    logger.info("Fetched %d seeds from Worker", len(seeds))
                    # Cache the seeds
                    peer_addrs = [f"{s.get('node_id', '')}" for s in seeds]
                    if peer_addrs:
                        self.save_cached_peers(peer_addrs)
                    return seeds
        except urllib.error.HTTPError as e:
            logger.warning("Worker HTTP error: %s", e)
        except urllib.error.URLError as e:
            logger.warning("Worker URL error: %s", e)
        except Exception as e:
            logger.debug("Failed to fetch seeds: %s", e)
        return []

    def register_seed(self) -> bool:
        """Register this node as a seed. Returns True on success."""
        if not self.node_ip:
            logger.debug("No public IP, skipping registration")
            return False

        url = f"{self.worker_url}/register"
        payload = json.dumps(
            {
                "ip": self.node_ip,
                "port": self.node_port,
                "node_id": self.node_id or "",
            }
        )
        try:
            req = urllib.request.Request(
                url,
                data=payload.encode(),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Oasyce-Node/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=REGISTER_TIMEOUT) as resp:
                if resp.status == 200:
                    self.is_registered = True
                    self.last_heartbeat = time.time()
                    logger.info("Registered as seed: %s:%d", self.node_ip, self.node_port)
                    return True
        except urllib.error.HTTPError as e:
            logger.warning("Worker registration HTTP error: %s", e)
        except urllib.error.URLError as e:
            logger.warning("Worker registration URL error: %s", e)
        except Exception as e:
            logger.debug("Failed to register seed: %s", e)
        return False

    def send_heartbeat(self) -> bool:
        """Send heartbeat to extend registration TTL. Returns True on success."""
        if not self.is_registered or not self.node_ip:
            return False

        # Check if enough time has passed
        now = time.time()
        if now - self.last_heartbeat < HEARTBEAT_INTERVAL_SECONDS:
            return True  # Not yet time

        url = f"{self.worker_url}/heartbeat"
        payload = json.dumps(
            {
                "ip": self.node_ip,
                "port": self.node_port,
            }
        )
        try:
            req = urllib.request.Request(
                url,
                data=payload.encode(),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Oasyce-Node/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=REGISTER_TIMEOUT) as resp:
                if resp.status == 200:
                    self.last_heartbeat = now
                    logger.debug("Heartbeat sent")
                    return True
        except urllib.error.HTTPError as e:
            logger.warning("Worker heartbeat HTTP error: %s", e)
            self.is_registered = False  # Registration may have expired
        except urllib.error.URLError as e:
            logger.warning("Worker heartbeat URL error: %s", e)
            self.is_registered = False
        except Exception as e:
            logger.debug("Failed to send heartbeat: %s", e)
            self.is_registered = False
        return False

    def should_send_heartbeat(self) -> bool:
        """Check if it's time to send a heartbeat."""
        if not self.is_registered:
            return False
        return time.time() - self.last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS

"""First-start auto-hardening for Oasyce nodes.

Runs on first node startup to:
1. Create data directory structure
2. Auto-generate Ed25519 keys if missing
3. Detect public IP / NAT status
4. Check port reachability
5. Save initial node config
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path
from typing import Optional

from oasyce.crypto.keys import load_or_create_keypair

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = os.path.expanduser("~/.oasyce")


def auto_harden(data_dir: str = DEFAULT_DATA_DIR) -> dict:
    """Run first-start auto-hardening. Returns status dict."""
    results = {}
    data_path = Path(data_dir)

    # 1. Create data directory
    data_path.mkdir(parents=True, exist_ok=True)
    results["data_dir"] = "exists" if data_path.exists() else "created"

    # 2. Auto-generate Ed25519 keys if missing
    keys_dir = data_path / "keys"
    priv_path = keys_dir / "private.key"
    already_existed = priv_path.exists()
    load_or_create_keypair(str(keys_dir))
    if not already_existed:
        # Set restrictive permissions on private key
        os.chmod(str(priv_path), 0o600)
        results["keys"] = "generated"
        logger.info("Generated new Ed25519 keypair")
    else:
        results["keys"] = "exists"

    # 3. Detect public IP
    public_ip = detect_public_ip()
    results["public_ip"] = public_ip
    results["nat"] = public_ip is None

    # 4. Check port reachability (only if we have a public IP)
    port_reachable = False
    if public_ip:
        port_reachable = check_port_reachable(public_ip, 9527)
        results["port_reachable"] = port_reachable
    else:
        results["port_reachable"] = False

    # 5. Save node config
    config_path = data_path / "node.json"
    if not config_path.exists():
        config = {
            "port": 9527,
            "public_ip": public_ip,
            "nat": public_ip is None,
            "auto_seed": port_reachable,  # Only become seed if port is reachable
            "port_reachable": port_reachable,
        }
        config_path.write_text(json.dumps(config, indent=2))
        results["config"] = "created"
    else:
        results["config"] = "exists"

    return results


def detect_public_ip() -> Optional[str]:
    """Try to detect if this machine has a public IP. Returns IP or None if behind NAT."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()

        if _is_private_ip(local_ip):
            return None
        return local_ip
    except Exception:
        return None


def check_port_reachable(public_ip: str, port: int, timeout: float = 3.0) -> bool:
    """Check if a port is reachable from the public internet.

    This is a local check - it verifies the port is open and listening.
    For true external reachability, you'd need an external checker or STUN.

    Returns True if port is open and listening, False otherwise.
    """
    try:
        # Try to bind to the port to see if it's available
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(timeout)
        result = test_sock.connect_ex((public_ip, port))
        test_sock.close()
        # If connect succeeds (result == 0), port is reachable
        return result == 0
    except Exception:
        return False


def _is_private_ip(ip: str) -> bool:
    """Check if IP is in private range (10.x, 172.16-31.x, 192.168.x, 127.x)."""
    parts = [int(p) for p in ip.split(".")]
    if parts[0] == 10:
        return True
    if parts[0] == 172 and 16 <= parts[1] <= 31:
        return True
    if parts[0] == 192 and parts[1] == 168:
        return True
    if parts[0] == 127:
        return True
    return False

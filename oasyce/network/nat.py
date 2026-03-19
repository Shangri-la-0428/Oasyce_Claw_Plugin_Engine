"""NAT traversal using a lightweight pure-Python STUN client.

Discovers the external IP:port mapping for a node behind NAT,
enabling peer-to-peer connectivity without manual port forwarding.
"""

from __future__ import annotations

import logging
import os
import socket
import struct
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Public STUN servers
STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
]

STUN_BINDING_REQUEST = 0x0001
STUN_BINDING_RESPONSE = 0x0101
STUN_MAGIC_COOKIE = 0x2112A442
STUN_ATTR_MAPPED_ADDRESS = 0x0001
STUN_ATTR_XOR_MAPPED_ADDRESS = 0x0020


def discover_external_address(
    local_port: int = 9527, timeout: float = 3.0
) -> Optional[Tuple[str, int]]:
    """Use STUN to discover external IP:port. Returns (ip, port) or None."""
    for server_host, server_port in STUN_SERVERS:
        try:
            result = _stun_request(server_host, server_port, local_port, timeout)
            if result:
                logger.info("STUN discovered external address: %s:%d", result[0], result[1])
                return result
        except Exception as e:
            logger.debug("STUN server %s failed: %s", server_host, e)
            continue
    logger.warning("All STUN servers failed — assuming behind symmetric NAT")
    return None


def _stun_request(
    server: str, server_port: int, local_port: int, timeout: float
) -> Optional[Tuple[str, int]]:
    """Send a STUN Binding Request and parse the response."""
    # Build request
    txn_id = os.urandom(12)
    header = struct.pack("!HHI", STUN_BINDING_REQUEST, 0, STUN_MAGIC_COOKIE) + txn_id

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.bind(("0.0.0.0", local_port))
    except OSError:
        # Port already in use, use ephemeral
        sock.bind(("0.0.0.0", 0))

    try:
        sock.sendto(header, (server, server_port))
        data, _ = sock.recvfrom(1024)
        return _parse_stun_response(data, txn_id)
    finally:
        sock.close()


def _parse_stun_response(data: bytes, expected_txn_id: bytes) -> Optional[Tuple[str, int]]:
    """Parse STUN Binding Response to extract mapped address."""
    if len(data) < 20:
        return None

    msg_type, msg_len, magic = struct.unpack_from("!HHI", data, 0)
    txn_id = data[8:20]

    if msg_type != STUN_BINDING_RESPONSE:
        return None
    if txn_id != expected_txn_id:
        return None

    # Parse attributes
    offset = 20
    while offset < 20 + msg_len:
        if offset + 4 > len(data):
            break
        attr_type, attr_len = struct.unpack_from("!HH", data, offset)
        offset += 4

        if attr_type == STUN_ATTR_XOR_MAPPED_ADDRESS and attr_len >= 8:
            family = data[offset + 1]
            if family == 0x01:  # IPv4
                xor_port = struct.unpack_from("!H", data, offset + 2)[0]
                xor_ip = struct.unpack_from("!I", data, offset + 4)[0]
                port = xor_port ^ (STUN_MAGIC_COOKIE >> 16)
                ip_int = xor_ip ^ STUN_MAGIC_COOKIE
                ip = socket.inet_ntoa(struct.pack("!I", ip_int))
                return (ip, port)

        elif attr_type == STUN_ATTR_MAPPED_ADDRESS and attr_len >= 8:
            family = data[offset + 1]
            if family == 0x01:  # IPv4
                port = struct.unpack_from("!H", data, offset + 2)[0]
                ip = socket.inet_ntoa(data[offset + 4 : offset + 8])
                return (ip, port)

        # Align to 4 bytes
        offset += attr_len + (4 - attr_len % 4) % 4

    return None


class NATTraversal:
    """Manages NAT traversal for a node."""

    def __init__(self, local_port: int = 9527):
        self.local_port = local_port
        self.external_address: Optional[Tuple[str, int]] = None
        self.nat_type: str = "unknown"  # 'none', 'full_cone', 'symmetric', 'unknown'

    def probe(self) -> dict:
        """Probe NAT status. Returns status dict."""
        result = discover_external_address(self.local_port)
        if result is None:
            self.nat_type = "symmetric"
            return {
                "nat": True,
                "type": "symmetric",
                "external": None,
                "reachable": False,
            }

        self.external_address = result
        ext_ip, ext_port = result

        # If external port == local port, likely no NAT or full cone
        if ext_port == self.local_port:
            self.nat_type = "none" if not _is_behind_nat(ext_ip) else "full_cone"
        else:
            self.nat_type = "full_cone"  # port mapped but reachable

        return {
            "nat": self.nat_type != "none",
            "type": self.nat_type,
            "external": "%s:%d" % (ext_ip, ext_port),
            "reachable": True,
        }


def _is_behind_nat(external_ip: str) -> bool:
    """Simple check: if external IP differs from local IP, we're behind NAT."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip != external_ip
    except Exception:
        return True

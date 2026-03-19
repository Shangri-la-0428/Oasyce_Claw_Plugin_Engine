"""Network configuration for Oasyce P2P protocol."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NetworkConfig:
    """Configuration for an Oasyce P2P node."""

    # Listening address
    host: str = "0.0.0.0"
    port: int = 9527

    # Cloudflare Worker URL for bootstrap discovery (optional)
    # Set to None to disable Worker-based discovery
    worker_url: Optional[str] = None

    # Seed nodes (host:port) used for initial peer discovery
    # Fallback if Worker is unavailable
    seed_nodes: List[str] = field(
        default_factory=lambda: [
            "seed1.oasyce.com:9527",
            "seed2.oasyce.com:9527",
        ]
    )

    # Consensus
    consensus_threshold: float = 2 / 3  # 2/3 majority required
    vote_timeout_seconds: float = 30.0  # seconds to collect votes

    # Gossip / heartbeat
    heartbeat_interval_seconds: float = 15.0
    peer_exchange_interval_seconds: float = 30.0

    # Peer limits
    max_peers: int = 50

    # Broadcast
    default_ttl: int = 5  # max hops for gossip messages

    # Identity
    key_dir: str = ".oasyce"  # directory to persist node keypair

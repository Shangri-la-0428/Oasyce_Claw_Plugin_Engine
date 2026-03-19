"""Peer scoring system for node reputation tracking."""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List


@dataclass
class PeerScore:
    address: str
    node_id: str = ""
    score: float = 50.0
    uptime_streak: int = 0
    total_seen: int = 0
    failed_connects: int = 0
    avg_rtt_ms: float = 0.0
    good_referrals: int = 0
    bad_referrals: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    last_score_update: float = 0.0
    reputation_score: float = 0.0


class PeerScoring:
    def __init__(self, data_dir: str = "~/.oasyce"):
        self.data_dir = os.path.expanduser(data_dir)
        self.peers: Dict[str, PeerScore] = {}
        self._score_file = os.path.join(self.data_dir, "peer_scores.json")

    def _get_or_create(self, address: str, node_id: str = "") -> PeerScore:
        if address not in self.peers:
            now = time.time()
            self.peers[address] = PeerScore(
                address=address,
                node_id=node_id,
                first_seen=now,
                last_seen=now,
            )
        peer = self.peers[address]
        if node_id and not peer.node_id:
            peer.node_id = node_id
        return peer

    def calculate_score(self, peer: PeerScore) -> float:
        now = time.time()

        # Uptime: continuous heartbeats, cap at 100 (30 pts)
        uptime = min(peer.uptime_streak / 100.0, 1.0) * 30

        # Responsiveness: RTT < 50ms = full, > 2000ms = 0 (25 pts)
        if peer.avg_rtt_ms <= 0:
            resp = 12.5  # no data, half score
        else:
            resp = max(0, 1.0 - peer.avg_rtt_ms / 2000.0) * 25

        # Data Quality: good / (good + bad) (20 pts)
        total_ref = peer.good_referrals + peer.bad_referrals
        if total_ref == 0:
            quality = 10  # no data, half score
        else:
            quality = (peer.good_referrals / total_ref) * 20

        # Age: > 7 days = full (10 pts)
        age_days = (now - peer.first_seen) / 86400
        age = min(age_days / 7.0, 1.0) * 10

        # Reputation: external reputation score (15 pts)
        reputation = min(peer.reputation_score / 95.0, 1.0) * 15

        return uptime + resp + quality + age + reputation

    def _update_score(self, peer: PeerScore) -> None:
        peer.score = self.calculate_score(peer)
        peer.last_score_update = time.time()

    def record_heartbeat(self, address: str, node_id: str = "") -> None:
        """Record a heartbeat from a peer."""
        peer = self._get_or_create(address, node_id)
        peer.uptime_streak += 1
        peer.total_seen += 1
        peer.last_seen = time.time()
        self._update_score(peer)

    def record_failure(self, address: str) -> None:
        """Record a connection failure."""
        peer = self._get_or_create(address)
        peer.failed_connects += 1
        peer.uptime_streak = 0
        self._update_score(peer)

    def record_rtt(self, address: str, rtt_ms: float) -> None:
        """Record a round-trip time measurement."""
        peer = self._get_or_create(address)
        if peer.avg_rtt_ms <= 0:
            peer.avg_rtt_ms = rtt_ms
        else:
            # Exponential moving average
            peer.avg_rtt_ms = peer.avg_rtt_ms * 0.7 + rtt_ms * 0.3
        self._update_score(peer)

    def update_reputation(self, address: str, reputation: float) -> None:
        """Update the external reputation score for a peer."""
        peer = self._get_or_create(address)
        peer.reputation_score = reputation
        self._update_score(peer)

    def record_referral(self, address: str, referred: str, reachable: bool) -> None:
        """Record referral quality for a peer."""
        peer = self._get_or_create(address)
        if reachable:
            peer.good_referrals += 1
        else:
            peer.bad_referrals += 1
        self._update_score(peer)

    def get_score(self, address: str) -> float:
        """Get current score for a peer."""
        if address not in self.peers:
            return 0.0
        return self.peers[address].score

    def get_best_peers(self, n: int = 20) -> List[PeerScore]:
        """Get top N peers by score, descending."""
        sorted_peers = sorted(self.peers.values(), key=lambda p: p.score, reverse=True)
        return sorted_peers[:n]

    def get_banned(self) -> List[str]:
        """Get addresses of banned peers (score < 10)."""
        return [p.address for p in self.peers.values() if p.score < 10]

    def save(self) -> None:
        """Persist scores to disk."""
        os.makedirs(self.data_dir, exist_ok=True)
        data = {addr: asdict(peer) for addr, peer in self.peers.items()}
        with open(self._score_file, "w") as f:
            json.dump(data, f, indent=2)

    def load(self) -> None:
        """Load scores from disk."""
        if not os.path.exists(self._score_file):
            return
        with open(self._score_file, "r") as f:
            data = json.load(f)
        self.peers = {}
        for addr, fields in data.items():
            self.peers[addr] = PeerScore(**fields)

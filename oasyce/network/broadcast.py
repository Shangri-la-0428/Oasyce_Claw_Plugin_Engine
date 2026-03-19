"""Gossip broadcast with TTL and deduplication.

When a node receives a new message it forwards the message to all known
peers (minus the sender).  TTL is decremented on each hop and messages
with TTL <= 0 are dropped.  A set of seen message hashes prevents
infinite loops.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Callable, Awaitable

from oasyce.network.message import NetworkMessage

if TYPE_CHECKING:
    from oasyce.network.discovery import PeerDiscovery

logger = logging.getLogger(__name__)

# Type alias for the function that actually sends a message to a peer.
SendFunc = Callable[[str, NetworkMessage], Awaitable[bool]]

# Maximum number of message hashes to keep for dedup.
_MAX_SEEN = 10_000


class GossipBroadcast:
    """Manages gossip-style message propagation."""

    def __init__(
        self,
        discovery: PeerDiscovery,
        send_func: SendFunc,
    ) -> None:
        self._discovery = discovery
        self._send = send_func
        # OrderedDict used as an LRU-bounded set.
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Dedup
    # ------------------------------------------------------------------

    async def _is_seen(self, msg_hash: str) -> bool:
        async with self._lock:
            if msg_hash in self._seen:
                return True
            self._seen[msg_hash] = None
            if len(self._seen) > _MAX_SEEN:
                self._seen.popitem(last=False)
            return False

    async def mark_seen(self, msg_hash: str) -> None:
        async with self._lock:
            self._seen[msg_hash] = None
            if len(self._seen) > _MAX_SEEN:
                self._seen.popitem(last=False)

    async def already_seen(self, msg: NetworkMessage) -> bool:
        return await self._is_seen(msg.msg_hash)

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def broadcast(self, msg: NetworkMessage) -> int:
        """Forward *msg* to all known peers.

        Returns the number of peers the message was successfully sent to.
        The message's TTL is decremented before forwarding.
        """
        if msg.ttl <= 0:
            return 0

        # Mark as seen so we don't re-broadcast if it comes back to us.
        await self.mark_seen(msg.msg_hash)

        forwarded = NetworkMessage.from_dict(msg.to_dict())
        forwarded.ttl = msg.ttl - 1

        peers = await self._discovery.get_peer_addresses()
        if not peers:
            return 0

        tasks = [self._send(addr, forwarded) for addr in peers if addr]  # skip blanks
        results = await asyncio.gather(*tasks, return_exceptions=True)
        sent = sum(1 for r in results if r is True)
        logger.debug("Broadcast %s to %d/%d peers", msg.msg_type, sent, len(peers))
        return sent

    async def receive_and_rebroadcast(self, msg: NetworkMessage) -> bool:
        """Process an incoming message: verify, dedup, and rebroadcast.

        Returns True if the message is new and valid.
        """
        if not msg.verify_signature():
            logger.warning("Dropping message %s – bad signature", msg.msg_id)
            return False

        if await self.already_seen(msg):
            return False

        # Rebroadcast to other peers if TTL allows.
        await self.broadcast(msg)
        return True

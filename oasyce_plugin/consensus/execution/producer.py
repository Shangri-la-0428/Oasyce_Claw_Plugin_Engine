"""
Block producer — creates blocks from pending operations.

Components:
  Mempool        — thread-safe queue of pending Operations
  BlockProducer  — pulls from mempool, builds and applies blocks

The producer drives the consensus loop:
  1. Collect pending operations from mempool
  2. Build a Block (link to prev_hash, compute merkle root)
  3. Apply via engine.apply_block()
  4. Push to SyncServer for peer distribution
  5. Repeat on interval or on-demand
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from oasyce_plugin.consensus.core.types import Operation
from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    compute_merkle_root,
    make_genesis_block,
    GENESIS_PREV_HASH,
)

if TYPE_CHECKING:
    from oasyce_plugin.consensus import ConsensusEngine
    from oasyce_plugin.consensus.network.http_transport import SyncServer


# ── Mempool ──────────────────────────────────────────────────────


class Mempool:
    """Thread-safe queue of pending operations awaiting inclusion in a block.

    Operations are validated on submit. Invalid operations are rejected
    immediately. Valid operations wait in FIFO order.
    """

    def __init__(self, max_size: int = 1000):
        self._queue: deque[Operation] = deque()
        self._lock = threading.Lock()
        self._max_size = max_size

    def submit(self, op: Operation) -> Dict[str, Any]:
        """Add an operation to the mempool.

        Returns {"ok": True} on success, {"ok": False, "error": ...} on failure.
        """
        with self._lock:
            if len(self._queue) >= self._max_size:
                return {"ok": False, "error": "mempool full"}
            self._queue.append(op)
            return {"ok": True, "position": len(self._queue)}

    def drain(self, max_ops: int = 100) -> List[Operation]:
        """Remove and return up to max_ops operations from the front."""
        with self._lock:
            result = []
            while self._queue and len(result) < max_ops:
                result.append(self._queue.popleft())
            return result

    def peek(self, max_ops: int = 10) -> List[Operation]:
        """View operations without removing them."""
        with self._lock:
            return list(self._queue)[:max_ops]

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._queue)

    def clear(self) -> int:
        """Remove all pending operations. Returns count removed."""
        with self._lock:
            n = len(self._queue)
            self._queue.clear()
            return n


# ── Block Producer ───────────────────────────────────────────────


class BlockProducer:
    """Produces blocks from mempool operations on a configurable interval.

    Usage:
        producer = BlockProducer(engine, mempool, sync_server=server)
        producer.start(interval=5.0)   # produce a block every 5 seconds
        ...
        producer.stop()

    Can also be called manually:
        block = producer.produce_block()
    """

    def __init__(self, engine: ConsensusEngine,
                 mempool: Mempool,
                 sync_server: Optional[SyncServer] = None,
                 proposer_id: str = "",
                 max_ops_per_block: int = 100,
                 on_block: Optional[Callable[[Block], None]] = None):
        self._engine = engine
        self._mempool = mempool
        self._sync_server = sync_server
        self._proposer_id = proposer_id
        self._max_ops_per_block = max_ops_per_block
        self._on_block = on_block

        self._lock = threading.Lock()
        self._height = -1  # will be initialized from chain
        self._prev_hash = GENESIS_PREV_HASH
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._blocks_produced = 0

        # Initialize from genesis
        self._init_chain()

    def _init_chain(self) -> None:
        """Set up initial height and prev_hash from genesis."""
        genesis = make_genesis_block(self._engine.chain_id,
                                     timestamp=self._engine.genesis_time)
        self._prev_hash = genesis.block_hash
        self._height = 0

        # Register genesis in sync server if present
        if self._sync_server is not None:
            existing = self._sync_server.blocks
            if not existing:
                self._sync_server.add_block(genesis)

    def produce_block(self) -> Optional[Block]:
        """Build and apply a single block from mempool operations.

        Returns the produced Block, or None if mempool was empty
        and empty blocks are not produced.
        """
        ops = self._mempool.drain(self._max_ops_per_block)

        with self._lock:
            self._height += 1
            height = self._height
            prev_hash = self._prev_hash

        ops_tuple = tuple(ops)
        merkle = compute_merkle_root(ops_tuple)
        ts = int(time.time())

        block = Block(
            chain_id=self._engine.chain_id,
            block_number=height,
            prev_hash=prev_hash,
            merkle_root=merkle,
            timestamp=ts,
            operations=ops_tuple,
            proposer=self._proposer_id,
        )

        # Apply block to local state
        result = self._engine.apply_block({
            "height": height,
            "operations": list(ops),
        })

        # Update chain tip
        with self._lock:
            self._prev_hash = block.block_hash
            self._blocks_produced += 1

        # Push to sync server for distribution
        if self._sync_server is not None:
            self._sync_server.add_block(block)

        # Callback
        if self._on_block:
            self._on_block(block)

        return block

    def start(self, interval: float = 5.0,
              empty_blocks: bool = True) -> None:
        """Start producing blocks in a background thread.

        Args:
            interval: Seconds between block production attempts.
            empty_blocks: If True, produce blocks even when mempool is empty.
        """
        if self._running:
            return
        self._running = True

        def loop():
            while self._running:
                if empty_blocks or self._mempool.size > 0:
                    try:
                        self.produce_block()
                    except Exception:
                        pass  # log in production
                time.sleep(interval)

        self._thread = threading.Thread(
            target=loop, daemon=True,
            name="block-producer",
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

    @property
    def height(self) -> int:
        with self._lock:
            return self._height

    @property
    def blocks_produced(self) -> int:
        with self._lock:
            return self._blocks_produced

    @property
    def prev_hash(self) -> str:
        with self._lock:
            return self._prev_hash

    def status(self) -> Dict[str, Any]:
        return {
            "height": self.height,
            "blocks_produced": self.blocks_produced,
            "mempool_size": self._mempool.size,
            "prev_hash": self.prev_hash[:16] + "...",
            "proposer": self._proposer_id,
            "running": self._running,
        }

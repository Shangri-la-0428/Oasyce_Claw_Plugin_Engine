"""
Block synchronization and network protocol for Oasyce PoS consensus.

Provides:
  - sync_protocol: Block, BlockHeader, sync message types
  - block_sync: Peer sync, block verification, network sync
  - protocol: Extended protocol messages (height, headers, sync status)
"""

from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    BlockHeader,
    GetBlocksRequest,
    GetBlocksResponse,
    GetPeerInfoRequest,
    GetPeerInfoResponse,
    SyncResult,
    SyncStatus,
)
from oasyce_plugin.consensus.network.block_sync import (
    verify_block,
    verify_block_chain,
    apply_synced_block,
    sync_from_peer,
    sync_from_network,
)
from oasyce_plugin.consensus.network.protocol import (
    GetHeight,
    HeightResponse,
    GetBlocks,
    BlocksResponse,
    GetBlockHeaders,
    BlockHeaders,
    SyncStatusMessage,
    SyncState,
    SyncInfo,
)

from oasyce_plugin.consensus.network.offline_detector import OfflineDetector

__all__ = [
    "Block",
    "BlockHeader",
    "GetBlocksRequest",
    "GetBlocksResponse",
    "GetPeerInfoRequest",
    "GetPeerInfoResponse",
    "SyncResult",
    "SyncStatus",
    "verify_block",
    "verify_block_chain",
    "apply_synced_block",
    "sync_from_peer",
    "sync_from_network",
    "GetHeight",
    "HeightResponse",
    "GetBlocks",
    "BlocksResponse",
    "GetBlockHeaders",
    "BlockHeaders",
    "SyncStatusMessage",
    "SyncState",
    "SyncInfo",
    "OfflineDetector",
]

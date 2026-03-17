"""Storage layer — uses oasyce_core if available, fallback for Ledger."""

from oasyce_plugin.storage.ledger import Ledger

try:
    from oasyce_core.storage import IPFSClient, StorageBackend
except ImportError:
    # Minimal stubs when oasyce_core is not installed
    class StorageBackend:
        """Stub: oasyce_core not installed."""
        LOCAL = "local"

    class IPFSClient:
        """Stub: IPFS requires oasyce_core."""
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "IPFS storage requires oasyce-core. Install with: pip install oasyce-core"
            )

__all__ = ["Ledger", "IPFSClient", "StorageBackend"]

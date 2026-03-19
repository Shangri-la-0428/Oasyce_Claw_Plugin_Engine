"""
OasyceProtocol -- simplified orchestrator that delegates to the Cosmos chain.

Provides the high-level protocol interface used by the bridge and engine.
Local verification is done via MockVerifier; all economic operations
(register, buy, quote, stake, shares) go through the chain client.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from oasyce.chain_client import ChainClientError, OasyceClient
from oasyce.mock.mock_verifier import MockVerifier
from oasyce.models.capture_pack import CapturePack

logger = logging.getLogger(__name__)


@dataclass
class SubmitResult:
    """Result of a data submission."""

    valid: bool
    reason: Optional[str] = None
    asset_id: Optional[str] = None


@dataclass
class BuyResult:
    """Result of an asset purchase."""

    asset_id: str
    buyer: str
    amount_oas: float
    tx_id: str
    success: bool = True


class OasyceProtocol:
    """High-level protocol orchestrator.

    - Local verification via MockVerifier
    - All chain operations delegated to OasyceClient
    """

    def __init__(
        self,
        rest_url: str = "http://localhost:1317",
        grpc_url: str = "localhost:9090",
    ):
        self._chain = OasyceClient(rest_url=rest_url, grpc_url=grpc_url)
        self._verifier = MockVerifier()

    @property
    def chain(self) -> OasyceClient:
        """Access the underlying chain client."""
        return self._chain

    async def submit_data(
        self,
        pack: CapturePack,
        creator: str,
        name: str = "",
        description: str = "",
        rights_type: str = "original",
        tags: Optional[List[str]] = None,
    ) -> SubmitResult:
        """Verify a CapturePack locally, then register on-chain."""
        # Step 1: local verification
        result = self._verifier.verify(pack)
        if not result.valid:
            return SubmitResult(valid=False, reason=result.reason)

        # Step 2: register on chain
        asset_name = name or f"asset-{pack.media_hash[:8]}"
        try:
            tx_result = self._chain.chain.register_data_asset(
                owner=creator,
                name=asset_name,
                description=description,
                content_hash=pack.media_hash,
                rights_type=rights_type,
                tags=tags or [],
            )
            asset_id = tx_result.get("tx_response", {}).get(
                "txhash",
                hashlib.sha256(f"{creator}:{pack.media_hash}".encode()).hexdigest()[:16],
            )
        except ChainClientError:
            # Fallback: generate local asset ID
            asset_id = hashlib.sha256(f"{creator}:{pack.media_hash}".encode()).hexdigest()[:16]
            logger.warning("Chain unavailable; registered locally as %s", asset_id)

        return SubmitResult(valid=True, reason=result.reason, asset_id=asset_id)

    async def buy_asset(
        self,
        asset_id: str,
        buyer: str,
        amount: float = 10.0,
    ) -> BuyResult:
        """Buy shares of a data asset on-chain."""
        amount_uoas = int(amount * 1e8)
        try:
            tx_result = self._chain.chain.buy_shares(
                buyer=buyer,
                asset_id=asset_id,
                amount_uoas=amount_uoas,
            )
            tx_id = tx_result.get("tx_response", {}).get("txhash", uuid.uuid4().hex)
            return BuyResult(
                asset_id=asset_id,
                buyer=buyer,
                amount_oas=amount,
                tx_id=tx_id,
                success=True,
            )
        except ChainClientError as exc:
            logger.error("Buy failed: %s", exc)
            return BuyResult(
                asset_id=asset_id,
                buyer=buyer,
                amount_oas=amount,
                tx_id="",
                success=False,
            )

    def get_quote(self, asset_id: str) -> Dict[str, Any]:
        """Get bonding-curve price for an asset."""
        return self._chain.get_bonding_curve_price(asset_id)

    def get_asset(self, asset_id: str) -> Dict[str, Any]:
        """Get data asset details."""
        return self._chain.get_data_asset(asset_id)

    def get_shares(self, owner: str) -> List[Dict[str, Any]]:
        """Get all share holdings for an owner from the chain."""
        try:
            assets = self._chain.list_data_assets(owner=owner)
            shares: List[Dict[str, Any]] = []
            for asset in assets:
                aid = asset.get("id", asset.get("asset_id", ""))
                if aid:
                    try:
                        sh_data = self._chain.chain.get_shareholders(aid)
                        for sh in sh_data.get("shareholders", []):
                            if sh.get("address") == owner:
                                shares.append(
                                    {
                                        "asset_id": aid,
                                        "owner": owner,
                                        "shares": int(sh.get("shares", 0)),
                                    }
                                )
                    except ChainClientError:
                        pass
            return shares
        except ChainClientError:
            return []

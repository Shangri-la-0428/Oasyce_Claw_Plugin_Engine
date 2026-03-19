from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from oasyce.config import get_config
from oasyce.engine import OasyceEngine
from oasyce.services.facade import OasyceServiceFacade, ServiceResult


@lru_cache(maxsize=1)
def get_engine() -> OasyceEngine:
    mode: Literal["mock", "real", "postgres"] = os.environ.get("OASYCE_MODE", "mock")  # type: ignore[assignment]
    config = get_config(mode)

    # Auto-init schema for persistent backends
    if mode == "postgres":
        from oasyce.postgres.connection import get_connection, init_schema

        init_schema(get_connection())

    return OasyceEngine(config)


class _EngineBacked(OasyceServiceFacade):
    """Facade subclass that delegates buy() to OasyceEngine.

    This ensures assets submitted via OasyceEngine are visible to the
    facade's buy path, while still routing through the facade interface.
    """

    def __init__(self, engine: OasyceEngine) -> None:
        super().__init__()
        self._engine = engine

    def buy(self, asset_id: str, buyer: str, amount_oas: float = 10.0) -> ServiceResult:
        quote, settle = self._engine.buy(asset_id, buyer=buyer)

        if quote is None or settle is None:
            return ServiceResult(success=False, error=f"asset '{asset_id}' not found")

        split_data = None
        if settle.split is not None:
            split_data = {
                "creator": settle.split.creator,
                "protocol_burn": settle.split.protocol_burn,
                "protocol_validator": settle.split.protocol_validator,
                "router": settle.split.router,
            }

        return ServiceResult(
            success=settle.success,
            data={
                "quote": {
                    "asset_id": quote.asset_id,
                    "price_oas": quote.price_oas,
                    "supply": quote.supply,
                },
                "settlement": {
                    "success": settle.success,
                    "tx_id": settle.tx_id,
                    "split": split_data,
                    "reason": settle.reason,
                },
            },
            error=settle.reason if not settle.success else None,
        )


@lru_cache(maxsize=1)
def get_facade() -> OasyceServiceFacade:
    return _EngineBacked(get_engine())

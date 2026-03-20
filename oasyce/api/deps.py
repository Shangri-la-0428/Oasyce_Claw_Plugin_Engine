from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from oasyce.config import get_config
from oasyce.engine import OasyceEngine
from oasyce.services.facade import OasyceServiceFacade


@lru_cache(maxsize=1)
def get_engine() -> OasyceEngine:
    mode: Literal["mock", "real", "postgres"] = os.environ.get("OASYCE_MODE", "mock")  # type: ignore[assignment]
    config = get_config(mode)

    # Auto-init schema for persistent backends
    if mode == "postgres":
        from oasyce.postgres.connection import get_connection, init_schema

        init_schema(get_connection())

    return OasyceEngine(config)


@lru_cache(maxsize=1)
def get_facade() -> OasyceServiceFacade:
    return OasyceServiceFacade()

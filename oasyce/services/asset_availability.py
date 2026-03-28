from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class AssetAvailabilityResult:
    available: bool
    http_status: int = 200
    error: Optional[str] = None
    message: Optional[str] = None


class AssetAvailabilityProbe:
    """Checks whether a locally tracked asset file is still available and intact."""

    def __init__(self, ledger: Any):
        self._ledger = ledger

    def _update_integrity_projection(self, asset_id: str, **updates: Any) -> None:
        if self._ledger is None:
            return
        try:
            self._ledger.update_asset_metadata(asset_id, updates)
        except Exception:
            pass

    def inspect(self, asset_id: str) -> AssetAvailabilityResult:
        if self._ledger is None:
            return AssetAvailabilityResult(
                available=False,
                http_status=503,
                error="not initialized",
            )

        asset_meta = self._ledger.get_asset_metadata(asset_id)
        if asset_meta is None:
            return AssetAvailabilityResult(available=True)

        file_path = asset_meta.get("file_path")
        file_hash = asset_meta.get("file_hash")
        if not file_path or not file_hash:
            return AssetAvailabilityResult(available=True)

        if not os.path.isfile(file_path):
            self._update_integrity_projection(asset_id, _integrity_status="missing")
            return AssetAvailabilityResult(
                available=False,
                http_status=409,
                error="UNAVAILABLE",
                message="Asset file is missing or modified",
            )

        need_hash = True
        try:
            stat = os.stat(file_path)
            cached_size = asset_meta.get("_cached_size")
            cached_mtime = asset_meta.get("_cached_mtime")
            if cached_size == stat.st_size and cached_mtime == stat.st_mtime:
                need_hash = False
        except OSError:
            pass

        if need_hash:
            hasher = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    hasher.update(chunk)
            if hasher.hexdigest() != file_hash:
                self._update_integrity_projection(asset_id, _integrity_status="changed")
                return AssetAvailabilityResult(
                    available=False,
                    http_status=409,
                    error="UNAVAILABLE",
                    message="Asset file is missing or modified",
                )
            try:
                stat = os.stat(file_path)
                self._ledger.update_asset_metadata(
                    asset_id,
                    {
                        "_cached_size": stat.st_size,
                        "_cached_mtime": stat.st_mtime,
                        "_integrity_status": "ok",
                    },
                )
            except Exception:
                pass
        else:
            self._update_integrity_projection(asset_id, _integrity_status="ok")

        return AssetAvailabilityResult(available=True)

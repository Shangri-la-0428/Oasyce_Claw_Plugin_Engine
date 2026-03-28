from __future__ import annotations

import os
from typing import Any, Dict, Optional

from oasyce.storage.ledger import Ledger


TEST_OWNER_MARKERS = {"TestUser", "demo_user", "test_001"}
TEST_TAG_MARKERS = {"Test", "Batch", "SearchTest", "Demo"}


def audit_local_asset_update(asset_id: str, ledger: Optional[Ledger] = None) -> Dict[str, Any]:
    own_ledger = ledger is None
    ledger = ledger or Ledger()
    try:
        meta = ledger.get_asset_metadata(asset_id)
        if meta is None:
            return {
                "ok": False,
                "asset_id": asset_id,
                "status": "not_found",
                "recommended_action": "create_canonical_asset",
                "reason": "Asset not found in local ledger",
            }

        holders = ledger.get_asset_holders(asset_id)
        versions = meta.get("versions") or ledger.get_versions(asset_id)
        file_path = meta.get("file_path")
        file_exists = bool(file_path and os.path.isfile(file_path))
        owner = meta.get("owner", "")
        tags = list(meta.get("tags") or [])
        is_test_like = (
            owner in TEST_OWNER_MARKERS
            or bool(TEST_TAG_MARKERS.intersection(set(tags)))
            or not file_path
        )
        free_flag = bool(meta.get("free"))
        holders_count = len(holders)
        total_shares = round(sum(float(row.get("amount") or 0.0) for row in holders), 8)

        warnings = []
        if not file_path:
            warnings.append("metadata has no file_path; local re-register cannot safely track source")
        elif not file_exists:
            warnings.append("file_path no longer exists on disk")
        if is_test_like:
            warnings.append("asset looks test-like or non-canonical")
        if holders_count > 0:
            warnings.append("existing holders detected; avoid overwriting economics in place")

        if holders_count > 0:
            recommended_action = "create_new_chain_version_with_migration"
            rationale = (
                "Existing holders must keep their old rights. Publish a new immutable asset version "
                "and offer an optional migration path instead of mutating the original."
            )
        elif not file_path or is_test_like:
            recommended_action = "create_canonical_asset"
            rationale = (
                "This asset is not a clean canonical release asset. Create a new canonical asset for "
                "the current repo/release instead of reusing this local record."
            )
        else:
            recommended_action = "local_reregister_or_chain_new_version"
            rationale = (
                "No holders are attached. For local standalone iteration you can re-register in place; "
                "for real chain publication you should still create a new immutable version."
            )

        return {
            "ok": True,
            "asset_id": asset_id,
            "status": "ok",
            "owner": owner,
            "filename": meta.get("filename"),
            "file_path": file_path,
            "file_exists": file_exists,
            "rights_type": meta.get("rights_type"),
            "free": free_flag,
            "tags": tags,
            "holders_count": holders_count,
            "holders": holders,
            "total_shares": total_shares,
            "versions_count": len(versions),
            "versions": versions,
            "is_test_like": is_test_like,
            "recommended_action": recommended_action,
            "rationale": rationale,
            "warnings": warnings,
            "local_guidance": (
                "Use /api/re-register only for local standalone iteration, when the source file still exists "
                "and no public holder rights need protection."
            ),
            "chain_guidance": (
                "On chain, new content should be a new immutable asset version linked by parent_asset_id; "
                "use migration paths to protect existing holders."
            ),
        }
    finally:
        if own_ledger:
            try:
                ledger._conn.close()  # pragma: no cover - simple resource cleanup
            except Exception:
                pass

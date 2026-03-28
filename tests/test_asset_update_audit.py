from __future__ import annotations

from oasyce.services.asset_update_audit import audit_local_asset_update
from oasyce.storage.ledger import Ledger


def test_audit_local_asset_update_recommends_new_chain_version_for_holders(tmp_path):
    ledger = Ledger(str(tmp_path / "chain.db"))
    ledger.register_asset(
        "ASSET_AUDIT_1",
        "owner-1",
        "hash-v1",
        {
            "asset_id": "ASSET_AUDIT_1",
            "owner": "owner-1",
            "filename": "repo.tar.gz",
            "file_path": str(tmp_path / "repo.tar.gz"),
            "tags": ["release"],
            "rights_type": "original",
        },
    )
    ledger.update_shares("buyer-1", "ASSET_AUDIT_1", 12.5)

    report = audit_local_asset_update("ASSET_AUDIT_1", ledger)

    assert report["ok"] is True
    assert report["holders_count"] == 1
    assert report["recommended_action"] == "create_new_chain_version_with_migration"


def test_audit_local_asset_update_marks_test_like_assets_non_canonical(tmp_path):
    ledger = Ledger(str(tmp_path / "chain.db"))
    ledger.register_asset(
        "ASSET_AUDIT_2",
        "TestUser",
        "hash-v1",
        {
            "asset_id": "ASSET_AUDIT_2",
            "owner": "TestUser",
            "filename": "README.md",
            "tags": ["SearchTest"],
            "rights_type": "original",
        },
    )

    report = audit_local_asset_update("ASSET_AUDIT_2", ledger)

    assert report["ok"] is True
    assert report["is_test_like"] is True
    assert report["recommended_action"] == "create_canonical_asset"


def test_audit_local_asset_update_reports_missing_asset(tmp_path):
    ledger = Ledger(str(tmp_path / "chain.db"))

    report = audit_local_asset_update("MISSING_ASSET", ledger)

    assert report["ok"] is False
    assert report["status"] == "not_found"

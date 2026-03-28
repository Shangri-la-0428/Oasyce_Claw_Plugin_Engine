from __future__ import annotations

import hashlib

from oasyce.services.asset_availability import AssetAvailabilityProbe
from oasyce.storage.ledger import Ledger


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_probe_returns_unavailable_when_file_missing(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_MISSING",
        "owner-1",
        "hash-1",
        {
            "owner": "owner-1",
            "file_path": str(tmp_path / "missing.txt"),
            "file_hash": "hash-1",
        },
    )

    probe = AssetAvailabilityProbe(ledger)
    result = probe.inspect("ASSET_MISSING")

    assert result.available is False
    assert result.http_status == 409
    assert result.error == "UNAVAILABLE"
    assert result.message == "Asset file is missing or modified"
    meta = ledger.get_asset_metadata("ASSET_MISSING")
    assert meta["_integrity_status"] == "missing"


def test_probe_updates_cached_size_and_mtime_when_hash_matches(tmp_path):
    file_path = tmp_path / "asset.txt"
    file_path.write_text("hello", encoding="utf-8")
    file_hash = _sha256_text("hello")

    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_OK",
        "owner-1",
        file_hash,
        {
            "owner": "owner-1",
            "file_path": str(file_path),
            "file_hash": file_hash,
        },
    )

    probe = AssetAvailabilityProbe(ledger)
    result = probe.inspect("ASSET_OK")

    assert result.available is True
    meta = ledger.get_asset_metadata("ASSET_OK")
    assert meta["_cached_size"] == file_path.stat().st_size
    assert meta["_cached_mtime"] == file_path.stat().st_mtime
    assert meta["_integrity_status"] == "ok"


def test_probe_marks_changed_when_hash_mismatches(tmp_path):
    file_path = tmp_path / "asset.txt"
    file_path.write_text("hello", encoding="utf-8")
    original_hash = _sha256_text("hello")

    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_CHANGED",
        "owner-1",
        original_hash,
        {
            "owner": "owner-1",
            "file_path": str(file_path),
            "file_hash": original_hash,
        },
    )

    file_path.write_text("changed", encoding="utf-8")

    probe = AssetAvailabilityProbe(ledger)
    result = probe.inspect("ASSET_CHANGED")

    assert result.available is False
    assert result.http_status == 409
    assert result.error == "UNAVAILABLE"
    meta = ledger.get_asset_metadata("ASSET_CHANGED")
    assert meta["_integrity_status"] == "changed"


def test_probe_allows_unknown_local_asset_for_chain_fallback(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))

    probe = AssetAvailabilityProbe(ledger)
    result = probe.inspect("UNKNOWN_ASSET")

    assert result.available is True
    assert result.error is None

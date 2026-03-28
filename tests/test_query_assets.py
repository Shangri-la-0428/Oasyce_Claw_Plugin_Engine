from __future__ import annotations

import os
from types import SimpleNamespace

from oasyce.services.facade import OasyceServiceFacade
from oasyce.storage.ledger import Ledger


def test_query_assets_does_not_hash_files_on_list(monkeypatch, tmp_path):
    file_path = tmp_path / "asset.txt"
    file_path.write_text("hello", encoding="utf-8")
    stat = os.stat(file_path)

    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_LIST_1",
        "owner-1",
        "hash-1",
        {
            "owner": "owner-1",
            "file_path": str(file_path),
            "file_hash": "hash-1",
            "_cached_size": stat.st_size,
            "_cached_mtime": stat.st_mtime,
        },
    )
    facade = OasyceServiceFacade(ledger=ledger, allow_local_fallback=True)

    monkeypatch.setattr(
        facade,
        "_get_settlement",
        lambda: SimpleNamespace(pools={}),
    )

    def _unexpected_open(*args, **kwargs):
        raise AssertionError("query_assets should not open files for integrity hashing")

    monkeypatch.setattr("builtins.open", _unexpected_open)

    result = facade.query_assets()

    assert result.success is True
    assert result.data[0]["hash_status"] == "ok"


def test_query_assets_uses_cached_projection_for_hash_status(monkeypatch, tmp_path):
    ok_file = tmp_path / "ok.txt"
    ok_file.write_text("ok", encoding="utf-8")
    ok_stat = os.stat(ok_file)

    stale_file = tmp_path / "stale.txt"
    stale_file.write_text("stale", encoding="utf-8")
    stale_stat = os.stat(stale_file)

    missing_file = tmp_path / "missing.txt"

    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_OK",
        "owner-1",
        "hash-ok",
        {
            "owner": "owner-1",
            "file_path": str(ok_file),
            "file_hash": "hash-ok",
            "_cached_size": ok_stat.st_size,
            "_cached_mtime": ok_stat.st_mtime,
        },
    )
    ledger.register_asset(
        "ASSET_STALE",
        "owner-1",
        "hash-stale",
        {
            "owner": "owner-1",
            "file_path": str(stale_file),
            "file_hash": "hash-stale",
            "_cached_size": stale_stat.st_size + 1,
            "_cached_mtime": stale_stat.st_mtime,
        },
    )
    ledger.register_asset(
        "ASSET_MISSING",
        "owner-1",
        "hash-missing",
        {
            "owner": "owner-1",
            "file_path": str(missing_file),
            "file_hash": "hash-missing",
        },
    )
    facade = OasyceServiceFacade(ledger=ledger, allow_local_fallback=True)

    monkeypatch.setattr(
        facade,
        "_get_settlement",
        lambda: SimpleNamespace(pools={}),
    )

    result = facade.query_assets()

    assert result.success is True
    by_id = {item["asset_id"]: item for item in result.data}
    assert by_id["ASSET_OK"]["hash_status"] == "ok"
    assert "hash_status" not in by_id["ASSET_STALE"]
    assert by_id["ASSET_MISSING"]["hash_status"] == "missing"

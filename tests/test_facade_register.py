from __future__ import annotations

import os
from types import SimpleNamespace

from oasyce.services.facade import OasyceServiceFacade
from oasyce.storage.ledger import Ledger


def test_register_rejects_duplicate_file_hash(monkeypatch, tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_DUP_1",
        "owner-1",
        "hash-dup",
        {"owner": "owner-1", "file_hash": "hash-dup"},
    )
    facade = OasyceServiceFacade(ledger=ledger, allow_local_fallback=True)

    file_path = tmp_path / "new.txt"
    file_path.write_text("new", encoding="utf-8")

    monkeypatch.setattr(
        facade,
        "_get_skills",
        lambda: SimpleNamespace(
            scan_data_skill=lambda fp: {"file_hash": "hash-dup"},
        ),
    )

    result = facade.register(
        file_path=str(file_path),
        owner="owner-2",
        tags=["beta"],
        rights_type="original",
        price_model="auto",
    )

    assert result.success is False
    assert "Duplicate: file already registered as ASSET_DUP_1" == result.error


def test_register_enforces_allowed_path_policy(monkeypatch, tmp_path):
    facade = OasyceServiceFacade(allow_local_fallback=True)

    file_path = tmp_path / "outside-home.txt"
    file_path.write_text("data", encoding="utf-8")

    monkeypatch.setattr(
        facade,
        "_get_skills",
        lambda: SimpleNamespace(
            scan_data_skill=lambda fp: {"file_hash": "hash-1"},
        ),
    )

    result = facade.register(
        file_path=str(file_path),
        owner="owner-1",
        tags=["beta"],
        rights_type="original",
        price_model="auto",
        enforce_allowed_paths=True,
    )

    assert result.success is False
    assert result.error == "file path not allowed"


def test_register_allows_symlinked_home_when_realpath_is_under_home(monkeypatch, tmp_path):
    facade = OasyceServiceFacade(allow_local_fallback=True)
    real_home = tmp_path / "real-home"
    real_home.mkdir()
    symlink_home = tmp_path / "symlink-home"
    symlink_home.symlink_to(real_home, target_is_directory=True)
    file_path = symlink_home / "inside-home.txt"
    file_path.write_text("data", encoding="utf-8")

    original_expanduser = os.path.expanduser
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: str(symlink_home) if path == "~" else original_expanduser(path),
    )
    monkeypatch.setattr(
        facade,
        "_get_skills",
        lambda: SimpleNamespace(
            scan_data_skill=lambda fp: {"file_hash": "hash-symlink-1"},
            classify_data_skill=lambda file_info: {"risk_level": "public"},
            generate_metadata_skill=lambda file_info, tags, owner=None, classification=None, rights_type="original", co_creators=None: {
                "asset_id": "ASSET_SYMLINK_META",
                "owner": owner,
                "tags": tags,
            },
            create_certificate_skill=lambda metadata: {**metadata, "asset_id": "ASSET_SYMLINK_1"},
            register_data_asset_skill=lambda signed, file_path=None, storage_backend=None: {
                "status": "success",
                "asset_id": signed["asset_id"],
            },
        ),
    )

    result = facade.register(
        file_path=str(file_path),
        owner="owner-1",
        tags=["beta"],
        rights_type="original",
        price_model="auto",
        enforce_allowed_paths=True,
    )

    assert result.success is True
    assert result.data["asset_id"] == "ASSET_SYMLINK_1"


def test_register_bundle_sets_bundle_metadata_and_response(monkeypatch, tmp_path):
    facade = OasyceServiceFacade(allow_local_fallback=True)
    zip_path = tmp_path / "bundle.zip"
    zip_path.write_bytes(b"zip-bytes")
    original_expanduser = os.path.expanduser
    captured = {}

    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path: str(tmp_path) if path == "~" else original_expanduser(path),
    )

    monkeypatch.setattr(
        facade,
        "_get_skills",
        lambda: SimpleNamespace(
            scan_data_skill=lambda fp: {"file_hash": "bundle-hash-1"},
            classify_data_skill=lambda file_info: {"risk_level": "public"},
            generate_metadata_skill=lambda file_info, tags, owner=None, classification=None, rights_type="original", co_creators=None: {
                "asset_id": "ASSET_BUNDLE_META",
                "owner": owner,
                "tags": tags,
            },
            create_certificate_skill=lambda metadata: {**metadata, "asset_id": "ASSET_BUNDLE_1"},
            register_data_asset_skill=lambda signed, file_path=None, storage_backend=None: (
                captured.update(
                    {"signed": signed, "file_path": file_path, "storage_backend": storage_backend}
                )
                or {"status": "success", "asset_id": signed["asset_id"]}
            ),
        ),
    )

    result = facade.register_bundle(
        zip_path=str(zip_path),
        owner="owner-1",
        tags=["beta", "launch"],
        bundle_name="launch-pack",
        file_count=2,
        file_names=["a.txt", "b.txt"],
        enforce_allowed_paths=True,
    )

    assert result.success is True
    assert result.data == {
        "status": "success",
        "asset_id": "ASSET_BUNDLE_1",
        "file_hash": "bundle-hash-1",
        "owner": "owner-1",
        "price_model": "auto",
        "rights_type": "original",
        "bundle_name": "launch-pack",
        "tags": ["beta", "launch"],
        "file_count": 2,
        "file_names": ["a.txt", "b.txt"],
    }
    assert captured["file_path"] == str(zip_path.resolve())
    assert captured["signed"]["bundle"] is True
    assert captured["signed"]["bundle_name"] == "launch-pack"
    assert captured["signed"]["file_count"] == 2

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from oasyce.gui import app as gui_app
from oasyce.services.facade import ServiceResult


class _DummyHandler:
    def __init__(self, path: str = "/", headers: dict | None = None):
        self.path = path
        self.headers = headers or {}
        self.wfile = BytesIO()
        self.status = None
        self.sent_headers: dict[str, str] = {}

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        self.sent_headers[key] = value

    def end_headers(self) -> None:
        pass


def _read_json(handler: _DummyHandler) -> dict:
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def test_asset_update_route_uses_facade(monkeypatch):
    handler = _DummyHandler()
    seen = {}

    def _unexpected(*args, **kwargs):
        raise AssertionError("GUI handler should not write ledger directly for asset/update")

    monkeypatch.setattr(
        gui_app,
        "_ledger",
        SimpleNamespace(
            get_asset_metadata=_unexpected,
            update_asset_metadata=_unexpected,
        ),
    )
    monkeypatch.setattr(gui_app, "_default_identity", lambda: "owner-1")

    def _update_asset_metadata(asset_id, updates, owner="", signature=None):
        seen.update(
            {
                "asset_id": asset_id,
                "updates": updates,
                "owner": owner,
                "signature": signature,
            }
        )
        return ServiceResult(
            success=True,
            data={"asset_id": asset_id, "updated_keys": list(updates.keys())},
        )

    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(update_asset_metadata=_update_asset_metadata),
    )

    gui_app._Handler._handle_assets(  # type: ignore[arg-type]
        handler,
        "/api/asset/update",
        {"asset_id": "ASSET_1", "tags": ["beta", "launch"]},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert seen == {
        "asset_id": "ASSET_1",
        "updates": {"tags": ["beta", "launch"]},
        "owner": "owner-1",
        "signature": None,
    }
    assert body == {"ok": True, "asset_id": "ASSET_1", "tags": ["beta", "launch"]}


def test_asset_update_route_maps_owner_conflict_to_403(monkeypatch):
    handler = _DummyHandler()

    def _unexpected(*args, **kwargs):
        raise AssertionError("GUI handler should not read/write ledger directly for asset/update")

    monkeypatch.setattr(
        gui_app,
        "_ledger",
        SimpleNamespace(
            get_asset_metadata=_unexpected,
            update_asset_metadata=_unexpected,
        ),
    )
    monkeypatch.setattr(gui_app, "_default_identity", lambda: "intruder-1")
    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(
            update_asset_metadata=lambda *args, **kwargs: ServiceResult(
                success=False,
                error="Only the asset owner can update metadata",
            )
        ),
    )

    gui_app._Handler._handle_assets(  # type: ignore[arg-type]
        handler,
        "/api/asset/update",
        {"asset_id": "ASSET_1", "tags": ["beta"]},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 403
    assert body["error"] == "Only the asset owner can update metadata"


def test_reregister_route_uses_facade(monkeypatch):
    handler = _DummyHandler()
    seen = {}

    def _unexpected(*args, **kwargs):
        raise AssertionError("GUI handler should not touch ledger directly for re-register")

    monkeypatch.setattr(
        gui_app,
        "_ledger",
        SimpleNamespace(
            get_asset_metadata=_unexpected,
            set_asset_metadata=_unexpected,
        ),
    )
    monkeypatch.setattr(gui_app, "_default_identity", lambda: "owner-1")

    def _reregister_asset(asset_id, owner="", signature=None, trace_id=None):
        seen.update(
            {
                "asset_id": asset_id,
                "owner": owner,
                "signature": signature,
                "trace_id": trace_id,
            }
        )
        return ServiceResult(
            success=True,
            data={
                "asset_id": asset_id,
                "changed": True,
                "version": 2,
                "file_hash": "new-hash-123",
            },
        )

    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(reregister_asset=_reregister_asset),
    )

    gui_app._Handler._handle_assets(  # type: ignore[arg-type]
        handler,
        "/api/re-register",
        {"asset_id": "ASSET_1"},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert seen == {
        "asset_id": "ASSET_1",
        "owner": "owner-1",
        "signature": None,
        "trace_id": None,
    }
    assert body == {"ok": True, "version": 2, "file_hash": "new-hash-123"}


def test_register_route_uses_facade(monkeypatch):
    handler = _DummyHandler(headers={"X-Trace-Id": "trace-register-route"})
    seen = {}

    monkeypatch.setattr("oasyce.identity.Wallet.exists", lambda wallet_path=None: True)
    monkeypatch.setattr(
        gui_app,
        "_get_skills",
        lambda: (_ for _ in ()).throw(
            AssertionError("GUI handler should not call skills directly for register")
        ),
    )
    monkeypatch.setattr(
        gui_app,
        "_ledger",
        SimpleNamespace(
            list_assets=lambda: (_ for _ in ()).throw(
                AssertionError("GUI handler should not inspect ledger directly for register")
            )
        ),
    )

    def _register(**kwargs):
        seen.update(kwargs)
        return ServiceResult(
            success=True,
            data={
                "asset_id": "ASSET_REGISTER_1",
                "file_hash": "hash-1",
                "owner": kwargs["owner"],
                "price_model": kwargs["price_model"],
                "rights_type": kwargs["rights_type"],
            },
            trace_id=kwargs.get("trace_id"),
        )

    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(register=_register),
    )

    gui_app._Handler._handle_assets(  # type: ignore[arg-type]
        handler,
        "/api/register",
        {
            "file_path": str(Path(__file__).resolve()),
            "owner": "owner-1",
            "tags": ["beta", "launch"],
            "rights_type": "original",
            "price_model": "auto",
        },
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert seen == {
        "file_path": str(Path(__file__).resolve()),
        "owner": "owner-1",
        "tags": ["beta", "launch"],
        "rights_type": "original",
        "co_creators": None,
        "price_model": "auto",
        "manual_price": None,
        "trace_id": "trace-register-route",
        "enforce_allowed_paths": True,
        "allowed_price_models": ["auto", "fixed", "floor"],
    }
    assert body == {
        "ok": True,
        "asset_id": "ASSET_REGISTER_1",
        "file_hash": "hash-1",
        "owner": "owner-1",
        "price_model": "auto",
        "rights_type": "original",
        "trace_id": "trace-register-route",
        "state": "success",
        "retryable": False,
    }


def test_register_bundle_route_uses_facade(monkeypatch, tmp_path):
    handler = _DummyHandler()
    seen = {}
    original_expanduser = gui_app.os.path.expanduser

    class _Form:
        def get_files(self, name):
            assert name == "files"
            return [
                SimpleNamespace(filename="a.txt", file=BytesIO(b"alpha")),
                SimpleNamespace(filename="b.txt", file=BytesIO(b"beta")),
            ]

        def getfirst(self, name, default=None):
            mapping = {
                "name": "launch-pack",
                "owner": "owner-1",
                "tags": "beta, launch",
            }
            return mapping.get(name, default)

    monkeypatch.setattr(
        gui_app,
        "_MultipartForm",
        lambda handler, content_type: _Form(),
    )
    monkeypatch.setattr(
        gui_app,
        "_get_skills",
        lambda: (_ for _ in ()).throw(
            AssertionError("GUI handler should not call skills directly for register-bundle")
        ),
    )
    monkeypatch.setattr(
        gui_app.os.path,
        "expanduser",
        lambda path: str(tmp_path) if path == "~" else original_expanduser(path),
    )

    def _register_bundle(**kwargs):
        seen.update(kwargs)
        return ServiceResult(
            success=True,
            data={
                "asset_id": "ASSET_BUNDLE_1",
                "file_hash": "bundle-hash-1",
                "owner": kwargs["owner"],
                "bundle_name": kwargs["bundle_name"],
                "tags": kwargs["tags"],
                "file_count": kwargs["file_count"],
                "file_names": kwargs["file_names"],
            },
        )

    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(register_bundle=_register_bundle),
    )

    gui_app._Handler._handle_assets(  # type: ignore[arg-type]
        handler,
        "/api/register-bundle",
        {},
        "multipart/form-data; boundary=test",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert seen["owner"] == "owner-1"
    assert seen["bundle_name"] == "launch-pack"
    assert seen["tags"] == ["beta", "launch"]
    assert seen["file_count"] == 2
    assert seen["file_names"] == ["a.txt", "b.txt"]
    assert seen["enforce_allowed_paths"] is True
    assert seen["zip_path"].endswith(".zip")
    assert body == {
        "ok": True,
        "asset_id": "ASSET_BUNDLE_1",
        "file_hash": "bundle-hash-1",
        "owner": "owner-1",
        "bundle_name": "launch-pack",
        "tags": ["beta", "launch"],
        "file_count": 2,
        "file_names": ["a.txt", "b.txt"],
    }


def test_reregister_route_preserves_no_change_response(monkeypatch):
    handler = _DummyHandler()

    def _unexpected(*args, **kwargs):
        raise AssertionError("GUI handler should not touch ledger directly for re-register")

    monkeypatch.setattr(
        gui_app,
        "_ledger",
        SimpleNamespace(
            get_asset_metadata=_unexpected,
            set_asset_metadata=_unexpected,
        ),
    )
    monkeypatch.setattr(gui_app, "_default_identity", lambda: "owner-1")
    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(
            reregister_asset=lambda *args, **kwargs: ServiceResult(
                success=True,
                data={"asset_id": "ASSET_1", "changed": False, "message": "no changes detected"},
            )
        ),
    )

    gui_app._Handler._handle_assets(  # type: ignore[arg-type]
        handler,
        "/api/re-register",
        {"asset_id": "ASSET_1"},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert body == {"ok": False, "message": "no changes detected"}


def test_stake_route_uses_facade(monkeypatch):
    handler = _DummyHandler()
    seen = {}

    def _unexpected(*args, **kwargs):
        raise AssertionError("GUI handler should not touch ledger directly for stake")

    monkeypatch.setattr(
        gui_app,
        "_ledger",
        SimpleNamespace(update_stake=_unexpected, get_stakes_summary=_unexpected),
    )
    monkeypatch.setattr(gui_app, "_default_identity", lambda: "staker-1")

    def _stake_node(node_id, staker, amount, signature=None):
        seen.update(
            {
                "node_id": node_id,
                "staker": staker,
                "amount": amount,
                "signature": signature,
            }
        )
        return ServiceResult(
            success=True,
            data={"node_id": node_id, "total_stake": amount},
        )

    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(stake_node=_stake_node),
    )

    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler,
        "/api/stake",
        {"node_id": "validator-1", "amount": 25},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert seen == {
        "node_id": "validator-1",
        "staker": "staker-1",
        "amount": 25.0,
        "signature": None,
    }
    assert body == {"ok": True, "node_id": "validator-1", "total_stake": 25.0}


def test_stake_route_maps_service_unavailable(monkeypatch):
    handler = _DummyHandler()

    def _unexpected(*args, **kwargs):
        raise AssertionError("GUI handler should not touch ledger directly for stake")

    monkeypatch.setattr(
        gui_app,
        "_ledger",
        SimpleNamespace(update_stake=_unexpected, get_stakes_summary=_unexpected),
    )
    monkeypatch.setattr(gui_app, "_default_identity", lambda: "staker-1")
    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(
            stake_node=lambda *args, **kwargs: ServiceResult(
                success=False,
                error="Ledger not available",
            )
        ),
    )

    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler,
        "/api/stake",
        {"node_id": "validator-1", "amount": 25},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 503
    assert body["error"] == "Ledger not available"


def test_device_export_route_uses_account_service(monkeypatch):
    handler = _DummyHandler()

    monkeypatch.setattr(
        "oasyce.services.account_service.export_device_bundle_data_payload",
        lambda readonly=False: {
            "ok": True,
            "bundle": {
                "kind": "oasyce_trusted_device_bundle",
                "version": 1,
                "bundle_mode": "signing" if not readonly else "readonly",
            },
            "bundle_mode": "signing" if not readonly else "readonly",
            "filename": "oasyce-device-signing.json",
            "account_address": "oasyce1shared",
            "signer_name": "oasyce-agent",
        },
    )

    gui_app._Handler._handle_identity(  # type: ignore[arg-type]
        handler,
        "/api/device/export",
        {"readonly": False},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert body["ok"] is True
    assert body["bundle_mode"] == "signing"
    assert body["filename"] == "oasyce-device-signing.json"


def test_device_join_route_accepts_bundle_payload(monkeypatch):
    handler = _DummyHandler()
    seen = {}

    def _join_device_payload(**kwargs):
        seen.update(kwargs)
        return {
            "ok": True,
            "account_address": "oasyce1shared",
            "readonly": False,
            "write_ready": True,
            "verify": {"ok": True, "issues": [], "warnings": []},
        }

    monkeypatch.setattr(
        "oasyce.services.account_service.join_device_payload",
        _join_device_payload,
    )

    gui_app._Handler._handle_identity(  # type: ignore[arg-type]
        handler,
        "/api/device/join",
        {
            "bundle": {
                "kind": "oasyce_trusted_device_bundle",
                "version": 1,
                "account_address": "oasyce1shared",
                "bundle_mode": "readonly",
            }
        },
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert seen["bundle"] == {
        "kind": "oasyce_trusted_device_bundle",
        "version": 1,
        "account_address": "oasyce1shared",
        "bundle_mode": "readonly",
    }
    assert body["ok"] is True

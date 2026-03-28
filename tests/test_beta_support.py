from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace

from oasyce.gui import app as gui_app
from oasyce.services.beta_support import BetaSupportStore
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


def test_support_beta_endpoint_returns_recent_events_failures_and_transactions(monkeypatch):
    store = BetaSupportStore(max_events=10)
    store.record("register.success", "trace-1", "info", {"asset_id": "ASSET_1"}, now=1.0)
    store.record("buy.failed", "trace-2", "warning", {"asset_id": "ASSET_1"}, now=2.0)
    handler = _DummyHandler(path="/api/support/beta?limit=5&transactions_limit=2")

    monkeypatch.setattr(gui_app, "get_beta_support_store", lambda: store)
    monkeypatch.setattr(
        gui_app,
        "_get_query",
        lambda: SimpleNamespace(
            query_transactions=lambda limit=20: ServiceResult(
                success=True,
                data=[
                    {"tx_id": "tx-1", "kind": "buy", "status": "success"},
                    {"tx_id": "tx-2", "kind": "register", "status": "success"},
                ][:limit],
            )
        ),
    )

    gui_app._Handler.do_GET(handler)  # type: ignore[arg-type]

    body = _read_json(handler)
    assert handler.status == 200
    assert body["ok"] is True
    assert body["events"][0]["event"] == "buy.failed"
    assert body["failures"][0]["event"] == "buy.failed"
    assert len(body["transactions"]) == 2

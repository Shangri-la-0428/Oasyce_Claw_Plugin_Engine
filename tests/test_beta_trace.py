from __future__ import annotations

import json
import logging
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from oasyce.gui import app as gui_app
from oasyce.services.facade import OasyceServiceFacade, ServiceResult


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


def test_quote_get_returns_trace_id_and_logs(caplog, monkeypatch):
    trace_id = "trace-quote-001"
    handler = _DummyHandler(
        path="/api/quote?asset_id=ASSET_1&amount=10",
        headers={"X-Trace-Id": trace_id},
    )

    monkeypatch.setattr(gui_app, "_ledger", None)
    monkeypatch.setattr(
        gui_app,
        "_get_query",
        lambda: SimpleNamespace(
            quote=lambda asset_id, amount, trace_id=None: ServiceResult(
                success=True,
                data={
                    "asset_id": asset_id,
                    "payment_oas": amount,
                    "equity_minted": 1.25,
                    "spot_price_before": 1.0,
                    "spot_price_after": 1.2,
                    "price_impact_pct": 20.0,
                    "protocol_fee": 0.3,
                    "burn_amount": 0.2,
                },
                trace_id=trace_id,
            )
        ),
    )

    with caplog.at_level(logging.INFO, logger=gui_app.__name__):
        gui_app._Handler.do_GET(handler)  # type: ignore[arg-type]

    body = _read_json(handler)
    assert handler.status == 200
    assert body["ok"] is True
    assert body["state"] == "success"
    assert body["retryable"] is False
    assert body["trace_id"] == trace_id
    assert "trace-quote-001" in caplog.text
    assert "quote.success" in caplog.text


def test_buy_post_returns_trace_id_and_logs(caplog, monkeypatch):
    trace_id = "trace-buy-001"
    handler = _DummyHandler(headers={"X-Trace-Id": trace_id})

    monkeypatch.setattr(gui_app, "_ledger", SimpleNamespace(get_asset_metadata=lambda aid: None))
    monkeypatch.setattr(
        gui_app, "_get_notification_service", lambda: SimpleNamespace(notify=lambda *a, **k: None)
    )
    monkeypatch.setattr(
        gui_app,
        "_get_settlement",
        lambda: (_ for _ in ()).throw(
            AssertionError("GUI buy handler should not inspect settlement state directly")
        ),
    )
    monkeypatch.setattr(gui_app, "_buy_cooldowns", {})
    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(
            buy=lambda aid, buyer, amount, trace_id=None: ServiceResult(
                success=True,
                data={
                    "settled": True,
                    "receipt_id": "rcpt-1",
                    "quote": {
                        "equity_minted": 2.0,
                        "spot_price_after": 1.5,
                    },
                    "equity_balance": 2.0,
                },
                trace_id=trace_id,
            )
        ),
    )

    with caplog.at_level(logging.INFO, logger=gui_app.__name__):
        gui_app._Handler._handle_trading(  # type: ignore[arg-type]
            handler,
            "/api/buy",
            {"asset_id": "ASSET_1", "buyer": "buyer-1", "amount": 10},
            "application/json",
        )

    body = _read_json(handler)
    assert handler.status == 200
    assert body["trace_id"] == trace_id
    assert body["ok"] is True
    assert body["state"] == "success"
    assert body["retryable"] is False
    assert body["equity_balance"] == 2.0
    assert "trace-buy-001" in caplog.text
    assert "buy.success" in caplog.text


def test_register_post_returns_trace_id_and_logs(caplog, monkeypatch, tmp_path):
    trace_id = "trace-register-001"
    handler = _DummyHandler(headers={"X-Trace-Id": trace_id})

    home_file = Path.home() / ".oasyce-test-beta-trace.txt"
    home_file.write_text("beta trace", encoding="utf-8")
    monkeypatch.setattr(
        gui_app,
        "_get_skills",
        lambda: (_ for _ in ()).throw(
            AssertionError("GUI register handler should not call skills directly")
        ),
    )
    monkeypatch.setattr(
        gui_app,
        "_ledger",
        SimpleNamespace(
            list_assets=lambda: (_ for _ in ()).throw(
                AssertionError("GUI register handler should not inspect ledger directly")
            )
        ),
    )
    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(
            register=lambda **kwargs: ServiceResult(
                success=True,
                data={
                    "asset_id": "ASSET_TRACE",
                    "file_hash": "abc123",
                    "owner": kwargs["owner"],
                    "price_model": kwargs["price_model"],
                    "rights_type": kwargs["rights_type"],
                },
                trace_id=kwargs.get("trace_id"),
            )
        ),
    )
    monkeypatch.setattr("oasyce.identity.Wallet.exists", lambda wallet_path=None: True)

    try:
        with caplog.at_level(logging.INFO, logger=gui_app.__name__):
            gui_app._Handler._handle_assets(  # type: ignore[arg-type]
                handler,
                "/api/register",
                {
                    "file_path": str(home_file),
                    "owner": "owner-1",
                    "tags": ["beta"],
                    "rights_type": "original",
                    "price_model": "auto",
                },
                "application/json",
            )
    finally:
        home_file.unlink(missing_ok=True)

    body = _read_json(handler)
    assert handler.status == 200
    assert body["trace_id"] == trace_id
    assert body["ok"] is True
    assert body["state"] == "success"
    assert body["retryable"] is False
    assert "trace-register-001" in caplog.text
    assert "register.success" in caplog.text


def test_quote_invalid_amount_marks_failed_state(monkeypatch):
    handler = _DummyHandler(
        path="/api/quote?asset_id=ASSET_1&amount=bad",
        headers={"X-Trace-Id": "trace-quote-invalid"},
    )

    monkeypatch.setattr(gui_app, "_ledger", None)

    gui_app._Handler.do_GET(handler)  # type: ignore[arg-type]

    body = _read_json(handler)
    assert handler.status == 400
    assert body["ok"] is False
    assert body["state"] == "failed"
    assert body["retryable"] is False
    assert body["trace_id"] == "trace-quote-invalid"


def test_buy_cooldown_marks_retryable_state(monkeypatch):
    trace_id = "trace-buy-retryable"
    handler = _DummyHandler(headers={"X-Trace-Id": trace_id})

    monkeypatch.setattr(gui_app, "_ledger", SimpleNamespace(get_asset_metadata=lambda aid: None))
    monkeypatch.setattr(gui_app, "_buy_cooldowns", {("buyer-1", "ASSET_1"): time.time()})

    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler,
        "/api/buy",
        {"asset_id": "ASSET_1", "buyer": "buyer-1", "amount": 10},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 429
    assert body["ok"] is False
    assert body["state"] == "retryable"
    assert body["retryable"] is True
    assert body["trace_id"] == trace_id


def test_register_missing_wallet_marks_failed_state(monkeypatch):
    trace_id = "trace-register-failed"
    handler = _DummyHandler(headers={"X-Trace-Id": trace_id})

    monkeypatch.setattr("oasyce.identity.Wallet.exists", lambda wallet_path=None: False)

    gui_app._Handler._handle_assets(  # type: ignore[arg-type]
        handler,
        "/api/register",
        {
            "file_path": str(Path.home() / "missing.txt"),
            "owner": "owner-1",
            "tags": ["beta"],
            "rights_type": "original",
            "price_model": "auto",
        },
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 400
    assert body["ok"] is False
    assert body["state"] == "failed"
    assert body["retryable"] is False
    assert body["trace_id"] == trace_id


def test_facade_quote_logs_trace_id(caplog, monkeypatch):
    facade = OasyceServiceFacade(allow_local_fallback=True)
    quote_result = SimpleNamespace(
        asset_id="ASSET_1",
        payment_oas=10.0,
        equity_minted=1.0,
        spot_price_before=1.0,
        spot_price_after=1.2,
        price_impact_pct=20.0,
        protocol_fee=0.3,
        burn_amount=0.2,
    )
    monkeypatch.setattr(facade, "_strict_chain_mode", lambda: False)
    monkeypatch.setattr(
        facade,
        "_get_settlement",
        lambda: SimpleNamespace(quote=lambda asset_id, amount: quote_result),
    )

    with caplog.at_level(logging.INFO, logger="oasyce.services.facade"):
        result = facade.quote("ASSET_1", 10.0, trace_id="trace-facade-quote-001")

    assert result.success is True
    assert result.trace_id == "trace-facade-quote-001"
    assert "trace-facade-quote-001" in caplog.text
    assert "facade.quote.success" in caplog.text


def test_facade_buy_logs_trace_id(caplog, monkeypatch):
    facade = OasyceServiceFacade(allow_local_fallback=True)
    receipt = SimpleNamespace(
        receipt_id="rcpt-1",
        asset_id="ASSET_1",
        buyer="buyer-1",
        amount_oas=10.0,
        status=SimpleNamespace(value="settled"),
        quote=SimpleNamespace(
            equity_minted=2.0,
            spot_price_after=1.5,
            protocol_fee=0.3,
        ),
    )
    settlement = SimpleNamespace(
        get_pool=lambda aid: object(),
        execute=lambda aid, buyer, amount: receipt,
    )

    monkeypatch.setattr(facade, "_verify_agent", lambda buyer, signature=None: True)
    monkeypatch.setattr(facade, "_strict_chain_mode", lambda: False)
    monkeypatch.setattr(facade, "_get_settlement", lambda: settlement)
    monkeypatch.setattr(facade, "get_equity_access_level", lambda aid, buyer: "L0")

    with caplog.at_level(logging.INFO, logger="oasyce.services.facade"):
        result = facade.buy("ASSET_1", "buyer-1", 10.0, trace_id="trace-facade-buy-001")

    assert result.success is True
    assert result.trace_id == "trace-facade-buy-001"
    assert "trace-facade-buy-001" in caplog.text
    assert "facade.buy.success" in caplog.text

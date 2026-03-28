from __future__ import annotations

import json
from io import BytesIO
from types import SimpleNamespace
import time

from oasyce.client import Oasyce
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


def _read_json(handler: _DummyHandler):
    return json.loads(handler.wfile.getvalue().decode("utf-8"))


def test_portfolio_agent_format_returns_machine_contract(monkeypatch):
    handler = _DummyHandler(
        path="/api/portfolio?buyer=agent-1&format=agent",
        headers={"X-Trace-Id": "trace-portfolio-001"},
    )
    monkeypatch.setattr(
        gui_app,
        "_get_query",
        lambda: SimpleNamespace(
            get_portfolio=lambda buyer: ServiceResult(
                success=True,
                data={
                    "agent_id": buyer,
                    "holdings": [
                        {
                            "asset_id": "ASSET_1",
                            "tokens": 2.5,
                            "pct": 12.5,
                            "access_level": "L1",
                            "value_oas": 20.0,
                        }
                    ],
                },
            )
        ),
    )

    gui_app._Handler.do_GET(handler)  # type: ignore[arg-type]

    body = _read_json(handler)
    assert handler.status == 200
    assert body["ok"] is True
    assert body["action"] == "portfolio"
    assert body["state"] == "success"
    assert body["retryable"] is False
    assert body["trace_id"] == "trace-portfolio-001"
    assert body["data"]["buyer"] == "agent-1"
    assert body["data"]["holdings"][0]["asset_id"] == "ASSET_1"
    assert body["data"]["holdings"][0]["shares"] == 2.5


def test_portfolio_agent_format_failure_is_retryable(monkeypatch):
    handler = _DummyHandler(
        path="/api/portfolio?buyer=agent-1&format=agent",
        headers={"X-Trace-Id": "trace-portfolio-fail"},
    )
    monkeypatch.setattr(
        gui_app,
        "_get_query",
        lambda: SimpleNamespace(
            get_portfolio=lambda buyer: ServiceResult(
                success=False,
                error="ledger unavailable",
            )
        ),
    )

    gui_app._Handler.do_GET(handler)  # type: ignore[arg-type]

    body = _read_json(handler)
    assert handler.status == 500
    assert body["ok"] is False
    assert body["action"] == "portfolio"
    assert body["state"] == "retryable"
    assert body["retryable"] is True
    assert body["trace_id"] == "trace-portfolio-fail"
    assert body["error"] == "ledger unavailable"
    assert body["data"]["holdings"] == []


def test_client_core_methods_forward_trace_id(monkeypatch):
    client = Oasyce("http://localhost:8080", token="test-token")
    calls = []

    def fake_request(method, path, body=None, headers=None):
        calls.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": headers or {},
            }
        )
        return {}

    monkeypatch.setattr(client, "_request", fake_request)

    client.register("/tmp/demo.txt", "agent-1", trace_id="trace-register")
    client.quote("ASSET_1", amount=10, trace_id="trace-quote")
    client.buy(
        "ASSET_1",
        "agent-1",
        amount=10.0,
        trace_id="trace-buy",
        idempotency_key="buy-once-001",
    )

    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/api/register"
    assert calls[0]["headers"]["X-Trace-Id"] == "trace-register"
    assert calls[0]["body"]["price_model"] == "auto"

    assert calls[1]["method"] == "GET"
    assert calls[1]["path"] == "/api/quote?asset_id=ASSET_1&amount=10"
    assert calls[1]["headers"]["X-Trace-Id"] == "trace-quote"

    assert calls[2]["method"] == "POST"
    assert calls[2]["path"] == "/api/buy"
    assert calls[2]["headers"]["X-Trace-Id"] == "trace-buy"
    assert calls[2]["headers"]["Idempotency-Key"] == "buy-once-001"


def test_client_machine_core_methods_use_agent_format(monkeypatch):
    client = Oasyce("http://localhost:8080", token="test-token")
    calls = []

    def fake_request(method, path, body=None, headers=None):
        calls.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": headers or {},
            }
        )
        return {}

    monkeypatch.setattr(client, "_request", fake_request)

    client.register("/tmp/demo.txt", "agent-1", machine=True, trace_id="trace-reg-agent")
    client.quote("ASSET_1", amount=10, machine=True, trace_id="trace-quote-agent")
    client.buy(
        "ASSET_1",
        "agent-1",
        amount=10.0,
        machine=True,
        trace_id="trace-buy-agent",
        idempotency_key="buy-agent-001",
    )

    assert calls[0]["body"]["format"] == "agent"
    assert calls[1]["path"] == "/api/quote?asset_id=ASSET_1&amount=10&format=agent"
    assert calls[2]["body"]["format"] == "agent"
    assert calls[2]["headers"]["Idempotency-Key"] == "buy-agent-001"


def test_client_portfolio_machine_mode_uses_agent_format(monkeypatch):
    client = Oasyce("http://localhost:8080", token="test-token")
    seen = {}

    def fake_request(method, path, body=None, headers=None):
        seen.update(
            {
                "method": method,
                "path": path,
                "body": body,
                "headers": headers or {},
            }
        )
        return {"ok": True}

    monkeypatch.setattr(client, "_request", fake_request)

    client.portfolio("agent-1", machine=True, trace_id="trace-portfolio")

    assert seen["method"] == "GET"
    assert seen["path"] == "/api/portfolio?buyer=agent-1&format=agent"
    assert seen["headers"]["X-Trace-Id"] == "trace-portfolio"


def test_quote_agent_format_returns_normalized_contract(monkeypatch):
    handler = _DummyHandler(
        path="/api/quote?asset_id=ASSET_1&amount=10&format=agent",
        headers={"X-Trace-Id": "trace-quote-agent"},
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

    gui_app._Handler.do_GET(handler)  # type: ignore[arg-type]

    body = _read_json(handler)
    assert handler.status == 200
    assert body["ok"] is True
    assert body["action"] == "quote"
    assert body["data"]["asset_id"] == "ASSET_1"
    assert body["data"]["amount_oas"] == 10.0
    assert body["data"]["payment_oas"] == 10.0


def test_register_agent_format_returns_normalized_contract(monkeypatch):
    handler = _DummyHandler(headers={"X-Trace-Id": "trace-register-agent"})
    monkeypatch.setattr("oasyce.identity.Wallet.exists", lambda wallet_path=None: True)
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

    gui_app._Handler._handle_assets(  # type: ignore[arg-type]
        handler,
        "/api/register",
        {
            "file_path": str(__file__),
            "owner": "owner-1",
            "tags": ["beta"],
            "rights_type": "original",
            "price_model": "auto",
            "format": "agent",
        },
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert body["ok"] is True
    assert body["action"] == "register"
    assert body["data"]["asset_id"] == "ASSET_TRACE"
    assert body["data"]["owner"] == "owner-1"


def test_buy_agent_format_returns_normalized_contract(monkeypatch):
    handler = _DummyHandler(headers={"X-Trace-Id": "trace-buy-agent"})

    monkeypatch.setattr(gui_app, "_ledger", SimpleNamespace(get_asset_metadata=lambda aid: None))
    monkeypatch.setattr(gui_app, "_get_notification_service", lambda: SimpleNamespace(notify=lambda *a, **k: None))
    monkeypatch.setattr(gui_app, "_get_settlement", lambda: SimpleNamespace(get_pool=lambda aid: None))
    monkeypatch.setattr(gui_app, "_buy_cooldowns", {})
    monkeypatch.setattr(gui_app, "_buy_idempotency_cache", {})
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
                },
                trace_id=trace_id,
            )
        ),
    )

    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler,
        "/api/buy",
        {"asset_id": "ASSET_1", "buyer": "buyer-1", "amount": 10, "format": "agent"},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 200
    assert body["ok"] is True
    assert body["action"] == "buy"
    assert body["data"]["asset_id"] == "ASSET_1"
    assert body["data"]["buyer"] == "buyer-1"
    assert body["data"]["receipt_id"] == "rcpt-1"


def test_buy_reuses_cached_result_for_same_idempotency_key(monkeypatch):
    handler1 = _DummyHandler(
        headers={
            "X-Trace-Id": "trace-buy-idem",
            "Idempotency-Key": "buy-once-123",
        }
    )
    handler2 = _DummyHandler(
        headers={
            "X-Trace-Id": "trace-buy-idem",
            "Idempotency-Key": "buy-once-123",
        }
    )
    calls = {"count": 0}

    monkeypatch.setattr(gui_app, "_ledger", SimpleNamespace(get_asset_metadata=lambda aid: None))
    monkeypatch.setattr(gui_app, "_get_notification_service", lambda: SimpleNamespace(notify=lambda *a, **k: None))
    monkeypatch.setattr(gui_app, "_get_settlement", lambda: SimpleNamespace(get_pool=lambda aid: None))
    monkeypatch.setattr(gui_app, "_buy_cooldowns", {})
    monkeypatch.setattr(gui_app, "_buy_idempotency_cache", {})

    def _buy(aid, buyer, amount, trace_id=None):
        calls["count"] += 1
        return ServiceResult(
            success=True,
            data={
                "settled": True,
                "receipt_id": "rcpt-idem-1",
                "quote": {"equity_minted": 2.0, "spot_price_after": 1.5},
            },
            trace_id=trace_id,
        )

    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(buy=_buy),
    )

    payload = {"asset_id": "ASSET_1", "buyer": "agent-1", "amount": 10}
    gui_app._Handler._handle_trading(handler1, "/api/buy", payload, "application/json")  # type: ignore[arg-type]
    gui_app._Handler._handle_trading(handler2, "/api/buy", payload, "application/json")  # type: ignore[arg-type]

    first = _read_json(handler1)
    second = _read_json(handler2)
    assert calls["count"] == 1
    assert first["receipt_id"] == "rcpt-idem-1"
    assert second["receipt_id"] == "rcpt-idem-1"
    assert second["idempotent_replay"] is True
    assert second["ok"] is True
    assert second["state"] == "success"


def test_buy_rejects_payload_mismatch_for_same_idempotency_key(monkeypatch):
    handler1 = _DummyHandler(
        headers={
            "X-Trace-Id": "trace-buy-idem-conflict",
            "Idempotency-Key": "buy-once-456",
        }
    )
    handler2 = _DummyHandler(
        headers={
            "X-Trace-Id": "trace-buy-idem-conflict",
            "Idempotency-Key": "buy-once-456",
        }
    )
    calls = {"count": 0}

    monkeypatch.setattr(gui_app, "_ledger", SimpleNamespace(get_asset_metadata=lambda aid: None))
    monkeypatch.setattr(gui_app, "_get_notification_service", lambda: SimpleNamespace(notify=lambda *a, **k: None))
    monkeypatch.setattr(gui_app, "_get_settlement", lambda: SimpleNamespace(get_pool=lambda aid: None))
    monkeypatch.setattr(gui_app, "_buy_cooldowns", {})
    monkeypatch.setattr(gui_app, "_buy_idempotency_cache", {})

    def _buy(aid, buyer, amount, trace_id=None):
        calls["count"] += 1
        return ServiceResult(
            success=True,
            data={
                "settled": True,
                "receipt_id": "rcpt-idem-2",
                "quote": {"equity_minted": 2.0, "spot_price_after": 1.5},
            },
            trace_id=trace_id,
        )

    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(buy=_buy),
    )

    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler1,
        "/api/buy",
        {"asset_id": "ASSET_1", "buyer": "agent-1", "amount": 10},
        "application/json",
    )
    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler2,
        "/api/buy",
        {"asset_id": "ASSET_1", "buyer": "agent-1", "amount": 20},
        "application/json",
    )

    body = _read_json(handler2)
    assert calls["count"] == 1
    assert handler2.status == 409
    assert body["ok"] is False
    assert body["state"] == "failed"
    assert body["retryable"] is False
    assert "payload" in body["error"]


def test_buy_agent_rejects_payload_mismatch_with_machine_contract(monkeypatch):
    handler1 = _DummyHandler(
        headers={
            "X-Trace-Id": "trace-buy-agent-idem-conflict",
            "Idempotency-Key": "buy-agent-once-456",
        }
    )
    handler2 = _DummyHandler(
        headers={
            "X-Trace-Id": "trace-buy-agent-idem-conflict",
            "Idempotency-Key": "buy-agent-once-456",
        }
    )

    monkeypatch.setattr(gui_app, "_ledger", SimpleNamespace(get_asset_metadata=lambda aid: None))
    monkeypatch.setattr(
        gui_app, "_get_notification_service", lambda: SimpleNamespace(notify=lambda *a, **k: None)
    )
    monkeypatch.setattr(gui_app, "_get_settlement", lambda: SimpleNamespace(get_pool=lambda aid: None))
    monkeypatch.setattr(gui_app, "_buy_cooldowns", {})
    monkeypatch.setattr(gui_app, "_buy_idempotency_cache", {})
    monkeypatch.setattr(
        gui_app,
        "_get_facade",
        lambda: SimpleNamespace(
            buy=lambda aid, buyer, amount, trace_id=None: ServiceResult(
                success=True,
                data={
                    "settled": True,
                    "receipt_id": "rcpt-agent-idem-2",
                    "quote": {"equity_minted": 2.0, "spot_price_after": 1.5},
                },
                trace_id=trace_id,
            )
        ),
    )

    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler1,
        "/api/buy",
        {"asset_id": "ASSET_1", "buyer": "agent-1", "amount": 10, "format": "agent"},
        "application/json",
    )
    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler2,
        "/api/buy",
        {"asset_id": "ASSET_1", "buyer": "agent-1", "amount": 20, "format": "agent"},
        "application/json",
    )

    body = _read_json(handler2)
    assert handler2.status == 409
    assert body["action"] == "buy"
    assert body["ok"] is False
    assert body["state"] == "failed"
    assert body["retryable"] is False
    assert body["trace_id"] == "trace-buy-agent-idem-conflict"
    assert body["data"]["asset_id"] == "ASSET_1"
    assert body["data"]["buyer"] == "agent-1"
    assert body["data"]["amount_oas"] == 20.0
    assert body["error"] == "idempotency key payload mismatch"
    assert body["idempotency_key"] == "buy-agent-once-456"


def test_buy_agent_cooldown_returns_retryable_machine_contract(monkeypatch):
    handler = _DummyHandler(headers={"X-Trace-Id": "trace-buy-agent-cooldown"})

    monkeypatch.setattr(gui_app, "_ledger", SimpleNamespace(get_asset_metadata=lambda aid: None))
    monkeypatch.setattr(
        gui_app, "_get_notification_service", lambda: SimpleNamespace(notify=lambda *a, **k: None)
    )
    monkeypatch.setattr(gui_app, "_get_settlement", lambda: SimpleNamespace(get_pool=lambda aid: None))
    monkeypatch.setattr(gui_app, "_buy_cooldowns", {("agent-1", "ASSET_1"): time.time()})
    monkeypatch.setattr(gui_app, "_buy_idempotency_cache", {})

    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler,
        "/api/buy",
        {"asset_id": "ASSET_1", "buyer": "agent-1", "amount": 10, "format": "agent"},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 429
    assert body["action"] == "buy"
    assert body["ok"] is False
    assert body["state"] == "retryable"
    assert body["retryable"] is True
    assert body["trace_id"] == "trace-buy-agent-cooldown"
    assert body["data"]["asset_id"] == "ASSET_1"
    assert body["data"]["buyer"] == "agent-1"
    assert body["data"]["amount_oas"] == 10.0
    assert body["error"].startswith("cooldown: wait ")


def test_buy_agent_unavailable_asset_returns_machine_contract(monkeypatch):
    handler = _DummyHandler(headers={"X-Trace-Id": "trace-buy-agent-unavailable"})

    monkeypatch.setattr(gui_app, "_ledger", SimpleNamespace(get_asset_metadata=lambda aid: None))
    monkeypatch.setattr(
        gui_app, "_get_notification_service", lambda: SimpleNamespace(notify=lambda *a, **k: None)
    )
    monkeypatch.setattr(gui_app, "_get_settlement", lambda: SimpleNamespace(get_pool=lambda aid: None))
    monkeypatch.setattr(gui_app, "_buy_cooldowns", {})
    monkeypatch.setattr(gui_app, "_buy_idempotency_cache", {})
    monkeypatch.setattr(
        gui_app,
        "_get_asset_availability_probe",
        lambda: SimpleNamespace(
            inspect=lambda aid: SimpleNamespace(
                available=False,
                http_status=409,
                error="UNAVAILABLE",
                message="Asset file is missing or modified",
            )
        ),
    )

    gui_app._Handler._handle_trading(  # type: ignore[arg-type]
        handler,
        "/api/buy",
        {"asset_id": "ASSET_1", "buyer": "agent-1", "amount": 10, "format": "agent"},
        "application/json",
    )

    body = _read_json(handler)
    assert handler.status == 409
    assert body["action"] == "buy"
    assert body["ok"] is False
    assert body["state"] == "failed"
    assert body["retryable"] is False
    assert body["trace_id"] == "trace-buy-agent-unavailable"
    assert body["data"]["asset_id"] == "ASSET_1"
    assert body["data"]["buyer"] == "agent-1"
    assert body["data"]["amount_oas"] == 10.0
    assert body["data"]["message"] == "Asset file is missing or modified"
    assert body["error"] == "UNAVAILABLE"

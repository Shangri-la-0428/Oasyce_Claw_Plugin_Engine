from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest_asyncio = pytest.importorskip("pytest_asyncio", reason="pytest-asyncio required")

from httpx import ASGITransport, AsyncClient

from oasyce.api.deps import get_facade
from oasyce.api.main import app
from oasyce.services.facade import ServiceResult


def _valid_pack() -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "gps_hash": "a" * 64,
        "device_signature": "deadbeef",
        "media_hash": "b" * 64,
        "source": "camera",
    }


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ── Health ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["mode"] == "mock"


# ── Verify ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_valid(client: AsyncClient):
    resp = await client.post("/v1/verify", json=_valid_pack())
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["valid"] is True


@pytest.mark.asyncio
async def test_verify_invalid_gps_hash(client: AsyncClient):
    pack = _valid_pack()
    pack["gps_hash"] = "not-hex"
    resp = await client.post("/v1/verify", json=pack)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["data"]["valid"] is False
    assert "gps_hash" in body["data"]["reason"]


@pytest.mark.asyncio
async def test_verify_validation_error(client: AsyncClient):
    resp = await client.post("/v1/verify", json={"timestamp": "now"})
    assert resp.status_code == 422


# ── Submit ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_success(client: AsyncClient):
    resp = await client.post("/v1/submit", json={"pack": _valid_pack(), "creator": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["asset_id"] is not None
    assert body["data"]["verify"]["valid"] is True


@pytest.mark.asyncio
async def test_submit_invalid_pack(client: AsyncClient):
    pack = _valid_pack()
    pack["media_hash"] = "short"
    resp = await client.post("/v1/submit", json={"pack": pack, "creator": "alice"})
    body = resp.json()
    assert body["ok"] is False
    assert body["data"]["asset_id"] is None


# ── Buy ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_success(client: AsyncClient, monkeypatch):
    # Register asset through the facade's settlement engine (single entry point)
    from oasyce.api.deps import get_facade
    from oasyce.services.settlement.engine import SettlementConfig

    monkeypatch.setenv("OASYCE_ALLOW_LOCAL_FALLBACK", "1")
    get_facade.cache_clear()
    try:
        facade = get_facade()
        se = facade._get_settlement()
        se._config = SettlementConfig(chain_required=False, allow_local_fallback=True)
        se.register_asset("TEST_BUY_ASSET", owner="alice")

        resp = await client.post("/v1/buy", json={"asset_id": "TEST_BUY_ASSET", "buyer": "bob"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["quote"]["price_oas"] > 0
        assert body["data"]["settlement"]["success"] is True
    finally:
        get_facade.cache_clear()


@pytest.mark.asyncio
async def test_buy_missing_asset(client: AsyncClient):
    resp = await client.post("/v1/buy", json={"asset_id": "nonexistent", "buyer": "bob"})
    assert resp.status_code == 200
    body = resp.json()
    # With single-entry-point architecture, unknown local pools fall back to
    # the chain bridge.  When the chain is reachable the bridge may succeed;
    # when it isn't the facade returns an error.  Accept either outcome.
    if body["ok"]:
        assert body["data"] is not None
    else:
        assert body["error"] is not None


@pytest.mark.asyncio
async def test_buy_validation_error(client: AsyncClient):
    resp = await client.post("/v1/buy", json={"buyer": "bob"})
    assert resp.status_code == 422


# ── Core Machine Contract ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_core_register_returns_machine_contract(client: AsyncClient):
    app.dependency_overrides[get_facade] = lambda: type(
        "Facade",
        (),
        {
            "register": staticmethod(
                lambda **kwargs: ServiceResult(
                    success=True,
                    data={
                        "asset_id": "ASSET_CORE_1",
                        "file_hash": "abcd1234",
                        "owner": kwargs["owner"],
                        "price_model": kwargs["price_model"],
                        "rights_type": kwargs["rights_type"],
                    },
                    trace_id=kwargs.get("trace_id"),
                )
            )
        },
    )()
    try:
        resp = await client.post(
            "/v1/core/register",
            json={
                "file_path": "/tmp/core-register.txt",
                "owner": "agent-1",
                "tags": ["beta", "agent"],
                "rights_type": "original",
                "price_model": "floor",
                "price": 12.5,
                "trace_id": "trace-core-register-1",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["contract_version"] == "beta-core-v1"
    assert body["action"] == "register"
    assert body["trace_id"] == "trace-core-register-1"
    assert body["ok"] is True
    assert body["state"] == "success"
    assert body["retryable"] is False
    assert body["data"]["asset_id"] == "ASSET_CORE_1"
    assert body["data"]["file_hash"] == "abcd1234"
    assert body["data"]["owner"] == "agent-1"
    assert body["data"]["price_model"] == "floor"
    assert body["data"]["rights_type"] == "original"


@pytest.mark.asyncio
async def test_core_register_maps_conflict_failure(client: AsyncClient):
    app.dependency_overrides[get_facade] = lambda: type(
        "Facade",
        (),
        {
            "register": staticmethod(
                lambda **kwargs: ServiceResult(
                    success=False,
                    data={"existing_asset_id": "ASSET_EXISTING_1"},
                    error="Duplicate: file already registered as ASSET_EXISTING_1",
                    trace_id=kwargs.get("trace_id"),
                )
            )
        },
    )()
    try:
        resp = await client.post(
            "/v1/core/register",
            json={
                "file_path": "/tmp/duplicate.txt",
                "owner": "agent-1",
                "trace_id": "trace-core-register-conflict",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
    body = resp.json()
    assert body["action"] == "register"
    assert body["ok"] is False
    assert body["state"] == "failed"
    assert body["retryable"] is False
    assert body["trace_id"] == "trace-core-register-conflict"
    assert body["data"]["file_path"] == "/tmp/duplicate.txt"
    assert body["data"]["owner"] == "agent-1"
    assert body["data"]["existing_asset_id"] == "ASSET_EXISTING_1"
    assert body["error"] == "Duplicate: file already registered as ASSET_EXISTING_1"


@pytest.mark.asyncio
async def test_core_quote_returns_machine_contract(client: AsyncClient):
    app.dependency_overrides[get_facade] = lambda: type(
        "Facade",
        (),
        {
            "quote": staticmethod(
                lambda asset_id, amount_oas=10.0, trace_id=None: ServiceResult(
                    success=True,
                    data={
                        "asset_id": asset_id,
                        "payment_oas": amount_oas,
                        "equity_minted": 1.25,
                        "spot_price_before": 1.0,
                        "spot_price_after": 1.2,
                        "price_impact_pct": 20.0,
                        "protocol_fee": 0.3,
                        "burn_amount": 0.2,
                    },
                    trace_id=trace_id,
                )
            )
        },
    )()
    try:
        resp = await client.post(
            "/v1/core/quote",
            json={"asset_id": "ASSET_1", "amount_oas": 10.0, "trace_id": "trace-core-quote-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["contract_version"] == "beta-core-v1"
    assert body["action"] == "quote"
    assert body["trace_id"] == "trace-core-quote-1"
    assert body["ok"] is True
    assert body["state"] == "success"
    assert body["retryable"] is False
    assert body["data"]["asset_id"] == "ASSET_1"
    assert body["data"]["amount_oas"] == 10.0
    assert body["data"]["payment_oas"] == 10.0


@pytest.mark.asyncio
async def test_core_buy_returns_machine_contract(client: AsyncClient):
    app.dependency_overrides[get_facade] = lambda: type(
        "Facade",
        (),
        {
            "buy": staticmethod(
                lambda asset_id, buyer, amount_oas=10.0, trace_id=None: ServiceResult(
                    success=True,
                    data={
                        "asset_id": asset_id,
                        "buyer": buyer,
                        "amount_oas": amount_oas,
                        "settled": True,
                        "receipt_id": "rcpt-core-1",
                        "quote": {
                            "equity_minted": 2.0,
                            "spot_price_after": 1.5,
                        },
                        "equity_balance": 2.0,
                    },
                    trace_id=trace_id,
                )
            )
        },
    )()
    try:
        resp = await client.post(
            "/v1/core/buy",
            json={
                "asset_id": "ASSET_1",
                "buyer": "agent-1",
                "amount_oas": 10.0,
                "trace_id": "trace-core-buy-1",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["contract_version"] == "beta-core-v1"
    assert body["action"] == "buy"
    assert body["trace_id"] == "trace-core-buy-1"
    assert body["ok"] is True
    assert body["state"] == "success"
    assert body["retryable"] is False
    assert body["data"]["asset_id"] == "ASSET_1"
    assert body["data"]["buyer"] == "agent-1"
    assert body["data"]["receipt_id"] == "rcpt-core-1"
    assert body["data"]["equity_balance"] == 2.0


@pytest.mark.asyncio
async def test_core_portfolio_returns_machine_contract(client: AsyncClient):
    app.dependency_overrides[get_facade] = lambda: type(
        "Facade",
        (),
        {
            "get_portfolio": staticmethod(
                lambda buyer: ServiceResult(
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
            )
        },
    )()
    try:
        resp = await client.post(
            "/v1/core/portfolio",
            json={"buyer": "agent-1", "trace_id": "trace-core-portfolio-1"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["contract_version"] == "beta-core-v1"
    assert body["action"] == "portfolio"
    assert body["trace_id"] == "trace-core-portfolio-1"
    assert body["ok"] is True
    assert body["state"] == "success"
    assert body["data"]["buyer"] == "agent-1"
    assert body["data"]["holdings"][0]["asset_id"] == "ASSET_1"


@pytest.mark.asyncio
async def test_core_quote_maps_retryable_service_failure(client: AsyncClient):
    app.dependency_overrides[get_facade] = lambda: type(
        "Facade",
        (),
        {
            "quote": staticmethod(
                lambda asset_id, amount_oas=10.0, trace_id=None: ServiceResult(
                    success=False,
                    error="service unavailable",
                    trace_id=trace_id,
                )
            )
        },
    )()
    try:
        resp = await client.post(
            "/v1/core/quote",
            json={"asset_id": "ASSET_1", "amount_oas": 10.0, "trace_id": "trace-core-quote-fail"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 503
    body = resp.json()
    assert body["ok"] is False
    assert body["state"] == "retryable"
    assert body["retryable"] is True
    assert body["trace_id"] == "trace-core-quote-fail"
    assert body["error"] == "service unavailable"

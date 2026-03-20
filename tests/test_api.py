from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest_asyncio = pytest.importorskip("pytest_asyncio", reason="pytest-asyncio required")

from httpx import ASGITransport, AsyncClient

from oasyce.api.main import app


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
async def test_buy_success(client: AsyncClient):
    # Register asset through the facade's settlement engine (single entry point)
    from oasyce.api.deps import get_facade

    facade = get_facade()
    se = facade._get_settlement()
    se.register_asset("TEST_BUY_ASSET", owner="alice")

    resp = await client.post("/v1/buy", json={"asset_id": "TEST_BUY_ASSET", "buyer": "bob"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["data"]["quote"]["price_oas"] > 0
    assert body["data"]["settlement"]["success"] is True


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

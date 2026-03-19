"""Tests for AHRP HTTP API — full lifecycle via REST."""

from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from oasyce.ahrp.api import api, _router_instance, _executor_instance
import oasyce.ahrp.api as api_module


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset global state between tests."""
    api_module._router_instance = None
    api_module._executor_instance = None
    yield
    api_module._router_instance = None
    api_module._executor_instance = None


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(api)
    return TestClient(app)


def _announce(client, agent_id, tags, price=1.0, origin="human", rep=50.0):
    return client.post(
        "/ahrp/v1/announce",
        json={
            "identity": {
                "agent_id": agent_id,
                "public_key": f"pk-{agent_id}",
                "reputation": rep,
                "stake": 1000.0,
            },
            "capabilities": [
                {
                    "capability_id": f"cap-{agent_id}",
                    "tags": tags,
                    "price_floor": price,
                    "origin_type": origin,
                    "access_levels": ["L0", "L1"],
                }
            ],
            "endpoints": [f"https://{agent_id}.example.com"],
        },
    )


class TestAnnounceAPI:
    def test_announce(self, client):
        r = _announce(client, "alice", ["NLP", "sentiment"])
        assert r.status_code == 200
        data = r.json()
        assert data["ok"]
        assert data["data"]["agent_id"] == "alice"
        assert data["data"]["capabilities_indexed"] == 1

    def test_announce_refresh(self, client):
        _announce(client, "alice", ["NLP"])
        r = _announce(client, "alice", ["NLP", "new"])
        assert r.json()["data"]["announce_count"] == 2


class TestSearchAPI:
    def test_search_by_tag(self, client):
        _announce(client, "alice", ["NLP"], rep=60.0)
        _announce(client, "bob", ["finance"], rep=80.0)
        r = client.post("/ahrp/v1/search", json={"tags": ["finance"]})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 1
        assert data["results"][0]["agent_id"] == "bob"

    def test_search_by_origin(self, client):
        _announce(client, "alice", ["data"], origin="human")
        _announce(client, "bob", ["data"], origin="synthetic")
        r = client.post("/ahrp/v1/search", json={"origin_type": "human"})
        assert r.json()["data"]["count"] == 1


class TestRequestAPI:
    def test_route_request(self, client):
        _announce(client, "alice", ["NLP"])
        _announce(client, "bob", ["finance", "SEC"])
        r = client.post(
            "/ahrp/v1/request",
            json={
                "requester_id": "alice",
                "need": {"description": "financial data", "tags": ["finance"]},
                "budget_oas": 10.0,
                "request_id": "req-api-001",
            },
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] >= 1
        assert data["matches"][0]["agent_id"] == "bob"


class TestFullLifecycleAPI:
    def test_announce_to_confirm(self, client):
        # 1. Announce two agents
        _announce(client, "alice", ["NLP"], rep=50.0)
        _announce(client, "bob", ["finance"], price=2.0, rep=70.0)

        # 2. Alice searches
        r = client.post("/ahrp/v1/search", json={"tags": ["finance"]})
        assert r.json()["data"]["count"] == 1

        # 3. Alice accepts Bob's offer
        r = client.post(
            "/ahrp/v1/accept",
            json={
                "buyer_id": "alice",
                "seller_id": "bob",
                "offer": {
                    "request_id": "req-001",
                    "capability_id": "cap-bob",
                    "price_oas": 5.0,
                    "offer_id": "off-001",
                },
            },
        )
        assert r.status_code == 200
        tx_data = r.json()["data"]
        assert tx_data["state"] == "accepted"
        tx_id = tx_data["tx_id"]

        # 4. Check transaction status
        r = client.get(f"/ahrp/v1/tx/{tx_id}")
        assert r.json()["data"]["state"] == "accepted"

        # 5. Bob delivers
        r = client.post(
            "/ahrp/v1/deliver",
            json={
                "tx_id": tx_id,
                "offer_id": "off-001",
                "content_hash": "sha256:abc123",
                "content_ref": "ipfs://QmData",
                "content_size_bytes": 2048,
            },
        )
        assert r.json()["data"]["state"] == "delivered"

        # 6. Alice confirms
        r = client.post(
            "/ahrp/v1/confirm",
            json={
                "tx_id": tx_id,
                "offer_id": "off-001",
                "content_hash_verified": True,
                "rating": 5,
            },
        )
        assert r.json()["data"]["state"] == "confirmed"
        assert r.json()["data"]["settled_at"] is not None

        # 7. Check stats
        r = client.get("/ahrp/v1/stats")
        stats = r.json()["data"]
        assert stats["executor"]["completed_transactions"] == 1


class TestErrorsAPI:
    def test_tx_not_found(self, client):
        r = client.get("/ahrp/v1/tx/nonexistent")
        assert r.status_code == 404

    def test_deliver_not_found(self, client):
        r = client.post(
            "/ahrp/v1/deliver",
            json={
                "tx_id": "nonexistent",
                "content_hash": "x",
            },
        )
        assert r.status_code == 404

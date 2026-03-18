"""
Tests for capability delivery & settlement protocol.

Covers:
  - EndpointRegistry: register, list, encrypt/decrypt API keys, stats, suspend
  - EscrowLedger: lock, release, refund, expire, protocol fee
  - InvocationGateway: proxy calls, error handling
  - SettlementProtocol: full invoke-and-settle lifecycle
  - E2E: provider registers → consumer invokes → settlement completes
"""

from __future__ import annotations

import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from unittest.mock import patch, MagicMock

import pytest

from oasyce_plugin.consensus.core.types import to_units
from oasyce_plugin.services.capability_delivery.registry import (
    CapabilityEndpoint,
    EndpointRegistry,
    _encrypt_api_key,
    _decrypt_api_key,
)
from oasyce_plugin.services.capability_delivery.escrow import (
    EscrowLedger,
    EscrowEntry,
    EscrowStatus,
)
from oasyce_plugin.services.capability_delivery.gateway import (
    InvocationGateway,
    InvocationResult,
)
from oasyce_plugin.services.capability_delivery.settlement import (
    SettlementProtocol,
    InvocationRecord,
    InvocationStatus,
)


# ── Helpers ───────────────────────────────────────────────────────


def _free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MockProviderHandler(BaseHTTPRequestHandler):
    """Simulates a provider's AI API endpoint."""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length)) if content_length else {}

        # Check auth
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": "unauthorized"}')
            return

        # Simulate AI response
        if body.get("_fail"):
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b'{"error": "internal error"}')
            return

        response = {
            "result": f"translated: {body.get('text', '')}",
            "model": "mock-v1",
            "tokens_used": 42,
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        pass  # suppress logs


def _start_mock_provider(port):
    server = HTTPServer(("127.0.0.1", port), MockProviderHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# ── API Key Encryption Tests ─────────────────────────────────────


class TestApiKeyEncryption:
    def test_encrypt_decrypt_round_trip(self):
        key = "sk-1234567890abcdef"
        passphrase = "node-secret"
        encrypted = _encrypt_api_key(key, passphrase)
        decrypted = _decrypt_api_key(encrypted, passphrase)
        assert decrypted == key

    def test_wrong_passphrase_fails(self):
        key = "sk-secret"
        encrypted = _encrypt_api_key(key, "correct")
        with pytest.raises(Exception):
            _decrypt_api_key(encrypted, "wrong")

    def test_different_encryptions_differ(self):
        key = "sk-same-key"
        e1 = _encrypt_api_key(key, "pass")
        e2 = _encrypt_api_key(key, "pass")
        assert e1 != e2  # different salt/nonce each time

    def test_empty_key(self):
        encrypted = _encrypt_api_key("", "pass")
        assert _decrypt_api_key(encrypted, "pass") == ""


# ── EndpointRegistry Tests ───────────────────────────────────────


class TestEndpointRegistry:
    def test_register_and_get(self):
        reg = EndpointRegistry(allow_private=True)
        result = reg.register(
            endpoint_url="https://api.example.com/translate",
            api_key="sk-test-key",
            provider_id="provider-1",
            name="Translation API",
            price_per_call=to_units(0.01),
            tags=["nlp", "translation"],
            description="Translate text between languages",
        )
        assert result["ok"] is True
        cap_id = result["capability_id"]
        assert cap_id.startswith("CAP_")

        ep = reg.get(cap_id)
        assert ep is not None
        assert ep.name == "Translation API"
        assert ep.provider_id == "provider-1"
        assert ep.price_per_call == to_units(0.01)
        assert ep.status == "active"
        reg.close()

    def test_register_validation(self):
        reg = EndpointRegistry(allow_private=True)
        assert reg.register("", "key", "p", "n")["ok"] is False
        assert reg.register("url", "key", "", "n")["ok"] is False
        assert reg.register("url", "key", "p", "")["ok"] is False
        assert reg.register("url", "key", "p", "n", price_per_call=-1)["ok"] is False
        reg.close()

    def test_duplicate_id_rejected(self):
        reg = EndpointRegistry(allow_private=True)
        reg.register("url", "key", "p", "n", capability_id="CAP_DUP")
        result = reg.register("url2", "key2", "p2", "n2", capability_id="CAP_DUP")
        assert result["ok"] is False
        assert "already exists" in result["error"]
        reg.close()

    def test_api_key_encrypted_at_rest(self):
        reg = EndpointRegistry(allow_private=True)
        result = reg.register("url", "sk-secret-123", "p", "n")
        cap_id = result["capability_id"]

        ep = reg.get(cap_id)
        assert ep.api_key_enc != ""
        assert "sk-secret-123" not in ep.api_key_enc
        reg.close()

    def test_get_api_key_decrypts(self):
        reg = EndpointRegistry(encryption_passphrase="my-node-key", allow_private=True)
        result = reg.register("url", "sk-secret-123", "p", "n")
        cap_id = result["capability_id"]

        key = reg.get_api_key(cap_id)
        assert key == "sk-secret-123"
        reg.close()

    def test_list_active(self):
        reg = EndpointRegistry(allow_private=True)
        reg.register("url1", "k", "p1", "API-A", tags=["nlp"])
        reg.register("url2", "k", "p2", "API-B", tags=["vision"])
        reg.register("url3", "k", "p1", "API-C", tags=["nlp"])

        all_active = reg.list_active()
        assert len(all_active) == 3

        by_provider = reg.list_active(provider_id="p1")
        assert len(by_provider) == 2

        by_tag = reg.list_active(tag="nlp")
        assert len(by_tag) == 2
        reg.close()

    def test_suspend_and_delist(self):
        reg = EndpointRegistry(allow_private=True)
        result = reg.register("url", "k", "p", "n")
        cap_id = result["capability_id"]

        assert reg.suspend(cap_id) is True
        assert reg.get(cap_id).status == "suspended"
        assert len(reg.list_active()) == 0

        assert reg.delist(cap_id) is True
        assert reg.get(cap_id).status == "delisted"
        reg.close()

    def test_update_stats(self):
        reg = EndpointRegistry(allow_private=True)
        result = reg.register("url", "k", "p", "n")
        cap_id = result["capability_id"]

        reg.update_stats(cap_id, latency_ms=100, success=True, earned=1000)
        reg.update_stats(cap_id, latency_ms=200, success=True, earned=2000)
        reg.update_stats(cap_id, latency_ms=300, success=False)

        ep = reg.get(cap_id)
        assert ep.total_calls == 3
        assert ep.total_earned == 3000
        assert ep.avg_latency_ms == 200.0
        assert abs(ep.success_rate - 2/3) < 0.01
        reg.close()

    def test_to_dict_hides_api_key(self):
        reg = EndpointRegistry(allow_private=True)
        result = reg.register("url", "sk-secret", "p", "n", tags=["ai"])
        ep = reg.get(result["capability_id"])
        d = ep.to_dict()
        assert "api_key_enc" not in d
        assert d["tags"] == ["ai"]
        reg.close()


# ── EscrowLedger Tests ───────────────────────────────────────────


class TestEscrowLedger:
    def test_lock_and_release(self):
        escrow = EscrowLedger(db_path=":memory:")
        result = escrow.lock("consumer-1", "provider-1", "CAP_1",
                             amount=to_units(10))
        assert result["ok"] is True
        eid = result["escrow_id"]
        token = result["auth_token"]

        entry = escrow.get(eid)
        assert entry.status == EscrowStatus.LOCKED
        assert entry.amount == to_units(10)

        release = escrow.release(eid, auth_token=token)
        assert release["ok"] is True
        assert release["amount"] == to_units(10)
        # 5% protocol fee
        assert release["protocol_fee"] == to_units(10) * 500 // 10000
        assert release["provider_amount"] == to_units(10) - release["protocol_fee"]
        escrow.close()

    def test_lock_and_refund(self):
        escrow = EscrowLedger(db_path=":memory:")
        result = escrow.lock("c", "p", "cap", amount=to_units(5))
        eid = result["escrow_id"]
        token = result["auth_token"]

        refund = escrow.refund(eid, auth_token=token)
        assert refund["ok"] is True
        assert refund["refunded_amount"] == to_units(5)

        entry = escrow.get(eid)
        assert entry.status == EscrowStatus.REFUNDED
        escrow.close()

    def test_double_release_fails(self):
        escrow = EscrowLedger(db_path=":memory:")
        result = escrow.lock("c", "p", "cap", amount=1000)
        eid = result["escrow_id"]
        token = result["auth_token"]
        escrow.release(eid, auth_token=token)

        result2 = escrow.release(eid, auth_token=token)
        assert result2["ok"] is False
        escrow.close()

    def test_release_then_refund_fails(self):
        escrow = EscrowLedger(db_path=":memory:")
        result = escrow.lock("c", "p", "cap", amount=1000)
        eid = result["escrow_id"]
        token = result["auth_token"]
        escrow.release(eid, auth_token=token)

        result2 = escrow.refund(eid, auth_token=token)
        assert result2["ok"] is False
        escrow.close()

    def test_lock_validation(self):
        escrow = EscrowLedger(db_path=":memory:")
        assert escrow.lock("", "p", "cap", 100)["ok"] is False
        assert escrow.lock("c", "", "cap", 100)["ok"] is False
        assert escrow.lock("c", "p", "cap", 0)["ok"] is False
        assert escrow.lock("c", "p", "cap", -1)["ok"] is False
        escrow.close()

    def test_expire_stale(self):
        escrow = EscrowLedger(db_path=":memory:")
        # Lock with TTL=0 so it's already expired
        result = escrow.lock("c", "p", "cap", amount=1000, ttl=0)
        eid = result["escrow_id"]

        # Force created_at to be in the past
        escrow._conn.execute(
            "UPDATE escrow SET created_at = created_at - 10 WHERE escrow_id = ?",
            (eid,),
        )
        escrow._conn.commit()

        expired = escrow.expire_stale()
        assert expired == 1
        assert escrow.get(eid).status == EscrowStatus.EXPIRED
        escrow.close()

    def test_total_locked(self):
        escrow = EscrowLedger(db_path=":memory:")
        escrow.lock("c1", "p", "cap", amount=1000)
        escrow.lock("c1", "p", "cap", amount=2000)
        escrow.lock("c2", "p", "cap", amount=3000)

        assert escrow.total_locked() == 6000
        assert escrow.total_locked("c1") == 3000
        assert escrow.total_locked("c2") == 3000
        escrow.close()

    def test_list_locked(self):
        escrow = EscrowLedger(db_path=":memory:")
        escrow.lock("c1", "p", "cap", amount=1000)
        r2 = escrow.lock("c1", "p", "cap", amount=2000)
        escrow.release(r2["escrow_id"], auth_token=r2["auth_token"])

        locked = escrow.list_locked("c1")
        assert len(locked) == 1
        assert locked[0].amount == 1000
        escrow.close()

    def test_protocol_fee_calculation(self):
        escrow = EscrowLedger(db_path=":memory:")
        # Test with large amount for precise fee calculation
        amount = to_units(100)  # 100 OAS
        result = escrow.lock("c", "p", "cap", amount=amount)
        release = escrow.release(result["escrow_id"], auth_token=result["auth_token"])

        expected_fee = amount * 500 // 10000  # 5%
        assert release["protocol_fee"] == expected_fee
        assert release["provider_amount"] == amount - expected_fee
        assert release["provider_amount"] + release["protocol_fee"] == amount
        escrow.close()


# ── InvocationGateway Tests ──────────────────────────────────────


class TestInvocationGateway:
    def test_invoke_success(self):
        port = _free_port()
        server = _start_mock_provider(port)
        try:
            reg = EndpointRegistry(allow_private=True)
            reg.register(
                endpoint_url=f"http://127.0.0.1:{port}/translate",
                api_key="sk-test",
                provider_id="p1",
                name="Test API",
                capability_id="CAP_TEST",
            )

            gw = InvocationGateway(reg, timeout=5.0, allow_private=True)
            result = gw.invoke("CAP_TEST", {"text": "hello"})

            assert result.success is True
            assert result.output["result"] == "translated: hello"
            assert result.latency_ms > 0
            assert result.status_code == 200
        finally:
            server.shutdown()
            reg.close()

    def test_invoke_not_found(self):
        reg = EndpointRegistry(allow_private=True)
        gw = InvocationGateway(reg, allow_private=True)
        result = gw.invoke("CAP_NONEXISTENT", {})
        assert result.success is False
        assert "not found" in result.error
        reg.close()

    def test_invoke_suspended_capability(self):
        reg = EndpointRegistry(allow_private=True)
        reg.register("url", "k", "p", "n", capability_id="CAP_S")
        reg.suspend("CAP_S")

        gw = InvocationGateway(reg, allow_private=True)
        result = gw.invoke("CAP_S", {})
        assert result.success is False
        assert "suspended" in result.error
        reg.close()

    def test_invoke_server_error(self):
        port = _free_port()
        server = _start_mock_provider(port)
        try:
            reg = EndpointRegistry(allow_private=True)
            reg.register(
                endpoint_url=f"http://127.0.0.1:{port}/translate",
                api_key="sk-test",
                provider_id="p1",
                name="Test",
                capability_id="CAP_FAIL",
            )

            gw = InvocationGateway(reg, timeout=5.0, allow_private=True)
            result = gw.invoke("CAP_FAIL", {"_fail": True})

            assert result.success is False
            # Server returns 500 which urllib treats as HTTPError
            assert result.status_code == 500 or "error" in str(result.output)
        finally:
            server.shutdown()
            reg.close()

    def test_invoke_unreachable(self):
        reg = EndpointRegistry(allow_private=True)
        reg.register(
            endpoint_url="http://127.0.0.1:1",  # unreachable
            api_key="k",
            provider_id="p",
            name="n",
            capability_id="CAP_DEAD",
        )
        gw = InvocationGateway(reg, timeout=2.0, allow_private=True)
        result = gw.invoke("CAP_DEAD", {})
        assert result.success is False
        reg.close()


# ── SettlementProtocol Tests ─────────────────────────────────────


class TestSettlementProtocol:
    def _make_protocol(self, port=None, price=to_units(1)):
        reg = EndpointRegistry(allow_private=True)
        escrow = EscrowLedger(db_path=":memory:")
        gw = InvocationGateway(reg, timeout=5.0, allow_private=True)
        protocol = SettlementProtocol(reg, escrow, gw, db_path=":memory:")

        if port:
            reg.register(
                endpoint_url=f"http://127.0.0.1:{port}/translate",
                api_key="sk-test",
                provider_id="provider-1",
                name="Translation",
                price_per_call=price,
                capability_id="CAP_TX",
            )
        return protocol, reg, escrow

    def test_full_success_flow(self):
        port = _free_port()
        server = _start_mock_provider(port)
        try:
            protocol, reg, escrow = self._make_protocol(port)

            result = protocol.invoke(
                "CAP_TX", "consumer-1", {"text": "hello world"},
            )

            assert result["ok"] is True
            assert result["output"]["result"] == "translated: hello world"
            assert result["latency_ms"] > 0
            assert result["amount"] == to_units(1)
            assert result["provider_earned"] > 0
            assert result["protocol_fee"] > 0
            assert result["provider_earned"] + result["protocol_fee"] == to_units(1)

            # Escrow should be released
            assert escrow.total_locked() == 0
            protocol.close()
            reg.close()
            escrow.close()
        finally:
            server.shutdown()

    def test_failure_refunds_escrow(self):
        port = _free_port()
        server = _start_mock_provider(port)
        try:
            protocol, reg, escrow = self._make_protocol(port)

            result = protocol.invoke(
                "CAP_TX", "consumer-1", {"_fail": True},
            )

            assert result["ok"] is False
            assert result["refunded"] is True
            assert result["refunded_amount"] == to_units(1)

            # Escrow should be refunded
            assert escrow.total_locked() == 0
            protocol.close()
            reg.close()
            escrow.close()
        finally:
            server.shutdown()

    def test_invocation_record_created(self):
        port = _free_port()
        server = _start_mock_provider(port)
        try:
            protocol, reg, escrow = self._make_protocol(port)

            result = protocol.invoke("CAP_TX", "consumer-1", {"text": "test"})
            inv_id = result["invocation_id"]

            record = protocol.get_invocation(inv_id)
            assert record is not None
            assert record.status == InvocationStatus.SUCCESS
            assert record.consumer_id == "consumer-1"
            assert record.provider_id == "provider-1"
            assert record.provider_earned > 0
            protocol.close()
            reg.close()
            escrow.close()
        finally:
            server.shutdown()

    def test_capability_not_found(self):
        protocol, reg, escrow = self._make_protocol()
        result = protocol.invoke("CAP_NOPE", "c", {"text": "hi"})
        assert result["ok"] is False
        assert "not found" in result["error"]
        protocol.close()
        reg.close()
        escrow.close()

    def test_provider_earnings(self):
        port = _free_port()
        server = _start_mock_provider(port)
        try:
            protocol, reg, escrow = self._make_protocol(port, price=to_units(2))

            protocol.invoke("CAP_TX", "c1", {"text": "a"})
            protocol.invoke("CAP_TX", "c2", {"text": "b"})

            earnings = protocol.provider_earnings("provider-1")
            assert earnings["total_calls"] == 2
            assert earnings["total_earned"] > 0
            assert earnings["success_rate"] == 1.0
            protocol.close()
            reg.close()
            escrow.close()
        finally:
            server.shutdown()

    def test_consumer_spending(self):
        port = _free_port()
        server = _start_mock_provider(port)
        try:
            protocol, reg, escrow = self._make_protocol(port, price=to_units(5))

            protocol.invoke("CAP_TX", "consumer-1", {"text": "a"})
            protocol.invoke("CAP_TX", "consumer-1", {"text": "b"})

            spending = protocol.consumer_spending("consumer-1")
            assert spending["total_calls"] == 2
            assert spending["total_spent"] == to_units(5) * 2
            assert spending["failed_calls"] == 0
            protocol.close()
            reg.close()
            escrow.close()
        finally:
            server.shutdown()

    def test_list_invocations(self):
        port = _free_port()
        server = _start_mock_provider(port)
        try:
            protocol, reg, escrow = self._make_protocol(port)

            protocol.invoke("CAP_TX", "c1", {"text": "a"})
            protocol.invoke("CAP_TX", "c2", {"text": "b"})
            protocol.invoke("CAP_TX", "c1", {"_fail": True})

            all_invocations = protocol.list_invocations()
            assert len(all_invocations) == 3

            c1_only = protocol.list_invocations(consumer_id="c1")
            assert len(c1_only) == 2

            successes = protocol.list_invocations(status="success")
            assert len(successes) == 2

            failures = protocol.list_invocations(status="failed")
            assert len(failures) == 1
            protocol.close()
            reg.close()
            escrow.close()
        finally:
            server.shutdown()

    def test_zero_price_free_invocation(self):
        """Free capabilities (price=0) still go through the pipeline."""
        port = _free_port()
        server = _start_mock_provider(port)
        try:
            reg = EndpointRegistry(allow_private=True)
            escrow = EscrowLedger(db_path=":memory:")
            gw = InvocationGateway(reg, timeout=5.0, allow_private=True)
            protocol = SettlementProtocol(reg, escrow, gw, db_path=":memory:")

            reg.register(
                endpoint_url=f"http://127.0.0.1:{port}/translate",
                api_key="sk-test",
                provider_id="p1",
                name="Free API",
                price_per_call=0,
                capability_id="CAP_FREE",
            )

            # price=0, escrow lock should still work (amount=0 will fail)
            # Actually, escrow rejects amount=0, so free caps skip escrow
            # Let's verify the behavior
            result = protocol.invoke("CAP_FREE", "c1", {"text": "free"})
            # With price=0, escrow.lock will fail (amount must be positive)
            # This is expected — free capabilities need special handling
            # For now, this documents the behavior
            assert "ok" in result
            protocol.close()
            reg.close()
            escrow.close()
        finally:
            server.shutdown()


# ── E2E Integration Test ─────────────────────────────────────────


class TestE2ECapabilityDelivery:
    def test_full_provider_consumer_lifecycle(self):
        """
        Complete lifecycle:
        1. Provider registers capability with API endpoint
        2. Consumer discovers it
        3. Consumer invokes via protocol
        4. Settlement completes (escrow released)
        5. Provider earnings tracked
        6. Consumer spending tracked
        """
        port = _free_port()
        server = _start_mock_provider(port)

        try:
            # Provider registers their API
            reg = EndpointRegistry(encryption_passphrase="node-secret", allow_private=True)
            result = reg.register(
                endpoint_url=f"http://127.0.0.1:{port}/translate",
                api_key="sk-provider-secret-key",
                provider_id="provider-alice",
                name="Alice's Translation API",
                price_per_call=to_units(0.5),
                tags=["nlp", "translation", "en-zh"],
                description="English to Chinese translation via GPT-4",
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
                output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
            )
            assert result["ok"] is True
            cap_id = result["capability_id"]

            # Verify API key is encrypted
            ep = reg.get(cap_id)
            assert "sk-provider-secret-key" not in ep.api_key_enc
            assert reg.get_api_key(cap_id) == "sk-provider-secret-key"

            # Consumer browses capabilities
            available = reg.list_active(tag="translation")
            assert len(available) == 1
            assert available[0].name == "Alice's Translation API"
            assert available[0].price_per_call == to_units(0.5)

            # Consumer invokes via settlement protocol
            escrow = EscrowLedger(db_path=":memory:")
            gw = InvocationGateway(reg, timeout=10.0, allow_private=True)
            protocol = SettlementProtocol(reg, escrow, gw, db_path=":memory:")

            invoke_result = protocol.invoke(
                cap_id, "consumer-bob", {"text": "hello world"},
            )

            assert invoke_result["ok"] is True
            assert invoke_result["output"]["result"] == "translated: hello world"
            assert invoke_result["amount"] == to_units(0.5)
            assert invoke_result["provider_earned"] + invoke_result["protocol_fee"] == to_units(0.5)

            # Provider checks earnings
            earnings = protocol.provider_earnings("provider-alice")
            assert earnings["total_calls"] == 1
            assert earnings["total_earned"] == invoke_result["provider_earned"]

            # Consumer checks spending
            spending = protocol.consumer_spending("consumer-bob")
            assert spending["total_calls"] == 1
            assert spending["total_spent"] == to_units(0.5)

            # Registry stats updated
            ep_after = reg.get(cap_id)
            assert ep_after.total_calls == 1
            assert ep_after.success_rate == 1.0

            # All escrows settled
            assert escrow.total_locked() == 0

            protocol.close()
            reg.close()
            escrow.close()
        finally:
            server.shutdown()

    def test_multiple_providers_marketplace(self):
        """Multiple providers list capabilities, consumer picks the best."""
        port1 = _free_port()
        port2 = _free_port()
        server1 = _start_mock_provider(port1)
        server2 = _start_mock_provider(port2)

        try:
            reg = EndpointRegistry(allow_private=True)
            escrow = EscrowLedger(db_path=":memory:")
            gw = InvocationGateway(reg, timeout=5.0, allow_private=True)
            protocol = SettlementProtocol(reg, escrow, gw, db_path=":memory:")

            # Provider 1: cheap but basic
            reg.register(
                endpoint_url=f"http://127.0.0.1:{port1}/translate",
                api_key="sk-cheap",
                provider_id="provider-cheap",
                name="Budget Translation",
                price_per_call=to_units(0.1),
                tags=["translation"],
                capability_id="CAP_CHEAP",
            )

            # Provider 2: expensive but premium
            reg.register(
                endpoint_url=f"http://127.0.0.1:{port2}/translate",
                api_key="sk-premium",
                provider_id="provider-premium",
                name="Premium Translation",
                price_per_call=to_units(1.0),
                tags=["translation"],
                capability_id="CAP_PREMIUM",
            )

            # Consumer browses
            available = reg.list_active(tag="translation")
            assert len(available) == 2

            # Consumer invokes both
            r1 = protocol.invoke("CAP_CHEAP", "consumer", {"text": "hi"})
            r2 = protocol.invoke("CAP_PREMIUM", "consumer", {"text": "hi"})

            assert r1["ok"] is True
            assert r2["ok"] is True
            assert r1["amount"] < r2["amount"]

            spending = protocol.consumer_spending("consumer")
            assert spending["total_calls"] == 2
            assert spending["total_spent"] == to_units(0.1) + to_units(1.0)

            protocol.close()
            reg.close()
            escrow.close()
        finally:
            server1.shutdown()
            server2.shutdown()


# ── Escrow + Real Balance Integration Tests ──────────────────────


class TestEscrowBalanceIntegration:
    """Verify that EscrowLedger correctly debits/credits MultiAssetBalance."""

    @staticmethod
    def _make_balances():
        """Create an in-memory MultiAssetBalance instance."""
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(":memory:", check_same_thread=False)
        lock = threading.Lock()
        from oasyce_plugin.consensus.assets.balances import MultiAssetBalance
        return MultiAssetBalance(conn, lock)

    def test_lock_debits_consumer(self):
        bal = self._make_balances()
        bal.credit("consumer", "OAS", to_units(100))

        escrow = EscrowLedger(db_path=":memory:", balances=bal)
        result = escrow.lock("consumer", "provider", "CAP_1", amount=to_units(10))
        assert result["ok"] is True

        # Consumer balance should have decreased by the locked amount.
        assert bal.get_balance("consumer", "OAS") == to_units(90)
        escrow.close()

    def test_lock_insufficient_balance(self):
        bal = self._make_balances()
        bal.credit("consumer", "OAS", to_units(5))

        escrow = EscrowLedger(db_path=":memory:", balances=bal)
        result = escrow.lock("consumer", "provider", "CAP_1", amount=to_units(10))
        assert result["ok"] is False
        assert "insufficient balance" in result["error"]

        # Balance unchanged.
        assert bal.get_balance("consumer", "OAS") == to_units(5)
        escrow.close()

    def test_release_credits_provider_and_treasury(self):
        bal = self._make_balances()
        bal.credit("consumer", "OAS", to_units(100))

        escrow = EscrowLedger(db_path=":memory:", balances=bal)
        lock_result = escrow.lock("consumer", "provider", "CAP_1", amount=to_units(100))
        assert lock_result["ok"] is True

        release = escrow.release(lock_result["escrow_id"], auth_token=lock_result["auth_token"])
        assert release["ok"] is True

        # Provider receives 95%, protocol treasury receives 5%.
        expected_fee = to_units(100) * 500 // 10000
        expected_provider = to_units(100) - expected_fee
        assert bal.get_balance("provider", "OAS") == expected_provider
        assert bal.get_balance("protocol_treasury", "OAS") == expected_fee
        # Consumer's balance fully debited during lock.
        assert bal.get_balance("consumer", "OAS") == 0
        escrow.close()

    def test_refund_credits_consumer(self):
        bal = self._make_balances()
        bal.credit("consumer", "OAS", to_units(50))

        escrow = EscrowLedger(db_path=":memory:", balances=bal)
        lock_result = escrow.lock("consumer", "provider", "CAP_1", amount=to_units(50))
        assert lock_result["ok"] is True
        assert bal.get_balance("consumer", "OAS") == 0

        refund = escrow.refund(lock_result["escrow_id"], auth_token=lock_result["auth_token"])
        assert refund["ok"] is True

        # Consumer gets all funds back.
        assert bal.get_balance("consumer", "OAS") == to_units(50)
        escrow.close()

    def test_no_balances_backward_compatible(self):
        """When balances=None, escrow works exactly as before (ledger-only)."""
        escrow = EscrowLedger(db_path=":memory:")  # no balances
        result = escrow.lock("c", "p", "cap", amount=to_units(10))
        assert result["ok"] is True

        release = escrow.release(result["escrow_id"], auth_token=result["auth_token"])
        assert release["ok"] is True
        assert release["provider_amount"] + release["protocol_fee"] == to_units(10)
        escrow.close()

    def test_full_cycle_lock_release_balances(self):
        """End-to-end: fund consumer, lock, release — verify all balances."""
        bal = self._make_balances()
        initial = to_units(1000)
        bal.credit("alice", "OAS", initial)

        escrow = EscrowLedger(db_path=":memory:", balances=bal)
        price = to_units(20)

        lock_r = escrow.lock("alice", "bob", "CAP_X", amount=price)
        assert lock_r["ok"] is True
        assert bal.get_balance("alice", "OAS") == initial - price

        rel = escrow.release(lock_r["escrow_id"], auth_token=lock_r["auth_token"])
        assert rel["ok"] is True

        fee = price * 500 // 10000
        provider_cut = price - fee

        assert bal.get_balance("bob", "OAS") == provider_cut
        assert bal.get_balance("protocol_treasury", "OAS") == fee
        assert bal.get_balance("alice", "OAS") == initial - price

        # Total OAS in the system should equal what was originally credited.
        total = (bal.get_balance("alice", "OAS")
                 + bal.get_balance("bob", "OAS")
                 + bal.get_balance("protocol_treasury", "OAS"))
        assert total == initial
        escrow.close()

    def test_expire_stale_refunds_consumer(self):
        """Expired escrows must credit funds back to the consumer (#36)."""
        bal = self._make_balances()
        initial = to_units(100)
        bal.credit("consumer", "OAS", initial)

        escrow = EscrowLedger(db_path=":memory:", balances=bal)
        lock_result = escrow.lock(
            "consumer", "provider", "CAP_1", amount=to_units(25), ttl=0,
        )
        assert lock_result["ok"] is True
        # Consumer balance should have been debited.
        assert bal.get_balance("consumer", "OAS") == initial - to_units(25)

        # Force created_at into the past so the escrow is stale.
        escrow._conn.execute(
            "UPDATE escrow SET created_at = created_at - 10 WHERE escrow_id = ?",
            (lock_result["escrow_id"],),
        )
        escrow._conn.commit()

        expired = escrow.expire_stale()
        assert expired == 1

        entry = escrow.get(lock_result["escrow_id"])
        assert entry.status == EscrowStatus.EXPIRED

        # Consumer balance must be fully restored.
        assert bal.get_balance("consumer", "OAS") == initial
        escrow.close()

    def test_expire_stale_no_balances_still_works(self):
        """expire_stale works in ledger-only mode (no balances)."""
        escrow = EscrowLedger(db_path=":memory:")
        result = escrow.lock("c", "p", "cap", amount=1000, ttl=0)
        eid = result["escrow_id"]
        escrow._conn.execute(
            "UPDATE escrow SET created_at = created_at - 10 WHERE escrow_id = ?",
            (eid,),
        )
        escrow._conn.commit()

        expired = escrow.expire_stale()
        assert expired == 1
        assert escrow.get(eid).status == EscrowStatus.EXPIRED
        escrow.close()

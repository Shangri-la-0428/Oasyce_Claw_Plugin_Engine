from __future__ import annotations

from oasyce.services.buy_runtime import BuyRuntime


def test_buy_runtime_replays_matching_idempotency_key():
    runtime = BuyRuntime(cooldown_seconds=30, idempotency_ttl_seconds=3600)

    runtime.record_success(
        buyer="buyer-1",
        asset_id="ASSET_1",
        idempotency_key="idem-1",
        request_fingerprint="fp-1",
        response={"receipt_id": "rcpt-1"},
        trace_id="trace-1",
        now=100.0,
    )

    lookup = runtime.lookup_idempotency("idem-1", "fp-1", now=110.0)

    assert lookup.kind == "replay"
    assert lookup.replay is not None
    assert lookup.replay.response == {"receipt_id": "rcpt-1"}
    assert lookup.replay.original_trace_id == "trace-1"


def test_buy_runtime_rejects_payload_conflict_for_same_idempotency_key():
    runtime = BuyRuntime(cooldown_seconds=30, idempotency_ttl_seconds=3600)
    runtime.record_success(
        buyer="buyer-1",
        asset_id="ASSET_1",
        idempotency_key="idem-1",
        request_fingerprint="fp-1",
        response={"receipt_id": "rcpt-1"},
        trace_id="trace-1",
        now=100.0,
    )

    lookup = runtime.lookup_idempotency("idem-1", "fp-2", now=110.0)

    assert lookup.kind == "conflict"
    assert lookup.replay is None


def test_buy_runtime_tracks_and_expires_cooldown():
    runtime = BuyRuntime(cooldown_seconds=30, idempotency_ttl_seconds=3600)

    runtime.record_success(
        buyer="buyer-1",
        asset_id="ASSET_1",
        idempotency_key="idem-1",
        request_fingerprint="fp-1",
        response={"receipt_id": "rcpt-1"},
        trace_id="trace-1",
        now=100.0,
    )

    assert runtime.cooldown_remaining("buyer-1", "ASSET_1", now=110.0) == 20
    assert runtime.cooldown_remaining("buyer-1", "ASSET_1", now=131.0) == 0


def test_buy_runtime_prunes_stale_idempotency_entries():
    runtime = BuyRuntime(cooldown_seconds=30, idempotency_ttl_seconds=10)
    runtime.record_success(
        buyer="buyer-1",
        asset_id="ASSET_1",
        idempotency_key="idem-1",
        request_fingerprint="fp-1",
        response={"receipt_id": "rcpt-1"},
        trace_id="trace-1",
        now=100.0,
    )

    lookup = runtime.lookup_idempotency("idem-1", "fp-1", now=111.0)

    assert lookup.kind == "miss"
    assert lookup.replay is None

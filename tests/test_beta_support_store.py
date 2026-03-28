from __future__ import annotations

from oasyce.services.beta_support import BetaSupportStore


def test_beta_support_store_keeps_recent_events_and_failures():
    store = BetaSupportStore(max_events=3)

    store.record("quote.start", "trace-1", "info", {"asset_id": "A1"}, now=1.0)
    store.record("quote.failed", "trace-2", "warning", {"asset_id": "A1"}, now=2.0)
    store.record("buy.success", "trace-3", "info", {"asset_id": "A1"}, now=3.0)
    store.record("buy.failed", "trace-4", "error", {"asset_id": "A1"}, now=4.0)

    snapshot = store.snapshot(limit=3)

    assert [event["event"] for event in snapshot["events"]] == [
        "buy.failed",
        "buy.success",
        "quote.failed",
    ]
    assert [event["event"] for event in snapshot["failures"]] == [
        "buy.failed",
        "quote.failed",
    ]

from __future__ import annotations

from oasyce.services.buy_notifications import BuyNotificationAdapter
from oasyce.storage.ledger import Ledger


def test_buy_notification_adapter_notifies_buyer_and_owner(tmp_path):
    ledger = Ledger(str(tmp_path / "ledger.db"))
    ledger.register_asset(
        "ASSET_NOTIFY_1",
        "owner-1",
        "hash-1",
        {"owner": "owner-1"},
    )

    calls = []

    class _NotificationService:
        def notify(self, address, event_type, message, data):
            calls.append((address, event_type, message, data))

    adapter = BuyNotificationAdapter(
        ledger=ledger,
        notification_service=_NotificationService(),
    )

    adapter.dispatch(
        "ASSET_NOTIFY_1",
        "buyer-1",
        {
            "equity_minted": 2.0,
            "spot_price_after": 1.5,
            "protocol_fee": 0.1,
        },
    )

    assert calls[0][0] == "buyer-1"
    assert calls[0][1] == "PURCHASE"
    assert calls[0][3] == {"asset_id": "ASSET_NOTIFY_1", "shares": 2.0}
    assert calls[1][0] == "owner-1"
    assert calls[1][1] == "SALE"
    assert calls[1][3] == {"asset_id": "ASSET_NOTIFY_1", "buyer": "buyer-1"}

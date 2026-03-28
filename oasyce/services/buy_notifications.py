from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BuyNotificationAdapter:
    """Send buyer/owner notifications for successful buy operations."""

    def __init__(self, ledger=None, config=None, notification_service=None):
        self._ledger = ledger
        self._config = config
        self._notification_service = notification_service
        self._init_lock = threading.Lock()

    def _get_notifications(self):
        if self._notification_service is None:
            with self._init_lock:
                if self._notification_service is None:  # double-check
                    from oasyce.services.notifications import NotificationService

                    db_path = None
                    if self._config and getattr(self._config, "data_dir", None):
                        db_path = os.path.join(self._config.data_dir, "notifications.db")
                    self._notification_service = NotificationService(db_path=db_path)
        return self._notification_service

    def dispatch(self, asset_id: str, buyer: str, quote: Optional[Dict[str, Any]]) -> None:
        try:
            quote_data = quote or {}
            shares = round(float(quote_data.get("equity_minted", 0) or 0), 4)
            notifications = self._get_notifications()
            notifications.notify(
                buyer,
                "PURCHASE",
                f"Purchased {shares} shares of {asset_id[:12]}...",
                {"asset_id": asset_id, "shares": shares},
            )
            if self._ledger is not None:
                owner = self._ledger.get_asset_owner(asset_id)
                if owner:
                    notifications.notify(
                        owner,
                        "SALE",
                        f"Your asset {asset_id[:12]}... was purchased by {buyer[:12]}...",
                        {"asset_id": asset_id, "buyer": buyer},
                    )
        except Exception:
            logger.debug("Buy notification failed", exc_info=True)

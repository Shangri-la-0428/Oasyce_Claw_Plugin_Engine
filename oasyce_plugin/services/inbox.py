"""Confirmation Inbox — pending register/purchase queue with trust levels.

Users approve, reject, or edit items before they hit the protocol.
Trust levels control how much automation is allowed.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# Trust levels
TRUST_MANUAL = 0       # every action needs confirmation
TRUST_SEMI_AUTO = 1    # low-value auto, high-value confirm
TRUST_FULL_AUTO = 2    # everything auto, notify on anomaly

_DEFAULT_AUTO_THRESHOLD = 10.0  # OAS — below this, auto-approve at level 1


class InboxError(Exception):
    """Raised for inbox operation errors."""


@dataclass
class InboxItem:
    """A pending action awaiting user confirmation."""
    item_id: str
    item_type: str  # 'register' | 'purchase'
    status: str  # 'pending' | 'approved' | 'rejected'
    created_at: int
    # Register fields
    file_path: Optional[str] = None
    suggested_name: Optional[str] = None
    suggested_tags: Optional[List[str]] = None
    suggested_description: Optional[str] = None
    sensitivity: Optional[str] = None
    confidence: Optional[float] = None
    # Purchase fields
    asset_id: Optional[str] = None
    price: Optional[float] = None
    reason: Optional[str] = None
    # Resolution
    resolved_at: Optional[int] = None


class ConfirmationInbox:
    """Manages pending registrations and purchases."""

    def __init__(self, data_dir: Optional[str] = None) -> None:
        if data_dir is None:
            data_dir = os.path.join(os.path.expanduser("~"), ".oasyce")
        self._data_dir = data_dir
        self._inbox_path = os.path.join(data_dir, "inbox.json")
        self._config_path = os.path.join(data_dir, "inbox_config.json")
        self._items: Dict[str, InboxItem] = {}
        self._trust_level: int = TRUST_MANUAL
        self._auto_threshold: float = _DEFAULT_AUTO_THRESHOLD
        self._load()

    # ── Trust level ───────────────────────────────────────────────────

    def get_trust_level(self) -> int:
        return self._trust_level

    def set_trust_level(self, level: int) -> None:
        if level not in (TRUST_MANUAL, TRUST_SEMI_AUTO, TRUST_FULL_AUTO):
            raise InboxError(f"Invalid trust level: {level}. Must be 0, 1, or 2.")
        self._trust_level = level
        self._save_config()

    def get_auto_threshold(self) -> float:
        return self._auto_threshold

    def set_auto_threshold(self, threshold: float) -> None:
        self._auto_threshold = threshold
        self._save_config()

    # ── Add items ─────────────────────────────────────────────────────

    def add_pending_register(
        self,
        file_path: str,
        suggested_name: str,
        suggested_tags: Optional[List[str]] = None,
        suggested_description: Optional[str] = None,
        sensitivity: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> InboxItem:
        """Add a scanned asset to the registration queue."""
        item = InboxItem(
            item_id=str(uuid.uuid4())[:8],
            item_type="register",
            status="pending",
            created_at=int(time.time()),
            file_path=file_path,
            suggested_name=suggested_name,
            suggested_tags=suggested_tags or [],
            suggested_description=suggested_description,
            sensitivity=sensitivity,
            confidence=confidence,
        )

        # Auto-approve logic
        if self._trust_level == TRUST_FULL_AUTO:
            item.status = "approved"
            item.resolved_at = int(time.time())
        elif self._trust_level == TRUST_SEMI_AUTO and sensitivity == "public" and (confidence or 0) > 0.5:
            item.status = "approved"
            item.resolved_at = int(time.time())

        self._items[item.item_id] = item
        self._save()
        return item

    def add_pending_purchase(
        self,
        asset_id: str,
        price: float,
        reason: Optional[str] = None,
    ) -> InboxItem:
        """Add a purchase recommendation to the queue."""
        item = InboxItem(
            item_id=str(uuid.uuid4())[:8],
            item_type="purchase",
            status="pending",
            created_at=int(time.time()),
            asset_id=asset_id,
            price=price,
            reason=reason,
        )

        # Auto-approve logic
        if self._trust_level == TRUST_FULL_AUTO:
            item.status = "approved"
            item.resolved_at = int(time.time())
        elif self._trust_level == TRUST_SEMI_AUTO and price <= self._auto_threshold:
            item.status = "approved"
            item.resolved_at = int(time.time())

        self._items[item.item_id] = item
        self._save()
        return item

    # ── Actions ───────────────────────────────────────────────────────

    def approve(self, item_id: str) -> InboxItem:
        """Approve a pending item."""
        item = self._get_pending(item_id)
        item.status = "approved"
        item.resolved_at = int(time.time())
        self._save()
        return item

    def reject(self, item_id: str) -> InboxItem:
        """Reject a pending item."""
        item = self._get_pending(item_id)
        item.status = "rejected"
        item.resolved_at = int(time.time())
        self._save()
        return item

    def edit(self, item_id: str, changes: Dict[str, Any]) -> InboxItem:
        """Edit and auto-approve an item."""
        item = self._get_pending(item_id)
        for key, value in changes.items():
            if hasattr(item, key) and key not in ("item_id", "item_type", "status"):
                setattr(item, key, value)
        item.status = "approved"
        item.resolved_at = int(time.time())
        self._save()
        return item

    # ── Queries ───────────────────────────────────────────────────────

    def list_pending(self, item_type: str = "all") -> List[InboxItem]:
        """List pending items. type: 'register', 'purchase', or 'all'."""
        items = [i for i in self._items.values() if i.status == "pending"]
        if item_type != "all":
            items = [i for i in items if i.item_type == item_type]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def list_all(self, item_type: str = "all") -> List[InboxItem]:
        """List all items regardless of status."""
        items = list(self._items.values())
        if item_type != "all":
            items = [i for i in items if i.item_type == item_type]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def get(self, item_id: str) -> Optional[InboxItem]:
        return self._items.get(item_id)

    def count_pending(self) -> int:
        """Return count of pending items."""
        return sum(1 for i in self._items.values() if i.status == "pending")

    # ── Persistence ───────────────────────────────────────────────────

    def _get_pending(self, item_id: str) -> InboxItem:
        item = self._items.get(item_id)
        if item is None:
            raise InboxError(f"Item '{item_id}' not found")
        if item.status != "pending":
            raise InboxError(f"Item '{item_id}' is already {item.status}")
        return item

    def _save(self) -> None:
        os.makedirs(self._data_dir, exist_ok=True)
        data = {k: asdict(v) for k, v in self._items.items()}
        with open(self._inbox_path, "w") as f:
            json.dump(data, f, indent=2)

    def _save_config(self) -> None:
        os.makedirs(self._data_dir, exist_ok=True)
        config = {
            "trust_level": self._trust_level,
            "auto_threshold": self._auto_threshold,
        }
        with open(self._config_path, "w") as f:
            json.dump(config, f, indent=2)

    def _load(self) -> None:
        # Load config
        if os.path.exists(self._config_path):
            with open(self._config_path) as f:
                config = json.load(f)
                self._trust_level = config.get("trust_level", TRUST_MANUAL)
                self._auto_threshold = config.get("auto_threshold", _DEFAULT_AUTO_THRESHOLD)

        # Load inbox
        if os.path.exists(self._inbox_path):
            with open(self._inbox_path) as f:
                data = json.load(f)
                for k, v in data.items():
                    self._items[k] = InboxItem(**v)

"""Protocol Task Manager — schedules and settles protocol-internal work.

When the protocol needs computational work done (e.g. similarity verification,
fingerprint embedding), it creates tasks that nodes can bid on.  The lowest
bidder wins, performs the work, and gets paid from the protocol wallet.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from oasyce.capabilities.protocol_consumer import (
    ProtocolConsumer,
    ProtocolFundError,
    RequestStatus,
)


class TaskError(Exception):
    """Raised when a task operation violates invariants."""


@dataclass
class Bid:
    """A node's bid on a protocol task."""

    bid_id: str
    task_id: str
    node_id: str
    price: float
    timestamp: int = field(default_factory=lambda: int(time.time()))


@dataclass
class ProtocolTask:
    """A unit of protocol-internal work."""

    task_id: str
    capability_type: str
    input_data: Dict
    max_price: float
    source_id: str  # e.g. asset_id that triggered this task
    status: str = RequestStatus.PENDING
    bids: List[Bid] = field(default_factory=list)
    winner_node: Optional[str] = None
    result: Optional[Dict] = None
    created_at: int = field(default_factory=lambda: int(time.time()))
    completed_at: Optional[int] = None
    fail_reason: Optional[str] = None


class ProtocolTaskManager:
    """Manages the lifecycle of protocol-internal tasks."""

    def __init__(self, consumer: ProtocolConsumer) -> None:
        self._consumer = consumer
        self._tasks: Dict[str, ProtocolTask] = {}

    # ── Task creation ─────────────────────────────────────────────────

    def create_task(
        self,
        capability_type: str,
        input_data: Dict,
        max_price: float,
        source_id: str,
    ) -> ProtocolTask:
        """Create a new protocol task open for bidding."""
        task = ProtocolTask(
            task_id=str(uuid.uuid4()),
            capability_type=capability_type,
            input_data=input_data,
            max_price=max_price,
            source_id=source_id,
        )
        self._tasks[task.task_id] = task
        return task

    # ── Bidding ───────────────────────────────────────────────────────

    def submit_bid(self, task_id: str, node_id: str, price: float) -> Bid:
        """Submit a bid for a task. Price must be <= max_price."""
        task = self._get_task(task_id)
        if task.status != RequestStatus.PENDING:
            raise TaskError(f"Task '{task_id}' is not open for bidding (status={task.status})")
        if price > task.max_price:
            raise TaskError(f"Bid price {price} exceeds max {task.max_price}")
        if price <= 0:
            raise TaskError("Bid price must be positive")

        bid = Bid(
            bid_id=str(uuid.uuid4()),
            task_id=task_id,
            node_id=node_id,
            price=price,
        )
        task.bids.append(bid)
        return bid

    def select_winner(self, task_id: str) -> Bid:
        """Select the lowest bidder, lock funds, move to IN_PROGRESS."""
        task = self._get_task(task_id)
        if task.status != RequestStatus.PENDING:
            raise TaskError(f"Task '{task_id}' is not in PENDING state")
        if not task.bids:
            raise TaskError(f"Task '{task_id}' has no bids")

        winner = min(task.bids, key=lambda b: b.price)
        # Lock funds from protocol wallet
        self._consumer.withdraw(winner.price)
        task.winner_node = winner.node_id
        task.status = RequestStatus.IN_PROGRESS
        return winner

    # ── Completion ────────────────────────────────────────────────────

    def complete_task(self, task_id: str, node_id: str, result: Dict) -> ProtocolTask:
        """Mark task as completed by the winning node."""
        task = self._get_task(task_id)
        if task.status != RequestStatus.IN_PROGRESS:
            raise TaskError(f"Task '{task_id}' is not IN_PROGRESS")
        if task.winner_node != node_id:
            raise TaskError(f"Node '{node_id}' is not the winner of task '{task_id}'")

        task.result = result
        task.status = RequestStatus.COMPLETED
        task.completed_at = int(time.time())
        return task

    def fail_task(self, task_id: str, reason: str) -> ProtocolTask:
        """Mark task as failed, refund protocol wallet."""
        task = self._get_task(task_id)
        if task.status != RequestStatus.IN_PROGRESS:
            raise TaskError(f"Task '{task_id}' is not IN_PROGRESS")

        # Refund: find the winning bid price
        winner_bid = self._find_winner_bid(task)
        if winner_bid:
            self._consumer.deposit(winner_bid.price)

        task.status = RequestStatus.FAILED
        task.fail_reason = reason
        return task

    # ── Queries ───────────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[ProtocolTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_pending_tasks(self) -> List[ProtocolTask]:
        """Return all tasks open for bidding."""
        return [t for t in self._tasks.values() if t.status == RequestStatus.PENDING]

    def get_all_tasks(self) -> List[ProtocolTask]:
        """Return all tasks."""
        return list(self._tasks.values())

    # ── Internal ──────────────────────────────────────────────────────

    def _get_task(self, task_id: str) -> ProtocolTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskError(f"Task '{task_id}' not found")
        return task

    def _find_winner_bid(self, task: ProtocolTask) -> Optional[Bid]:
        if task.winner_node is None:
            return None
        for bid in task.bids:
            if bid.node_id == task.winner_node:
                return bid
        return None

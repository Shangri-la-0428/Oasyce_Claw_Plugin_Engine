"""
AHRP v0.2 — Task Market with competitive bidding.

Extends AHRP with a marketplace where:
  1. Requester posts a Task (description, budget, deadline, capabilities)
  2. Provider Agents submit Bids (price, estimated_time, capability_proof)
  3. Winner selected via configurable strategy (lowest_price, best_reputation,
     weighted_score, or requester_choice)
  4. Selected Agent gets escrow-locked budget; others released
  5. On completion, flows into normal settlement (with diminishing returns)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(Enum):
    OPEN = "open"
    BIDDING = "bidding"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SelectionStrategy(Enum):
    LOWEST_PRICE = "lowest_price"
    BEST_REPUTATION = "best_reputation"
    WEIGHTED_SCORE = "weighted_score"
    REQUESTER_CHOICE = "requester_choice"


@dataclass
class TaskBid:
    bid_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    agent_id: str = ""
    price: float = 0.0
    estimated_seconds: int = 0
    capability_proof: Dict[str, Any] = field(default_factory=dict)
    reputation_score: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class Task:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    requester_id: str = ""
    description: str = ""
    budget: float = 0.0
    deadline: float = 0.0  # unix timestamp
    required_capabilities: List[str] = field(default_factory=list)
    selection_strategy: SelectionStrategy = SelectionStrategy.WEIGHTED_SCORE
    status: TaskStatus = TaskStatus.OPEN
    bids: List[TaskBid] = field(default_factory=list)
    assigned_agent: str = ""
    created_at: float = field(default_factory=time.time)
    min_reputation: float = 0.0


class TaskMarket:
    """Competitive bidding marketplace for AHRP tasks."""

    def __init__(self) -> None:
        self._tasks: Dict[str, Task] = {}

    def post_task(
        self,
        requester_id: str,
        description: str,
        budget: float,
        deadline_seconds: int = 3600,
        required_capabilities: Optional[List[str]] = None,
        selection_strategy: SelectionStrategy = SelectionStrategy.WEIGHTED_SCORE,
        min_reputation: float = 0.0,
    ) -> Task:
        """Create and store a new task."""
        task = Task(
            requester_id=requester_id,
            description=description,
            budget=budget,
            deadline=time.time() + deadline_seconds,
            required_capabilities=required_capabilities or [],
            selection_strategy=selection_strategy,
            min_reputation=min_reputation,
        )
        self._tasks[task.task_id] = task
        return task

    def submit_bid(
        self,
        task_id: str,
        agent_id: str,
        price: float,
        estimated_seconds: int = 0,
        capability_proof: Optional[Dict[str, Any]] = None,
        reputation_score: float = 0.0,
    ) -> TaskBid:
        """Submit a bid on an open/bidding task.

        Validates: task exists, status is OPEN or BIDDING, agent meets
        min_reputation, and price <= budget.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task.status not in (TaskStatus.OPEN, TaskStatus.BIDDING):
            raise ValueError(f"Task {task_id} is {task.status.value}, cannot accept bids")
        if reputation_score < task.min_reputation:
            raise ValueError(f"Reputation {reputation_score} below minimum {task.min_reputation}")
        if price > task.budget:
            raise ValueError(f"Bid price {price} exceeds task budget {task.budget}")

        bid = TaskBid(
            agent_id=agent_id,
            price=price,
            estimated_seconds=estimated_seconds,
            capability_proof=capability_proof or {},
            reputation_score=reputation_score,
        )
        task.bids.append(bid)
        if task.status == TaskStatus.OPEN:
            task.status = TaskStatus.BIDDING
        return bid

    def select_winner(self, task_id: str, agent_id: Optional[str] = None) -> TaskBid:
        """Select the winning bid.

        If *agent_id* is given (REQUESTER_CHOICE), that agent is chosen.
        Otherwise the task's selection_strategy is applied.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if not task.bids:
            raise ValueError(f"Task {task_id} has no bids")

        if agent_id is not None:
            # Requester's manual pick
            winner = next((b for b in task.bids if b.agent_id == agent_id), None)
            if winner is None:
                raise ValueError(f"Agent {agent_id} has no bid on task {task_id}")
        else:
            strategy = task.selection_strategy
            if strategy == SelectionStrategy.LOWEST_PRICE:
                winner = min(task.bids, key=lambda b: b.price)
            elif strategy == SelectionStrategy.BEST_REPUTATION:
                winner = max(task.bids, key=lambda b: b.reputation_score)
            elif strategy == SelectionStrategy.WEIGHTED_SCORE:
                scored = [(b, self._score_bid(b, task)) for b in task.bids]
                scored.sort(key=lambda x: x[1], reverse=True)
                winner = scored[0][0]
            else:
                raise ValueError(f"Strategy {strategy.value} requires explicit agent_id")

        task.status = TaskStatus.ASSIGNED
        task.assigned_agent = winner.agent_id
        return winner

    def complete_task(self, task_id: str) -> Task:
        """Mark a task as completed."""
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task.status != TaskStatus.ASSIGNED:
            raise ValueError(f"Task {task_id} is {task.status.value}, cannot complete")
        task.status = TaskStatus.COMPLETED
        return task

    def cancel_task(self, task_id: str) -> Task:
        """Cancel a task (only if OPEN or BIDDING)."""
        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        if task.status not in (TaskStatus.OPEN, TaskStatus.BIDDING):
            raise ValueError(f"Task {task_id} is {task.status.value}, cannot cancel")
        task.status = TaskStatus.CANCELLED
        return task

    def expire_stale_tasks(self) -> List[str]:
        """Expire tasks past their deadline that are still OPEN or BIDDING."""
        now = time.time()
        expired: List[str] = []
        for task in self._tasks.values():
            if (
                task.status in (TaskStatus.OPEN, TaskStatus.BIDDING)
                and task.deadline > 0
                and now > task.deadline
            ):
                task.status = TaskStatus.EXPIRED
                expired.append(task.task_id)
        return expired

    def get_open_tasks(self, capabilities: Optional[List[str]] = None) -> List[Task]:
        """Return tasks that are OPEN or BIDDING.

        If *capabilities* is provided, only tasks whose
        required_capabilities are a subset of *capabilities* are returned.
        """
        results: List[Task] = []
        for task in self._tasks.values():
            if task.status not in (TaskStatus.OPEN, TaskStatus.BIDDING):
                continue
            if capabilities is not None and task.required_capabilities:
                if not set(task.required_capabilities).issubset(set(capabilities)):
                    continue
            results.append(task)
        return results

    def get_task(self, task_id: str) -> Optional[Task]:
        """Return a task by ID, or None."""
        return self._tasks.get(task_id)

    # ── scoring ─────────────────────────────────────────────────────

    def _score_bid(self, bid: TaskBid, task: Task) -> float:
        """Weighted score: 0.4*price + 0.3*reputation + 0.3*speed.

        price_score  = 1 - (bid.price / task.budget)
        rep_score    = bid.reputation_score / 100
        speed_score  = 1 - (bid.estimated_seconds / max_estimated)
        """
        if task.budget <= 0:
            price_score = 0.0
        else:
            price_score = 1.0 - (bid.price / task.budget)

        rep_score = bid.reputation_score / 100.0

        max_est = max((b.estimated_seconds for b in task.bids), default=1)
        if max_est <= 0:
            speed_score = 1.0
        else:
            speed_score = 1.0 - (bid.estimated_seconds / max_est)

        return 0.4 * price_score + 0.3 * rep_score + 0.3 * speed_score

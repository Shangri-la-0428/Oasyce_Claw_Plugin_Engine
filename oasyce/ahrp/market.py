"""
AHRP Task Market — Competitive bidding for agent requests.

Extends AHRP with multi-provider competition:
  1. Client posts REQUEST with budget + SLA
  2. Router broadcasts to matching Providers
  3. Multiple Providers submit OFFERs (bids)
  4. Client auto-selects winner via Score formula
  5. Winner gets ACCEPT → normal escrow/deliver/confirm flow

Score = (Reputation × StakeWeight × OriginBonus) / BidPrice

This replaces one-to-one matching with market-driven price discovery.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from oasyce.ahrp import (
    AgentIdentity,
    Capability,
    Need,
    OfferPayload,
    RequestPayload,
    Transaction,
    TxState,
    MessageType,
)
from oasyce.ahrp.executor import AHRPExecutor
from oasyce.ahrp.router import Router


# ── Origin type bonus multipliers ────────────────────────────────────
_ORIGIN_BONUS = {
    "human": 1.3,
    "sensor": 1.2,
    "curated": 1.1,
    "synthetic": 0.5,
}


@dataclass
class Bid:
    """A Provider's sealed bid for a task."""

    offer: OfferPayload
    provider_id: str
    reputation: float
    stake: float
    origin_type: str = "human"
    submitted_at: int = field(default_factory=lambda: int(time.time()))
    score: float = 0.0


@dataclass
class TaskAuction:
    """A competitive auction for a single REQUEST."""

    request: RequestPayload
    requester_id: str
    budget_oas: float
    deadline: int  # unix timestamp, 0 = no deadline
    sla_ms: int = 5000  # max acceptable latency
    min_reputation: float = 0.0
    created_at: int = field(default_factory=lambda: int(time.time()))
    bids: List[Bid] = field(default_factory=list)
    bidding_window_ms: int = 2000  # how long to collect bids
    winner: Optional[Bid] = None
    closed: bool = False

    @property
    def is_expired(self) -> bool:
        if self.deadline > 0 and int(time.time()) > self.deadline:
            return True
        return False

    @property
    def bidding_closed(self) -> bool:
        elapsed_ms = (int(time.time()) - self.created_at) * 1000
        return elapsed_ms >= self.bidding_window_ms or self.closed


def score_bid(bid: Bid, budget: float) -> float:
    """Score formula: higher is better.

    Score = (Reputation × StakeWeight × OriginBonus) / BidPrice

    Where:
      - Reputation ∈ [0, 95], normalized to [0, 1]
      - StakeWeight = log2(1 + stake/1000), capped at 5
      - OriginBonus = 1.3 for human, 0.5 for synthetic
      - BidPrice must be > 0 and ≤ budget

    Returns 0.0 if bid violates hard constraints.
    """
    if bid.offer.price_oas <= 0 or bid.offer.price_oas > budget:
        return 0.0

    rep_normalized = bid.reputation / 95.0
    stake_weight = min(5.0, math.log2(1.0 + bid.stake / 1000.0))
    origin_bonus = _ORIGIN_BONUS.get(bid.origin_type, 1.0)

    score = (rep_normalized * stake_weight * origin_bonus) / bid.offer.price_oas
    return round(score, 6)


class TaskMarket:
    """Competitive bidding layer on top of AHRP.

    Usage:
        market = TaskMarket(router, executor)
        auction = market.create_auction(request, requester_id)
        market.submit_bid(auction_id, offer, provider_id)
        winner = market.close_auction(auction_id)  # auto-selects best bid
        tx = market.execute_winner(auction_id)      # triggers escrow
    """

    def __init__(self, router: Router, executor: AHRPExecutor):
        self.router = router
        self.executor = executor
        self.auctions: Dict[str, TaskAuction] = {}

    def create_auction(
        self,
        request: RequestPayload,
        requester_id: str,
        sla_ms: int = 5000,
        bidding_window_ms: int = 2000,
    ) -> TaskAuction:
        """Create a competitive auction for a task.

        1. Route the request to find candidate providers
        2. Create an auction with a bidding window
        3. Return auction (providers will submit bids)
        """
        # Route to find candidates (for notification)
        self.router.route(request, requester_id)

        auction = TaskAuction(
            request=request,
            requester_id=requester_id,
            budget_oas=request.budget_oas,
            deadline=request.deadline,
            sla_ms=sla_ms,
            min_reputation=request.need.min_reputation,
            bidding_window_ms=bidding_window_ms,
        )
        self.auctions[request.request_id] = auction
        return auction

    def submit_bid(
        self,
        auction_id: str,
        offer: OfferPayload,
        provider_id: str,
    ) -> Bid:
        """Provider submits a bid for an auction."""
        auction = self.auctions.get(auction_id)
        if not auction:
            raise ValueError(f"Auction {auction_id} not found")
        if auction.closed:
            raise ValueError(f"Auction {auction_id} is closed")

        # Get provider info from router/executor
        agent = self.executor.agents.get(provider_id)
        if not agent:
            raise ValueError(f"Agent {provider_id} not registered")

        if agent.reputation < auction.min_reputation:
            raise ValueError(
                f"Agent reputation {agent.reputation} below minimum {auction.min_reputation}"
            )

        # Get capability info for origin_type
        caps = self.executor.capabilities.get(provider_id, [])
        origin_type = "human"
        for cap in caps:
            if cap.capability_id == offer.capability_id:
                origin_type = cap.origin_type
                break

        bid = Bid(
            offer=offer,
            provider_id=provider_id,
            reputation=agent.reputation,
            stake=agent.stake,
            origin_type=origin_type,
        )
        bid.score = score_bid(bid, auction.budget_oas)
        auction.bids.append(bid)
        return bid

    def close_auction(self, auction_id: str) -> Optional[Bid]:
        """Close bidding and select the winner (highest score)."""
        auction = self.auctions.get(auction_id)
        if not auction:
            raise ValueError(f"Auction {auction_id} not found")

        auction.closed = True

        if not auction.bids:
            return None

        # Sort by score descending
        valid_bids = [b for b in auction.bids if b.score > 0]
        if not valid_bids:
            return None

        valid_bids.sort(key=lambda b: b.score, reverse=True)
        auction.winner = valid_bids[0]
        return auction.winner

    def execute_winner(self, auction_id: str) -> Transaction:
        """Execute the winning bid: lock escrow via AHRP Executor."""
        auction = self.auctions.get(auction_id)
        if not auction:
            raise ValueError(f"Auction {auction_id} not found")
        if not auction.winner:
            raise ValueError(f"No winner for auction {auction_id}")

        return self.executor.handle_accept(
            buyer_id=auction.requester_id,
            seller_id=auction.winner.provider_id,
            offer=auction.winner.offer,
        )

    def stats(self) -> Dict[str, Any]:
        total = len(self.auctions)
        closed = sum(1 for a in self.auctions.values() if a.closed)
        with_winner = sum(1 for a in self.auctions.values() if a.winner)
        total_bids = sum(len(a.bids) for a in self.auctions.values())
        return {
            "total_auctions": total,
            "closed_auctions": closed,
            "auctions_with_winner": with_winner,
            "total_bids": total_bids,
            "avg_bids_per_auction": round(total_bids / max(1, total), 1),
        }

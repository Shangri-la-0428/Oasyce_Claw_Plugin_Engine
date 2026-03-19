"""
AHRP Router — Capability discovery and request routing.

The Router is the "search engine" of the agent network:
  1. Indexes ANNOUNCE messages into a capability registry
  2. Routes REQUEST messages to best-matching agents
  3. Manages agent liveness (TTL-based expiry)
  4. Provides network-wide capability search

Design: in-memory for v0.1, swappable to distributed index later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from oasyce.ahrp import (
    AgentIdentity,
    AnnouncePayload,
    Capability,
    Need,
    RequestPayload,
    OfferPayload,
    match_score,
)


@dataclass
class AgentRecord:
    """Indexed agent with liveness tracking."""

    identity: AgentIdentity
    capabilities: List[Capability]
    endpoints: List[str]
    last_seen: int = field(default_factory=lambda: int(time.time()))
    heartbeat_interval: int = 600  # expected re-announce interval
    announce_count: int = 1

    @property
    def is_alive(self) -> bool:
        """Agent is alive if last_seen within 2× heartbeat interval."""
        return (int(time.time()) - self.last_seen) < (self.heartbeat_interval * 2)


@dataclass
class PendingRequest:
    """A REQUEST waiting for OFFERs."""

    request_id: str
    requester_id: str
    need: Need
    budget_oas: float
    deadline: int  # 0 = no deadline
    created_at: int = field(default_factory=lambda: int(time.time()))
    matches_sent: int = 0
    offers_received: List[OfferPayload] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        return self.deadline > 0 and int(time.time()) > self.deadline


class Router:
    """Capability search engine and request router.

    Usage:
        router = Router()
        router.announce(payload)           # index agent
        matches = router.route(request)    # find matches for a need
        results = router.search(tags=["finance"], top_k=10)  # browse
    """

    def __init__(self, default_ttl: int = 1200):
        self._agents: Dict[str, AgentRecord] = {}
        self._requests: Dict[str, PendingRequest] = {}
        self._default_ttl = default_ttl

    # ── Index ────────────────────────────────────────────────────────
    def announce(self, payload: AnnouncePayload) -> AgentRecord:
        """Index or refresh an agent's capabilities."""
        agent_id = payload.identity.agent_id
        existing = self._agents.get(agent_id)

        if existing:
            # Refresh: update capabilities, bump last_seen
            existing.capabilities = list(payload.capabilities)
            existing.endpoints = list(payload.endpoints)
            existing.last_seen = int(time.time())
            existing.announce_count += 1
            existing.identity = payload.identity  # might have updated rep
            return existing

        record = AgentRecord(
            identity=payload.identity,
            capabilities=list(payload.capabilities),
            endpoints=list(payload.endpoints),
            heartbeat_interval=payload.heartbeat_interval,
        )
        self._agents[agent_id] = record
        return record

    def remove(self, agent_id: str) -> bool:
        """Explicitly remove an agent from the index."""
        return self._agents.pop(agent_id, None) is not None

    # ── Search ───────────────────────────────────────────────────────
    def search(
        self,
        tags: Optional[List[str]] = None,
        origin_type: Optional[str] = None,
        min_reputation: float = 0.0,
        max_price: float = float("inf"),
        top_k: int = 10,
        alive_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Browse capabilities by filters. Returns sorted by relevance."""
        results = []
        for agent_id, record in self._agents.items():
            if alive_only and not record.is_alive:
                continue
            if record.identity.reputation < min_reputation:
                continue
            for cap in record.capabilities:
                # Filter by tags
                if tags and not set(tags) & set(cap.tags):
                    continue
                # Filter by origin_type
                if origin_type and cap.origin_type != origin_type:
                    continue
                # Filter by price
                if cap.price_floor > max_price:
                    continue
                results.append(
                    {
                        "agent_id": agent_id,
                        "capability_id": cap.capability_id,
                        "tags": cap.tags,
                        "origin_type": cap.origin_type,
                        "price_floor": cap.price_floor,
                        "access_levels": cap.access_levels,
                        "reputation": record.identity.reputation,
                        "endpoints": record.endpoints,
                    }
                )
        # Sort by reputation descending
        results.sort(key=lambda x: x["reputation"], reverse=True)
        return results[:top_k]

    # ── Route ────────────────────────────────────────────────────────
    def route(
        self,
        request: RequestPayload,
        requester_id: str,
        top_k: int = 5,
        min_score: float = 0.1,
    ) -> List[Dict[str, Any]]:
        """Route a REQUEST to best-matching agents.

        Returns ranked list of {agent_id, capability_id, score, ...}.
        Also stores the request for potential reverse-matching
        (when a new ANNOUNCE arrives that matches a pending request).
        """
        # Store pending request
        self._requests[request.request_id] = PendingRequest(
            request_id=request.request_id,
            requester_id=requester_id,
            need=request.need,
            budget_oas=request.budget_oas,
            deadline=request.deadline,
        )

        # Find matches
        results = []
        for agent_id, record in self._agents.items():
            if agent_id == requester_id:
                continue
            if not record.is_alive:
                continue
            if record.identity.reputation < request.need.min_reputation:
                continue
            for cap in record.capabilities:
                score = match_score(request.need, cap)
                if score >= min_score:
                    results.append(
                        {
                            "agent_id": agent_id,
                            "capability_id": cap.capability_id,
                            "score": round(score, 4),
                            "price_floor": cap.price_floor,
                            "origin_type": cap.origin_type,
                            "access_levels": cap.access_levels,
                            "endpoints": record.endpoints,
                        }
                    )

        results.sort(key=lambda x: x["score"], reverse=True)
        matched = results[:top_k]
        self._requests[request.request_id].matches_sent = len(matched)
        return matched

    # ── Reverse match (new announce triggers pending requests) ───────
    def check_pending_requests(self, agent_id: str) -> List[Tuple[str, float]]:
        """When a new agent announces, check if it matches any pending requests.

        Returns list of (request_id, score) for requests this agent could fulfill.
        """
        record = self._agents.get(agent_id)
        if not record:
            return []

        matches = []
        for req_id, pending in self._requests.items():
            if pending.is_expired or pending.requester_id == agent_id:
                continue
            for cap in record.capabilities:
                score = match_score(pending.need, cap)
                if score >= 0.1:
                    matches.append((req_id, round(score, 4)))
                    break  # one match per request is enough
        return matches

    # ── Maintenance ──────────────────────────────────────────────────
    def gc(self) -> int:
        """Garbage collect expired agents and requests. Returns count removed."""
        removed = 0
        # Expire dead agents
        dead = [aid for aid, rec in self._agents.items() if not rec.is_alive]
        for aid in dead:
            del self._agents[aid]
            removed += 1
        # Expire old requests
        expired = [rid for rid, req in self._requests.items() if req.is_expired]
        for rid in expired:
            del self._requests[rid]
            removed += 1
        return removed

    # ── Stats ────────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        alive = sum(1 for r in self._agents.values() if r.is_alive)
        total_caps = sum(len(r.capabilities) for r in self._agents.values())
        return {
            "total_agents": len(self._agents),
            "alive_agents": alive,
            "total_capabilities": total_caps,
            "pending_requests": len(self._requests),
            "unique_tags": len(
                set(
                    tag for r in self._agents.values() for cap in r.capabilities for tag in cap.tags
                )
            ),
        }

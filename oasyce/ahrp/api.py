"""
AHRP HTTP API — RESTful interface for the Agent Handshake & Routing Protocol.

Any scaffolding (OpenClaw, LangChain, raw Python) can interact with Oasyce
via these endpoints. This is the "plug-and-play" surface.

Endpoints:
  POST /ahrp/v1/announce       — Register agent + capabilities
  POST /ahrp/v1/search         — Browse capabilities by filters
  POST /ahrp/v1/request        — Submit a need, get matched agents
  POST /ahrp/v1/accept         — Accept an offer, lock escrow
  POST /ahrp/v1/deliver        — Submit delivery proof
  POST /ahrp/v1/confirm        — Confirm receipt, release payment
  GET  /ahrp/v1/tx/{tx_id}     — Transaction status
  GET  /ahrp/v1/stats          — Network statistics

Task Market (v0.2):
  POST   /ahrp/v1/tasks                — Post a new task
  GET    /ahrp/v1/tasks                — List open tasks
  POST   /ahrp/v1/tasks/{id}/bid       — Submit bid
  POST   /ahrp/v1/tasks/{id}/select    — Select winner
  POST   /ahrp/v1/tasks/{id}/complete  — Mark completed
  DELETE /ahrp/v1/tasks/{id}           — Cancel task
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from oasyce.ahrp import (
    AgentIdentity,
    AnnouncePayload,
    Capability,
    ConfirmPayload,
    DeliverPayload,
    Need,
    OfferPayload,
    RequestPayload,
    TxState,
)
from oasyce.ahrp.executor import AHRPExecutor
from oasyce.ahrp.router import Router
from oasyce.ahrp.task_market import (
    SelectionStrategy,
    TaskMarket as _TaskMarket,
)

# ── Pydantic Schemas ─────────────────────────────────────────────────


class CapabilityIn(BaseModel):
    capability_id: str
    tags: List[str] = []
    description: str = ""
    semantic_vector: Optional[List[float]] = None
    access_levels: List[str] = ["L0"]
    price_floor: float = 0.0
    origin_type: str = "human"


class AgentIdentityIn(BaseModel):
    agent_id: str
    public_key: str
    reputation: float = 10.0
    stake: float = 0.0
    metadata: Dict[str, str] = {}


class AnnounceIn(BaseModel):
    identity: AgentIdentityIn
    capabilities: List[CapabilityIn]
    endpoints: List[str] = []
    heartbeat_interval: int = 600


class SearchIn(BaseModel):
    tags: Optional[List[str]] = None
    origin_type: Optional[str] = None
    min_reputation: float = 0.0
    max_price: float = float("inf")
    top_k: int = 10


class NeedIn(BaseModel):
    description: str
    tags: List[str] = []
    semantic_vector: Optional[List[float]] = None
    min_reputation: float = 0.0
    max_price: float = float("inf")
    required_access_level: str = "L0"
    preferred_origin_type: Optional[str] = None


class RequestIn(BaseModel):
    requester_id: str
    need: NeedIn
    budget_oas: float = 0.0
    request_id: str = ""
    deadline: int = 0


class OfferIn(BaseModel):
    request_id: str = ""
    capability_id: str = ""
    price_oas: float = 0.0
    access_level: str = "L0"
    offer_id: str = ""


class AcceptIn(BaseModel):
    buyer_id: str
    seller_id: str
    offer: OfferIn


class DeliverIn(BaseModel):
    tx_id: str
    offer_id: str = ""
    content_hash: str = ""
    content_ref: str = ""
    content_size_bytes: int = 0
    access_level: str = "L0"


class ConfirmIn(BaseModel):
    tx_id: str
    offer_id: str = ""
    content_hash_verified: bool = False
    rating: Optional[int] = None


class TaskPostIn(BaseModel):
    requester_id: str
    description: str
    budget: float
    deadline_seconds: int = 3600
    required_capabilities: List[str] = []
    selection_strategy: str = "weighted_score"
    min_reputation: float = 0.0


class TaskBidIn(BaseModel):
    agent_id: str
    price: float
    estimated_seconds: int = 0
    capability_proof: Dict[str, Any] = {}
    reputation_score: float = 0.0


class TaskSelectIn(BaseModel):
    agent_id: Optional[str] = None


class Envelope(BaseModel):
    ok: bool
    data: Any = None
    error: Optional[str] = None


# ── Converters ───────────────────────────────────────────────────────


def _to_identity(i: AgentIdentityIn) -> AgentIdentity:
    return AgentIdentity(
        agent_id=i.agent_id,
        public_key=i.public_key,
        reputation=i.reputation,
        stake=i.stake,
        metadata=i.metadata,
    )


def _to_capability(c: CapabilityIn) -> Capability:
    return Capability(
        capability_id=c.capability_id,
        tags=c.tags,
        description=c.description,
        semantic_vector=c.semantic_vector,
        access_levels=c.access_levels,
        price_floor=c.price_floor,
        origin_type=c.origin_type,
    )


def _to_need(n: NeedIn) -> Need:
    return Need(
        description=n.description,
        tags=n.tags,
        semantic_vector=n.semantic_vector,
        min_reputation=n.min_reputation,
        max_price=n.max_price,
        required_access_level=n.required_access_level,
        preferred_origin_type=n.preferred_origin_type,
    )


# ── Router Factory ───────────────────────────────────────────────────

_router_instance: Optional[Router] = None
_executor_instance: Optional[AHRPExecutor] = None
_task_market_instance: Optional[_TaskMarket] = None


def init_api(router: Router, executor: AHRPExecutor) -> None:
    """Inject shared instances (called by server.py)."""
    global _router_instance, _executor_instance
    _router_instance = router
    _executor_instance = executor


def get_router() -> Router:
    global _router_instance
    if _router_instance is None:
        _router_instance = Router()
    return _router_instance


def get_executor() -> AHRPExecutor:
    global _executor_instance
    if _executor_instance is None:
        from oasyce.config import get_network_mode, get_security

        mode = get_network_mode()
        security = get_security(mode)
        _executor_instance = AHRPExecutor(
            require_signature=security["require_signatures"],
            network_mode=mode,
        )
    return _executor_instance


def get_task_market() -> _TaskMarket:
    global _task_market_instance
    if _task_market_instance is None:
        _task_market_instance = _TaskMarket()
    return _task_market_instance


# ── API Routes ───────────────────────────────────────────────────────

api = APIRouter(prefix="/ahrp/v1", tags=["AHRP"])


@api.post("/announce", response_model=Envelope)
def announce(body: AnnounceIn) -> Envelope:
    """Register or refresh an agent's identity and capabilities."""
    router = get_router()
    executor = get_executor()

    payload = AnnouncePayload(
        identity=_to_identity(body.identity),
        capabilities=[_to_capability(c) for c in body.capabilities],
        endpoints=body.endpoints,
        heartbeat_interval=body.heartbeat_interval,
    )
    record = router.announce(payload)
    executor.handle_announce(payload)

    # Check if new agent matches any pending requests
    pending = router.check_pending_requests(body.identity.agent_id)

    return Envelope(
        ok=True,
        data={
            "agent_id": body.identity.agent_id,
            "capabilities_indexed": len(body.capabilities),
            "announce_count": record.announce_count,
            "pending_matches": [{"request_id": r, "score": s} for r, s in pending],
        },
    )


@api.post("/search", response_model=Envelope)
def search(body: SearchIn) -> Envelope:
    """Browse capabilities by filters."""
    router = get_router()
    results = router.search(
        tags=body.tags,
        origin_type=body.origin_type,
        min_reputation=body.min_reputation,
        max_price=body.max_price,
        top_k=body.top_k,
    )
    return Envelope(ok=True, data={"results": results, "count": len(results)})


@api.post("/request", response_model=Envelope)
def request_route(body: RequestIn) -> Envelope:
    """Submit a need and get matched agents."""
    router = get_router()
    payload = RequestPayload(
        need=_to_need(body.need),
        budget_oas=body.budget_oas,
        request_id=body.request_id or f"req-{id(body)}",
        deadline=body.deadline,
    )
    matches = router.route(payload, requester_id=body.requester_id)
    return Envelope(ok=True, data={"matches": matches, "count": len(matches)})


@api.post("/accept", response_model=Envelope)
def accept(body: AcceptIn) -> Envelope:
    """Accept an offer and lock escrow."""
    executor = get_executor()
    try:
        offer = OfferPayload(
            request_id=body.offer.request_id,
            capability_id=body.offer.capability_id,
            price_oas=body.offer.price_oas,
            access_level=body.offer.access_level,
            offer_id=body.offer.offer_id,
        )
        tx = executor.handle_accept(body.buyer_id, body.seller_id, offer)
        return Envelope(
            ok=True,
            data={
                "tx_id": tx.tx_id,
                "state": tx.state.value,
                "escrow_tx_id": tx.accept.escrow_tx_id if tx.accept else None,
            },
        )
    except Exception as e:
        return Envelope(ok=False, error=str(e))


@api.post("/deliver", response_model=Envelope)
def deliver(body: DeliverIn) -> Envelope:
    """Submit delivery proof."""
    executor = get_executor()
    try:
        payload = DeliverPayload(
            offer_id=body.offer_id,
            content_hash=body.content_hash,
            content_ref=body.content_ref,
            content_size_bytes=body.content_size_bytes,
            access_level=body.access_level,
        )
        tx = executor.handle_deliver(body.tx_id, payload)
        return Envelope(ok=True, data={"tx_id": tx.tx_id, "state": tx.state.value})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@api.post("/confirm", response_model=Envelope)
def confirm(body: ConfirmIn) -> Envelope:
    """Confirm receipt and release payment."""
    executor = get_executor()
    try:
        payload = ConfirmPayload(
            offer_id=body.offer_id,
            content_hash_verified=body.content_hash_verified,
            rating=body.rating,
        )
        tx = executor.handle_confirm(body.tx_id, payload)
        return Envelope(
            ok=True,
            data={
                "tx_id": tx.tx_id,
                "state": tx.state.value,
                "settled_at": tx.settled_at,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@api.get("/tx/{tx_id}", response_model=Envelope)
def get_transaction(tx_id: str) -> Envelope:
    """Get transaction status."""
    executor = get_executor()
    tx = executor.transactions.get(tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail=f"Transaction {tx_id} not found")
    return Envelope(
        ok=True,
        data={
            "tx_id": tx.tx_id,
            "buyer": tx.buyer,
            "seller": tx.seller,
            "state": tx.state.value,
            "created_at": tx.created_at,
            "settled_at": tx.settled_at,
        },
    )


@api.get("/stats", response_model=Envelope)
def stats() -> Envelope:
    """Network statistics."""
    router = get_router()
    executor = get_executor()
    return Envelope(
        ok=True,
        data={
            "router": router.stats(),
            "executor": executor.stats(),
        },
    )


# ── Task Market (v0.2) ─────────────────────────────────────────────


@api.post("/tasks", response_model=Envelope)
def post_task(body: TaskPostIn) -> Envelope:
    """Post a new task to the market."""
    market = get_task_market()
    try:
        strategy = SelectionStrategy(body.selection_strategy)
    except ValueError:
        return Envelope(ok=False, error=f"Invalid strategy: {body.selection_strategy}")
    try:
        task = market.post_task(
            requester_id=body.requester_id,
            description=body.description,
            budget=body.budget,
            deadline_seconds=body.deadline_seconds,
            required_capabilities=body.required_capabilities or None,
            selection_strategy=strategy,
            min_reputation=body.min_reputation,
        )
        return Envelope(
            ok=True,
            data={
                "task_id": task.task_id,
                "status": task.status.value,
                "budget": task.budget,
            },
        )
    except Exception as e:
        return Envelope(ok=False, error=str(e))


@api.get("/tasks", response_model=Envelope)
def list_tasks(capability: Optional[str] = None) -> Envelope:
    """List open tasks, optionally filtered by capability."""
    market = get_task_market()
    caps = [capability] if capability else None
    tasks = market.get_open_tasks(capabilities=caps)
    return Envelope(
        ok=True,
        data={
            "tasks": [
                {
                    "task_id": t.task_id,
                    "description": t.description,
                    "budget": t.budget,
                    "status": t.status.value,
                    "required_capabilities": t.required_capabilities,
                    "bid_count": len(t.bids),
                }
                for t in tasks
            ],
            "count": len(tasks),
        },
    )


@api.post("/tasks/{task_id}/bid", response_model=Envelope)
def submit_task_bid(task_id: str, body: TaskBidIn) -> Envelope:
    """Submit a bid on a task."""
    market = get_task_market()
    try:
        bid = market.submit_bid(
            task_id=task_id,
            agent_id=body.agent_id,
            price=body.price,
            estimated_seconds=body.estimated_seconds,
            capability_proof=body.capability_proof or None,
            reputation_score=body.reputation_score,
        )
        return Envelope(
            ok=True,
            data={
                "bid_id": bid.bid_id,
                "agent_id": bid.agent_id,
                "price": bid.price,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/tasks/{task_id}/select", response_model=Envelope)
def select_task_winner(task_id: str, body: TaskSelectIn) -> Envelope:
    """Select the winning bid (auto or manual)."""
    market = get_task_market()
    try:
        winner = market.select_winner(task_id, agent_id=body.agent_id)
        task = market.get_task(task_id)
        return Envelope(
            ok=True,
            data={
                "task_id": task_id,
                "winner_agent": winner.agent_id,
                "winning_price": winner.price,
                "status": task.status.value if task else "unknown",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/tasks/{task_id}/complete", response_model=Envelope)
def complete_task(task_id: str) -> Envelope:
    """Mark a task as completed."""
    market = get_task_market()
    try:
        task = market.complete_task(task_id)
        return Envelope(
            ok=True,
            data={
                "task_id": task.task_id,
                "status": task.status.value,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.delete("/tasks/{task_id}", response_model=Envelope)
def cancel_task(task_id: str) -> Envelope:
    """Cancel a task (only OPEN or BIDDING)."""
    market = get_task_market()
    try:
        task = market.cancel_task(task_id)
        return Envelope(
            ok=True,
            data={
                "task_id": task.task_id,
                "status": task.status.value,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

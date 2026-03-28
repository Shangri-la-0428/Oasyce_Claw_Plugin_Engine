"""Oasyce API Client — zero-dependency HTTP client for AI agent integration.

Quick start (10 lines, full search → buy → access flow):

    from oasyce.client import Oasyce

    node = Oasyce("http://localhost:8080")
    node.create_identity()                          # first run only
    node.faucet()                                   # get testnet OAS

    assets = node.assets()                          # browse marketplace
    quote  = node.quote(assets[0]["asset_id"])      # check price
    node.buy(quote["asset_id"], buyer="agent-1")    # buy tokens
    preview = node.preview(quote["asset_id"], level="L1")  # access data

    caps = node.discover(intents="translation")     # find capabilities
    result = node.invoke_capability(caps[0]["capability_id"], input={"text": "hello"})

All methods return plain dicts.  Errors raise OasyceAPIError.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


class OasyceAPIError(Exception):
    """Raised when the Oasyce API returns an error."""

    def __init__(self, message: str, status: int = 0, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class Oasyce:
    """Lightweight HTTP client for a remote Oasyce node.

    Args:
        base_url: Node URL, e.g. "http://localhost:8080"
        token: Bearer auth token. If None, auto-fetched from /api/auth/token.
    """

    def __init__(self, base_url: str = "http://localhost:8080", token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self._token = token

    @property
    def token(self) -> str:
        if self._token is None:
            resp = self._get("/api/auth/token")
            self._token = resp.get("token", "")
        return self._token

    # ── HTTP primitives ──────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        request_headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            request_headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if method == "POST" or method == "DELETE":
            request_headers["Authorization"] = f"Bearer {self.token}"
        if headers:
            request_headers.update(headers)
        req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with self._open_request(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                err_body = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                err_body = raw
            msg = err_body.get("error", raw) if isinstance(err_body, dict) else raw
            raise OasyceAPIError(msg, status=e.code, body=err_body) from None

    def _open_request(self, req: urllib.request.Request, timeout: int = 30):
        if self._should_bypass_proxy(req.full_url):
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            return opener.open(req, timeout=timeout)
        return urllib.request.urlopen(req, timeout=timeout)

    @staticmethod
    def _should_bypass_proxy(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

    @staticmethod
    def _trace_headers(trace_id: Optional[str]) -> Dict[str, str]:
        if not trace_id:
            return {}
        return {"X-Trace-Id": trace_id}

    def _get(self, path: str, headers: Optional[Dict[str, str]] = None, **params) -> Any:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        return self._request("GET", f"{path}?{qs}" if qs else path, headers=headers)

    def _post(
        self,
        path: str,
        body: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        return self._request("POST", path, body or {}, headers=headers)

    def _delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    # ── System ───────────────────────────────────────────────────

    def info(self, lang: str = "en") -> Dict:
        """Project metadata and version info."""
        return self._get("/api/info", lang=lang)

    def status(self) -> Dict:
        """Dashboard API status."""
        return self._get("/api/status")

    def support_beta(self, limit: int = 20, transactions_limit: int = 20) -> Dict:
        """Recent beta core-flow events, failures, and transactions."""
        return self._get(
            "/api/support/beta",
            limit=limit,
            transactions_limit=transactions_limit,
        )

    def balance(self, address: str) -> Dict:
        """Query OAS balance for an address."""
        return self._get("/api/balance", address=address)

    # ── Identity ─────────────────────────────────────────────────

    def identity(self) -> Dict:
        """Get node identity and wallet info."""
        return self._get("/api/identity")

    def create_identity(self) -> Dict:
        """Generate a new node identity and wallet."""
        return self._post("/api/identity/create")

    def faucet(self) -> Dict:
        """Claim testnet OAS tokens (rate limited)."""
        return self._post("/api/faucet")

    # ── Assets ───────────────────────────────────────────────────

    def assets(self) -> List[Dict]:
        """List all registered data assets."""
        resp = self._get("/api/assets")
        return resp.get("assets", resp.get("data", []))

    def asset(self, asset_id: str) -> Dict:
        """Get single asset details."""
        return self._get(f"/api/asset/{asset_id}")

    def preview(self, asset_id: str, level: str = "L0", buyer: Optional[str] = None) -> Dict:
        """Preview asset content with access control."""
        return self._get(f"/api/asset/{asset_id}/preview", level=level, buyer=buyer)

    def register(
        self,
        file_path: str,
        owner: str,
        tags: str = "",
        rights_type: str = "original",
        price_model: str = "auto",
        price: float = 0,
        machine: bool = False,
        trace_id: Optional[str] = None,
    ) -> Dict:
        """Register a new data asset.

        When `machine=True`, request the normalized agent contract envelope.
        """
        body = {
            "file_path": file_path,
            "owner": owner,
            "tags": tags,
            "rights_type": rights_type,
            "price_model": price_model,
            "price": price,
        }
        if machine:
            body["format"] = "agent"
        return self._post(
            "/api/register",
            body,
            headers=self._trace_headers(trace_id),
        )

    def delete_asset(self, asset_id: str) -> Dict:
        """Delete an asset."""
        return self._delete(f"/api/asset/{asset_id}")

    # ── Trading ──────────────────────────────────────────────────

    def quote(
        self,
        asset_id: str,
        amount: int = 10,
        machine: bool = False,
        trace_id: Optional[str] = None,
    ) -> Dict:
        """Get bonding curve price quote.

        When `machine=True`, request the normalized agent contract envelope.
        """
        return self._get(
            "/api/quote",
            asset_id=asset_id,
            amount=amount,
            format="agent" if machine else None,
            headers=self._trace_headers(trace_id),
        )

    def access_quote(self, asset_id: str, buyer: Optional[str] = None) -> Dict:
        """Get access-level pricing with bond requirements."""
        return self._get("/api/access/quote", asset_id=asset_id, buyer=buyer)

    def buy(
        self,
        asset_id: str,
        buyer: str,
        amount: float = 10.0,
        machine: bool = False,
        trace_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict:
        """Buy data asset tokens via bonding curve.

        Pass `idempotency_key` for agent-driven retries so the node can replay
        the original success instead of executing a duplicate financial action.
        """
        headers = self._trace_headers(trace_id)
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        body = {
            "asset_id": asset_id,
            "buyer": buyer,
            "amount": amount,
        }
        if machine:
            body["format"] = "agent"
        return self._post(
            "/api/buy",
            body,
            headers=headers,
        )

    def sell(
        self, asset_id: str, seller: str, tokens: float, max_slippage: Optional[float] = None
    ) -> Dict:
        """Sell data asset tokens back to bonding curve."""
        body: Dict[str, Any] = {"asset_id": asset_id, "seller": seller, "tokens": tokens}
        if max_slippage is not None:
            body["max_slippage"] = max_slippage
        return self._post("/api/sell", body)

    def access_buy(self, asset_id: str, buyer: str, level: str = "L1") -> Dict:
        """Buy tiered access (L0-L3) to a data asset."""
        return self._post(
            "/api/access/buy",
            {
                "asset_id": asset_id,
                "buyer": buyer,
                "level": level,
            },
        )

    def portfolio(
        self,
        buyer: Optional[str] = None,
        machine: bool = False,
        trace_id: Optional[str] = None,
    ) -> Any:
        """Holdings with equity and access levels.

        When `machine=True`, returns the agent contract envelope with
        `contract_version/action/data/ok/state/retryable/trace_id`.
        """
        return self._get(
            "/api/portfolio",
            buyer=buyer,
            format="agent" if machine else None,
            headers=self._trace_headers(trace_id),
        )

    def earnings(self, owner: str) -> Dict:
        """Total earnings and transaction list."""
        return self._get("/api/earnings", owner=owner)

    def shares(self, owner: Optional[str] = None) -> Dict:
        """Token holdings with share prices."""
        return self._get("/api/shares", owner=owner)

    # ── Capabilities ─────────────────────────────────────────────

    def capabilities(self) -> List[Dict]:
        """List all registered capabilities."""
        resp = self._get("/api/capabilities")
        return resp.get("capabilities", resp.get("data", []))

    def discover(
        self, intents: Optional[str] = None, tags: Optional[str] = None, limit: int = 10
    ) -> List[Dict]:
        """Semantic discovery of capabilities by intent."""
        resp = self._get("/api/discover", intents=intents, tags=tags, limit=limit)
        return resp.get("results", resp.get("data", []))

    def register_capability(
        self,
        name: str,
        description: str,
        tags: List[str],
        endpoint: str = "",
        api_key: str = "",
        price: float = 0,
    ) -> Dict:
        """Register a new AI capability."""
        return self._post(
            "/api/capability/register",
            {
                "name": name,
                "description": description,
                "tags": tags,
                "endpoint": endpoint,
                "api_key": api_key,
                "price": price,
            },
        )

    def invoke_capability(self, capability_id: str, input: Any, consumer_id: str = "") -> Dict:
        """Invoke a registered capability."""
        return self._post(
            "/api/capability/invoke",
            {
                "capability_id": capability_id,
                "input": input,
                "consumer_id": consumer_id,
            },
        )

    # ── Tasks ────────────────────────────────────────────────────

    def tasks(self, capability: Optional[str] = None) -> List[Dict]:
        """List task market listings."""
        resp = self._get("/api/tasks", capability=capability)
        return resp.get("tasks", resp.get("data", []))

    def post_task(
        self,
        requester_id: str,
        description: str,
        budget: float,
        deadline_seconds: int = 3600,
        required_capabilities: Optional[List[str]] = None,
        min_reputation: float = 0,
    ) -> Dict:
        """Post a new task to the marketplace."""
        return self._post(
            "/api/task/post",
            {
                "requester_id": requester_id,
                "description": description,
                "budget": budget,
                "deadline_seconds": deadline_seconds,
                "required_capabilities": required_capabilities or [],
                "min_reputation": min_reputation,
            },
        )

    def bid_task(
        self, task_id: str, agent_id: str, price: float, estimated_seconds: int = 0
    ) -> Dict:
        """Submit a bid on a task."""
        return self._post(
            f"/api/task/{task_id}/bid",
            {
                "agent_id": agent_id,
                "price": price,
                "estimated_seconds": estimated_seconds,
            },
        )

    def select_task_winner(self, task_id: str, agent_id: Optional[str] = None) -> Dict:
        """Select the winning bid (auto if agent_id=None)."""
        return self._post(f"/api/task/{task_id}/select", {"agent_id": agent_id})

    def complete_task(self, task_id: str) -> Dict:
        """Mark a task as completed."""
        return self._post(f"/api/task/{task_id}/complete")

    # ── Disputes ─────────────────────────────────────────────────

    def file_dispute(self, asset_id: str, reason: str, buyer: str, evidence_text: str = "") -> Dict:
        """File a dispute with evidence."""
        return self._post(
            "/api/dispute/file",
            {
                "asset_id": asset_id,
                "reason": reason,
                "buyer": buyer,
                "evidence_text": evidence_text,
            },
        )

    def disputes(self, buyer: str) -> List[Dict]:
        """List disputes for a buyer."""
        resp = self._get("/api/disputes", buyer=buyer)
        return resp.get("disputes", resp.get("data", []))

    # ── Fingerprint ──────────────────────────────────────────────

    def fingerprint_embed(
        self, asset_id: str, caller_id: str, file_path: str = "", content: str = ""
    ) -> Dict:
        """Embed a watermark fingerprint into content."""
        return self._post(
            "/api/fingerprint/embed",
            {
                "asset_id": asset_id,
                "caller_id": caller_id,
                "file_path": file_path,
                "content": content,
            },
        )

    def fingerprint_extract(self, file_path: str = "", content: str = "") -> Dict:
        """Extract a watermark fingerprint from content."""
        return self._post(
            "/api/fingerprint/extract",
            {
                "file_path": file_path,
                "content": content,
            },
        )

    def trace(self, fingerprint: str) -> Dict:
        """Trace a fingerprint to its source."""
        return self._get("/api/trace", fp=fingerprint)

    # ── AHRP (Agent Handshake & Routing Protocol) ────────────────

    def ahrp_announce(
        self, agent_id: str, public_key: str, capabilities: List[Dict], reputation: float = 10.0
    ) -> Dict:
        """Register agent identity and capabilities on the AHRP network."""
        return self._post(
            "/ahrp/v1/announce",
            {
                "identity": {
                    "agent_id": agent_id,
                    "public_key": public_key,
                    "reputation": reputation,
                },
                "capabilities": capabilities,
            },
        )

    def ahrp_search(
        self,
        tags: Optional[List[str]] = None,
        min_reputation: float = 0,
        max_price: float = 0,
        top_k: int = 10,
    ) -> Dict:
        """Browse capabilities on the AHRP network."""
        body: Dict[str, Any] = {"top_k": top_k, "min_reputation": min_reputation}
        if tags:
            body["tags"] = tags
        if max_price > 0:
            body["max_price"] = max_price
        return self._post("/ahrp/v1/search", body)

    def ahrp_request(
        self,
        requester_id: str,
        description: str,
        tags: Optional[List[str]] = None,
        budget_oas: float = 0,
    ) -> Dict:
        """Submit a need and get matched agents."""
        return self._post(
            "/ahrp/v1/request",
            {
                "requester_id": requester_id,
                "need": {"description": description, "tags": tags or []},
                "budget_oas": budget_oas,
            },
        )

    def ahrp_stats(self) -> Dict:
        """AHRP network statistics."""
        return self._get("/ahrp/v1/stats")

    # ── Node ─────────────────────────────────────────────────────

    def node_role(self) -> Dict:
        """Current node role, stake, and arbitrator tags."""
        return self._get("/api/node/role")

    def become_validator(self, amount: float, api_provider: str = "", api_key: str = "") -> Dict:
        """Register this node as a validator."""
        body: Dict[str, Any] = {"amount": amount}
        if api_provider:
            body["api_provider"] = api_provider
        if api_key:
            body["api_key"] = api_key
        return self._post("/api/node/become-validator", body)

    # ── Agent Scheduler ──────────────────────────────────────────

    def agent_status(self) -> Dict:
        """Autonomous agent scheduler status."""
        return self._get("/api/agent/status")

    def agent_run(self) -> Dict:
        """Trigger an agent scheduler run."""
        return self._post("/api/agent/run")

    def agent_config(self, **updates) -> Dict:
        """Get or update agent scheduler config."""
        if updates:
            return self._post("/api/agent/config", updates)
        return self._get("/api/agent/config")

    # ── Convenience ──────────────────────────────────────────────

    def openapi(self) -> Dict:
        """Fetch this node's OpenAPI spec."""
        return self._get("/openapi.yaml")

    def __repr__(self) -> str:
        return f"Oasyce({self.base_url!r})"

"""
Oasyce Web Dashboard — zero-dependency SPA served via Python stdlib.

Serves on port 8420. All HTML/CSS/JS is embedded in this single file.
Reads chain data from the local Ledger database.
"""

from __future__ import annotations

import cgi
import hashlib
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import time
import zipfile
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError

from oasyce.config import Config
from oasyce.storage.ledger import Ledger
from oasyce.fingerprint import FingerprintRegistry


# ── Shared state (set by OasyceGUI before server starts) ─────────────
DASHBOARD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "dashboard", "dist"
)

_ledger: Optional[Ledger] = None
_config: Optional[Config] = None
_settlement: Any = None
_staking: Any = None
_skills: Any = None
_cap_registry: Any = None
_cap_escrow: Any = None
_cap_shares: Any = None
_cap_engine: Any = None
_discovery: Any = None
_mempool: Any = None
_block_producer: Any = None
_consensus_engine: Any = None
_notification_service: Any = None
_dispute_db_conn: Any = None


def _get_notification_service():
    """Lazy-init notification service."""
    global _notification_service
    if _notification_service is None:
        from oasyce.services.notifications import NotificationService

        db_path = None
        if _config:
            db_path = os.path.join(_config.data_dir, "notifications.db")
        _notification_service = NotificationService(db_path=db_path)
    return _notification_service


def _get_dispute_db():
    """Lazy-init dispute SQLite database."""
    global _dispute_db_conn
    if _dispute_db_conn is None:
        data_dir = _config.data_dir if _config else os.path.join(os.path.expanduser("~"), ".oasyce")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "disputes.db")
        _dispute_db_conn = sqlite3.connect(db_path, check_same_thread=False)
        _dispute_db_conn.row_factory = sqlite3.Row
        _dispute_db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS disputes (
                dispute_id TEXT PRIMARY KEY,
                asset_id TEXT NOT NULL,
                buyer TEXT NOT NULL,
                reason TEXT NOT NULL,
                evidence_text TEXT DEFAULT '',
                status TEXT DEFAULT 'open',
                created_at REAL NOT NULL,
                resolved_at REAL,
                resolution TEXT
            )
        """
        )
        _dispute_db_conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_disputes_buyer
            ON disputes (buyer, created_at DESC)
        """
        )
        _dispute_db_conn.commit()
    return _dispute_db_conn


def _default_identity() -> str:
    """Return the wallet address if available, otherwise 'anonymous'."""
    try:
        from oasyce.identity import Wallet

        return Wallet.get_address() or "anonymous"
    except Exception:
        return "anonymous"


# ── Security: API token + rate limiting ──────────────────────────────
_api_token: str = ""

# Rate limiter: {ip: [(timestamp, ...)] }
_rate_limits: Dict[str, list] = defaultdict(list)
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 60  # max requests per window for mutating endpoints

# Anti-wash-trading cooldown: {(buyer, asset_id): last_buy_timestamp}
_buy_cooldowns: Dict[tuple, float] = {}
BUY_COOLDOWN_SECONDS = 30  # minimum seconds between same buyer+asset purchases


def _save_api_key(data_dir: str, api_key: str) -> None:
    """Save AI API key to a separate, chmod-protected file."""
    from pathlib import Path as _P

    key_file = _P(data_dir) / "ai_api_key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(api_key)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if request is within rate limit, False if exceeded."""
    now = time.time()
    window = _rate_limits[client_ip]
    # Prune old entries
    _rate_limits[client_ip] = [t for t in window if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[client_ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_limits[client_ip].append(now)
    return True


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    """Check authorization for mutating endpoints.

    Accepts either:
    - Authorization: Bearer <token> header
    - Same-origin request (Origin/Referer matches localhost)
    """
    # Check Bearer token
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {_api_token}" and _api_token:
        return True

    # Check same-origin (Dashboard served from same server)
    origin = handler.headers.get("Origin", "")
    referer = handler.headers.get("Referer", "")
    localhost_patterns = ("http://localhost:", "http://127.0.0.1:", "http://[::1]:")
    for pattern in localhost_patterns:
        if origin.startswith(pattern) or referer.startswith(pattern):
            return True

    return False


def _get_settlement():
    global _settlement
    if _settlement is None:
        from oasyce.services.settlement.engine import SettlementEngine

        _settlement = SettlementEngine()
    return _settlement


def _get_staking():
    global _staking
    if _staking is None:
        from oasyce.services.staking import StakingEngine

        _staking = StakingEngine()
    return _staking


_delivery_protocol = None
_delivery_registry = None
_delivery_escrow = None


def _get_delivery_stack():
    """Lazy-init capability delivery protocol stack."""
    global _delivery_protocol, _delivery_registry, _delivery_escrow
    if _delivery_protocol is None:
        from oasyce.services.capability_delivery.registry import EndpointRegistry
        from oasyce.services.capability_delivery.escrow import EscrowLedger
        from oasyce.services.capability_delivery.gateway import InvocationGateway
        from oasyce.services.capability_delivery.settlement import SettlementProtocol

        config = Config.from_env()
        db_dir = config.data_dir
        os.makedirs(db_dir, exist_ok=True)

        _delivery_registry = EndpointRegistry(
            db_path=os.path.join(db_dir, "capability_endpoints.db"),
            encryption_passphrase=config.signing_key or "oasyce-default-key",
        )
        _delivery_escrow = EscrowLedger(
            db_path=os.path.join(db_dir, "escrow.db"),
        )
        gateway = InvocationGateway(_delivery_registry, timeout=30.0)
        _delivery_protocol = SettlementProtocol(
            registry=_delivery_registry,
            escrow=_delivery_escrow,
            gateway=gateway,
            db_path=os.path.join(db_dir, "invocations.db"),
        )
    return _delivery_protocol, _delivery_registry, _delivery_escrow


def _get_cap_stack():
    """Lazy-init capability stack (registry + escrow + shares + engine)."""
    global _cap_registry, _cap_escrow, _cap_shares, _cap_engine
    if _cap_registry is None:
        from oasyce.capabilities.registry import CapabilityRegistry
        from oasyce.capabilities.escrow import EscrowManager
        from oasyce.capabilities.shares import ShareLedger
        from oasyce.capabilities.invocation import CapabilityInvocationEngine

        _cap_registry = CapabilityRegistry()
        _cap_escrow = EscrowManager()
        _cap_shares = ShareLedger()
        _cap_engine = CapabilityInvocationEngine(
            registry=_cap_registry,
            escrow=_cap_escrow,
            shares=_cap_shares,
        )
    return _cap_registry, _cap_escrow, _cap_shares, _cap_engine


def _get_skills():
    global _skills
    if _skills is None:
        from oasyce.skills.agent_skills import OasyceSkills

        _skills = OasyceSkills(_config)
    return _skills


def _get_discovery():
    global _discovery
    if _discovery is None:
        from oasyce.services.discovery import SkillDiscoveryEngine

        def _list_capabilities():
            try:
                reg, _, _, _ = _get_cap_stack()
                caps = reg.list_all()
                return [
                    {
                        "capability_id": m.capability_id,
                        "name": m.name,
                        "provider": m.provider,
                        "tags": m.tags,
                        "intents": m.tags,  # use tags as intents for now
                        "semantic_vector": m.semantic_vector,
                        "base_price": m.pricing.base_price if m.pricing else 1.0,
                    }
                    for m in caps
                ]
            except Exception:
                return []

        _discovery = SkillDiscoveryEngine(get_capabilities=_list_capabilities)
    return _discovery


def _json_response(handler: BaseHTTPRequestHandler, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)


def _serve_static(handler, file_path):
    """Serve a static file from dashboard/dist/"""
    if not os.path.isfile(file_path):
        handler.send_error(404)
        return
    mime, _ = mimetypes.guess_type(file_path)
    if mime is None:
        mime = "application/octet-stream"
    with open(file_path, "rb") as f:
        body = f.read()
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "public, max-age=31536000, immutable")
    handler.end_headers()
    handler.wfile.write(body)


# ── API helpers ──────────────────────────────────────────────────────


def _api_status() -> Dict[str, Any]:
    assert _ledger and _config
    node_id = (_config.public_key or "unknown")[:16]
    height = _ledger.get_chain_height()

    total_assets = _ledger._conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"]
    total_blocks = height
    total_distributions = _ledger._conn.execute(
        "SELECT COUNT(*) AS c FROM fingerprint_records"
    ).fetchone()["c"]

    return {
        "node_id": node_id,
        "host": _config.node_host,
        "port": _config.node_port,
        "chain_height": height,
        "total_assets": total_assets,
        "total_blocks": total_blocks,
        "total_distributions": total_distributions,
    }


def _api_blocks(limit: int = 20) -> list:
    assert _ledger
    rows = _ledger._conn.execute(
        "SELECT * FROM blocks ORDER BY block_number DESC LIMIT ?", (limit,)
    ).fetchall()
    return [
        {
            "block_number": r["block_number"],
            "block_hash": r["block_hash"],
            "prev_hash": r["prev_hash"],
            "merkle_root": r["merkle_root"],
            "timestamp": r["timestamp"],
            "tx_count": r["tx_count"],
            "nonce": r["nonce"],
        }
        for r in rows
    ]


def _api_block(n: int) -> Optional[Dict[str, Any]]:
    assert _ledger
    return _ledger.get_block(n, include_tx=True)


def _api_assets() -> list:
    assert _ledger
    rows = _ledger._conn.execute(
        "SELECT asset_id, owner, metadata, created_at FROM assets ORDER BY created_at DESC"
    ).fetchall()
    results = []
    for r in rows:
        meta = json.loads(r["metadata"]) if r["metadata"] else {}
        results.append(
            {
                "asset_id": r["asset_id"],
                "owner": r["owner"],
                "tags": meta.get("tags", []),
                "created_at": r["created_at"],
                "file_path": meta.get("file_path"),
                "file_hash": meta.get("file_hash"),
                "rights_type": meta.get("rights_type", "original"),
                "co_creators": meta.get("co_creators"),
                "disputed": meta.get("disputed", False),
                "dispute_reason": meta.get("dispute_reason"),
                "dispute_time": meta.get("dispute_time"),
                "arbitrator_candidates": meta.get("arbitrator_candidates"),
                "dispute_status": meta.get("dispute_status"),
                "dispute_resolution": meta.get("dispute_resolution"),
                "delisted": meta.get("delisted", False),
            }
        )
    # Attach spot price from settlement engine where available
    se = _get_settlement()
    for r in results:
        aid = r["asset_id"]
        if aid in se.pools:
            pool = se.pools[aid]
            if pool.supply > 0:
                r["spot_price"] = round(pool.spot_price, 6)
        if "spot_price" not in r:
            r["spot_price"] = None

    # Attach hash_status and version info
    for r in results:
        file_path = r.get("file_path")
        file_hash = r.get("file_hash")
        if not file_path or not file_hash:
            r["hash_status"] = "ok"
            continue
        try:
            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            r["hash_status"] = "ok" if h.hexdigest() == file_hash else "changed"
        except FileNotFoundError:
            r["hash_status"] = "missing"

    # Attach version info from metadata
    for r in results:
        aid = r["asset_id"]
        row = _ledger._conn.execute(
            "SELECT metadata FROM assets WHERE asset_id = ?", (aid,)
        ).fetchone()
        meta = json.loads(row["metadata"]) if row and row["metadata"] else {}
        versions = meta.get("versions", [])
        r["version"] = versions[-1]["version"] if versions else 1
        r["versions_count"] = len(versions) if versions else 1
    return results


def _api_fingerprints(asset_id: str) -> list:
    assert _ledger
    registry = FingerprintRegistry(_ledger)
    return registry.get_distributions(asset_id)


def _api_trace(fp: str) -> Optional[Dict[str, Any]]:
    assert _ledger
    registry = FingerprintRegistry(_ledger)
    return registry.trace_fingerprint(fp)


def _api_stakes() -> list:
    assert _ledger
    rows = _ledger._conn.execute(
        "SELECT validator_id, SUM(amount) AS total FROM stakes GROUP BY validator_id"
    ).fetchall()
    return [{"validator_id": r["validator_id"], "total": r["total"]} for r in rows]


# ── Capability API helpers ───────────────────────────────────────────


def _api_capabilities() -> list:
    """List all registered capabilities."""
    registry, _, shares, _ = _get_cap_stack()
    results = []
    for m in registry.list_all():
        spot = 0.0
        reserve = shares.pool_reserve(m.capability_id)
        supply = shares.total_supply(m.capability_id)
        if supply > 0 and m.pricing.reserve_ratio > 0:
            spot = round(reserve / (supply * m.pricing.reserve_ratio), 6)
        results.append(
            {
                "asset_type": "capability",
                "asset_id": m.capability_id,
                "name": m.name,
                "description": m.description,
                "version": m.version,
                "provider": m.provider,
                "tags": m.tags,
                "status": m.status,
                "spot_price": spot,
                "created_at": m.created_at,
                "input_schema": m.input_schema,
                "output_schema": m.output_schema,
            }
        )
    return results


def _api_capability_detail(cap_id: str) -> Optional[Dict[str, Any]]:
    """Get capability detail by ID."""
    registry, _, shares, _ = _get_cap_stack()
    m = registry.get(cap_id)
    if m is None:
        return None
    reserve = shares.pool_reserve(cap_id)
    supply = shares.total_supply(cap_id)
    spot = (
        round(reserve / (supply * m.pricing.reserve_ratio), 6)
        if supply > 0 and m.pricing.reserve_ratio > 0
        else 0.0
    )
    return {
        "asset_type": "capability",
        "asset_id": m.capability_id,
        "name": m.name,
        "description": m.description,
        "version": m.version,
        "provider": m.provider,
        "tags": m.tags,
        "status": m.status,
        "spot_price": spot,
        "total_supply": round(supply, 4),
        "reserve": round(reserve, 4),
        "created_at": m.created_at,
        "input_schema": m.input_schema,
        "output_schema": m.output_schema,
        "pricing": {"base_price": m.pricing.base_price, "reserve_ratio": m.pricing.reserve_ratio},
        "staking": {"min_bond": m.staking.min_bond},
        "quality": {"verification_type": m.quality.verification_type},
    }


def _api_capability_register(body: Dict[str, Any]) -> Dict[str, Any]:
    """Register a new capability."""
    from oasyce.capabilities.manifest import (
        CapabilityManifest,
        PricingConfig,
        StakingConfig,
        QualityPolicy,
        ExecutionLimits,
    )

    registry, _, _, _ = _get_cap_stack()

    name = body.get("name", "")
    provider = body.get("provider", "")
    if not name or not provider:
        return {"error": "name and provider required"}

    manifest = CapabilityManifest(
        name=name,
        description=body.get("description", ""),
        version=body.get("version", "1.0.0"),
        provider=provider,
        tags=body.get("tags", []),
        input_schema=body.get("input_schema", {"type": "object"}),
        output_schema=body.get("output_schema", {"type": "object"}),
        pricing=PricingConfig(
            base_price=body.get("base_price", 1.0),
            reserve_ratio=body.get("reserve_ratio", 0.35),
        ),
        staking=StakingConfig(min_bond=body.get("min_bond", 100.0)),
        quality=QualityPolicy(verification_type=body.get("verification_type", "optimistic")),
    )

    errors = manifest.validate()
    if errors:
        return {"error": "; ".join(errors)}

    try:
        cap_id = registry.register(manifest)
        return {"ok": True, "capability_id": cap_id, "name": name}
    except Exception as e:
        return {"error": str(e)}


def _api_capability_invoke(body: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke a capability (deposit → invoke → submit mock result → settle)."""
    _, escrow, shares, engine = _get_cap_stack()

    cap_id = body.get("capability_id", "")
    consumer = body.get("consumer") or _default_identity()
    input_payload = body.get("input", {})
    max_price = float(body.get("max_price", 100.0))
    amount = float(body.get("amount", 10.0))

    if not cap_id:
        return {"error": "capability_id required"}

    # Auto-deposit if needed
    if escrow.balance(consumer) < max_price:
        escrow.deposit(consumer, amount)

    try:
        handle = engine.invoke(consumer, cap_id, input_payload, max_price)
        # For GUI demo: auto-settle with a mock result
        result = engine.submit_result(
            handle.invocation_id,
            {
                "result": "Executed successfully",
                "execution_time_ms": 150,
            },
        )
        return {
            "ok": True,
            "invocation_id": handle.invocation_id,
            "price": round(handle.price, 6),
            "shares_minted": (
                round(result.mint_result.shares_minted, 4) if result.mint_result else 0
            ),
            "protocol_fee": round(result.protocol_fee, 6),
            "net_to_curve": round(result.net_to_curve, 6),
        }
    except Exception as e:
        return {"error": str(e)}


def _api_capability_shares(holder: str) -> list:
    """List capability shares held by a user."""
    registry, _, shares, _ = _get_cap_stack()
    holdings = []
    for m in registry.list_all():
        bal = shares.balance(m.capability_id, holder)
        if bal > 0:
            reserve = shares.pool_reserve(m.capability_id)
            supply = shares.total_supply(m.capability_id)
            spot = (
                round(reserve / (supply * m.pricing.reserve_ratio), 6)
                if supply > 0 and m.pricing.reserve_ratio > 0
                else 0.0
            )
            holdings.append(
                {
                    "capability_id": m.capability_id,
                    "name": m.name,
                    "shares": round(bal, 4),
                    "spot_price": spot,
                    "value_oas": round(bal * spot, 4),
                }
            )
    return holdings


# ── Capability Delivery Protocol API ─────────────────────────────


def _api_delivery_endpoints(provider_id=None, tag=None, limit=50):
    """List capability endpoints from the delivery registry."""
    _, reg, _ = _get_delivery_stack()
    endpoints = reg.list_active(provider_id=provider_id, tag=tag, limit=limit)
    return [ep.to_dict() for ep in endpoints]


def _api_delivery_register(body: Dict[str, Any]) -> Dict[str, Any]:
    """Register a capability endpoint via the delivery protocol."""
    from oasyce.utils import to_units

    _, reg, _ = _get_delivery_stack()

    name = body.get("name", "")
    endpoint_url = body.get("endpoint", "")
    if not name or not endpoint_url:
        return {"error": "name and endpoint required"}

    tags = body.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    result = reg.register(
        endpoint_url=endpoint_url,
        api_key=body.get("api_key", ""),
        provider_id=body.get("provider", "self"),
        name=name,
        price_per_call=to_units(float(body.get("price", 0))),
        rate_limit=int(body.get("rate_limit", 60)),
        tags=tags,
        description=body.get("description", ""),
    )
    return result


def _api_delivery_invoke(body: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke a capability via the delivery settlement protocol."""
    protocol, _, _ = _get_delivery_stack()

    cap_id = body.get("capability_id", "")
    consumer = body.get("consumer") or _default_identity()
    input_payload = body.get("input", {})

    if not cap_id:
        return {"ok": False, "error": "capability_id required"}

    result = protocol.invoke(cap_id, consumer, input_payload)
    return result


def _api_delivery_earnings(provider_id=None, consumer_id=None) -> Dict[str, Any]:
    """Get earnings for a provider or spending for a consumer."""
    protocol, _, _ = _get_delivery_stack()

    if provider_id:
        return protocol.provider_earnings(provider_id)
    elif consumer_id:
        return protocol.consumer_spending(consumer_id)
    else:
        return {"error": "specify provider or consumer"}


def _api_delivery_invocations(consumer_id=None, provider_id=None, limit=20):
    """List recent invocation records."""
    protocol, _, _ = _get_delivery_stack()
    records = protocol.list_invocations(
        consumer_id=consumer_id,
        provider_id=provider_id,
        limit=limit,
    )
    return [r.to_dict() for r in records]


_AHRP_CORE_BASE = os.getenv("OASYCE_CORE_BASE", "http://localhost:8000")
_AHRP_UNREACHABLE = json.dumps(
    {"ok": False, "error": "AHRP node not running. Start with: oasyce serve"}
).encode("utf-8")


def _proxy_ahrp(handler: BaseHTTPRequestHandler, method: str, path: str, body: bytes = b"") -> None:
    url = _AHRP_CORE_BASE + path
    req = Request(url, data=body if body else None, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        resp = urlopen(req, timeout=10)
        data = resp.read()
        handler.send_response(resp.status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
    except (URLError, OSError):
        handler.send_response(502)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(_AHRP_UNREACHABLE)))
        handler.end_headers()
        handler.wfile.write(_AHRP_UNREACHABLE)


# ── Request handler ──────────────────────────────────────────────────


class _Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silence default stderr logging

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        # ── API routes ───────────────────────────────────────────
        if path == "/api/info":
            from oasyce.info import get_info

            lang = qs.get("lang", ["en"])[0]
            return _json_response(self, get_info(lang))

        if path == "/api/status":
            return _json_response(self, _api_status())

        if path == "/api/blocks":
            limit = int(qs.get("limit", ["20"])[0])
            return _json_response(self, _api_blocks(limit))

        m = re.match(r"^/api/block/(\d+)$", path)
        if m:
            block = _api_block(int(m.group(1)))
            if block is None:
                return _json_response(self, {"error": "block not found"}, 404)
            return _json_response(self, block)

        if path == "/api/discover":
            intents = qs.get("intents", [""])[0]
            tags = qs.get("tags", [""])[0]
            limit = int(qs.get("limit", ["10"])[0])
            try:
                discovery = _get_discovery()
                candidates = discovery.discover(
                    intents=intents.split(",") if intents else None,
                    query_tags=tags.split(",") if tags else None,
                    limit=limit,
                )
                return _json_response(
                    self,
                    [
                        {
                            "capability_id": c.capability_id,
                            "name": c.name,
                            "provider": c.provider,
                            "tags": c.tags,
                            "intent_score": c.intent_score,
                            "semantic_score": c.semantic_score,
                            "trust_score": c.trust_score,
                            "economic_score": c.economic_score,
                            "final_score": c.final_score,
                            "base_price": c.base_price,
                            "success_rate": c.success_rate,
                            "rating": c.rating,
                        }
                        for c in candidates
                    ],
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/assets":
            return _json_response(self, _api_assets())

        if path == "/api/fingerprints":
            asset_id = qs.get("asset_id", [""])[0]
            if not asset_id:
                return _json_response(self, {"error": "asset_id required"}, 400)
            return _json_response(self, _api_fingerprints(asset_id))

        if path == "/api/trace":
            fp = qs.get("fp", [""])[0]
            if not fp:
                return _json_response(self, {"error": "fp required"}, 400)
            result = _api_trace(fp)
            return _json_response(self, result or {"error": "not found"})

        if path == "/api/stakes":
            return _json_response(self, _api_stakes())

        # ── Capability routes (GET) ──────────────────────────────
        if path == "/api/capabilities":
            return _json_response(self, _api_capabilities())

        m = re.match(r"^/api/capability/shares$", path)
        if m:
            holder = qs.get("holder", [_default_identity()])[0]
            return _json_response(self, _api_capability_shares(holder))

        m = re.match(r"^/api/capability/(.+)$", path)
        if m:
            detail = _api_capability_detail(m.group(1))
            if detail is None:
                return _json_response(self, {"error": "not found"}, 404)
            return _json_response(self, detail)

        # ── Capability delivery routes (GET) ────────────────────────
        if path == "/api/delivery/endpoints":
            provider = qs.get("provider", [None])[0]
            tag = qs.get("tag", [None])[0]
            limit = int(qs.get("limit", ["50"])[0])
            return _json_response(self, _api_delivery_endpoints(provider, tag, limit))

        if path == "/api/delivery/earnings":
            provider = qs.get("provider", [None])[0]
            consumer = qs.get("consumer", [None])[0]
            return _json_response(self, _api_delivery_earnings(provider, consumer))

        if path == "/api/delivery/invocations":
            consumer = qs.get("consumer", [None])[0]
            provider = qs.get("provider", [None])[0]
            limit = int(qs.get("limit", ["20"])[0])
            return _json_response(self, _api_delivery_invocations(consumer, provider, limit))

        # Asset detail
        m = re.match(r"^/api/asset/(.+)$", path)
        if m:
            aid = m.group(1)
            if not _ledger:
                return _json_response(self, {"error": "ledger not initialized"}, 503)
            row = _ledger._conn.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (aid,)
            ).fetchone()
            if not row:
                return _json_response(self, {"error": "not found"}, 404)
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            return _json_response(
                self,
                {
                    "asset_id": row["asset_id"],
                    "owner": row["owner"],
                    "metadata": meta,
                    "created_at": row["created_at"],
                },
            )

        # ── Tiered access quote (L0-L3 bond pricing) — via shared facade ──
        if path == "/api/access/quote":
            asset_id = qs.get("asset_id", [""])[0]
            buyer = qs.get("buyer", [_default_identity()])[0]
            if not asset_id:
                return _json_response(self, {"error": "asset_id required"}, 400)
            try:
                from oasyce.services.facade import OasyceServiceFacade

                facade = OasyceServiceFacade(config=None, ledger=_ledger)
                result = facade.access_quote(asset_id, buyer)
                if not result.success:
                    return _json_response(self, {"error": result.error}, 400)

                # Remap to GUI's expected format (bond → bond, lock_days → liability_days)
                gui_levels = []
                for lv in result.data["levels"]:
                    entry = {
                        "level": lv["level"],
                        "bond": lv["bond_oas"],
                        "available": lv["available"],
                        "liability_days": lv["lock_days"],
                    }
                    if not lv["available"]:
                        entry["locked_reason"] = "al-reputation_too_low"
                    gui_levels.append(entry)

                return _json_response(
                    self,
                    {
                        "asset_id": asset_id,
                        "levels": gui_levels,
                        "reputation": result.data["reputation"],
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # Bancor quote
        if path == "/api/quote":
            asset_id = qs.get("asset_id", [""])[0]
            amount = float(qs.get("amount", ["10"])[0])
            if not asset_id:
                return _json_response(self, {"error": "asset_id required"}, 400)
            try:
                # Check if asset has a manual pricing model
                asset_info = _ledger.get_asset(asset_id) if _ledger else None
                asset_price_model = (asset_info or {}).get("price_model", "auto")
                asset_manual_price = (asset_info or {}).get("manual_price")

                if asset_price_model == "fixed" and asset_manual_price is not None:
                    # Fixed price: bypass bonding curve entirely
                    return _json_response(
                        self,
                        {
                            "asset_id": asset_id,
                            "payment": round(asset_manual_price, 6),
                            "tokens": 1,
                            "price_before": round(asset_manual_price, 6),
                            "price_after": round(asset_manual_price, 6),
                            "impact_pct": 0.0,
                            "fee": 0.0,
                            "burn": 0.0,
                            "price_model": "fixed",
                        },
                    )

                se = _get_settlement()
                if asset_id not in se.pools:
                    se.register_asset(asset_id, "protocol")
                q = se.quote(asset_id, amount)

                price_before = round(q.spot_price_before, 6)
                price_after = round(q.spot_price_after, 6)

                # Floor price: enforce manual_price as minimum
                if asset_price_model == "floor" and asset_manual_price is not None:
                    floor = float(asset_manual_price)
                    price_before = max(price_before, floor)
                    price_after = max(price_after, floor)

                resp = {
                    "asset_id": q.asset_id,
                    "payment": q.payment_oas,
                    "tokens": round(q.equity_minted, 4),
                    "price_before": price_before,
                    "price_after": price_after,
                    "impact_pct": round(q.price_impact_pct, 2),
                    "fee": round(q.protocol_fee, 4),
                    "burn": round(q.burn_amount, 4),
                    "price_model": asset_price_model,
                }
                if asset_manual_price is not None:
                    resp["manual_price"] = round(float(asset_manual_price), 6)
                return _json_response(self, resp)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # Portfolio (holdings)
        if path == "/api/portfolio":
            buyer = qs.get("buyer", [_default_identity()])[0]
            se = _get_settlement()
            holdings = []
            for asset_id, pool in se.pools.items():
                balance = pool.equity.get(buyer, 0)
                if balance > 0:
                    spot = round(pool.spot_price, 6)
                    holdings.append(
                        {
                            "asset_id": asset_id,
                            "shares": round(balance, 4),
                            "spot_price": spot,
                            "value_oas": round(balance * spot, 4),
                        }
                    )
            return _json_response(self, holdings)

        # Transaction history
        if path == "/api/transactions":
            se = _get_settlement()
            txs = []
            if hasattr(se, "receipts"):
                for r in se.receipts[-50:]:
                    txs.append(
                        {
                            "receipt_id": r.receipt_id,
                            "asset_id": r.asset_id,
                            "buyer": r.buyer,
                            "amount": r.quote.payment_oas if r.quote else r.amount_oas,
                            "tokens": round(r.quote.equity_minted, 4) if r.quote else 0,
                            "status": r.status.value,
                            "timestamp": getattr(r, "timestamp", 0),
                        }
                    )
            return _json_response(self, list(reversed(txs)))

        # ── Data asset owner earnings ──────────────────────────────
        if path == "/api/earnings":
            owner = qs.get("owner", [None])[0]
            if not owner:
                return _json_response(self, {"error": "owner param required"}, 400)
            se = _get_settlement()
            total_earned = 0.0
            transactions = []
            if hasattr(se, "receipts"):
                for r in se.receipts:
                    if getattr(r, "status", None) and r.status.value != "SETTLED":
                        continue
                    # Match receipts where the asset owner earned from trades.
                    # The asset owner earns creator fees from bonding curve trades.
                    asset_owner = None
                    if _ledger:
                        row = _ledger._conn.execute(
                            "SELECT owner FROM assets WHERE asset_id = ?",
                            (r.asset_id,),
                        ).fetchone()
                        if row:
                            asset_owner = row["owner"]
                    if asset_owner and asset_owner == owner:
                        earned = getattr(r.quote, "protocol_fee", 0) if r.quote else 0
                        total_earned += earned
                        transactions.append(
                            {
                                "asset_id": r.asset_id,
                                "buyer": r.buyer,
                                "amount": round(earned, 6),
                                "timestamp": getattr(r, "timestamp", 0),
                            }
                        )
            # Also include capability delivery earnings (provider = owner)
            try:
                protocol, _, _ = _get_delivery_stack()
                cap_earnings = protocol.provider_earnings(owner)
                total_earned += cap_earnings.get("total_earned", 0)
                cap_invocations = protocol.list_invocations(
                    provider_id=owner, status="success", limit=20
                )
                for inv in cap_invocations:
                    transactions.append(
                        {
                            "asset_id": inv.capability_id,
                            "buyer": inv.consumer_id,
                            "amount": inv.provider_earned,
                            "timestamp": inv.settled_at or inv.created_at,
                        }
                    )
            except Exception:
                pass  # delivery stack may not be initialized

            transactions.sort(key=lambda t: t.get("timestamp", 0), reverse=True)
            return _json_response(
                self,
                {
                    "total_earned": round(total_earned, 6),
                    "transactions": transactions[:50],
                },
            )

        # ── AHRP proxy (GET) ─────────────────────────────────────
        if path.startswith("/ahrp/"):
            return _proxy_ahrp(self, "GET", self.path)

        # ── Identity (node + wallet) ─────────────────────────────
        if path == "/api/identity":
            from oasyce.identity import Wallet

            result = {}
            # Node identity
            if _config and _config.public_key:
                key_dir = os.path.join(_config.data_dir, "keys")
                created_at = None
                pub_path = os.path.join(key_dir, "public.key")
                if os.path.isfile(pub_path):
                    created_at = os.path.getctime(pub_path)
                result.update(
                    {
                        "public_key": _config.public_key,
                        "node_id": _config.public_key[:16],
                        "created_at": created_at,
                    }
                )
            # Wallet identity
            wallet_address = Wallet.get_address()
            result["wallet_exists"] = wallet_address is not None
            if wallet_address:
                result["wallet_address"] = wallet_address
            if not result.get("public_key") and not wallet_address:
                return _json_response(self, {"wallet_exists": False}, 200)
            return _json_response(self, result)

        # ── Wallet identity (standalone) ──────────────────────────
        if path == "/api/identity/wallet":
            from oasyce.identity import Wallet

            wallet_address = Wallet.get_address()
            if wallet_address:
                return _json_response(self, {"exists": True, "address": wallet_address})
            return _json_response(self, {"exists": False})

        # ── Node role ─────────────────────────────────────────────
        if path == "/api/node/role":
            from oasyce.config import load_node_role, load_or_create_node_identity

            if not _config:
                return _json_response(self, {"error": "not initialized"}, 503)
            _priv, node_id = load_or_create_node_identity(_config.data_dir)
            role = load_node_role(_config.data_dir)
            height = _ledger.get_chain_height() if _ledger else 0

            # Peer count
            from pathlib import Path as _Path

            peers_path = _Path(_config.data_dir) / "peers.json"
            peers_count = 0
            if peers_path.exists():
                try:
                    peers_count = len(json.loads(peers_path.read_text()))
                except Exception:
                    pass

            return _json_response(
                self,
                {
                    "node_id": node_id[:16],
                    "public_key": _config.public_key or node_id,
                    "roles": role.get("roles", []),
                    "validator_stake": role.get("validator_stake", 0),
                    "arbitrator_tags": role.get("arbitrator_tags", []),
                    "api_provider": role.get("api_provider", ""),
                    "api_key_set": role.get("api_key_set", False),
                    "api_endpoint": role.get("api_endpoint", ""),
                    "chain_height": height,
                    "peers": peers_count,
                },
            )

        # ── Work tasks (GET) ─────────────────────────────────────
        if path == "/api/work/tasks":
            if not _config:
                return _json_response(self, {"error": "not initialized"}, 503)
            from oasyce.services.work_value import WorkValueEngine

            db_path = os.path.join(_config.data_dir, "work.db")
            engine = WorkValueEngine(db_path=db_path)
            status_filter = qs.get("status", [None])[0]
            task_type = qs.get("type", [None])[0]
            limit = int(qs.get("limit", ["20"])[0])
            tasks = engine.list_tasks(status=status_filter, task_type=task_type, limit=limit)
            engine.close()
            return _json_response(self, {"tasks": [t.to_dict() for t in tasks]})

        if path == "/api/work/stats":
            if not _config:
                return _json_response(self, {"error": "not initialized"}, 503)
            from oasyce.services.work_value import WorkValueEngine
            from oasyce.config import load_or_create_node_identity

            db_path = os.path.join(_config.data_dir, "work.db")
            engine = WorkValueEngine(db_path=db_path)
            _priv, node_id = load_or_create_node_identity(_config.data_dir)
            node_id_short = node_id[:16]
            global_s = engine.global_stats()
            worker_s = engine.worker_stats(node_id_short)
            engine.close()
            return _json_response(self, {"global": global_s, "worker": worker_s})

        # ── Auth token (localhost only) ──────────────────────────
        if path == "/api/auth/token":
            client_ip = self.client_address[0]
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                return _json_response(self, {"error": "forbidden"}, 403)
            return _json_response(self, {"token": _api_token})

        # ── Config ───────────────────────────────────────────────
        if path == "/api/config":
            assert _config
            return _json_response(
                self,
                {
                    "public_key": _config.public_key,
                    "owner": _config.owner,
                    "node_host": _config.node_host,
                    "node_port": _config.node_port,
                },
            )

        # ── Inbox API (GET) ──────────────────────────────────────
        if path == "/api/inbox":
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            items = inbox.list_all()
            return _json_response(
                self,
                {
                    "items": [
                        {
                            "item_id": i.item_id,
                            "item_type": i.item_type,
                            "status": i.status,
                            "file_path": i.file_path,
                            "suggested_name": i.suggested_name,
                            "suggested_tags": i.suggested_tags,
                            "suggested_description": i.suggested_description,
                            "sensitivity": i.sensitivity,
                            "confidence": i.confidence,
                            "asset_id": i.asset_id,
                            "price": i.price,
                            "reason": i.reason,
                            "created_at": i.created_at,
                        }
                        for i in items
                    ],
                },
            )

        if path == "/api/inbox/trust":
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            return _json_response(
                self,
                {
                    "trust_level": inbox.get_trust_level(),
                    "auto_threshold": inbox.get_auto_threshold(),
                },
            )

        # ── Consensus API (GET) ─────────────────────────────────
        if path == "/api/consensus/status":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import get_consensus_params, get_economics, NetworkMode

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                status = engine.status()
                return _json_response(self, status)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        if path == "/api/consensus/validators":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import get_consensus_params, get_economics, NetworkMode

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                include_all = qs.get("all", ["false"])[0] == "true"
                validators = engine.get_validators(include_inactive=include_all)
                return _json_response(self, validators)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        if path == "/api/consensus/rewards":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import get_consensus_params, get_economics, NetworkMode

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                epoch = qs.get("epoch", [None])[0]
                epoch_num = int(epoch) if epoch else None
                rewards = engine.get_rewards(epoch_number=epoch_num)
                return _json_response(self, rewards)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        # ── Governance API (GET) ───────────────────────────────
        if path == "/api/governance/proposals":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import get_consensus_params, get_economics, NetworkMode

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                status_filter = qs.get("status", [None])[0]
                proposals = engine.list_proposals(status=status_filter)
                return _json_response(self, proposals)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        if path.startswith("/api/governance/proposal/"):
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import get_consensus_params, get_economics, NetworkMode

                proposal_id = path.split("/")[-1]
                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                proposal = engine.get_proposal(proposal_id)
                if proposal is None:
                    return _json_response(self, {"error": "not found"}, 404)
                return _json_response(self, proposal)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        if path == "/api/governance/params":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import get_consensus_params, get_economics, NetworkMode

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                module = qs.get("module", [None])[0]
                params = engine.list_governable_params(module=module)
                return _json_response(self, params)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        # ── Slashing & Sync API (GET) ──────────────────────────────
        if path == "/api/consensus/slashing":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import get_consensus_params, get_economics, NetworkMode

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                validator_id = qs.get("validator", [None])[0]
                slashing = engine.get_slashing(validator_id=validator_id)
                return _json_response(self, slashing)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        if path == "/api/consensus/sync":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import get_consensus_params, NetworkMode

                params = get_consensus_params(NetworkMode.TESTNET)
                chain_id = params.get("chain_id", "oasyce-testnet-1")
                genesis_hash = make_genesis_block(chain_id).block_hash
                info = SyncInfo(
                    state=SyncState.IDLE,
                    chain_id=chain_id,
                    genesis_hash=genesis_hash,
                )
                return _json_response(self, info.to_dict())
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)

        if path == "/api/consensus/mempool":
            if _mempool is None:
                return _json_response(self, {"error": "mempool not running"}, 503)
            ops = _mempool.peek(50)
            return _json_response(
                self,
                {
                    "size": _mempool.size,
                    "pending": [
                        {
                            "op_type": (
                                op.op_type.value
                                if hasattr(op.op_type, "value")
                                else str(op.op_type)
                            ),
                            "validator_id": op.validator_id,
                            "amount": op.amount,
                            "from_addr": op.from_addr,
                            "to_addr": op.to_addr,
                            "asset_type": op.asset_type,
                        }
                        for op in ops
                    ],
                },
            )

        if path == "/api/consensus/producer":
            if _block_producer is None:
                return _json_response(self, {"error": "block producer not running"}, 503)
            return _json_response(self, _block_producer.status())

        # ── Agent scheduler API (GET) ─────────────────────────────
        if path == "/api/agent/status":
            from oasyce.services.scheduler import get_scheduler

            data_dir = _config.data_dir if _config else None
            scheduler = get_scheduler(data_dir)
            return _json_response(self, scheduler.status())

        if path == "/api/agent/config":
            from oasyce.services.scheduler import get_scheduler

            data_dir = _config.data_dir if _config else None
            scheduler = get_scheduler(data_dir)
            return _json_response(self, scheduler.get_config().to_dict())

        if path == "/api/agent/history":
            from oasyce.services.scheduler import get_scheduler

            data_dir = _config.data_dir if _config else None
            scheduler = get_scheduler(data_dir)
            limit = int(qs.get("limit", ["10"])[0])
            return _json_response(self, scheduler.get_history(limit))

        # ── Balance query ──────────────────────────────────────────
        if path == "/api/balance":
            address = qs.get("address", [""])[0]
            if not address:
                return _json_response(self, {"error": "address required"}, 400)
            balance_oas = 0.0
            try:
                from oasyce.services.faucet import Faucet
                from oasyce.config import get_data_dir, NetworkMode

                data_dir = _config.data_dir if _config else get_data_dir(NetworkMode.TESTNET)
                faucet = Faucet(data_dir)
                balance_oas = faucet.balance(address)
            except Exception:
                pass
            return _json_response(self, {"address": address, "balance_oas": balance_oas})

        # ── Data Preview API (GET) ────────────────────────────────
        m = re.match(r"^/api/asset/(.+)/preview$", path)
        if m:
            asset_id = m.group(1)
            level_str = qs.get("level", ["L0"])[0].upper()
            if level_str not in ("L0", "L1", "L2", "L3"):
                return _json_response(self, {"error": "level must be L0, L1, L2, or L3"}, 400)
            if not _ledger:
                return _json_response(self, {"error": "ledger not initialized"}, 503)
            # Look up asset in ledger
            row = _ledger._conn.execute(
                "SELECT asset_id, owner, metadata, created_at FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
            # Also check capabilities
            cap_detail = None
            if not row:
                try:
                    cap_detail = _api_capability_detail(asset_id)
                except Exception:
                    pass
            if not row and not cap_detail:
                return _json_response(self, {"error": "asset not found"}, 404)

            if cap_detail:
                # Capability asset preview
                preview: Dict[str, Any] = {
                    "asset_id": asset_id,
                    "level": level_str,
                    "asset_type": "capability",
                    "metadata": {
                        "name": cap_detail.get("name", ""),
                        "tags": cap_detail.get("tags", []),
                        "description": cap_detail.get("description", ""),
                        "created_at": cap_detail.get("created_at"),
                        "provider": cap_detail.get("provider", ""),
                    },
                }
                if level_str in ("L1", "L2", "L3"):
                    preview["detail"] = {
                        "input_schema": cap_detail.get("input_schema"),
                        "output_schema": cap_detail.get("output_schema"),
                        "spot_price": cap_detail.get("spot_price"),
                    }
                return _json_response(self, preview)

            # Data asset preview
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            preview = {
                "asset_id": row["asset_id"],
                "level": level_str,
                "asset_type": "data",
                "metadata": {
                    "name": meta.get(
                        "name",
                        meta.get("tags", ["Untitled"])[0] if meta.get("tags") else "Untitled",
                    ),
                    "tags": meta.get("tags", []),
                    "size": meta.get("file_size", 0),
                    "rights_type": meta.get("rights_type", "original"),
                    "created_at": row["created_at"],
                    "owner": row["owner"],
                },
            }
            if level_str == "L0":
                return _json_response(self, preview)

            # L1+ : attempt content preview
            file_path = meta.get("file_path")
            if file_path and os.path.isfile(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                file_size = os.path.getsize(file_path)
                preview["metadata"]["size"] = file_size

                if ext in (".csv", ".tsv"):
                    try:
                        with open(file_path, "r", errors="replace") as fp:
                            lines = []
                            max_lines = (
                                10 if level_str == "L1" else (100 if level_str == "L2" else 10000)
                            )
                            for i, line in enumerate(fp):
                                if i >= max_lines:
                                    break
                                lines.append(line.rstrip("\n"))
                        preview["content_type"] = "csv"
                        preview["content"] = lines
                    except Exception:
                        preview["content_type"] = "error"
                        preview["content"] = "Could not read file"
                elif ext in (
                    ".txt",
                    ".md",
                    ".json",
                    ".py",
                    ".js",
                    ".ts",
                    ".yaml",
                    ".yml",
                    ".xml",
                    ".html",
                    ".css",
                    ".log",
                ):
                    try:
                        max_chars = (
                            500 if level_str == "L1" else (5000 if level_str == "L2" else file_size)
                        )
                        with open(file_path, "r", errors="replace") as fp:
                            content = fp.read(max_chars)
                        preview["content_type"] = "text"
                        preview["content"] = content
                        preview["truncated"] = file_size > max_chars
                    except Exception:
                        preview["content_type"] = "error"
                        preview["content"] = "Could not read file"
                elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
                    preview["content_type"] = "image"
                    preview["content"] = (
                        f"[Image file: {os.path.basename(file_path)}, {file_size} bytes]"
                    )
                else:
                    preview["content_type"] = "binary"
                    preview["content"] = (
                        f"[Binary file: {os.path.basename(file_path)}, {file_size} bytes]"
                    )
            else:
                preview["content_type"] = "unavailable"
                preview["content"] = "File not available for preview"

            if level_str == "L3":
                preview["full_access"] = True

            return _json_response(self, preview)

        # ── Disputes API (GET) ────────────────────────────────────
        if path == "/api/disputes":
            buyer = qs.get("buyer", [""])[0]
            if not buyer:
                return _json_response(self, {"error": "buyer param required"}, 400)
            db = _get_dispute_db()
            rows = db.execute(
                "SELECT * FROM disputes WHERE buyer = ? ORDER BY created_at DESC",
                (buyer,),
            ).fetchall()
            disputes = []
            for r in rows:
                disputes.append(
                    {
                        "dispute_id": r["dispute_id"],
                        "asset_id": r["asset_id"],
                        "buyer": r["buyer"],
                        "reason": r["reason"],
                        "evidence_text": r["evidence_text"],
                        "status": r["status"],
                        "created_at": r["created_at"],
                        "resolved_at": r["resolved_at"],
                        "resolution": r["resolution"],
                    }
                )
            return _json_response(self, {"disputes": disputes})

        m = re.match(r"^/api/dispute/detail/(.+)$", path)
        if m:
            dispute_id = m.group(1)
            db = _get_dispute_db()
            r = db.execute(
                "SELECT * FROM disputes WHERE dispute_id = ?",
                (dispute_id,),
            ).fetchone()
            if not r:
                return _json_response(self, {"error": "dispute not found"}, 404)
            return _json_response(
                self,
                {
                    "dispute_id": r["dispute_id"],
                    "asset_id": r["asset_id"],
                    "buyer": r["buyer"],
                    "reason": r["reason"],
                    "evidence_text": r["evidence_text"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "resolved_at": r["resolved_at"],
                    "resolution": r["resolution"],
                },
            )

        # ── Notifications API (GET) ───────────────────────────────
        if path == "/api/notifications":
            address = qs.get("address", [""])[0]
            if not address:
                return _json_response(self, {"error": "address param required"}, 400)
            unread_only = qs.get("unread_only", ["false"])[0].lower() == "true"
            limit = int(qs.get("limit", ["50"])[0])
            ns = _get_notification_service()
            items = ns.get_notifications(address, unread_only=unread_only, limit=limit)
            return _json_response(self, {"notifications": items})

        if path == "/api/notifications/count":
            address = qs.get("address", [""])[0]
            if not address:
                return _json_response(self, {"error": "address param required"}, 400)
            ns = _get_notification_service()
            count = ns.get_unread_count(address)
            return _json_response(self, {"unread_count": count})

        # ── Static files from dashboard/dist/ ────────────────────
        if path.startswith("/assets/"):
            file_path = os.path.join(DASHBOARD_DIR, path.lstrip("/"))
            return _serve_static(self, file_path)

        if path == "/favicon.svg" or path == "/icons.svg":
            file_path = os.path.join(DASHBOARD_DIR, path.lstrip("/"))
            return _serve_static(self, file_path)

        # ── SPA fallback — serve index.html for all routes ───────
        index_path = os.path.join(DASHBOARD_DIR, "index.html")
        if os.path.isfile(index_path):
            return _serve_static(self, index_path)

        # Fallback to legacy embedded HTML if dist/ not built
        return _html_response(self, _INDEX_HTML)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        content_type = self.headers.get("Content-Type", "")

        # ── Auth check for all POST endpoints ──
        if not _check_auth(self):
            return _json_response(self, {"error": "unauthorized"}, 401)

        # ── Rate limit ──
        client_ip = self.client_address[0]
        if not _check_rate_limit(client_ip):
            return _json_response(self, {"error": "rate limit exceeded"}, 429)

        # Pre-parse JSON body for non-multipart routes
        body: dict = {}
        if "application/json" in content_type:
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
            except (json.JSONDecodeError, ValueError):
                return _json_response(self, {"error": "invalid JSON body"}, 400)

        # ── Wallet creation ────────────────────────────────────
        if path == "/api/identity/create":
            from oasyce.identity import Wallet

            try:
                if Wallet.exists():
                    addr = Wallet.get_address()
                    return _json_response(self, {"ok": True, "address": addr, "created": False})
                wallet = Wallet.create()
                return _json_response(
                    self, {"ok": True, "address": wallet.address, "created": True}
                )
            except Exception as exc:
                return _json_response(self, {"ok": False, "error": str(exc)}, 500)

        # ── Testnet faucet ─────────────────────────────────────────
        if path == "/api/faucet":
            # Always use the local wallet address — never allow arbitrary addresses
            from oasyce.identity import Wallet as _FaucetWallet

            address = _FaucetWallet.get_address() if _FaucetWallet.exists() else None
            if not address:
                return _json_response(
                    self,
                    {"ok": False, "error": "no wallet — create one first via /api/identity/create"},
                    400,
                )
            try:
                from oasyce.services.faucet import Faucet
                from oasyce.config import get_data_dir, NetworkMode

                data_dir = _config.data_dir if _config else get_data_dir(NetworkMode.TESTNET)
                faucet = Faucet(data_dir)
                result = faucet.claim(address)
                if result["success"]:
                    return _json_response(
                        self,
                        {
                            "ok": True,
                            "amount": result["amount"],
                            "new_balance": result["balance"],
                        },
                    )
                else:
                    return _json_response(
                        self,
                        {
                            "ok": False,
                            "error": result["error"],
                            "next_claim_at": result.get("next_claim_at"),
                        },
                        429,
                    )
            except Exception as exc:
                return _json_response(self, {"ok": False, "error": str(exc)}, 500)

        if path == "/api/register":
            try:
                # ── multipart upload ──
                if "multipart/form-data" in content_type:
                    form = cgi.FieldStorage(
                        fp=self.rfile,
                        headers=self.headers,
                        environ={
                            "REQUEST_METHOD": "POST",
                            "CONTENT_TYPE": content_type,
                        },
                    )
                    file_item = form["file"] if "file" in form else None
                    if file_item is None or not getattr(file_item, "filename", None):
                        return _json_response(self, {"error": "file required"}, 400)

                    upload_dir = os.path.join(os.path.expanduser("~"), ".oasyce", "uploads")
                    os.makedirs(upload_dir, exist_ok=True)
                    safe_name = re.sub(r"[^\w.\-]", "_", file_item.filename)
                    dest = os.path.join(upload_dir, f"{int(time.time())}_{safe_name}")
                    with open(dest, "wb") as f:
                        f.write(file_item.file.read())

                    fp = dest
                    owner = form.getfirst("owner", _config.owner if _config else "unknown")
                    tags_raw = form.getfirst("tags", "")
                    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
                    rights_type = form.getfirst("rights_type", "original")
                    co_creators_raw = form.getfirst("co_creators", "")
                    co_creators = json.loads(co_creators_raw) if co_creators_raw else None
                    price_model = form.getfirst("price_model", "auto")
                    price_raw = form.getfirst("price", "")
                    manual_price = float(price_raw) if price_raw else None
                else:
                    # legacy JSON fallback — body already parsed at top of do_POST
                    fp = body.get("file_path", "")
                    owner = body.get("owner", _config.owner if _config else "unknown")
                    tags = body.get("tags", [])
                    rights_type = body.get("rights_type", "original")
                    co_creators = body.get("co_creators", None)
                    price_model = body.get("price_model", "auto")
                    manual_price = body.get("price", None)

                if not fp:
                    return _json_response(self, {"error": "file_path required"}, 400)

                # Validate rights_type
                from oasyce.models import VALID_RIGHTS_TYPES

                if rights_type not in VALID_RIGHTS_TYPES:
                    return _json_response(
                        self, {"error": f"invalid rights_type: {rights_type}"}, 400
                    )

                # Validate co_creators shares sum to 100
                if co_creators:
                    total_share = sum(c.get("share", 0) for c in co_creators)
                    if abs(total_share - 100) > 0.01:
                        return _json_response(
                            self,
                            {"error": f"co_creators shares must sum to 100, got {total_share}"},
                            400,
                        )

                # Validate price_model and manual price
                if price_model not in ("auto", "fixed", "floor"):
                    return _json_response(
                        self,
                        {
                            "error": f"invalid price_model: {price_model}. Must be auto, fixed, or floor."
                        },
                        400,
                    )
                if price_model in ("fixed", "floor"):
                    if manual_price is None or manual_price <= 0:
                        return _json_response(
                            self,
                            {"error": f"price must be > 0 when price_model is '{price_model}'"},
                            400,
                        )

                # Path traversal prevention: resolve and check against allowed dirs
                resolved_fp = os.path.realpath(fp)
                home_dir = os.path.expanduser("~")
                if not resolved_fp.startswith(home_dir):
                    return _json_response(self, {"error": "file path not allowed"}, 403)
                if not os.path.isfile(resolved_fp):
                    return _json_response(self, {"error": "file not found"}, 404)
                fp = resolved_fp
                skills = _get_skills()
                file_info = skills.scan_data_skill(fp)
                metadata = skills.generate_metadata_skill(
                    file_info,
                    tags,
                    owner,
                    rights_type=rights_type,
                    co_creators=co_creators,
                )
                metadata["file_path"] = os.path.abspath(fp)
                # Store pricing model in metadata
                metadata["price_model"] = price_model
                if manual_price is not None:
                    metadata["manual_price"] = manual_price
                signed = skills.create_certificate_skill(metadata)
                result = skills.register_data_asset_skill(signed)
                return _json_response(
                    self,
                    {
                        "ok": True,
                        "asset_id": signed.get("asset_id", ""),
                        "file_hash": file_info.get("file_hash", ""),
                        "price_model": price_model,
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/register-bundle":
            try:
                if "multipart/form-data" not in content_type:
                    return _json_response(self, {"error": "multipart/form-data required"}, 400)
                form = cgi.FieldStorage(
                    fp=self.rfile,
                    headers=self.headers,
                    environ={
                        "REQUEST_METHOD": "POST",
                        "CONTENT_TYPE": content_type,
                    },
                )
                # Collect all files from multipart
                file_items = form["files"] if "files" in form else []
                if not isinstance(file_items, list):
                    file_items = [file_items]
                file_items = [f for f in file_items if getattr(f, "filename", None)]
                if not file_items:
                    return _json_response(self, {"error": "no files provided"}, 400)

                bundle_name = form.getfirst("name", f"bundle_{int(time.time())}")
                owner = form.getfirst("owner", _config.owner if _config else "unknown")
                tags_raw = form.getfirst("tags", "")
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

                upload_dir = os.path.join(os.path.expanduser("~"), ".oasyce", "uploads")
                os.makedirs(upload_dir, exist_ok=True)
                safe_name = re.sub(r"[^\w.\-]", "_", bundle_name)
                zip_path = os.path.join(upload_dir, f"{int(time.time())}_{safe_name}.zip")

                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fi in file_items:
                        fname = re.sub(r"[^\w./\-]", "_", fi.filename)
                        zf.writestr(fname, fi.file.read())

                skills = _get_skills()
                file_info = skills.scan_data_skill(zip_path)
                metadata = skills.generate_metadata_skill(file_info, tags, owner)
                metadata["file_path"] = os.path.abspath(zip_path)
                metadata["bundle"] = True
                metadata["file_count"] = len(file_items)
                signed = skills.create_certificate_skill(metadata)
                result = skills.register_data_asset_skill(signed)
                return _json_response(
                    self,
                    {
                        "ok": True,
                        "asset_id": signed.get("asset_id", ""),
                        "file_hash": file_info.get("file_hash", ""),
                        "file_count": len(file_items),
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/re-register":
            try:
                aid = body.get("asset_id", "")
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                assert _ledger
                row = _ledger._conn.execute(
                    "SELECT metadata FROM assets WHERE asset_id = ?", (aid,)
                ).fetchone()
                if not row:
                    return _json_response(self, {"error": "asset not found"}, 404)
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
                file_path = meta.get("file_path")
                if not file_path or not os.path.isfile(file_path):
                    return _json_response(self, {"error": "file not found"}, 404)
                # Compute current hash
                h = hashlib.sha256()
                with open(file_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        h.update(chunk)
                new_hash = h.hexdigest()
                old_hash = meta.get("file_hash", "")
                if new_hash == old_hash:
                    return _json_response(self, {"ok": False, "message": "no changes detected"})
                # Build version chain
                versions = meta.get("versions", [])
                if not versions and old_hash:
                    versions.append(
                        {
                            "version": 1,
                            "file_hash": old_hash,
                            "timestamp": meta.get("created_at", ""),
                        }
                    )
                new_version = (versions[-1]["version"] + 1) if versions else 2
                from datetime import datetime, timezone

                versions.append(
                    {
                        "version": new_version,
                        "file_hash": new_hash,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
                meta["versions"] = versions
                meta["file_hash"] = new_hash
                _ledger._conn.execute(
                    "UPDATE assets SET metadata = ? WHERE asset_id = ?",
                    (json.dumps(meta), aid),
                )
                _ledger._conn.commit()
                return _json_response(
                    self, {"ok": True, "version": new_version, "file_hash": new_hash}
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/dispute":
            try:
                aid = body.get("asset_id", "")
                reason = body.get("reason", "").strip()
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if not reason:
                    return _json_response(self, {"error": "reason required"}, 400)
                assert _ledger
                row = _ledger._conn.execute(
                    "SELECT metadata FROM assets WHERE asset_id = ?", (aid,)
                ).fetchone()
                if not row:
                    return _json_response(self, {"error": "asset not found"}, 404)
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
                meta["disputed"] = True
                meta["dispute_reason"] = reason
                meta["dispute_time"] = int(time.time())
                meta["dispute_status"] = "open"

                # Auto-discover arbitrator capabilities
                arbitrators = []
                try:
                    discovery = _get_discovery()
                    tags = meta.get("tags", [])
                    candidates = discovery.discover_arbitrators(
                        dispute_tags=tags + ["arbitration"],
                        limit=3,
                    )
                    arbitrators = [
                        {
                            "capability_id": c.capability_id,
                            "name": c.name,
                            "provider": c.provider,
                            "score": c.final_score,
                        }
                        for c in candidates
                    ]
                    meta["arbitrator_candidates"] = arbitrators
                except Exception:
                    pass  # discovery is best-effort

                _ledger._conn.execute(
                    "UPDATE assets SET metadata = ? WHERE asset_id = ?",
                    (json.dumps(meta), aid),
                )
                _ledger._conn.commit()
                return _json_response(
                    self,
                    {
                        "ok": True,
                        "asset_id": aid,
                        "disputed": True,
                        "arbitrators": arbitrators,
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/dispute/resolve":
            try:
                from oasyce.models import VALID_REMEDY_TYPES

                aid = body.get("asset_id", "")
                remedy = body.get("remedy", "")
                details = body.get("details", {})
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if remedy not in VALID_REMEDY_TYPES:
                    return _json_response(
                        self,
                        {
                            "error": f"invalid remedy, must be one of: {', '.join(VALID_REMEDY_TYPES)}"
                        },
                        400,
                    )
                if not _ledger:
                    return _json_response(self, {"error": "ledger not initialized"}, 503)
                row = _ledger._conn.execute(
                    "SELECT metadata FROM assets WHERE asset_id = ?", (aid,)
                ).fetchone()
                if not row:
                    return _json_response(self, {"error": "asset not found"}, 404)
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
                if not meta.get("disputed"):
                    return _json_response(self, {"error": "asset is not disputed"}, 400)
                if meta.get("dispute_status") == "resolved":
                    return _json_response(self, {"error": "dispute already resolved"}, 400)

                # Apply remedy
                resolution = {"remedy": remedy, "details": details, "resolved_at": int(time.time())}
                meta["dispute_status"] = "resolved"
                meta["dispute_resolution"] = resolution

                if remedy == "delist":
                    meta["delisted"] = True
                elif remedy == "transfer":
                    new_owner = details.get("new_owner", "")
                    if new_owner:
                        meta["owner"] = new_owner
                        _ledger._conn.execute(
                            "UPDATE assets SET owner = ? WHERE asset_id = ?",
                            (new_owner, aid),
                        )
                elif remedy == "rights_correction":
                    new_rights = details.get("new_rights_type", "collection")
                    from oasyce.models import VALID_RIGHTS_TYPES

                    if new_rights in VALID_RIGHTS_TYPES:
                        meta["rights_type"] = new_rights
                elif remedy == "share_adjustment":
                    new_co_creators = details.get("co_creators")
                    if new_co_creators:
                        meta["co_creators"] = new_co_creators

                _ledger._conn.execute(
                    "UPDATE assets SET metadata = ? WHERE asset_id = ?",
                    (json.dumps(meta), aid),
                )
                _ledger._conn.commit()
                return _json_response(
                    self, {"ok": True, "asset_id": aid, "remedy": remedy, "resolution": resolution}
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # ── Tiered access buy (bond-based) — via shared facade ──
        if path == "/api/access/buy":
            try:
                from oasyce.services.facade import OasyceServiceFacade

                aid = body.get("asset_id", "")
                buyer = body.get("buyer") or _default_identity()
                level_str = body.get("level", "L1")
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if level_str not in ("L0", "L1", "L2", "L3"):
                    return _json_response(self, {"error": "invalid level"}, 400)

                facade = OasyceServiceFacade(config=None, ledger=_ledger)
                result = facade.access_buy(aid, buyer, level_str)

                if not result.success:
                    return _json_response(self, {"error": result.error}, 403)

                # Send notification
                try:
                    ns = _get_notification_service()
                    ns.notify(
                        buyer,
                        "ACCESS",
                        f"Granted {level_str} access to {aid[:12]}... (bond: {result.data['bond_oas']} OAS)",
                        {
                            "asset_id": aid,
                            "level": level_str,
                            "bond": result.data["bond_oas"],
                        },
                    )
                except Exception:
                    pass

                return _json_response(
                    self,
                    {
                        "ok": True,
                        "asset_id": aid,
                        "level": level_str,
                        "bond": result.data["bond_oas"],
                        "liability_days": result.data["lock_days"],
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/buy":
            try:
                se = _get_settlement()
                aid = body.get("asset_id", "")
                buyer = body.get("buyer") or _default_identity()
                amount = float(body.get("amount", 10))
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if amount <= 0:
                    return _json_response(self, {"error": "amount must be positive"}, 400)
                if amount > 1_000_000:
                    return _json_response(self, {"error": "amount exceeds maximum"}, 400)

                # Anti-wash-trading: cooldown per buyer+asset
                cooldown_key = (buyer, aid)
                last_buy = _buy_cooldowns.get(cooldown_key, 0)
                if time.time() - last_buy < BUY_COOLDOWN_SECONDS:
                    remaining = int(BUY_COOLDOWN_SECONDS - (time.time() - last_buy))
                    return _json_response(self, {"error": f"cooldown: wait {remaining}s"}, 429)
                # UNAVAILABLE check: verify file exists and hash matches
                assert _ledger
                asset_row = _ledger._conn.execute(
                    "SELECT metadata FROM assets WHERE asset_id = ?", (aid,)
                ).fetchone()
                if asset_row:
                    asset_meta = json.loads(asset_row["metadata"]) if asset_row["metadata"] else {}
                    a_file_path = asset_meta.get("file_path")
                    a_file_hash = asset_meta.get("file_hash")
                    if a_file_path and a_file_hash:
                        if not os.path.isfile(a_file_path):
                            return _json_response(
                                self,
                                {
                                    "error": "UNAVAILABLE",
                                    "message": "Asset file is missing or modified",
                                },
                                409,
                            )
                        hb = hashlib.sha256()
                        with open(a_file_path, "rb") as fb:
                            for chunk in iter(lambda: fb.read(8192), b""):
                                hb.update(chunk)
                        if hb.hexdigest() != a_file_hash:
                            return _json_response(
                                self,
                                {
                                    "error": "UNAVAILABLE",
                                    "message": "Asset file is missing or modified",
                                },
                                409,
                            )
                if aid not in se.pools:
                    se.register_asset(aid, "protocol")
                receipt = se.execute(aid, buyer, amount)
                if receipt.status.value == "SETTLED":
                    _buy_cooldowns[cooldown_key] = time.time()
                    # Send purchase notification to buyer
                    try:
                        ns = _get_notification_service()
                        ns.notify(
                            buyer,
                            "PURCHASE",
                            f"Purchased {round(receipt.quote.equity_minted, 4)} shares of {aid[:12]}...",
                            {"asset_id": aid, "shares": round(receipt.quote.equity_minted, 4)},
                        )
                        # Send sale notification to asset owner
                        if _ledger:
                            owner_row = _ledger._conn.execute(
                                "SELECT owner FROM assets WHERE asset_id = ?", (aid,)
                            ).fetchone()
                            if owner_row and owner_row["owner"]:
                                ns.notify(
                                    owner_row["owner"],
                                    "SALE",
                                    f"Your asset {aid[:12]}... was purchased by {buyer[:12]}...",
                                    {"asset_id": aid, "buyer": buyer},
                                )
                    except Exception:
                        pass  # notifications are best-effort
                resp = {
                    "ok": receipt.status.value == "SETTLED",
                    "receipt_id": receipt.receipt_id,
                }
                if receipt.quote:
                    resp["tokens"] = round(receipt.quote.equity_minted, 4)
                    resp["price_after"] = round(receipt.quote.spot_price_after, 6)
                else:
                    resp["tokens"] = 0
                    resp["price_after"] = 0
                # equity balance from pool
                pool = se.get_pool(aid)
                resp["equity_balance"] = round(pool.equity.get(buyer, 0), 4) if pool else 0
                resp["error"] = None
                return _json_response(self, resp)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/stake":
            try:
                sk = _get_staking()
                node_id = body.get("node_id", "")
                pub_key = body.get("public_key", node_id)
                amount = float(body.get("amount", 0))
                if not node_id or amount <= 0:
                    return _json_response(self, {"error": "node_id and amount required"}, 400)
                v = sk.stake(node_id, pub_key, amount)
                return _json_response(
                    self,
                    {
                        "ok": True,
                        "node_id": v.node_id,
                        "total_stake": v.stake,
                        "status": v.status.value,
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # ── Become validator ──────────────────────────────────────
        if path == "/api/node/become-validator":
            from oasyce.config import (
                load_or_create_node_identity,
                load_node_role,
                save_node_role,
                get_economics,
            )

            if not _config:
                return _json_response(self, {"error": "not initialized"}, 503)
            try:
                _priv, node_id = load_or_create_node_identity(_config.data_dir)
                node_id_short = node_id[:16]
                economics = get_economics()
                min_stake = economics["min_stake"]
                from oasyce.utils import from_units

                amount = float(body.get("amount", from_units(min_stake)))
                if amount < from_units(min_stake):
                    return _json_response(
                        self, {"error": f"Minimum stake is {from_units(min_stake):.0f} OAS"}, 400
                    )

                sk = _get_staking()
                pub_key = _config.public_key or node_id
                v = sk.stake(node_id_short, pub_key, amount)

                role = load_node_role(_config.data_dir)
                if "validator" not in role.get("roles", []):
                    role.setdefault("roles", []).append("validator")
                role["validator_stake"] = v.stake
                # Save AI provider config if provided
                api_provider = body.get("api_provider", "")
                api_key = body.get("api_key", "")
                api_endpoint = body.get("api_endpoint", "")
                if api_provider:
                    role["api_provider"] = api_provider
                if api_key:
                    role["api_key_set"] = True  # never store raw key in role file
                    # Store key securely in separate file
                    _save_api_key(_config.data_dir, api_key)
                if api_endpoint:
                    role["api_endpoint"] = api_endpoint
                save_node_role(_config.data_dir, role)

                return _json_response(
                    self,
                    {
                        "ok": True,
                        "node_id": node_id_short,
                        "role": "validator",
                        "staked": v.stake,
                        "status": v.status.value,
                        "min_stake": min_stake,
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # ── Become arbitrator ────────────────────────────────────
        if path == "/api/node/become-arbitrator":
            from oasyce.config import load_or_create_node_identity, load_node_role, save_node_role

            if not _config:
                return _json_response(self, {"error": "not initialized"}, 503)
            try:
                _priv, node_id = load_or_create_node_identity(_config.data_dir)
                node_id_short = node_id[:16]

                tags = ["arbitration", "dispute"]
                extra = body.get("tags", [])
                if isinstance(extra, str):
                    extra = [t.strip() for t in extra.split(",") if t.strip()]
                tags.extend(extra)
                desc = body.get("description", "Dispute arbitration service")

                # Try registering capability
                try:
                    from oasyce.capabilities.registry import CapabilityRegistry
                    from oasyce.capabilities.models import CapabilityMetadata, PricingConfig

                    registry = CapabilityRegistry()
                    cap = CapabilityMetadata(
                        capability_id=f"arb_{node_id_short}",
                        name=f"Arbitrator {node_id_short}",
                        provider=node_id_short,
                        description=desc,
                        tags=tags,
                        intents=["dispute_arbitrate"],
                        pricing=PricingConfig(base_price=0.0),
                    )
                    registry.register(cap)
                except ImportError:
                    pass

                role = load_node_role(_config.data_dir)
                if "arbitrator" not in role.get("roles", []):
                    role.setdefault("roles", []).append("arbitrator")
                role["arbitrator_tags"] = tags
                # Save AI provider config if provided
                api_provider = body.get("api_provider", "")
                api_key = body.get("api_key", "")
                api_endpoint = body.get("api_endpoint", "")
                if api_provider:
                    role["api_provider"] = api_provider
                if api_key:
                    role["api_key_set"] = True
                    _save_api_key(_config.data_dir, api_key)
                if api_endpoint:
                    role["api_endpoint"] = api_endpoint
                save_node_role(_config.data_dir, role)

                return _json_response(
                    self,
                    {
                        "ok": True,
                        "node_id": node_id_short,
                        "role": "arbitrator",
                        "tags": tags,
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # ── Save AI API key (standalone) ─────────────────────────
        if path == "/api/node/api-key":
            from oasyce.config import load_node_role, save_node_role

            if not _config:
                return _json_response(self, {"error": "not initialized"}, 503)
            try:
                api_provider = body.get("api_provider", "")
                api_key = body.get("api_key", "")
                api_endpoint = body.get("api_endpoint", "")
                if not api_provider:
                    return _json_response(self, {"error": "api_provider required"}, 400)

                role = load_node_role(_config.data_dir)
                role["api_provider"] = api_provider
                if api_endpoint:
                    role["api_endpoint"] = api_endpoint
                if api_key:
                    role["api_key_set"] = True
                    _save_api_key(_config.data_dir, api_key)
                save_node_role(_config.data_dir, role)
                return _json_response(self, {"ok": True, "api_provider": api_provider})
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # ── Work evaluate (POST) ──────────────────────────────────
        if path == "/api/work/evaluate":
            if not _config:
                return _json_response(self, {"error": "not initialized"}, 503)
            from oasyce.services.work_value import WorkValueEngine

            db_path = os.path.join(_config.data_dir, "work.db")
            engine = WorkValueEngine(db_path=db_path)
            task_id = body.get("task_id", "")
            quality = float(body.get("quality_score", 0.8))
            rep_bonus = float(body.get("reputation_bonus", 0.0))
            if not task_id:
                engine.close()
                return _json_response(self, {"error": "task_id required"}, 400)
            result = engine.evaluate_task(
                task_id, quality_score=quality, reputation_bonus=rep_bonus
            )
            if result is None:
                engine.close()
                return _json_response(
                    self, {"error": "task not found or not in completed state"}, 400
                )
            # Auto-settle after evaluation
            engine.settle_task(task_id)
            settled = engine.get_task(task_id)
            engine.close()
            return _json_response(
                self, {"ok": True, "task": settled.to_dict() if settled else result.to_dict()}
            )

        # ── Capability routes (POST) ─────────────────────────────
        if path == "/api/capability/register":
            result = _api_capability_register(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        if path == "/api/capability/invoke":
            result = _api_capability_invoke(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        # ── Capability delivery routes (POST) ────────────────────────
        if path == "/api/delivery/register":
            result = _api_delivery_register(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        if path == "/api/delivery/invoke":
            result = _api_delivery_invoke(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        # ── Mempool POST route ─────────────────────────────────────
        if path == "/api/consensus/mempool/submit":
            if _mempool is None:
                return _json_response(self, {"error": "mempool not running"}, 503)
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                op_type_str = body.get("op_type", "")
                try:
                    op_type = OperationType(op_type_str)
                except ValueError:
                    return _json_response(self, {"error": f"invalid op_type: {op_type_str}"}, 400)
                op = Operation(
                    op_type=op_type,
                    validator_id=body.get("validator_id", ""),
                    amount=int(body.get("amount", 0)),
                    from_addr=body.get("from_addr", ""),
                    to_addr=body.get("to_addr", ""),
                    asset_type=body.get("asset_type", "OAS"),
                    commission_rate=int(body.get("commission_rate", 0)),
                    reason=body.get("reason", ""),
                )
                result = _mempool.submit(op)
                status_code = 200 if result.get("ok") else 400
                return _json_response(self, result, status_code)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)

        # ── Consensus POST routes ──────────────────────────────────
        if path == "/api/consensus/delegate":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import (
                    get_consensus_params,
                    get_economics,
                    NetworkMode,
                    load_or_create_node_identity,
                )

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                _priv, pubkey = load_or_create_node_identity(_config.data_dir)
                from oasyce.utils import to_units  # dead code — raise above

                validator_id = body.get("validator_id", "")
                amount = float(body.get("amount", 0))
                if not validator_id or amount <= 0:
                    return _json_response(self, {"error": "validator_id and amount required"}, 400)
                result = engine.delegate(pubkey, validator_id, to_units(amount))
                status_code = 200 if result.get("ok") else 400
                return _json_response(self, result, status_code)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        if path == "/api/consensus/undelegate":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import (
                    get_consensus_params,
                    get_economics,
                    NetworkMode,
                    load_or_create_node_identity,
                )

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                _priv, pubkey = load_or_create_node_identity(_config.data_dir)
                from oasyce.utils import to_units  # dead code — raise above

                validator_id = body.get("validator_id", "")
                amount = float(body.get("amount", 0))
                if not validator_id or amount <= 0:
                    return _json_response(self, {"error": "validator_id and amount required"}, 400)
                result = engine.undelegate(pubkey, validator_id, to_units(amount))
                status_code = 200 if result.get("ok") else 400
                return _json_response(self, result, status_code)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        # ── Governance POST routes ────────────────────────────────
        if path == "/api/governance/propose":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import (
                    get_consensus_params,
                    get_economics,
                    NetworkMode,
                    load_or_create_node_identity,
                )

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                _priv, pubkey = load_or_create_node_identity(_config.data_dir)
                title = body.get("title", "")
                description = body.get("description", "")
                changes_raw = body.get("changes", [])
                deposit = int(body.get("deposit", 0))
                if not title:
                    return _json_response(self, {"error": "title required"}, 400)
                changes = [ParameterChange(**c) for c in changes_raw]
                result = engine.submit_proposal(
                    pubkey,
                    title,
                    description,
                    changes,
                    deposit,
                )
                status_code = 200 if result.get("ok") else 400
                return _json_response(self, result, status_code)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        if path == "/api/governance/vote":
            if not _config:
                return _json_response(self, {"error": "server not configured"}, 503)
            engine = None
            try:
                raise ImportError("Consensus features moved to Go chain. Use oasyced CLI.")
                from oasyce.config import (
                    get_consensus_params,
                    get_economics,
                    NetworkMode,
                    load_or_create_node_identity,
                )

                consensus_db = os.path.join(_config.data_dir, "consensus.db")
                engine = ConsensusEngine(
                    db_path=consensus_db,
                    consensus_params=get_consensus_params(NetworkMode.TESTNET),
                    economics=get_economics(NetworkMode.TESTNET),
                )
                _priv, pubkey = load_or_create_node_identity(_config.data_dir)
                proposal_id = body.get("proposal_id", "")
                option = body.get("option", "")
                if not proposal_id or not option:
                    return _json_response(self, {"error": "proposal_id and option required"}, 400)
                vote_option = VoteOption(option)
                result = engine.cast_vote(proposal_id, pubkey, vote_option)
                status_code = 200 if result.get("ok") else 400
                return _json_response(self, result, status_code)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            finally:
                if engine:
                    engine.close()

        if path == "/api/fingerprint/embed":
            try:
                from oasyce.fingerprint.engine import FingerprintEngine

                engine = FingerprintEngine(_config.signing_key if _config else "key")
                aid = body.get("asset_id", "")
                caller = body.get("caller_id", "")
                content = body.get("content", "")
                if not all([aid, caller, content]):
                    return _json_response(
                        self, {"error": "asset_id, caller_id, content required"}, 400
                    )
                import time as _time

                fp = engine.generate_fingerprint(aid, caller, int(_time.time()))
                watermarked = engine.embed_text(content, fp)
                if _ledger:
                    registry = FingerprintRegistry(_ledger)
                    registry.record_distribution(aid, caller, fp, int(_time.time()))
                return _json_response(
                    self,
                    {
                        "ok": True,
                        "fingerprint": fp,
                        "watermarked_content": watermarked,
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/asset/update":
            aid = body.get("asset_id", "")
            new_tags = body.get("tags", [])
            if not _ledger:
                return _json_response(self, {"error": "ledger not initialized"}, 503)
            row = _ledger._conn.execute(
                "SELECT metadata FROM assets WHERE asset_id = ?", (aid,)
            ).fetchone()
            if not row:
                return _json_response(self, {"error": "not found"}, 404)
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            meta["tags"] = new_tags
            _ledger._conn.execute(
                "UPDATE assets SET metadata = ? WHERE asset_id = ?",
                (json.dumps(meta), aid),
            )
            _ledger._conn.commit()
            return _json_response(self, {"ok": True, "asset_id": aid, "tags": new_tags})

        # ── Inbox API (POST) ─────────────────────────────────────
        if path.startswith("/api/inbox/") and path.endswith("/approve"):
            item_id = path.split("/")[-2]
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            try:
                item = inbox.approve(item_id)
                return _json_response(
                    self, {"ok": True, "item_id": item.item_id, "status": item.status}
                )
            except (KeyError, ValueError) as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path.startswith("/api/inbox/") and path.endswith("/reject"):
            item_id = path.split("/")[-2]
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            try:
                item = inbox.reject(item_id)
                return _json_response(
                    self, {"ok": True, "item_id": item.item_id, "status": item.status}
                )
            except (KeyError, ValueError) as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path.startswith("/api/inbox/") and path.endswith("/edit"):
            item_id = path.split("/")[-2]
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            try:
                changes = body or {}
                item = inbox.edit(item_id, changes)
                return _json_response(
                    self, {"ok": True, "item_id": item.item_id, "status": item.status}
                )
            except (KeyError, ValueError) as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/inbox/trust":
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            level = body.get("trust_level") if body else None
            threshold = body.get("auto_threshold") if body else None
            if level is not None:
                inbox.set_trust_level(int(level))
            if threshold is not None:
                inbox.set_auto_threshold(float(threshold))
            return _json_response(
                self,
                {
                    "ok": True,
                    "trust_level": inbox.get_trust_level(),
                    "auto_threshold": inbox.get_auto_threshold(),
                },
            )

        if path == "/api/scan":
            from oasyce.services.scanner import AssetScanner
            from oasyce.services.inbox import ConfirmationInbox

            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            scan_path = body.get("path", ".") if body else "."
            scanner = AssetScanner()
            results = scanner.scan_directory(scan_path)
            inbox = ConfirmationInbox()
            added = []
            for r in results:
                if r.sensitivity != "sensitive":
                    item = inbox.add_pending_register(
                        file_path=r.file_path,
                        suggested_name=r.suggested_name,
                        suggested_tags=r.suggested_tags,
                        suggested_description=r.suggested_description,
                        sensitivity=r.sensitivity,
                        confidence=r.confidence,
                    )
                    added.append(item.item_id)
            return _json_response(
                self, {"ok": True, "scanned": len(results), "added_to_inbox": len(added)}
            )

        # ── Inbox API (POST) ──────────────────────────────────────
        if path.startswith("/api/inbox/") and path.endswith("/approve"):
            item_id = path.split("/")[-2]
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            try:
                item = inbox.approve(item_id)
                return _json_response(self, {"ok": True, "item_id": item_id, "status": "approved"})
            except (KeyError, ValueError) as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path.startswith("/api/inbox/") and path.endswith("/reject"):
            item_id = path.split("/")[-2]
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            try:
                item = inbox.reject(item_id)
                return _json_response(self, {"ok": True, "item_id": item_id, "status": "rejected"})
            except (KeyError, ValueError) as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path.startswith("/api/inbox/") and path.endswith("/edit"):
            item_id = path.split("/")[-2]
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            try:
                item = inbox.edit(item_id, body or {})
                return _json_response(self, {"ok": True, "item_id": item_id, "status": "approved"})
            except (KeyError, ValueError) as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/inbox/trust":
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox()
            level = body.get("trust_level") if body else None
            threshold = body.get("auto_threshold") if body else None
            if level is not None:
                inbox.set_trust_level(int(level))
            if threshold is not None:
                inbox.set_auto_threshold(float(threshold))
            return _json_response(
                self,
                {
                    "ok": True,
                    "trust_level": inbox.get_trust_level(),
                    "auto_threshold": inbox.get_auto_threshold(),
                },
            )

        if path == "/api/scan":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            scan_path = body.get("path", ".") if body else "."
            from oasyce.services.scanner import AssetScanner
            from oasyce.services.inbox import ConfirmationInbox

            scanner = AssetScanner()
            results = scanner.scan_directory(scan_path)
            inbox = ConfirmationInbox()
            added = []
            for r in results:
                if r.sensitivity != "sensitive":
                    item = inbox.add_pending_register(
                        file_path=r.file_path,
                        suggested_name=r.suggested_name,
                        suggested_tags=r.suggested_tags,
                        suggested_description=r.suggested_description,
                        sensitivity=r.sensitivity,
                        confidence=r.confidence,
                    )
                    added.append(item.item_id)
            return _json_response(self, {"ok": True, "scanned": len(results), "added": len(added)})

        # ── Agent scheduler API (POST) ────────────────────────────
        if path == "/api/agent/config":
            from oasyce.services.scheduler import get_scheduler, SchedulerConfig

            data_dir = _config.data_dir if _config else None
            scheduler = get_scheduler(data_dir)
            current = scheduler.get_config()
            # Partial update: merge body into existing config
            cfg_dict = current.to_dict()
            cfg_dict.update(body)
            new_cfg = SchedulerConfig.from_dict(cfg_dict)
            scheduler.update_config(new_cfg)
            return _json_response(self, scheduler.get_config().to_dict())

        if path == "/api/agent/run":
            from oasyce.services.scheduler import get_scheduler

            data_dir = _config.data_dir if _config else None
            scheduler = get_scheduler(data_dir)
            result = scheduler.run_once()
            return _json_response(self, result.to_dict())

        # ── Buyer Dispute/Refund (POST) ──────────────────────────
        if path == "/api/dispute/file":
            try:
                asset_id = body.get("asset_id", "")
                reason = body.get("reason", "").strip()
                evidence_text = body.get("evidence_text", "").strip()
                if not asset_id:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if not reason:
                    return _json_response(self, {"error": "reason required"}, 400)
                buyer = body.get("buyer") or _default_identity()
                dispute_id = f"DSP_{secrets.token_hex(8)}"
                now = time.time()
                db = _get_dispute_db()
                db.execute(
                    "INSERT INTO disputes (dispute_id, asset_id, buyer, reason, evidence_text, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'open', ?)",
                    (dispute_id, asset_id, buyer, reason, evidence_text, now),
                )
                db.commit()
                # Send notification to buyer
                try:
                    ns = _get_notification_service()
                    ns.notify(
                        buyer,
                        "DISPUTE_FILED",
                        f"Dispute filed for asset {asset_id[:12]}...",
                        {"dispute_id": dispute_id, "asset_id": asset_id},
                    )
                except Exception:
                    pass
                return _json_response(
                    self,
                    {
                        "ok": True,
                        "dispute_id": dispute_id,
                        "asset_id": asset_id,
                        "status": "open",
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # ── Notifications (POST) ─────────────────────────────────
        if path == "/api/notifications/read":
            notification_id = body.get("notification_id", "")
            address = body.get("address", "")
            ns = _get_notification_service()
            if notification_id:
                ok = ns.mark_read(notification_id)
                return _json_response(self, {"ok": ok})
            elif address:
                count = ns.mark_all_read(address)
                return _json_response(self, {"ok": True, "marked": count})
            else:
                return _json_response(self, {"error": "notification_id or address required"}, 400)

        # ── AHRP proxy (POST) ────────────────────────────────────
        if path.startswith("/ahrp/"):
            raw = json.dumps(body).encode("utf-8") if body else b""
            return _proxy_ahrp(self, "POST", self.path, raw)

        return _json_response(self, {"error": "not found"}, 404)

    def do_DELETE(self):
        # ── Auth check ──
        if not _check_auth(self):
            return _json_response(self, {"error": "unauthorized"}, 401)
        client_ip = self.client_address[0]
        if not _check_rate_limit(client_ip):
            return _json_response(self, {"error": "rate limit exceeded"}, 429)

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        m = re.match(r"^/api/asset/(.+)$", path)
        if m:
            aid = m.group(1)
            if not _ledger:
                return _json_response(self, {"error": "ledger not initialized"}, 503)
            row = _ledger._conn.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (aid,)
            ).fetchone()
            if not row:
                return _json_response(self, {"error": "Asset not found"}, 404)
            _ledger._conn.execute("DELETE FROM assets WHERE asset_id = ?", (aid,))
            _ledger._conn.execute("DELETE FROM fingerprint_records WHERE asset_id = ?", (aid,))
            _ledger._conn.commit()
            return _json_response(self, {"ok": True, "deleted": aid})
        return _json_response(self, {"error": "not found"}, 404)


# ── HTML / CSS / JS (single-page app) ───────────────────────────────

_INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Oasyce</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}

:root{
  --bg:#ffffff;
  --bg-s:#f8f8f6;
  --bg-t:#f0eeeb;
  --text:#1a1a1a;
  --text-s:#5c5c5c;
  --text-t:#999;
  --border:#e5e3de;
  --border-h:#ccc;
  --accent:#1a1a1a;
  --accent-fg:#fff;
  --success:#1a7a35;
  --error:#c53030;
  --surface:#fff;
  --hover:#f5f4f1;
  --shadow:0 1px 3px rgba(0,0,0,0.06);
  --shadow-l:0 4px 16px rgba(0,0,0,0.08);
  --radius:8px;
}

@media(prefers-color-scheme:dark){
  :root{
    --bg:#0c0c0c;
    --bg-s:#141414;
    --bg-t:#1e1e1e;
    --text:#e5e3de;
    --text-s:#999;
    --text-t:#666;
    --border:#262626;
    --border-h:#3a3a3a;
    --accent:#e5e3de;
    --accent-fg:#0c0c0c;
    --success:#4ade80;
    --error:#f87171;
    --surface:#141414;
    --hover:#1a1a1a;
    --shadow:0 1px 3px rgba(0,0,0,0.3);
    --shadow-l:0 4px 16px rgba(0,0,0,0.4);
  }
}

body{
  background:var(--bg);
  color:var(--text);
  font-family:-apple-system,'Helvetica Neue',system-ui,sans-serif;
  font-size:15px;
  line-height:1.6;
  -webkit-font-smoothing:antialiased;
}

/* ── Shell ──────────── */
.shell{display:flex;flex-direction:column;min-height:100vh;}
.main{flex:1;max-width:720px;width:100%;margin:0 auto;padding:32px 24px 80px;}

/* ── Nav ──────────── */
.nav{
  position:sticky;top:0;z-index:100;
  background:var(--bg);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;
  height:52px;padding:0 24px;
  gap:0;
}
.nav-brand{
  font-size:15px;font-weight:600;color:var(--text);
  letter-spacing:0.06em;margin-right:40px;
  display:flex;align-items:center;gap:8px;
}
.nav-dot{width:6px;height:6px;border-radius:50%;background:var(--success);}
.nav-links{display:flex;gap:0;height:100%;}
.nav-link{
  display:flex;align-items:center;
  padding:0 16px;
  font-size:13px;font-weight:500;
  color:var(--text-t);
  text-decoration:none;
  border-bottom:2px solid transparent;
  cursor:pointer;
  transition:color 0.15s,border-color 0.15s;
  white-space:nowrap;
  user-select:none;
}
.nav-link:hover{color:var(--text-s);}
.nav-link.active{color:var(--text);border-bottom-color:var(--text);}

/* mobile nav */
@media(max-width:600px){
  .nav{padding:0 12px;gap:0;}
  .nav-brand{margin-right:16px;font-size:14px;}
  .nav-link{padding:0 10px;font-size:12px;}
}

.nav-lang,.nav-about{
  width:32px;height:32px;
  border-radius:50%;
  border:1px solid var(--border);
  background:transparent;
  color:var(--text-s);
  font-size:12px;font-weight:600;
  cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  transition:all 0.15s;
  font-family:inherit;
  flex-shrink:0;
}
.nav-lang:hover,.nav-about:hover{background:var(--hover);border-color:var(--border-h);color:var(--text);}
.about-panel{
  position:fixed;top:0;right:0;bottom:0;
  width:340px;max-width:90vw;
  background:var(--bg);
  border-left:1px solid var(--border);
  box-shadow:-4px 0 24px var(--shadow);
  z-index:250;
  padding:28px 24px;
  overflow-y:auto;
  animation:slideIn 0.2s ease;
  transition:background 0.3s;
}
.about-panel h3{font-size:18px;font-weight:600;margin-bottom:20px;}
.about-panel p{font-size:14px;color:var(--text-s);line-height:1.7;margin-bottom:16px;}
.about-links{list-style:none;padding:0;}
.about-links li{margin-bottom:10px;}
.about-links a{
  font-size:14px;color:var(--text);
  text-decoration:none;
  display:flex;align-items:center;gap:8px;
  padding:10px 14px;
  border:1px solid var(--border);
  border-radius:var(--radius);
  transition:all 0.15s;
}
.about-links a:hover{background:var(--hover);border-color:var(--border-h);}
.about-links .link-label{font-weight:500;}
.about-links .link-desc{font-size:12px;color:var(--text-t);}
.about-close{position:absolute;top:16px;right:16px;background:none;border:none;color:var(--text-t);font-size:18px;cursor:pointer;}
.about-close:hover{color:var(--text);}
.about-contact{margin-top:24px;padding-top:20px;border-top:1px solid var(--border);font-size:13px;color:var(--text-t);}
.about-contact a{color:var(--text-s);text-decoration:none;}
.about-tabs{display:flex;gap:0;border-bottom:1px solid var(--border);margin-bottom:16px;overflow-x:auto;}
.about-tab{padding:8px 12px;font-size:12px;font-weight:500;color:var(--text-t);cursor:pointer;border:none;background:none;border-bottom:2px solid transparent;white-space:nowrap;font-family:inherit;transition:all .15s;}
.about-tab:hover{color:var(--text);background:var(--hover);}
.about-tab.active{color:var(--text);border-bottom-color:var(--text);}
.about-section{display:none;animation:fadeIn .2s;}
.about-section.active{display:block;}
.about-section pre{font-size:12px;line-height:1.7;color:var(--text-s);white-space:pre-wrap;word-break:break-word;margin:0;font-family:inherit;}
.about-version{display:inline-block;font-size:11px;color:var(--text-t);background:var(--hover);padding:2px 8px;border-radius:10px;margin-left:8px;}
.about-contact a:hover{color:var(--text);}
@keyframes slideIn{from{transform:translateX(100%)}to{transform:translateX(0)}}
.about-overlay{position:fixed;inset:0;z-index:240;background:transparent;}

/* ── Pages ──────────── */
.page{display:none;}
.page.active{display:block;}
.page-title{
  font-size:24px;font-weight:600;
  color:var(--text);
  margin-bottom:8px;
  letter-spacing:-0.01em;
}
.page-desc{
  font-size:14px;color:var(--text-s);
  margin-bottom:32px;
  max-width:480px;
}

/* ── Form ──────────── */
.field{margin-bottom:16px;}
.field-label{
  display:block;
  font-size:12px;font-weight:500;
  color:var(--text-s);
  text-transform:uppercase;
  letter-spacing:0.06em;
  margin-bottom:6px;
}
input[type="text"],input[type="number"],select,textarea{
  width:100%;height:42px;
  font-size:14px;font-family:inherit;
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:var(--radius);
  color:var(--text);
  padding:0 14px;
  outline:none;
  transition:border-color 0.15s,box-shadow 0.15s;
}
input:focus,select:focus,textarea:focus{
  border-color:var(--border-h);
  box-shadow:0 0 0 3px rgba(0,0,0,0.04);
}
@media(prefers-color-scheme:dark){
  input:focus,select:focus,textarea:focus{box-shadow:0 0 0 3px rgba(255,255,255,0.06);}
}
input::placeholder,textarea::placeholder{color:var(--text-t);}
textarea{height:auto;min-height:80px;padding:12px 14px;resize:vertical;}
.row{display:flex;gap:12px;}
.row>*{flex:1;min-width:0;}

/* ── Buttons ──────────── */
.btn{
  height:42px;font-size:14px;font-weight:500;font-family:inherit;
  background:var(--accent);color:var(--accent-fg);
  border:none;border-radius:var(--radius);
  padding:0 24px;cursor:pointer;
  transition:opacity 0.15s;
  display:inline-flex;align-items:center;justify-content:center;
}
.btn:hover{opacity:0.85;}
.btn:disabled{opacity:0.4;cursor:default;}
.btn-full{width:100%;}
.btn-ghost{
  background:transparent;color:var(--text);
  border:1px solid var(--border);
}
.btn-ghost:hover{background:var(--hover);opacity:1;}
.btn-sm{height:34px;font-size:13px;padding:0 14px;}
.btn-danger{background:transparent;color:var(--error);border:1px solid var(--border);}
.btn-danger:hover{border-color:var(--error);opacity:1;}

/* ── Card ──────────── */
.card{
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:12px;
  padding:24px;
  margin-bottom:16px;
}
.card-title{
  font-size:14px;font-weight:600;
  color:var(--text);margin-bottom:16px;
}

/* ── Identity Box ──────────── */
.identity-box{
  display:flex;
  gap:16px;
  align-items:flex-start;
}
.id-avatar{
  width:44px;height:44px;
  border-radius:50%;
  background:var(--bg-t);
  display:flex;align-items:center;justify-content:center;
  font-size:16px;font-weight:600;
  color:var(--text-s);
  flex-shrink:0;
}
.id-node{
  font-family:ui-monospace,'SF Mono',monospace;
  font-size:14px;
  color:var(--text);
  font-weight:500;
}
.id-hint{
  font-size:13px;
  color:var(--text-s);
  margin-top:6px;
  line-height:1.5;
}
.id-backup{
  font-size:12px;
  color:var(--error);
  margin-top:8px;
  line-height:1.4;
  padding:8px 12px;
  background:var(--bg-s);
  border-radius:6px;
}
.id-backup code{
  font-family:ui-monospace,'SF Mono',monospace;
  font-size:11px;
  background:var(--bg-t);
  padding:1px 4px;
  border-radius:3px;
}

/* ── Drop Zone ──────────── */
.drop-zone{
  border:2px dashed var(--border);
  border-radius:12px;
  padding:48px 24px;
  text-align:center;
  cursor:pointer;
  transition:all 0.2s;
  position:relative;
}
.drop-zone:hover,.drop-zone.over{
  border-color:var(--border-h);
  background:var(--hover);
}
.drop-zone.has-file{
  border-style:solid;
  border-color:var(--success);
  background:transparent;
  padding:20px 24px;
}
.drop-icon{font-size:32px;margin-bottom:12px;opacity:0.5;}
.drop-text{font-size:14px;color:var(--text-s);}
.drop-link{color:var(--text);font-weight:500;cursor:pointer;text-decoration:underline;text-underline-offset:2px;}
.drop-hint{font-size:12px;color:var(--text-t);margin-top:8px;}
.drop-file{
  display:flex;align-items:center;gap:12px;
  font-size:14px;color:var(--text);
}
.drop-file-name{font-weight:500;word-break:break-all;}
.drop-file-size{font-size:12px;color:var(--text-t);}
.drop-file-remove{
  margin-left:auto;
  background:none;border:none;
  color:var(--text-t);font-size:16px;
  cursor:pointer;padding:4px 8px;
}
.drop-file-remove:hover{color:var(--error);}

/* ── Field Hints ──────────── */
.field-hint{
  font-size:12px;
  color:var(--text-t);
  margin-top:4px;
  line-height:1.4;
}
.required{
  font-size:10px;
  color:var(--error);
  font-weight:normal;
}
.optional{
  font-size:10px;
  color:var(--text-t);
  font-weight:normal;
  font-style:italic;
}

/* ── Asset List ──────────── */
.a-table{width:100%;}
.a-row{
  display:flex;align-items:center;
  padding:12px 0;
  border-bottom:1px solid var(--border);
  cursor:pointer;
  transition:background 0.1s;
}
.a-row:hover{background:var(--hover);margin:0 -12px;padding:12px 12px;border-radius:6px;border-color:transparent;}
.a-row:last-child{border-bottom:none;}
.a-info{flex:1;min-width:0;}
.a-id{
  font-size:13px;
  font-family:ui-monospace,'SF Mono',monospace;
  color:var(--text);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
.a-meta{font-size:12px;color:var(--text-t);margin-top:1px;}
.a-side{display:flex;align-items:center;gap:10px;flex-shrink:0;margin-left:16px;}
.a-price{
  font-size:13px;
  font-family:ui-monospace,'SF Mono',monospace;
  color:var(--text-s);
}
.a-del{
  width:28px;height:28px;
  border:none;background:transparent;
  color:var(--text-t);font-size:14px;
  cursor:pointer;border-radius:6px;
  opacity:0;transition:all 0.15s;
  display:flex;align-items:center;justify-content:center;
}
.a-row:hover .a-del{opacity:1;}
.a-del:hover{color:var(--error);background:var(--bg-s);}

/* ── Tag ──────────── */
.tag{
  display:inline-block;
  height:18px;line-height:18px;
  padding:0 6px;font-size:10px;
  color:var(--text-t);background:var(--bg-s);
  border-radius:4px;margin-right:3px;
}

/* ── Pagination ──────────── */
.pager{
  display:flex;align-items:center;
  justify-content:space-between;
  margin-top:16px;
  font-size:13px;color:var(--text-t);
}
.pager-btns{display:flex;gap:6px;}
.pager-btn{
  width:34px;height:34px;
  border:1px solid var(--border);
  border-radius:var(--radius);
  background:transparent;color:var(--text-s);
  font-size:13px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;
  transition:all 0.15s;
}
.pager-btn:hover{background:var(--hover);border-color:var(--border-h);}
.pager-btn:disabled{opacity:0.3;cursor:default;}
.pager-btn.active{background:var(--accent);color:var(--accent-fg);border-color:var(--accent);}

/* ── KV ──────────── */
.kv{display:flex;justify-content:space-between;align-items:baseline;padding:10px 0;font-size:14px;border-bottom:1px solid var(--border);}
.kv:last-child{border-bottom:none;}
.kv-k{color:var(--text-s);}
.kv-v{font-family:ui-monospace,'SF Mono',monospace;font-size:13px;color:var(--text);text-align:right;word-break:break-all;max-width:55%;}

/* ── Result ──────────── */
.res{background:var(--bg-s);border-radius:10px;padding:16px;margin-top:16px;}

/* ── Modal ──────────── */
.modal-bg{
  position:fixed;inset:0;
  background:rgba(0,0,0,0.3);
  backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);
  z-index:200;display:flex;align-items:center;justify-content:center;
  animation:fadeIn 0.15s ease;
}
@media(prefers-color-scheme:dark){.modal-bg{background:rgba(0,0,0,0.6);}}
.modal{
  background:var(--bg);
  border:1px solid var(--border);
  border-radius:14px;
  max-width:440px;width:92%;
  max-height:80vh;overflow-y:auto;
  padding:28px;position:relative;
  box-shadow:var(--shadow-l);
}
.modal-x{position:absolute;top:14px;right:14px;background:none;border:none;color:var(--text-t);font-size:18px;cursor:pointer;}
.modal-x:hover{color:var(--text);}
.modal h3{font-size:16px;font-weight:600;margin-bottom:16px;}

/* ── Toast ──────────── */
.toast-c{position:fixed;top:64px;right:20px;z-index:300;display:flex;flex-direction:column;gap:8px;}
.tst{background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:10px 16px;font-size:13px;color:var(--text);box-shadow:var(--shadow-l);animation:toastIn 0.15s ease,toastOut 0.15s ease 2.8s forwards;max-width:260px;}
.tst.error{color:var(--error);}

/* ── Pipeline (AHRP tx) ──────────── */
.pipe{display:flex;align-items:center;justify-content:center;margin:20px 0;}
.pipe-s{display:flex;flex-direction:column;align-items:center;gap:4px;padding:4px 8px;}
.pipe-d{width:8px;height:8px;border-radius:50%;border:1.5px solid var(--border);background:transparent;transition:all 0.3s;}
.pipe-s.done .pipe-d{background:var(--text);border-color:var(--text);}
.pipe-s.active .pipe-d{border-color:var(--text-s);}
.pipe-line{width:24px;height:1px;background:var(--border);margin-bottom:14px;}
.pipe-line.done{background:var(--text-t);}
.pipe-l{font-size:10px;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-t);}
.pipe-s.done .pipe-l{color:var(--text-s);}
.pipe-s.active .pipe-l{color:var(--text);}

/* ── Stars ──────────── */
.stars{display:flex;gap:2px;margin-bottom:12px;}
.stars span{font-size:18px;cursor:pointer;color:var(--border);user-select:none;}
.stars span.lit{color:var(--text);}

/* ── Checkboxes ──────────── */
.chk-g{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:12px;}
.chk-g label{display:flex;align-items:center;gap:5px;font-size:13px;color:var(--text-s);cursor:pointer;}

/* ── Sub-label ──────────── */
.sub-l{font-size:12px;font-weight:500;color:var(--text-s);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:12px;margin-top:4px;}
.divider{border-top:1px solid var(--border);margin-top:24px;padding-top:24px;}

/* ── Net Grid ──────────── */
.ng{display:grid;grid-template-columns:1fr 1fr;gap:4px 20px;font-size:13px;}
.ng-k{color:var(--text-t);}
.ng-v{font-family:ui-monospace,'SF Mono',monospace;font-size:12px;color:var(--text-s);text-align:right;}

/* ── Stat Row ──────────── */
.stat-row{
  display:flex;gap:24px;margin-bottom:32px;
}
.stat-item{text-align:center;flex:1;}
.stat-n{
  font-size:32px;font-weight:300;
  color:var(--text);
  font-variant-numeric:tabular-nums;
  letter-spacing:-0.02em;
}
.stat-l{font-size:11px;color:var(--text-t);text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;}

/* ── Portfolio row ──────────── */
.p-row{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--border);font-size:13px;}
.p-row:last-child{border-bottom:none;}
.p-id{font-family:ui-monospace,'SF Mono',monospace;color:var(--text);}
.p-v{color:var(--text-s);}

/* ── Empty ──────────── */
.empty{text-align:center;color:var(--text-t);padding:48px 16px;font-size:14px;}
.empty code{background:var(--bg-s);padding:2px 7px;border-radius:4px;font-size:12px;font-family:ui-monospace,'SF Mono',monospace;color:var(--text-s);}

.ok{color:var(--success);}
.err{color:var(--error);margin-top:10px;font-size:14px;}

/* ── Stake Items ──────────── */
.stk-item{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px;}
.stk-item:last-child{border-bottom:none;}
.stk-id{font-family:ui-monospace,'SF Mono',monospace;color:var(--text-s);}
.stk-a{font-family:ui-monospace,'SF Mono',monospace;color:var(--text);}

/* ── AHRP Match ──────────── */
.m-card{padding:12px 0;border-bottom:1px solid var(--border);}
.m-card:last-child{border-bottom:none;}
.m-top{display:flex;justify-content:space-between;font-size:13px;}
.m-agent{font-family:ui-monospace,'SF Mono',monospace;color:var(--text);}
.m-origin{font-size:11px;color:var(--text-t);text-transform:uppercase;}
.m-bar{width:100%;height:3px;background:var(--bg-t);border-radius:2px;margin:6px 0;}
.m-bar-fill{height:100%;border-radius:2px;background:var(--text-t);}
.m-bot{display:flex;justify-content:space-between;font-size:12px;color:var(--text-t);}

/* ── Animations ──────────── */
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes toastIn{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:translateY(0)}}
@keyframes toastOut{from{opacity:1}to{opacity:0}}

/* ── Responsive ──────────── */
@media(max-width:600px){
  .main{padding:24px 16px 64px;}
  .row{flex-direction:column;gap:8px;}
  .stat-row{gap:12px;}
  .stat-n{font-size:24px;}
  .ng{grid-template-columns:1fr;}
  .ng-v{text-align:left;}
  .kv{flex-direction:column;gap:2px;}
  .kv-v{text-align:left;max-width:100%;}
}
</style>
</head>
<body>
<div class="shell">

<!-- ── Nav ──────────── -->
<nav class="nav">
  <div class="nav-brand">Oasyce <span class="nav-dot" id="status-dot"></span></div>
  <div class="nav-links">
    <a class="nav-link active" data-page="register" data-en="Register" data-zh="注册">Register</a>
    <a class="nav-link" data-page="trade" data-en="Trade" data-zh="交易">Trade</a>
    <a class="nav-link" data-page="assets" data-en="Assets" data-zh="资产">Assets</a>
    <a class="nav-link" data-page="agents" data-en="Agents" data-zh="代理">Agents</a>
    <a class="nav-link" data-page="network" data-en="Network" data-zh="网络">Network</a>
  </div>
  <div style="display:flex;align-items:center;gap:8px;margin-left:auto;">
    <button class="nav-about" id="about-btn" title="About Oasyce">i</button>
    <button class="nav-lang" id="lang-btn">中</button>
  </div>
</nav>

<div class="main">

  <!-- ═══ Register Page ═══ -->
  <div class="page active" id="pg-register">
    <div class="page-title">Register a data asset</div>
    <div class="page-desc">Claim ownership of a file. Once registered, other agents can discover, quote, and purchase access rights.</div>
    <div class="card">
      <div class="field">
        <label class="field-label">File path</label>
        <input type="text" id="reg-path" placeholder="/path/to/your/file">
      </div>
      <div class="row">
        <div class="field"><label class="field-label">Owner</label><input type="text" id="reg-owner" placeholder="Your name or agent ID"></div>
        <div class="field"><label class="field-label">Tags</label><input type="text" id="reg-tags" placeholder="medical, imaging, dicom"></div>
      </div>
      <div class="row">
        <div class="field"><label class="field-label" data-i18n="lbl-rights-type">Rights type</label><select id="reg-rights-type"><option value="original">Original</option><option value="co_creation">Co-creation</option><option value="licensed">Licensed resale</option><option value="collection">Personal collection</option></select></div>
      </div>
      <div id="co-creators-section" style="display:none;">
        <label class="field-label" data-i18n="lbl-co-creators">Co-creators</label>
        <div class="field-hint" data-i18n="hint-co-creators">At least 2 co-creators, shares must total 100%</div>
        <div id="co-creators-list"></div>
        <button class="btn btn-ghost btn-sm" id="add-co-creator-btn" type="button">+ Add co-creator</button>
      </div>
      <button class="btn btn-full" id="reg-btn">Register</button>
      <div id="reg-result"></div>
    </div>
  </div>

  <!-- ═══ Trade Page ═══ -->
  <div class="page" id="pg-trade">
    <div class="page-title">Trade</div>
    <div class="page-desc">Quote and purchase shares in data assets. Buy to gain access rights and revenue share.</div>

    <div class="card">
      <div class="card-title" data-i18n="card-buy">Buy Shares</div>
      <div class="row">
        <div class="field"><label class="field-label"><span data-i18n="lbl-asset-id">Asset ID</span> <span class="required">*</span></label><input type="text" id="buy-asset" placeholder="Paste asset ID"><div class="field-hint" data-i18n="hint-buy-asset">Copy from the Assets tab or from the creator who shared it with you.</div></div>
        <div class="field" style="max-width:140px;"><label class="field-label"><span data-i18n="lbl-amount">Amount (OAS)</span></label><input type="number" id="buy-amount" value="10"><div class="field-hint" data-i18n="hint-buy-amount">How much to spend.</div></div>
      </div>
      <div class="row">
        <button class="btn btn-ghost btn-full" id="quote-btn">Quote</button>
        <button class="btn btn-full" id="buy-btn">Buy</button>
      </div>
      <div id="buy-result"></div>
    </div>

    <div class="card">
      <div class="card-title">Portfolio</div>
      <div id="portfolio-list"></div>
    </div>

    <div class="card">
      <div class="card-title">Stake</div>
      <div class="row">
        <div class="field"><label class="field-label">Node ID</label><input type="text" id="stake-node" placeholder="Validator node ID"></div>
        <div class="field" style="max-width:140px;"><label class="field-label">Amount</label><input type="number" id="stake-amount" value="10000"></div>
      </div>
      <button class="btn btn-full" id="stake-btn">Stake</button>
      <div id="stake-result"></div>
    </div>
  </div>

  <!-- ═══ Assets Page ═══ -->
  <div class="page" id="pg-assets">
    <div class="page-title">Your Assets</div>
    <div class="page-desc">Manage registered data assets. Click any asset for details.</div>

    <div style="display:flex;gap:8px;margin-bottom:20px;">
      <input type="text" id="asset-search" placeholder="Search by ID or tag...">
    </div>
    <div id="assets-list"></div>
    <div class="pager" id="pager"></div>
  </div>

  <!-- ═══ Agents Page (AHRP) ═══ -->
  <div class="page" id="pg-agents">
    <div class="page-title">Agent Protocol</div>
    <div class="page-desc">Register your agent on the AHRP network, discover data providers, and execute transactions.</div>

    <div class="card">
      <div class="card-title">Announce Agent</div>
      <div class="row">
        <div class="field"><label class="field-label">Agent ID</label><input type="text" id="ahrp-agent-id" placeholder="my-agent-001"></div>
        <div class="field"><label class="field-label">Public key</label><input type="text" id="ahrp-pub-key" placeholder="ed25519 public key"></div>
      </div>
      <div class="row">
        <div class="field"><label class="field-label">Reputation</label><input type="number" id="ahrp-reputation" value="10"></div>
        <div class="field"><label class="field-label">Stake</label><input type="number" id="ahrp-stake" value="100"></div>
      </div>
      <div class="row">
        <div class="field"><label class="field-label">Capability ID</label><input type="text" id="ahrp-cap-id" placeholder="medical-imaging"></div>
        <div class="field"><label class="field-label">Tags</label><input type="text" id="ahrp-cap-tags" placeholder="dicom, radiology"></div>
      </div>
      <div class="row">
        <div class="field" style="flex:2;"><label class="field-label">Description</label><input type="text" id="ahrp-cap-desc" placeholder="High-res medical imaging dataset"></div>
        <div class="field"><label class="field-label">Price floor</label><input type="number" id="ahrp-cap-price" value="1.0"></div>
      </div>
      <div class="row">
        <div class="field">
          <label class="field-label">Origin</label>
          <select id="ahrp-cap-origin"><option value="human">human</option><option value="sensor">sensor</option><option value="curated">curated</option><option value="synthetic">synthetic</option></select>
        </div>
        <div class="field">
          <label class="field-label">Access levels</label>
          <div class="chk-g" style="margin-top:6px;"><label><input type="checkbox" value="L0" checked> L0</label><label><input type="checkbox" value="L1" checked> L1</label><label><input type="checkbox" value="L2"> L2</label><label><input type="checkbox" value="L3"> L3</label></div>
        </div>
      </div>
      <button class="btn btn-full" id="ahrp-announce-btn">Announce</button>
      <div id="ahrp-announce-result"></div>
    </div>

    <div class="card">
      <div class="card-title">Discover Agents</div>
      <div class="row">
        <div class="field" style="flex:2;"><label class="field-label">What do you need?</label><input type="text" id="ahrp-search-desc" placeholder="Medical imaging data for training"></div>
        <div class="field"><label class="field-label">Tags</label><input type="text" id="ahrp-search-tags" placeholder="dicom"></div>
      </div>
      <div class="row">
        <div class="field"><label class="field-label">Min reputation</label><input type="number" id="ahrp-search-rep" value="5"></div>
        <div class="field"><label class="field-label">Max price</label><input type="number" id="ahrp-search-price" value="100"></div>
        <div class="field"><label class="field-label">Access</label><select id="ahrp-search-access"><option>L0</option><option>L1</option><option>L2</option><option>L3</option></select></div>
      </div>
      <button class="btn btn-ghost btn-full" id="ahrp-find-btn">Find</button>
      <div id="ahrp-matches" style="margin-top:14px;"></div>
    </div>

    <div class="card">
      <div class="card-title">Transaction</div>
      <div class="pipe" id="tx-pipeline">
        <div class="pipe-s" id="tx-s-request"><div class="pipe-d"></div><div class="pipe-l">Request</div></div><div class="pipe-line" id="tx-l-1"></div>
        <div class="pipe-s" id="tx-s-offer"><div class="pipe-d"></div><div class="pipe-l">Offer</div></div><div class="pipe-line" id="tx-l-2"></div>
        <div class="pipe-s" id="tx-s-accept"><div class="pipe-d"></div><div class="pipe-l">Accept</div></div><div class="pipe-line" id="tx-l-3"></div>
        <div class="pipe-s" id="tx-s-deliver"><div class="pipe-d"></div><div class="pipe-l">Deliver</div></div><div class="pipe-line" id="tx-l-4"></div>
        <div class="pipe-s" id="tx-s-confirm"><div class="pipe-d"></div><div class="pipe-l">Confirm</div></div>
      </div>
      <div class="row">
        <div class="field"><label class="field-label">Buyer</label><input type="text" id="tx-buyer" placeholder="Buyer agent ID"></div>
        <div class="field"><label class="field-label">Seller</label><input type="text" id="tx-seller" placeholder="Seller agent ID"></div>
      </div>
      <div class="row">
        <div class="field"><label class="field-label">Capability</label><input type="text" id="tx-cap-id" placeholder="Capability ID"></div>
        <div class="field"><label class="field-label">Price</label><input type="number" id="tx-price" value="10"></div>
      </div>
      <button class="btn btn-full" id="tx-accept-btn">Accept &amp; Create</button>
      <div id="tx-accept-result"></div>

      <div class="divider">
        <div class="row">
          <div class="field"><label class="field-label">Transaction ID</label><input type="text" id="tx-deliver-id" placeholder="TX ID"></div>
          <div class="field"><label class="field-label">Content hash</label><input type="text" id="tx-content-hash" placeholder="SHA-256"></div>
        </div>
        <button class="btn btn-ghost btn-full" id="tx-deliver-btn">Deliver</button>
        <div id="tx-deliver-result"></div>
      </div>
      <div class="divider">
        <div class="field"><label class="field-label">Transaction ID</label><input type="text" id="tx-confirm-id" placeholder="TX ID"></div>
        <div class="stars" id="star-rating"><span data-v="1">&#x2605;</span><span data-v="2">&#x2605;</span><span data-v="3">&#x2605;</span><span data-v="4">&#x2605;</span><span data-v="5">&#x2605;</span></div>
        <button class="btn btn-full" id="tx-confirm-btn">Confirm &amp; Settle</button>
        <div id="tx-confirm-result"></div>
      </div>
    </div>
  </div>

  <!-- ═══ Network Page ═══ -->
  <div class="page" id="pg-network">
    <div class="page-title">Network</div>
    <div class="page-desc">Node status and validator information.</div>

    <div class="stat-row">
      <div class="stat-item"><div class="stat-n" id="stat-assets">&mdash;</div><div class="stat-l" data-i18n="stat-assets">Assets</div></div>
      <div class="stat-item"><div class="stat-n" id="stat-blocks">&mdash;</div><div class="stat-l" data-i18n="stat-blocks">Blocks</div></div>
      <div class="stat-item"><div class="stat-n" id="stat-dists">&mdash;</div><div class="stat-l" data-i18n="stat-watermarks">Watermarks</div></div>
    </div>

    <div class="card" id="identity-card">
      <div class="card-title" data-i18n="card-identity">Your Identity</div>
      <div id="identity-info" class="empty" data-i18n="loading-identity">Loading...</div>
    </div>

    <div class="card">
      <div class="card-title" data-i18n="card-node">Node</div>
      <div class="ng" id="net-info"></div>
    </div>

    <div class="card" id="stakes-card" style="display:none;">
      <div class="card-title">Validators</div>
      <div id="stakes-list"></div>
    </div>

    <div class="card">
      <div class="card-title">Watermark</div>
      <div class="row">
        <div class="field"><label class="field-label">Asset ID</label><input type="text" id="emb-asset" placeholder="Asset ID"></div>
        <div class="field"><label class="field-label">Buyer ID</label><input type="text" id="emb-caller" placeholder="Buyer agent ID"></div>
      </div>
      <div class="field"><label class="field-label">Content</label><textarea id="emb-content" placeholder="Content to watermark..."></textarea></div>
      <button class="btn btn-full" id="emb-btn">Embed</button>
      <div id="emb-result"></div>

      <div class="divider">
        <div class="sub-l">Trace</div>
        <div class="row">
          <input type="text" id="fp-input" placeholder="Fingerprint to trace...">
          <button class="btn btn-ghost btn-sm" id="fp-trace-btn" style="max-width:80px;">Trace</button>
        </div>
        <div id="fp-trace-result"></div>
      </div>
      <div class="divider">
        <div class="sub-l">Lookup</div>
        <div class="row">
          <input type="text" id="fp-asset-input" placeholder="Asset ID">
          <button class="btn btn-ghost btn-sm" id="fp-list-btn" style="max-width:80px;">Lookup</button>
        </div>
        <div id="fp-dist-list"></div>
      </div>
    </div>
  </div>

</div>
</div>

<script>
(function(){
  /* ── Helpers ──────────── */
  function esc(s){if(s==null)return'';var d=document.createElement('div');d.textContent=String(s);return d.innerHTML;}
  function trunc(s,n){n=n||16;return s&&s.length>n?s.slice(0,n)+'\u2026':(s||'');}
  function timeAgo(ts){if(!ts)return'';var then=typeof ts==='number'?(ts>1e12?new Date(ts):new Date(ts*1000)):new Date(ts);var d=Math.floor((Date.now()-then.getTime())/1000);if(d<0)d=0;if(d<60)return d+'s ago';if(d<3600)return Math.floor(d/60)+'m ago';if(d<86400)return Math.floor(d/3600)+'h ago';return Math.floor(d/86400)+'d ago';}
  async function api(p){try{return(await fetch(p)).json();}catch(e){return null;}}
  async function postApi(p,b){try{return(await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})).json();}catch(e){return{error:e.message};}}
  function toast(msg,type){var c=document.getElementById('toast-c');if(!c){c=document.createElement('div');c.id='toast-c';c.className='toast-c';document.body.appendChild(c);}var el=document.createElement('div');el.className='tst'+(type==='error'?' error':'');el.textContent=msg;c.appendChild(el);setTimeout(function(){el.remove();},3000);}
  window.toast=toast;

  /* ── Wallet identity ──────────── */
  window.__oasyce_wallet='anonymous';
  api('/api/identity/wallet').then(function(r){if(r&&r.exists&&r.address)window.__oasyce_wallet=r.address;});

  /* ── Navigation ──────────── */
  var links=document.querySelectorAll('.nav-link');
  links.forEach(function(link){
    link.addEventListener('click',function(){
      links.forEach(function(l){l.classList.remove('active');});
      this.classList.add('active');
      document.querySelectorAll('.page').forEach(function(p){p.classList.remove('active');});
      document.getElementById('pg-'+this.dataset.page).classList.add('active');
      if(this.dataset.page==='assets')loadAssets();
      if(this.dataset.page==='trade')loadPortfolio();
      if(this.dataset.page==='network'){// ── Drop Zone ──
  var dropZone = document.getElementById('drop-zone');
  var filePick = document.getElementById('file-pick');
  var regFields = document.getElementById('reg-fields');
  var dropFileInfo = document.getElementById('drop-file-info');
  var dropText = document.getElementById('drop-text');
  var _droppedPath = '';

  function formatSize(bytes){
    if(bytes<1024)return bytes+' B';
    if(bytes<1048576)return(bytes/1024).toFixed(1)+' KB';
    return(bytes/1048576).toFixed(1)+' MB';
  }

  function handleFile(file){
    _droppedPath = file.name;
    // Try to get full path (only works in some browsers via webkitRelativePath)
    if(file.path) _droppedPath = file.path;
    else if(file.webkitRelativePath) _droppedPath = file.webkitRelativePath;

    document.getElementById('reg-path').value = _droppedPath;

    // Auto-generate tags from file extension and name
    var ext = file.name.split('.').pop().toLowerCase();
    var autoTags = [];
    if(['csv','json','xml','parquet','sqlite','db'].indexOf(ext)!==-1) autoTags.push('dataset');
    if(['jpg','jpeg','png','gif','webp','svg','bmp'].indexOf(ext)!==-1) autoTags.push('image');
    if(['mp4','mov','avi','mkv'].indexOf(ext)!==-1) autoTags.push('video');
    if(['mp3','wav','flac','ogg'].indexOf(ext)!==-1) autoTags.push('audio');
    if(['pdf','doc','docx','txt','md'].indexOf(ext)!==-1) autoTags.push('document');
    if(['py','js','ts','go','rs','java','c','cpp'].indexOf(ext)!==-1) autoTags.push('code');
    if(ext) autoTags.push(ext);
    document.getElementById('reg-tags').value = autoTags.join(', ');

    // Show file info in drop zone
    dropZone.classList.add('has-file');
    dropFileInfo.style.display = 'flex';
    dropFileInfo.innerHTML = '<div><div class="drop-file-name">'+esc(file.name)+'</div><div class="drop-file-size">'+formatSize(file.size)+'</div></div><button class="drop-file-remove" onclick="clearFile()">&times;</button>';
    dropText.style.display = 'none';
    document.querySelector('.drop-icon').style.display = 'none';
    document.querySelector('.drop-hint').style.display = 'none';

    // Show form fields
    regFields.style.display = 'block';
  }

  window.clearFile = function(){
    _droppedPath = '';
    document.getElementById('reg-path').value = '';
    document.getElementById('reg-tags').value = '';
    dropZone.classList.remove('has-file');
    dropFileInfo.style.display = 'none';
    dropFileInfo.innerHTML = '';
    dropText.style.display = '';
    document.querySelector('.drop-icon').style.display = '';
    document.querySelector('.drop-hint').style.display = '';
    regFields.style.display = 'none';
    filePick.value = '';
  };

  // Drag events
  ['dragenter','dragover'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.add('over');});
  });
  ['dragleave','drop'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.remove('over');});
  });
  dropZone.addEventListener('drop', function(e){
    var files = e.dataTransfer.files;
    if(files.length > 0) handleFile(files[0]);
  });
  dropZone.addEventListener('click', function(e){
    if(e.target.tagName !== 'BUTTON' && e.target.tagName !== 'LABEL' && !dropZone.classList.contains('has-file')){
      filePick.click();
    }
  });
  filePick.addEventListener('change', function(){
    if(this.files.length > 0) handleFile(this.files[0]);
  });

  // ── i18n ──
  var _lang = (navigator.language||'').startsWith('zh') ? 'zh' : 'en';
  var _t = {
    en: {
      'pg-register-title': 'Register a data asset',
      'pg-register-desc': 'Claim ownership of a file. Once registered, other agents can discover, quote, and purchase access rights.',
      'pg-trade-title': 'Trade',
      'pg-trade-desc': 'Quote and purchase shares in data assets. Buy to gain access rights and revenue share.',
      'pg-assets-title': 'Your Assets',
      'pg-assets-desc': 'Manage registered data assets. Click any asset for details.',
      'pg-agents-title': 'Agent Protocol',
      'pg-agents-desc': 'Register your agent on the AHRP network, discover data providers, and execute transactions.',
      'pg-network-title': 'Network',
      'pg-network-desc': 'Node status and validator information.',
      'reg-path-ph': '/path/to/your/file',
      'drop-text': 'Drag a file here, or <label for="file-pick" class="drop-link">browse</label>',
      'drop-hint': 'Register your file to claim ownership on the Oasyce network',
      'hint-file': 'Auto-filled from your dropped file',
      'hint-owner': 'Who owns this data? Defaults to your node ID if left blank.',
      'hint-tags': 'Help others find your asset. Comma-separated keywords.',
      'optional': 'optional',
      'reg-owner-ph': 'Your name or agent ID',
      'reg-tags-ph': 'medical, imaging, dicom',
      'reg-btn': 'Register',
      'buy-asset-ph': 'Paste asset ID',
      'quote-btn': 'Quote',
      'buy-btn': 'Buy',
      'card-buy': 'Buy Shares',
      'hint-buy-asset': 'Copy from the Assets tab or from the creator who shared it with you.',
      'hint-buy-amount': 'How much to spend.',
      'card-portfolio': 'Portfolio',
      'card-stake': 'Stake',
      'stake-node-ph': 'Validator node ID',
      'stake-btn': 'Stake',
      'search-ph': 'Search by ID or tag...',
      'card-announce': 'Announce Agent',
      'announce-btn': 'Announce',
      'card-discover': 'Discover Agents',
      'find-btn': 'Find',
      'card-tx': 'Transaction',
      'accept-btn': 'Accept & Create',
      'deliver-btn': 'Deliver',
      'confirm-btn': 'Confirm & Settle',
      'card-node': 'Node',
      'card-validators': 'Validators',
      'card-watermark': 'Watermark',
      'embed-btn': 'Embed',
      'trace-btn': 'Trace',
      'lookup-btn': 'Lookup',
      'lbl-file': 'File path',
      'lbl-owner': 'Owner',
      'lbl-tags': 'Tags',
      'lbl-rights-type': 'Rights type',
      'lbl-co-creators': 'Co-creators',
      'hint-co-creators': 'At least 2 co-creators, shares must total 100%',
      'rights-original': 'Original', 'rights-co_creation': 'Co-creation', 'rights-licensed': 'Licensed', 'rights-collection': 'Collection',
      'disputed': 'Disputed', 'dispute-btn': 'File dispute', 'dispute-reason-ph': 'Reason for dispute', 'dispute-submit': 'Submit', 'delisted': 'Delisted', 'dispute-resolved': 'Resolved', 'dispute-dismissed': 'Dismissed', 'remedy-delist': 'Delist', 'remedy-transfer': 'Transfer', 'remedy-rights_correction': 'Correct rights', 'remedy-share_adjustment': 'Adjust shares', 'drop-hint-unified': 'Drop file or folder, or click to select', 'pick-file': 'File', 'pick-folder': 'Folder', 'register-data': 'Register data', 'publish-cap': 'Publish capability', 'cap-name': 'Name', 'cap-provider': 'Provider', 'cap-base-price': 'Base price (OAS)', 'cap-published': 'Published',
      'lbl-asset-id': 'Asset ID',
      'lbl-amount': 'Amount (OAS)',
      'lbl-node-id': 'Node ID',
      'empty-assets': 'No assets yet. Go to <strong>Register</strong> to add your first.',
      'empty-portfolio': 'No holdings yet',
      'stat-assets': 'Assets',
      'stat-blocks': 'Blocks',
      'stat-watermarks': 'Watermarks',
      'lang-btn': '中',
      'card-identity': 'Your Identity',
      'no-identity': 'No identity found. Run <code>oasyce start</code> to generate your keys.',
      'id-hint': 'This is your unique identity on the Oasyce network. Every asset you register is cryptographically signed with your private key.',
      'id-backup': '&#9888; Back up <code>~/.oasyce/keys/</code> — if you lose your keys, you lose access to all your registered assets.',
      'copied': 'Copied',
      'auto-default': 'auto',
      'loading-identity': 'Loading...',
      'about-title': 'About Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'tab-overview': 'Overview',
      'tab-start': 'Quick Start',
      'tab-arch': 'Architecture',
      'tab-econ': 'Economics',
      'tab-update': 'Maintain',
      'tab-links': 'Links',
      'about-how': 'Oasyce is a decentralized protocol where AI agents autonomously register, discover, license, and settle data rights. Data owners register files and receive a cryptographic proof-of-provenance certificate (PoPc). AI agents discover data via a Recall-Rank pipeline, negotiate prices through bonding curves, and settle transactions with escrow-protected OAS tokens.',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # verify setup\n3. oasyce start           # launch node + dashboard\n4. Open http://localhost:8420',
      'about-arch': 'Core Layers:\n\u2022 Schema Registry \u2014 unified validation for data/capability/oracle/identity\n\u2022 Engine Pipeline \u2014 Scan \u2192 Classify \u2192 Metadata \u2192 PoPc Certificate \u2192 Register\n\u2022 Discovery \u2014 Recall (broad retrieval) \u2192 Rank (trust + economics) + feedback loop\n\u2022 Settlement \u2014 bonding curve pricing, escrow, share distribution\n\u2022 Access Control \u2014 L0 metadata / L1 sample / L2 compute / L3 full\n\u2022 P2P Network \u2014 Ed25519 identity, gossip sync, PoS consensus\n\u2022 Risk Engine \u2014 auto-classification (public / internal / sensitive)',
      'about-econ': 'Token: OAS\n\nPricing: Bonding curve (reserve ratio 0.35) \u2014 more buyers = higher price\nShares: Early buyers earn more (diminishing: 100% \u2192 80% \u2192 60% \u2192 40%)\nRights multiplier: original 1.0x / co_creation 0.9x / licensed 0.7x / collection 0.3x\nStaking: Validators stake OAS to produce blocks and earn rewards\nBlock reward: 4.0 OAS (mainnet), halving every ~1M blocks\nEscrow: Funds locked before execution, released after quality verification',
      'about-update': 'Update:\n  pip install --upgrade oasyce\n\nBuild from source:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\nRun tests:\n  python -m pytest tests/ -v\n\nContribute: Fork \u2192 Branch \u2192 PR (see CONTRIBUTING.md)',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Full protocol design and economics paper',
      'link-docs': 'Protocol Overview',
      'link-docs-d': 'Technical reference, API, and architecture',
      'link-github-project': 'GitHub (Project)',
      'link-github-project-d': 'Specs, docs, and roadmap',
      'link-github-engine': 'GitHub (Engine)',
      'link-github-engine-d': 'Plugin engine source code',
      'link-discord': 'Discord Community',
      'link-discord-d': 'Chat, support, and governance',
      'link-contact': 'Contact',
    },
    zh: {
      'pg-register-title': '注册数据资产',
      'pg-register-desc': '确立文件的归属权。注册后，其他代理可以发现、报价和购买访问权限。',
      'pg-trade-title': '交易',
      'pg-trade-desc': '报价并购买数据资产份额。购买即获得访问权和收益分成。',
      'pg-assets-title': '我的资产',
      'pg-assets-desc': '管理已注册的数据资产。点击任意资产查看详情。',
      'pg-agents-title': '代理协议',
      'pg-agents-desc': '在 AHRP 网络注册你的代理，发现数据提供者，执行交易。',
      'pg-network-title': '网络',
      'pg-network-desc': '节点状态与验证者信息。',
      'reg-path-ph': '文件路径',
      'drop-text': '拖拽文件到这里，或 <label for="file-pick" class="drop-link">浏览选择</label>',
      'drop-hint': '注册你的文件，在 Oasyce 网络上确立数据归属权',
      'hint-file': '已从拖入的文件自动填写',
      'hint-owner': '数据所有者。留空则默认使用你的节点 ID。',
      'hint-tags': '帮助其他代理发现你的资产。用逗号分隔关键词。',
      'optional': '可选',
      'reg-owner-ph': '所有者名称或代理 ID',
      'reg-tags-ph': '标签，用逗号分隔',
      'lbl-rights-type': '权利类型',
      'lbl-co-creators': '共创者',
      'hint-co-creators': '至少2个共创者，份额合计100%',
      'rights-original': '原创', 'rights-co_creation': '共创', 'rights-licensed': '授权转售', 'rights-collection': '个人收藏',
      'disputed': '争议中', 'dispute-btn': '发起争议', 'dispute-reason-ph': '争议原因', 'dispute-submit': '提交', 'delisted': '已下架', 'dispute-resolved': '已裁决', 'dispute-dismissed': '已驳回', 'remedy-delist': '下架', 'remedy-transfer': '转移所有权', 'remedy-rights_correction': '更正权利', 'remedy-share_adjustment': '调整份额', 'drop-hint-unified': '拖入文件或文件夹，或点击选择', 'pick-file': '文件', 'pick-folder': '文件夹', 'register-data': '注册数据', 'publish-cap': '发布能力', 'cap-name': '名称', 'cap-provider': '提供者', 'cap-base-price': '基础价格 (OAS)', 'cap-published': '已发布',
      'reg-btn': '注册',
      'buy-asset-ph': '粘贴资产 ID',
      'quote-btn': '报价',
      'buy-btn': '购买',
      'card-buy': '购买份额',
      'hint-buy-asset': '从资产页复制，或从数据创建者处获取。',
      'hint-buy-amount': '你愿意花多少 OAS。',
      'card-portfolio': '持仓',
      'card-stake': '质押',
      'stake-node-ph': '验证者节点 ID',
      'stake-btn': '质押',
      'search-ph': '按 ID 或标签搜索...',
      'card-announce': '注册代理',
      'announce-btn': '广播',
      'card-discover': '发现代理',
      'find-btn': '查找',
      'card-tx': '交易流程',
      'accept-btn': '接受并创建',
      'deliver-btn': '交付',
      'confirm-btn': '确认并结算',
      'card-node': '节点',
      'card-validators': '验证者',
      'card-watermark': '水印',
      'embed-btn': '嵌入',
      'trace-btn': '追溯',
      'lookup-btn': '查询',
      'lbl-file': '文件路径',
      'lbl-owner': '所有者',
      'lbl-tags': '标签',
      'lbl-asset-id': '资产 ID',
      'lbl-amount': '数量（OAS）',
      'lbl-node-id': '节点 ID',
      'empty-assets': '暂无资产。前往 <strong>注册</strong> 添加你的第一个资产。',
      'empty-portfolio': '暂无持仓',
      'stat-assets': '资产',
      'stat-blocks': '区块',
      'stat-watermarks': '水印',
      'lang-btn': 'En',
      'card-identity': '你的身份',
      'no-identity': '未找到密钥。运行 <code>oasyce start</code> 生成你的身份。',
      'id-hint': '这是你在 Oasyce 网络上的唯一身份。你注册的每个资产都会用你的私钥进行密码学签名。',
      'id-backup': '&#9888; 请备份 <code>~/.oasyce/keys/</code> 目录 —— 丢失密钥意味着永久失去所有已注册资产的控制权。',
      'copied': '已复制',
      'auto-default': '自动',
      'loading-identity': '加载中...',
      'about-title': '关于 Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'tab-overview': '概览',
      'tab-start': '快速开始',
      'tab-arch': '技术架构',
      'tab-econ': '经济模型',
      'tab-update': '维护更新',
      'tab-links': '链接',
      'about-how': 'Oasyce 是一个去中心化协议，AI 代理在其中自主注册、发现、许可和结算数据权利。数据所有者注册文件并获得加密来源证明证书 (PoPc)。AI 代理通过 Recall-Rank 管道发现数据，通过联合曲线协商价格，并使用托管保护的 OAS 代币进行结算。',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # 验证安装\n3. oasyce start           # 启动节点 + 仪表盘\n4. 浏览器打开 http://localhost:8420',
      'about-arch': '核心层级:\n\u2022 Schema Registry \u2014 统一验证 data/capability/oracle/identity 四种资产\n\u2022 引擎管道 \u2014 扫描 \u2192 分类 \u2192 元数据 \u2192 PoPc 证书 \u2192 注册\n\u2022 发现引擎 \u2014 Recall (广召回) \u2192 Rank (信任+经济) + 反馈循环\n\u2022 结算引擎 \u2014 联合曲线定价、托管、份额分配\n\u2022 访问控制 \u2014 L0 元数据 / L1 采样 / L2 计算 / L3 完整\n\u2022 P2P 网络 \u2014 Ed25519 身份、gossip 同步、PoS 共识\n\u2022 风险引擎 \u2014 自动分级 (public / internal / sensitive)',
      'about-econ': '代币: OAS\n\n定价: 联合曲线 (储备率 0.35) \u2014 买家越多价格越高\n份额: 早期买家获利更多 (递减: 100% \u2192 80% \u2192 60% \u2192 40%)\n权利系数: 原创 1.0x / 共创 0.9x / 授权 0.7x / 收藏 0.3x\n质押: 验证者质押 OAS 出块并获得奖励\n区块奖励: 4.0 OAS (主网)，每约 100 万块减半\n托管: 执行前锁定资金，质量验证后释放',
      'about-update': '更新:\n  pip install --upgrade oasyce\n\n从源码构建:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\n运行测试:\n  python -m pytest tests/ -v\n\n贡献: Fork \u2192 Branch \u2192 PR (详见 CONTRIBUTING.md)',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '完整协议设计与经济模型论文',
      'link-docs': '协议概览',
      'link-docs-d': '技术参考、API 与架构',
      'link-github-project': 'GitHub (项目)',
      'link-github-project-d': '规范、文档与路线图',
      'link-github-engine': 'GitHub (引擎)',
      'link-github-engine-d': '插件引擎源代码',
      'link-discord': 'Discord 社区',
      'link-discord-d': '聊天、支持与治理',
      'link-contact': '联系我们',
    }
  };

  function applyLang() {
    var t = _t[_lang];
    // Nav links
    document.querySelectorAll('.nav-link').forEach(function(el){
      el.textContent = el.getAttribute('data-'+_lang) || el.textContent;
    });
    // Lang button
    document.getElementById('lang-btn').textContent = t['lang-btn'];
    // Page titles & descs
    ['register','trade','assets','agents','network'].forEach(function(pg){
      var title = document.querySelector('#pg-'+pg+' .page-title');
      var desc = document.querySelector('#pg-'+pg+' .page-desc');
      if(title) title.textContent = t['pg-'+pg+'-title'] || title.textContent;
      if(desc) desc.textContent = t['pg-'+pg+'-desc'] || desc.textContent;
    });
    // Stat labels
    var statLabels = document.querySelectorAll('.stat-l');
    if(statLabels[0]) statLabels[0].textContent = t['stat-assets'];
    if(statLabels[1]) statLabels[1].textContent = t['stat-blocks'];
    if(statLabels[2]) statLabels[2].textContent = t['stat-watermarks'];
    // Buttons
    document.getElementById('reg-btn').textContent = t['reg-btn'];
    document.getElementById('quote-btn').textContent = t['quote-btn'];
    document.getElementById('buy-btn').textContent = t['buy-btn'];
    document.getElementById('stake-btn').textContent = t['stake-btn'];
    document.getElementById('ahrp-announce-btn').textContent = t['announce-btn'];
    document.getElementById('ahrp-find-btn').textContent = t['find-btn'];
    document.getElementById('tx-accept-btn').textContent = t['accept-btn'];
    document.getElementById('tx-deliver-btn').textContent = t['deliver-btn'];
    document.getElementById('tx-confirm-btn').textContent = t['confirm-btn'];
    document.getElementById('emb-btn').textContent = t['embed-btn'];
    document.getElementById('fp-trace-btn').textContent = t['trace-btn'];
    document.getElementById('fp-list-btn').textContent = t['lookup-btn'];
    // Placeholders
    document.getElementById('reg-path').placeholder = t['reg-path-ph'];
    document.getElementById('reg-owner').placeholder = t['reg-owner-ph'];
    document.getElementById('reg-tags').placeholder = t['reg-tags-ph'];
    document.getElementById('buy-asset').placeholder = t['buy-asset-ph'];
    document.getElementById('stake-node').placeholder = t['stake-node-ph'];
    document.getElementById('asset-search').placeholder = t['search-ph'];
    // Card titles
    var cardTitles = document.querySelectorAll('.card-title');
    var cardMap = ['card-buy','card-portfolio','card-stake','card-announce','card-discover','card-tx','card-node','','card-watermark'];
    cardTitles.forEach(function(el,i){if(cardMap[i]&&t[cardMap[i]])el.textContent=t[cardMap[i]];});
    // Field labels
    var labels = document.querySelectorAll('.field-label');


  }

  // Lang toggle
  document.getElementById('lang-btn').addEventListener('click', function(){
    _lang = _lang === 'en' ? 'zh' : 'en';
    applyLang();
  });

  // About panel — tabbed info hub for all audiences
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'<span class="about-version">'+t['about-version']+'</span></h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<div class="about-tabs">'+
        '<button class="about-tab active" data-about-tab="overview">'+t['tab-overview']+'</button>'+
        '<button class="about-tab" data-about-tab="start">'+t['tab-start']+'</button>'+
        '<button class="about-tab" data-about-tab="arch">'+t['tab-arch']+'</button>'+
        '<button class="about-tab" data-about-tab="econ">'+t['tab-econ']+'</button>'+
        '<button class="about-tab" data-about-tab="update">'+t['tab-update']+'</button>'+
        '<button class="about-tab" data-about-tab="links">'+t['tab-links']+'</button>'+
      '</div>'+
      '<div class="about-section active" data-about-section="overview">'+
        '<p>'+t['about-how']+'</p>'+
      '</div>'+
      '<div class="about-section" data-about-section="start">'+
        '<pre>'+t['about-quickstart']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="arch">'+
        '<pre>'+t['about-arch']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="econ">'+
        '<pre>'+t['about-econ']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="update">'+
        '<pre>'+t['about-update']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="links">'+
        '<ul class="about-links">'+
          '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github-project']+'</div><div class="link-desc">'+t['link-github-project-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine" target="_blank"><div><div class="link-label">'+t['link-github-engine']+'</div><div class="link-desc">'+t['link-github-engine-d']+'</div></div></a></li>'+
          '<li><a href="https://discord.gg/oasyce" target="_blank"><div><div class="link-label">'+t['link-discord']+'</div><div class="link-desc">'+t['link-discord-d']+'</div></div></a></li>'+
        '</ul>'+
        '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>'+
      '</div>';
    document.body.appendChild(overlay);
    // Tab switching
    overlay.querySelectorAll('.about-tab').forEach(function(tab){
      tab.addEventListener('click',function(){
        overlay.querySelectorAll('.about-tab').forEach(function(t){t.classList.remove('active');});
        overlay.querySelectorAll('.about-section').forEach(function(s){s.classList.remove('active');});
        tab.classList.add('active');
        var sec=overlay.querySelector('[data-about-section="'+tab.dataset.aboutTab+'"]');
        if(sec)sec.classList.add('active');
      });
    });
  });


  try{var saved=localStorage.getItem('oasyce-lang');if(saved)_lang=saved;}catch(e){}
  applyLang();

  loadStatus();loadStakes();}
    });
  });

  /* ── Modal ──────────── */
  function showModal(asset){
    var ex=document.getElementById('modal-bg');if(ex)ex.remove();
    var o=document.createElement('div');o.id='modal-bg';o.className='modal-bg';
    var tags=(asset.tags||[]).map(function(t){return'<span class="tag">'+esc(t)+'</span>';}).join(' ');
    var rightsLabels={original:'Original',co_creation:'Co-creation',licensed:'Licensed',collection:'Collection'};
    var rightsColors={original:'#4ade80',co_creation:'#60a5fa',licensed:'#facc15',collection:'#888'};
    var rt=asset.rights_type||'original';
    var rightsHtml='<div class="kv"><span class="kv-k">Rights</span><span class="kv-v" style="color:'+rightsColors[rt]+'">'+(rightsLabels[rt]||rt)+'</span></div>';
    var coHtml='';
    if(asset.co_creators&&asset.co_creators.length){coHtml='<div class="kv"><span class="kv-k">Co-creators</span><span class="kv-v">';asset.co_creators.forEach(function(c){coHtml+=esc(c.address||'—')+' ('+c.share+'%) ';});coHtml+='</span></div>';}
    var disputeHtml='';
    if(asset.disputed){disputeHtml='<div style="margin-top:8px;padding:8px;border:1px solid #f87171;border-radius:6px;"><span style="color:#f87171;font-weight:600;">⚠ Disputed</span>';if(asset.dispute_reason)disputeHtml+='<div style="font-size:12px;margin-top:4px;">Reason: '+esc(asset.dispute_reason)+'</div>';if(asset.arbitrator_candidates&&asset.arbitrator_candidates.length){disputeHtml+='<div style="font-size:12px;margin-top:4px;">Arbitrators:';asset.arbitrator_candidates.forEach(function(a){disputeHtml+=' '+(a.name||a.capability_id.slice(0,8))+'('+Math.round(a.score*100)+'%)';});disputeHtml+='</div>';}disputeHtml+='</div>';}
    else{disputeHtml='<div style="margin-top:8px;"><button class="btn btn-ghost btn-sm" onclick="showDisputeForm(\''+esc(asset.asset_id)+'\')">File dispute</button><div id="dispute-form-'+esc(asset.asset_id)+'" style="display:none;margin-top:6px;"><input type="text" id="dispute-reason-input" placeholder="Reason for dispute" style="margin-bottom:4px;"><button class="btn btn-danger btn-sm" onclick="submitDispute(\''+esc(asset.asset_id)+'\')">Submit</button></div></div>';}
    o.innerHTML='<div class="modal" onclick="event.stopPropagation()">'+
      '<button class="modal-x" onclick="document.getElementById(\'modal-bg\').remove()">&times;</button>'+
      '<h3>Asset Detail</h3>'+
      '<div class="kv"><span class="kv-k">ID</span><span class="kv-v" style="cursor:pointer;font-size:11px;" onclick="navigator.clipboard.writeText(\''+esc(asset.asset_id)+'\');toast(\'Copied\')">'+esc(asset.asset_id)+' &#128203;</span></div>'+
      '<div class="kv"><span class="kv-k">Owner</span><span class="kv-v">'+esc(asset.owner)+'</span></div>'+
      '<div class="kv"><span class="kv-k">Created</span><span class="kv-v">'+timeAgo(asset.created_at)+'</span></div>'+
      '<div class="kv"><span class="kv-k">Price</span><span class="kv-v">'+(asset.spot_price!=null?asset.spot_price+' OAS':'&mdash;')+'</span></div>'+
      rightsHtml+coHtml+
      '<div class="kv"><span class="kv-k">Tags</span><span class="kv-v">'+(tags||'&mdash;')+'</span></div>'+
      '<div style="margin-top:16px;display:flex;gap:8px;">'+
        '<input type="text" id="m-tags" value="'+(asset.tags||[]).join(', ')+'" placeholder="Edit tags...">'+
        '<button class="btn btn-ghost btn-sm" onclick="editTags(\''+esc(asset.asset_id)+'\')">Save</button>'+
      '</div>'+
      disputeHtml+
      '<button class="btn btn-danger btn-full" style="margin-top:10px;" onclick="if(confirm(\'Delete this asset?\')){deleteAsset(\''+esc(asset.asset_id)+'\');document.getElementById(\'modal-bg\').remove();}">Delete</button>'+
    '</div>';
    o.addEventListener('click',function(e){if(e.target===o)o.remove();});
    document.body.appendChild(o);
  }
  window.showDisputeForm=function(aid){var f=document.getElementById('dispute-form-'+aid);if(f)f.style.display='block';};
  window.submitDispute=async function(aid){var input=document.getElementById('dispute-reason-input');var reason=(input?input.value:'').trim();if(!reason){toast('Please enter a reason','error');return;}var r=await postApi('/api/dispute',{asset_id:aid,reason:reason});if(r&&r.ok){toast('Dispute filed');document.getElementById('modal-bg').remove();loadAssets();}else{toast(r?r.error:'Failed','error');}};

  window.editTags=async function(aid){var input=document.getElementById('m-tags');var tags=input.value.split(',').map(function(t){return t.trim();}).filter(Boolean);var r=await postApi('/api/asset/update',{asset_id:aid,tags:tags});if(r&&r.ok){toast('Tags updated');loadAssets();}else{toast(r?r.error:'Failed','error');}};
  window.deleteAsset=async function(aid){if(!confirm('Delete permanently?'))return;try{var r=await fetch('/api/asset/'+aid,{method:'DELETE'});var d=await r.json();if(d.ok){toast('Deleted');loadAssets();// ── Drop Zone ──
  var dropZone = document.getElementById('drop-zone');
  var filePick = document.getElementById('file-pick');
  var regFields = document.getElementById('reg-fields');
  var dropFileInfo = document.getElementById('drop-file-info');
  var dropText = document.getElementById('drop-text');
  var _droppedPath = '';

  function formatSize(bytes){
    if(bytes<1024)return bytes+' B';
    if(bytes<1048576)return(bytes/1024).toFixed(1)+' KB';
    return(bytes/1048576).toFixed(1)+' MB';
  }

  function handleFile(file){
    _droppedPath = file.name;
    // Try to get full path (only works in some browsers via webkitRelativePath)
    if(file.path) _droppedPath = file.path;
    else if(file.webkitRelativePath) _droppedPath = file.webkitRelativePath;

    document.getElementById('reg-path').value = _droppedPath;

    // Auto-generate tags from file extension and name
    var ext = file.name.split('.').pop().toLowerCase();
    var autoTags = [];
    if(['csv','json','xml','parquet','sqlite','db'].indexOf(ext)!==-1) autoTags.push('dataset');
    if(['jpg','jpeg','png','gif','webp','svg','bmp'].indexOf(ext)!==-1) autoTags.push('image');
    if(['mp4','mov','avi','mkv'].indexOf(ext)!==-1) autoTags.push('video');
    if(['mp3','wav','flac','ogg'].indexOf(ext)!==-1) autoTags.push('audio');
    if(['pdf','doc','docx','txt','md'].indexOf(ext)!==-1) autoTags.push('document');
    if(['py','js','ts','go','rs','java','c','cpp'].indexOf(ext)!==-1) autoTags.push('code');
    if(ext) autoTags.push(ext);
    document.getElementById('reg-tags').value = autoTags.join(', ');

    // Show file info in drop zone
    dropZone.classList.add('has-file');
    dropFileInfo.style.display = 'flex';
    dropFileInfo.innerHTML = '<div><div class="drop-file-name">'+esc(file.name)+'</div><div class="drop-file-size">'+formatSize(file.size)+'</div></div><button class="drop-file-remove" onclick="clearFile()">&times;</button>';
    dropText.style.display = 'none';
    document.querySelector('.drop-icon').style.display = 'none';
    document.querySelector('.drop-hint').style.display = 'none';

    // Show form fields
    regFields.style.display = 'block';
  }

  window.clearFile = function(){
    _droppedPath = '';
    document.getElementById('reg-path').value = '';
    document.getElementById('reg-tags').value = '';
    dropZone.classList.remove('has-file');
    dropFileInfo.style.display = 'none';
    dropFileInfo.innerHTML = '';
    dropText.style.display = '';
    document.querySelector('.drop-icon').style.display = '';
    document.querySelector('.drop-hint').style.display = '';
    regFields.style.display = 'none';
    filePick.value = '';
  };

  // Drag events
  ['dragenter','dragover'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.add('over');});
  });
  ['dragleave','drop'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.remove('over');});
  });
  dropZone.addEventListener('drop', function(e){
    var files = e.dataTransfer.files;
    if(files.length > 0) handleFile(files[0]);
  });
  dropZone.addEventListener('click', function(e){
    if(e.target.tagName !== 'BUTTON' && e.target.tagName !== 'LABEL' && !dropZone.classList.contains('has-file')){
      filePick.click();
    }
  });
  filePick.addEventListener('change', function(){
    if(this.files.length > 0) handleFile(this.files[0]);
  });

  // ── i18n ──
  var _lang = (navigator.language||'').startsWith('zh') ? 'zh' : 'en';
  var _t = {
    en: {
      'pg-register-title': 'Register a data asset',
      'pg-register-desc': 'Claim ownership of a file. Once registered, other agents can discover, quote, and purchase access rights.',
      'pg-trade-title': 'Trade',
      'pg-trade-desc': 'Quote and purchase shares in data assets. Buy to gain access rights and revenue share.',
      'pg-assets-title': 'Your Assets',
      'pg-assets-desc': 'Manage registered data assets. Click any asset for details.',
      'pg-agents-title': 'Agent Protocol',
      'pg-agents-desc': 'Register your agent on the AHRP network, discover data providers, and execute transactions.',
      'pg-network-title': 'Network',
      'pg-network-desc': 'Node status and validator information.',
      'reg-path-ph': '/path/to/your/file',
      'drop-text': 'Drag a file here, or <label for="file-pick" class="drop-link">browse</label>',
      'drop-hint': 'Register your file to claim ownership on the Oasyce network',
      'hint-file': 'Auto-filled from your dropped file',
      'hint-owner': 'Who owns this data? Defaults to your node ID if left blank.',
      'hint-tags': 'Help others find your asset. Comma-separated keywords.',
      'optional': 'optional',
      'reg-owner-ph': 'Your name or agent ID',
      'reg-tags-ph': 'medical, imaging, dicom',
      'reg-btn': 'Register',
      'buy-asset-ph': 'Paste asset ID',
      'quote-btn': 'Quote',
      'buy-btn': 'Buy',
      'card-buy': 'Buy Shares',
      'hint-buy-asset': 'Copy from the Assets tab or from the creator who shared it with you.',
      'hint-buy-amount': 'How much to spend.',
      'card-portfolio': 'Portfolio',
      'card-stake': 'Stake',
      'stake-node-ph': 'Validator node ID',
      'stake-btn': 'Stake',
      'search-ph': 'Search by ID or tag...',
      'card-announce': 'Announce Agent',
      'announce-btn': 'Announce',
      'card-discover': 'Discover Agents',
      'find-btn': 'Find',
      'card-tx': 'Transaction',
      'accept-btn': 'Accept & Create',
      'deliver-btn': 'Deliver',
      'confirm-btn': 'Confirm & Settle',
      'card-node': 'Node',
      'card-validators': 'Validators',
      'card-watermark': 'Watermark',
      'embed-btn': 'Embed',
      'trace-btn': 'Trace',
      'lookup-btn': 'Lookup',
      'lbl-file': 'File path',
      'lbl-owner': 'Owner',
      'lbl-tags': 'Tags',
      'lbl-rights-type': 'Rights type',
      'lbl-co-creators': 'Co-creators',
      'hint-co-creators': 'At least 2 co-creators, shares must total 100%',
      'rights-original': 'Original', 'rights-co_creation': 'Co-creation', 'rights-licensed': 'Licensed', 'rights-collection': 'Collection',
      'disputed': 'Disputed', 'dispute-btn': 'File dispute', 'dispute-reason-ph': 'Reason for dispute', 'dispute-submit': 'Submit', 'delisted': 'Delisted', 'dispute-resolved': 'Resolved', 'dispute-dismissed': 'Dismissed', 'remedy-delist': 'Delist', 'remedy-transfer': 'Transfer', 'remedy-rights_correction': 'Correct rights', 'remedy-share_adjustment': 'Adjust shares', 'drop-hint-unified': 'Drop file or folder, or click to select', 'pick-file': 'File', 'pick-folder': 'Folder', 'register-data': 'Register data', 'publish-cap': 'Publish capability', 'cap-name': 'Name', 'cap-provider': 'Provider', 'cap-base-price': 'Base price (OAS)', 'cap-published': 'Published',
      'lbl-asset-id': 'Asset ID',
      'lbl-amount': 'Amount (OAS)',
      'lbl-node-id': 'Node ID',
      'empty-assets': 'No assets yet. Go to <strong>Register</strong> to add your first.',
      'empty-portfolio': 'No holdings yet',
      'stat-assets': 'Assets',
      'stat-blocks': 'Blocks',
      'stat-watermarks': 'Watermarks',
      'lang-btn': '中',
      'card-identity': 'Your Identity',
      'no-identity': 'No identity found. Run <code>oasyce start</code> to generate your keys.',
      'id-hint': 'This is your unique identity on the Oasyce network. Every asset you register is cryptographically signed with your private key.',
      'id-backup': '&#9888; Back up <code>~/.oasyce/keys/</code> — if you lose your keys, you lose access to all your registered assets.',
      'copied': 'Copied',
      'auto-default': 'auto',
      'loading-identity': 'Loading...',
      'about-title': 'About Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'tab-overview': 'Overview',
      'tab-start': 'Quick Start',
      'tab-arch': 'Architecture',
      'tab-econ': 'Economics',
      'tab-update': 'Maintain',
      'tab-links': 'Links',
      'about-how': 'Oasyce is a decentralized protocol where AI agents autonomously register, discover, license, and settle data rights. Data owners register files and receive a cryptographic proof-of-provenance certificate (PoPc). AI agents discover data via a Recall-Rank pipeline, negotiate prices through bonding curves, and settle transactions with escrow-protected OAS tokens.',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # verify setup\n3. oasyce start           # launch node + dashboard\n4. Open http://localhost:8420',
      'about-arch': 'Core Layers:\n\u2022 Schema Registry \u2014 unified validation for data/capability/oracle/identity\n\u2022 Engine Pipeline \u2014 Scan \u2192 Classify \u2192 Metadata \u2192 PoPc Certificate \u2192 Register\n\u2022 Discovery \u2014 Recall (broad retrieval) \u2192 Rank (trust + economics) + feedback loop\n\u2022 Settlement \u2014 bonding curve pricing, escrow, share distribution\n\u2022 Access Control \u2014 L0 metadata / L1 sample / L2 compute / L3 full\n\u2022 P2P Network \u2014 Ed25519 identity, gossip sync, PoS consensus\n\u2022 Risk Engine \u2014 auto-classification (public / internal / sensitive)',
      'about-econ': 'Token: OAS\n\nPricing: Bonding curve (reserve ratio 0.35) \u2014 more buyers = higher price\nShares: Early buyers earn more (diminishing: 100% \u2192 80% \u2192 60% \u2192 40%)\nRights multiplier: original 1.0x / co_creation 0.9x / licensed 0.7x / collection 0.3x\nStaking: Validators stake OAS to produce blocks and earn rewards\nBlock reward: 4.0 OAS (mainnet), halving every ~1M blocks\nEscrow: Funds locked before execution, released after quality verification',
      'about-update': 'Update:\n  pip install --upgrade oasyce\n\nBuild from source:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\nRun tests:\n  python -m pytest tests/ -v\n\nContribute: Fork \u2192 Branch \u2192 PR (see CONTRIBUTING.md)',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Full protocol design and economics paper',
      'link-docs': 'Protocol Overview',
      'link-docs-d': 'Technical reference, API, and architecture',
      'link-github-project': 'GitHub (Project)',
      'link-github-project-d': 'Specs, docs, and roadmap',
      'link-github-engine': 'GitHub (Engine)',
      'link-github-engine-d': 'Plugin engine source code',
      'link-discord': 'Discord Community',
      'link-discord-d': 'Chat, support, and governance',
      'link-contact': 'Contact',
    },
    zh: {
      'pg-register-title': '注册数据资产',
      'pg-register-desc': '确立文件的归属权。注册后，其他代理可以发现、报价和购买访问权限。',
      'pg-trade-title': '交易',
      'pg-trade-desc': '报价并购买数据资产份额。购买即获得访问权和收益分成。',
      'pg-assets-title': '我的资产',
      'pg-assets-desc': '管理已注册的数据资产。点击任意资产查看详情。',
      'pg-agents-title': '代理协议',
      'pg-agents-desc': '在 AHRP 网络注册你的代理，发现数据提供者，执行交易。',
      'pg-network-title': '网络',
      'pg-network-desc': '节点状态与验证者信息。',
      'reg-path-ph': '文件路径',
      'drop-text': '拖拽文件到这里，或 <label for="file-pick" class="drop-link">浏览选择</label>',
      'drop-hint': '注册你的文件，在 Oasyce 网络上确立数据归属权',
      'hint-file': '已从拖入的文件自动填写',
      'hint-owner': '数据所有者。留空则默认使用你的节点 ID。',
      'hint-tags': '帮助其他代理发现你的资产。用逗号分隔关键词。',
      'optional': '可选',
      'reg-owner-ph': '所有者名称或代理 ID',
      'reg-tags-ph': '标签，用逗号分隔',
      'lbl-rights-type': '权利类型',
      'lbl-co-creators': '共创者',
      'hint-co-creators': '至少2个共创者，份额合计100%',
      'rights-original': '原创', 'rights-co_creation': '共创', 'rights-licensed': '授权转售', 'rights-collection': '个人收藏',
      'disputed': '争议中', 'dispute-btn': '发起争议', 'dispute-reason-ph': '争议原因', 'dispute-submit': '提交', 'delisted': '已下架', 'dispute-resolved': '已裁决', 'dispute-dismissed': '已驳回', 'remedy-delist': '下架', 'remedy-transfer': '转移所有权', 'remedy-rights_correction': '更正权利', 'remedy-share_adjustment': '调整份额', 'drop-hint-unified': '拖入文件或文件夹，或点击选择', 'pick-file': '文件', 'pick-folder': '文件夹', 'register-data': '注册数据', 'publish-cap': '发布能力', 'cap-name': '名称', 'cap-provider': '提供者', 'cap-base-price': '基础价格 (OAS)', 'cap-published': '已发布',
      'reg-btn': '注册',
      'buy-asset-ph': '粘贴资产 ID',
      'quote-btn': '报价',
      'buy-btn': '购买',
      'card-buy': '购买份额',
      'hint-buy-asset': '从资产页复制，或从数据创建者处获取。',
      'hint-buy-amount': '你愿意花多少 OAS。',
      'card-portfolio': '持仓',
      'card-stake': '质押',
      'stake-node-ph': '验证者节点 ID',
      'stake-btn': '质押',
      'search-ph': '按 ID 或标签搜索...',
      'card-announce': '注册代理',
      'announce-btn': '广播',
      'card-discover': '发现代理',
      'find-btn': '查找',
      'card-tx': '交易流程',
      'accept-btn': '接受并创建',
      'deliver-btn': '交付',
      'confirm-btn': '确认并结算',
      'card-node': '节点',
      'card-validators': '验证者',
      'card-watermark': '水印',
      'embed-btn': '嵌入',
      'trace-btn': '追溯',
      'lookup-btn': '查询',
      'lbl-file': '文件路径',
      'lbl-owner': '所有者',
      'lbl-tags': '标签',
      'lbl-asset-id': '资产 ID',
      'lbl-amount': '数量（OAS）',
      'lbl-node-id': '节点 ID',
      'empty-assets': '暂无资产。前往 <strong>注册</strong> 添加你的第一个资产。',
      'empty-portfolio': '暂无持仓',
      'stat-assets': '资产',
      'stat-blocks': '区块',
      'stat-watermarks': '水印',
      'lang-btn': 'En',
      'card-identity': '你的身份',
      'no-identity': '未找到密钥。运行 <code>oasyce start</code> 生成你的身份。',
      'id-hint': '这是你在 Oasyce 网络上的唯一身份。你注册的每个资产都会用你的私钥进行密码学签名。',
      'id-backup': '&#9888; 请备份 <code>~/.oasyce/keys/</code> 目录 —— 丢失密钥意味着永久失去所有已注册资产的控制权。',
      'copied': '已复制',
      'auto-default': '自动',
      'loading-identity': '加载中...',
      'about-title': '关于 Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'tab-overview': '概览',
      'tab-start': '快速开始',
      'tab-arch': '技术架构',
      'tab-econ': '经济模型',
      'tab-update': '维护更新',
      'tab-links': '链接',
      'about-how': 'Oasyce 是一个去中心化协议，AI 代理在其中自主注册、发现、许可和结算数据权利。数据所有者注册文件并获得加密来源证明证书 (PoPc)。AI 代理通过 Recall-Rank 管道发现数据，通过联合曲线协商价格，并使用托管保护的 OAS 代币进行结算。',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # 验证安装\n3. oasyce start           # 启动节点 + 仪表盘\n4. 浏览器打开 http://localhost:8420',
      'about-arch': '核心层级:\n\u2022 Schema Registry \u2014 统一验证 data/capability/oracle/identity 四种资产\n\u2022 引擎管道 \u2014 扫描 \u2192 分类 \u2192 元数据 \u2192 PoPc 证书 \u2192 注册\n\u2022 发现引擎 \u2014 Recall (广召回) \u2192 Rank (信任+经济) + 反馈循环\n\u2022 结算引擎 \u2014 联合曲线定价、托管、份额分配\n\u2022 访问控制 \u2014 L0 元数据 / L1 采样 / L2 计算 / L3 完整\n\u2022 P2P 网络 \u2014 Ed25519 身份、gossip 同步、PoS 共识\n\u2022 风险引擎 \u2014 自动分级 (public / internal / sensitive)',
      'about-econ': '代币: OAS\n\n定价: 联合曲线 (储备率 0.35) \u2014 买家越多价格越高\n份额: 早期买家获利更多 (递减: 100% \u2192 80% \u2192 60% \u2192 40%)\n权利系数: 原创 1.0x / 共创 0.9x / 授权 0.7x / 收藏 0.3x\n质押: 验证者质押 OAS 出块并获得奖励\n区块奖励: 4.0 OAS (主网)，每约 100 万块减半\n托管: 执行前锁定资金，质量验证后释放',
      'about-update': '更新:\n  pip install --upgrade oasyce\n\n从源码构建:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\n运行测试:\n  python -m pytest tests/ -v\n\n贡献: Fork \u2192 Branch \u2192 PR (详见 CONTRIBUTING.md)',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '完整协议设计与经济模型论文',
      'link-docs': '协议概览',
      'link-docs-d': '技术参考、API 与架构',
      'link-github-project': 'GitHub (项目)',
      'link-github-project-d': '规范、文档与路线图',
      'link-github-engine': 'GitHub (引擎)',
      'link-github-engine-d': '插件引擎源代码',
      'link-discord': 'Discord 社区',
      'link-discord-d': '聊天、支持与治理',
      'link-contact': '联系我们',
    }
  };

  function applyLang() {
    var t = _t[_lang];
    // Nav links
    document.querySelectorAll('.nav-link').forEach(function(el){
      el.textContent = el.getAttribute('data-'+_lang) || el.textContent;
    });
    // Lang button
    document.getElementById('lang-btn').textContent = t['lang-btn'];
    // Page titles & descs
    ['register','trade','assets','agents','network'].forEach(function(pg){
      var title = document.querySelector('#pg-'+pg+' .page-title');
      var desc = document.querySelector('#pg-'+pg+' .page-desc');
      if(title) title.textContent = t['pg-'+pg+'-title'] || title.textContent;
      if(desc) desc.textContent = t['pg-'+pg+'-desc'] || desc.textContent;
    });
    // Stat labels
    var statLabels = document.querySelectorAll('.stat-l');
    if(statLabels[0]) statLabels[0].textContent = t['stat-assets'];
    if(statLabels[1]) statLabels[1].textContent = t['stat-blocks'];
    if(statLabels[2]) statLabels[2].textContent = t['stat-watermarks'];
    // Buttons
    document.getElementById('reg-btn').textContent = t['reg-btn'];
    document.getElementById('quote-btn').textContent = t['quote-btn'];
    document.getElementById('buy-btn').textContent = t['buy-btn'];
    document.getElementById('stake-btn').textContent = t['stake-btn'];
    document.getElementById('ahrp-announce-btn').textContent = t['announce-btn'];
    document.getElementById('ahrp-find-btn').textContent = t['find-btn'];
    document.getElementById('tx-accept-btn').textContent = t['accept-btn'];
    document.getElementById('tx-deliver-btn').textContent = t['deliver-btn'];
    document.getElementById('tx-confirm-btn').textContent = t['confirm-btn'];
    document.getElementById('emb-btn').textContent = t['embed-btn'];
    document.getElementById('fp-trace-btn').textContent = t['trace-btn'];
    document.getElementById('fp-list-btn').textContent = t['lookup-btn'];
    // Placeholders
    document.getElementById('reg-path').placeholder = t['reg-path-ph'];
    document.getElementById('reg-owner').placeholder = t['reg-owner-ph'];
    document.getElementById('reg-tags').placeholder = t['reg-tags-ph'];
    document.getElementById('buy-asset').placeholder = t['buy-asset-ph'];
    document.getElementById('stake-node').placeholder = t['stake-node-ph'];
    document.getElementById('asset-search').placeholder = t['search-ph'];
    // Card titles
    var cardTitles = document.querySelectorAll('.card-title');
    var cardMap = ['card-buy','card-portfolio','card-stake','card-announce','card-discover','card-tx','card-node','','card-watermark'];
    cardTitles.forEach(function(el,i){if(cardMap[i]&&t[cardMap[i]])el.textContent=t[cardMap[i]];});
    // Field labels
    var labels = document.querySelectorAll('.field-label');


  }

  // Lang toggle
  document.getElementById('lang-btn').addEventListener('click', function(){
    _lang = _lang === 'en' ? 'zh' : 'en';
    applyLang();
  });

  // About panel — tabbed info hub for all audiences
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'<span class="about-version">'+t['about-version']+'</span></h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<div class="about-tabs">'+
        '<button class="about-tab active" data-about-tab="overview">'+t['tab-overview']+'</button>'+
        '<button class="about-tab" data-about-tab="start">'+t['tab-start']+'</button>'+
        '<button class="about-tab" data-about-tab="arch">'+t['tab-arch']+'</button>'+
        '<button class="about-tab" data-about-tab="econ">'+t['tab-econ']+'</button>'+
        '<button class="about-tab" data-about-tab="update">'+t['tab-update']+'</button>'+
        '<button class="about-tab" data-about-tab="links">'+t['tab-links']+'</button>'+
      '</div>'+
      '<div class="about-section active" data-about-section="overview">'+
        '<p>'+t['about-how']+'</p>'+
      '</div>'+
      '<div class="about-section" data-about-section="start">'+
        '<pre>'+t['about-quickstart']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="arch">'+
        '<pre>'+t['about-arch']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="econ">'+
        '<pre>'+t['about-econ']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="update">'+
        '<pre>'+t['about-update']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="links">'+
        '<ul class="about-links">'+
          '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github-project']+'</div><div class="link-desc">'+t['link-github-project-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine" target="_blank"><div><div class="link-label">'+t['link-github-engine']+'</div><div class="link-desc">'+t['link-github-engine-d']+'</div></div></a></li>'+
          '<li><a href="https://discord.gg/oasyce" target="_blank"><div><div class="link-label">'+t['link-discord']+'</div><div class="link-desc">'+t['link-discord-d']+'</div></div></a></li>'+
        '</ul>'+
        '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>'+
      '</div>';
    document.body.appendChild(overlay);
    // Tab switching
    overlay.querySelectorAll('.about-tab').forEach(function(tab){
      tab.addEventListener('click',function(){
        overlay.querySelectorAll('.about-tab').forEach(function(t){t.classList.remove('active');});
        overlay.querySelectorAll('.about-section').forEach(function(s){s.classList.remove('active');});
        tab.classList.add('active');
        var sec=overlay.querySelector('[data-about-section="'+tab.dataset.aboutTab+'"]');
        if(sec)sec.classList.add('active');
      });
    });
  });


  try{var saved=localStorage.getItem('oasyce-lang');if(saved)_lang=saved;}catch(e){}
  applyLang();

  loadStatus();}else{toast(d.error||'Failed','error');}}catch(e){toast(e.message,'error');}};

  /* ── Status ──────────── */
  async function loadStatus(){
    var d=await api('/api/status');if(!d)return;
    document.getElementById('stat-assets').textContent=d.total_assets;
    document.getElementById('stat-blocks').textContent=d.total_blocks;
    document.getElementById('stat-dists').textContent=d.total_distributions;
    var ni=document.getElementById('net-info');
    ni.innerHTML='<span class="ng-k">Node ID</span><span class="ng-v">'+esc(d.node_id)+'</span>'+
      '<span class="ng-k">Address</span><span class="ng-v">'+esc(d.host)+':'+esc(d.port)+'</span>'+
      '<span class="ng-k">Chain height</span><span class="ng-v">'+esc(d.chain_height)+'</span>';
  }

  /* ── Assets + Pagination ──────────── */
  var _all=[],_page=1,_perPage=15;
  async function loadAssets(){_all=await api('/api/assets')||[];_page=1;renderPage();}
  function renderPage(){
    var q=(document.getElementById('asset-search').value||'').toLowerCase();
    var filtered=q?_all.filter(function(a){return(a.asset_id||'').toLowerCase().indexOf(q)!==-1||(a.tags||[]).some(function(t){return t.toLowerCase().indexOf(q)!==-1;});}):_all;
    var total=filtered.length;
    var pages=Math.max(1,Math.ceil(total/_perPage));
    if(_page>pages)_page=pages;
    var start=(_page-1)*_perPage;
    var slice=filtered.slice(start,start+_perPage);
    var c=document.getElementById('assets-list');
    if(!slice.length){c.innerHTML='<div class="empty">'+(q?'No matches':'No assets yet. Go to <strong>Register</strong> to add your first.')+'</div>';document.getElementById('pager').innerHTML='';return;}
    var h='';
    slice.forEach(function(a){
      var tags=(a.tags||[]).map(function(t){return'<span class="tag">'+esc(t)+'</span>';}).join('');
      var rightsLabels={original:'Original',co_creation:'Co-creation',licensed:'Licensed',collection:'Collection'};
      var rightsColors={original:'#4ade80',co_creation:'#60a5fa',licensed:'#facc15',collection:'#888'};
      var rt=a.rights_type||'original';
      var rBadge='<span class="tag" style="color:'+rightsColors[rt]+';border-color:'+rightsColors[rt]+'">'+(rightsLabels[rt]||rt)+'</span>';
      var dBadge=a.disputed?'<span class="tag" style="color:#f87171;border-color:#f87171">Disputed</span>':'';
      h+='<div class="a-row" onclick=\'showD('+JSON.stringify(a).replace(/\x27/g,"&#39;")+')\'>'+
        '<div class="a-info"><div class="a-id">'+esc(trunc(a.asset_id,32))+' '+rBadge+dBadge+'</div><div class="a-meta">'+esc(a.owner)+' &middot; '+timeAgo(a.created_at)+(tags?' &middot; '+tags:'')+'</div></div>'+
        '<div class="a-side">'+(a.spot_price!=null?'<span class="a-price">'+a.spot_price+'</span>':'')+
        '<button class="a-del" title="Delete" onclick="event.stopPropagation();deleteAsset(\''+esc(a.asset_id)+'\')">&times;</button></div></div>';
    });
    c.innerHTML=h;
    // Pager
    var pg=document.getElementById('pager');
    if(pages<=1){pg.innerHTML='<span>'+total+' asset'+(total!==1?'s':'')+'</span><span></span>';return;}
    var ph='<span>'+start+1+'&ndash;'+Math.min(start+_perPage,total)+' of '+total+'</span><div class="pager-btns">';
    ph+='<button class="pager-btn" onclick="goPage('+(Math.max(1,_page-1))+')">&lsaquo;</button>';
    var lo=Math.max(1,_page-2),hi=Math.min(pages,_page+2);
    for(var i=lo;i<=hi;i++){ph+='<button class="pager-btn'+(i===_page?' active':'')+'" onclick="goPage('+i+')">'+i+'</button>';}
    ph+='<button class="pager-btn" onclick="goPage('+(Math.min(pages,_page+1))+')">&rsaquo;</button></div>';
    pg.innerHTML=ph;
  }
  window.goPage=function(p){_page=p;renderPage();window.scrollTo(0,0);};
  window.showD=function(a){showModal(a);};
  document.getElementById('asset-search').addEventListener('input',function(){_page=1;renderPage();});

  /* ── Register ──────────── */
  /* ── Rights type toggle ──────────── */
  var rightsSelect=document.getElementById('reg-rights-type');
  var coSection=document.getElementById('co-creators-section');
  var coList=document.getElementById('co-creators-list');
  if(rightsSelect){
    rightsSelect.addEventListener('change',function(){
      coSection.style.display=this.value==='co_creation'?'block':'none';
      if(this.value==='co_creation'&&coList.children.length===0){addCoCreatorRow();addCoCreatorRow();}
    });
  }
  function addCoCreatorRow(){
    var row=document.createElement('div');row.className='row';row.style.marginBottom='4px';
    row.innerHTML='<input type="text" class="cc-addr" placeholder="Address" style="flex:2;">'+
      '<input type="number" class="cc-share" placeholder="%" style="flex:1;max-width:80px;" value="50">'+
      '<button class="btn btn-ghost btn-sm cc-remove" type="button">&times;</button>';
    row.querySelector('.cc-remove').addEventListener('click',function(){row.remove();});
    coList.appendChild(row);
  }
  var addCCBtn=document.getElementById('add-co-creator-btn');
  if(addCCBtn)addCCBtn.addEventListener('click',function(){addCoCreatorRow();});

  document.getElementById('reg-btn').addEventListener('click',async function(){var btn=this;btn.textContent='Registering...';btn.disabled=true;var fp=document.getElementById('reg-path').value.trim();var owner=document.getElementById('reg-owner').value.trim();var tags=document.getElementById('reg-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean);var rightsType=(document.getElementById('reg-rights-type')||{}).value||'original';var coCreators=null;if(rightsType==='co_creation'){coCreators=[];var rows=document.querySelectorAll('#co-creators-list .row');rows.forEach(function(r){var addr=r.querySelector('.cc-addr').value.trim();var share=parseFloat(r.querySelector('.cc-share').value)||0;if(addr)coCreators.push({address:addr,share:share});});}var div=document.getElementById('reg-result');try{var r=await postApi('/api/register',{file_path:fp,owner:owner||undefined,tags:tags,rights_type:rightsType,co_creators:coCreators});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Asset ID</span><span class="kv-v" style="font-size:11px;">'+esc(r.asset_id)+'</span></div></div>';toast('Asset registered');_all=[];// ── Drop Zone ──
  var dropZone = document.getElementById('drop-zone');
  var filePick = document.getElementById('file-pick');
  var regFields = document.getElementById('reg-fields');
  var dropFileInfo = document.getElementById('drop-file-info');
  var dropText = document.getElementById('drop-text');
  var _droppedPath = '';

  function formatSize(bytes){
    if(bytes<1024)return bytes+' B';
    if(bytes<1048576)return(bytes/1024).toFixed(1)+' KB';
    return(bytes/1048576).toFixed(1)+' MB';
  }

  function handleFile(file){
    _droppedPath = file.name;
    // Try to get full path (only works in some browsers via webkitRelativePath)
    if(file.path) _droppedPath = file.path;
    else if(file.webkitRelativePath) _droppedPath = file.webkitRelativePath;

    document.getElementById('reg-path').value = _droppedPath;

    // Auto-generate tags from file extension and name
    var ext = file.name.split('.').pop().toLowerCase();
    var autoTags = [];
    if(['csv','json','xml','parquet','sqlite','db'].indexOf(ext)!==-1) autoTags.push('dataset');
    if(['jpg','jpeg','png','gif','webp','svg','bmp'].indexOf(ext)!==-1) autoTags.push('image');
    if(['mp4','mov','avi','mkv'].indexOf(ext)!==-1) autoTags.push('video');
    if(['mp3','wav','flac','ogg'].indexOf(ext)!==-1) autoTags.push('audio');
    if(['pdf','doc','docx','txt','md'].indexOf(ext)!==-1) autoTags.push('document');
    if(['py','js','ts','go','rs','java','c','cpp'].indexOf(ext)!==-1) autoTags.push('code');
    if(ext) autoTags.push(ext);
    document.getElementById('reg-tags').value = autoTags.join(', ');

    // Show file info in drop zone
    dropZone.classList.add('has-file');
    dropFileInfo.style.display = 'flex';
    dropFileInfo.innerHTML = '<div><div class="drop-file-name">'+esc(file.name)+'</div><div class="drop-file-size">'+formatSize(file.size)+'</div></div><button class="drop-file-remove" onclick="clearFile()">&times;</button>';
    dropText.style.display = 'none';
    document.querySelector('.drop-icon').style.display = 'none';
    document.querySelector('.drop-hint').style.display = 'none';

    // Show form fields
    regFields.style.display = 'block';
  }

  window.clearFile = function(){
    _droppedPath = '';
    document.getElementById('reg-path').value = '';
    document.getElementById('reg-tags').value = '';
    dropZone.classList.remove('has-file');
    dropFileInfo.style.display = 'none';
    dropFileInfo.innerHTML = '';
    dropText.style.display = '';
    document.querySelector('.drop-icon').style.display = '';
    document.querySelector('.drop-hint').style.display = '';
    regFields.style.display = 'none';
    filePick.value = '';
  };

  // Drag events
  ['dragenter','dragover'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.add('over');});
  });
  ['dragleave','drop'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.remove('over');});
  });
  dropZone.addEventListener('drop', function(e){
    var files = e.dataTransfer.files;
    if(files.length > 0) handleFile(files[0]);
  });
  dropZone.addEventListener('click', function(e){
    if(e.target.tagName !== 'BUTTON' && e.target.tagName !== 'LABEL' && !dropZone.classList.contains('has-file')){
      filePick.click();
    }
  });
  filePick.addEventListener('change', function(){
    if(this.files.length > 0) handleFile(this.files[0]);
  });

  // ── i18n ──
  var _lang = (navigator.language||'').startsWith('zh') ? 'zh' : 'en';
  var _t = {
    en: {
      'pg-register-title': 'Register a data asset',
      'pg-register-desc': 'Claim ownership of a file. Once registered, other agents can discover, quote, and purchase access rights.',
      'pg-trade-title': 'Trade',
      'pg-trade-desc': 'Quote and purchase shares in data assets. Buy to gain access rights and revenue share.',
      'pg-assets-title': 'Your Assets',
      'pg-assets-desc': 'Manage registered data assets. Click any asset for details.',
      'pg-agents-title': 'Agent Protocol',
      'pg-agents-desc': 'Register your agent on the AHRP network, discover data providers, and execute transactions.',
      'pg-network-title': 'Network',
      'pg-network-desc': 'Node status and validator information.',
      'reg-path-ph': '/path/to/your/file',
      'drop-text': 'Drag a file here, or <label for="file-pick" class="drop-link">browse</label>',
      'drop-hint': 'Register your file to claim ownership on the Oasyce network',
      'hint-file': 'Auto-filled from your dropped file',
      'hint-owner': 'Who owns this data? Defaults to your node ID if left blank.',
      'hint-tags': 'Help others find your asset. Comma-separated keywords.',
      'optional': 'optional',
      'reg-owner-ph': 'Your name or agent ID',
      'reg-tags-ph': 'medical, imaging, dicom',
      'reg-btn': 'Register',
      'buy-asset-ph': 'Paste asset ID',
      'quote-btn': 'Quote',
      'buy-btn': 'Buy',
      'card-buy': 'Buy Shares',
      'hint-buy-asset': 'Copy from the Assets tab or from the creator who shared it with you.',
      'hint-buy-amount': 'How much to spend.',
      'card-portfolio': 'Portfolio',
      'card-stake': 'Stake',
      'stake-node-ph': 'Validator node ID',
      'stake-btn': 'Stake',
      'search-ph': 'Search by ID or tag...',
      'card-announce': 'Announce Agent',
      'announce-btn': 'Announce',
      'card-discover': 'Discover Agents',
      'find-btn': 'Find',
      'card-tx': 'Transaction',
      'accept-btn': 'Accept & Create',
      'deliver-btn': 'Deliver',
      'confirm-btn': 'Confirm & Settle',
      'card-node': 'Node',
      'card-validators': 'Validators',
      'card-watermark': 'Watermark',
      'embed-btn': 'Embed',
      'trace-btn': 'Trace',
      'lookup-btn': 'Lookup',
      'lbl-file': 'File path',
      'lbl-owner': 'Owner',
      'lbl-tags': 'Tags',
      'lbl-rights-type': 'Rights type',
      'lbl-co-creators': 'Co-creators',
      'hint-co-creators': 'At least 2 co-creators, shares must total 100%',
      'rights-original': 'Original', 'rights-co_creation': 'Co-creation', 'rights-licensed': 'Licensed', 'rights-collection': 'Collection',
      'disputed': 'Disputed', 'dispute-btn': 'File dispute', 'dispute-reason-ph': 'Reason for dispute', 'dispute-submit': 'Submit', 'delisted': 'Delisted', 'dispute-resolved': 'Resolved', 'dispute-dismissed': 'Dismissed', 'remedy-delist': 'Delist', 'remedy-transfer': 'Transfer', 'remedy-rights_correction': 'Correct rights', 'remedy-share_adjustment': 'Adjust shares', 'drop-hint-unified': 'Drop file or folder, or click to select', 'pick-file': 'File', 'pick-folder': 'Folder', 'register-data': 'Register data', 'publish-cap': 'Publish capability', 'cap-name': 'Name', 'cap-provider': 'Provider', 'cap-base-price': 'Base price (OAS)', 'cap-published': 'Published',
      'lbl-asset-id': 'Asset ID',
      'lbl-amount': 'Amount (OAS)',
      'lbl-node-id': 'Node ID',
      'empty-assets': 'No assets yet. Go to <strong>Register</strong> to add your first.',
      'empty-portfolio': 'No holdings yet',
      'stat-assets': 'Assets',
      'stat-blocks': 'Blocks',
      'stat-watermarks': 'Watermarks',
      'lang-btn': '中',
      'card-identity': 'Your Identity',
      'no-identity': 'No identity found. Run <code>oasyce start</code> to generate your keys.',
      'id-hint': 'This is your unique identity on the Oasyce network. Every asset you register is cryptographically signed with your private key.',
      'id-backup': '&#9888; Back up <code>~/.oasyce/keys/</code> — if you lose your keys, you lose access to all your registered assets.',
      'copied': 'Copied',
      'auto-default': 'auto',
      'loading-identity': 'Loading...',
      'about-title': 'About Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'tab-overview': 'Overview',
      'tab-start': 'Quick Start',
      'tab-arch': 'Architecture',
      'tab-econ': 'Economics',
      'tab-update': 'Maintain',
      'tab-links': 'Links',
      'about-how': 'Oasyce is a decentralized protocol where AI agents autonomously register, discover, license, and settle data rights. Data owners register files and receive a cryptographic proof-of-provenance certificate (PoPc). AI agents discover data via a Recall-Rank pipeline, negotiate prices through bonding curves, and settle transactions with escrow-protected OAS tokens.',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # verify setup\n3. oasyce start           # launch node + dashboard\n4. Open http://localhost:8420',
      'about-arch': 'Core Layers:\n\u2022 Schema Registry \u2014 unified validation for data/capability/oracle/identity\n\u2022 Engine Pipeline \u2014 Scan \u2192 Classify \u2192 Metadata \u2192 PoPc Certificate \u2192 Register\n\u2022 Discovery \u2014 Recall (broad retrieval) \u2192 Rank (trust + economics) + feedback loop\n\u2022 Settlement \u2014 bonding curve pricing, escrow, share distribution\n\u2022 Access Control \u2014 L0 metadata / L1 sample / L2 compute / L3 full\n\u2022 P2P Network \u2014 Ed25519 identity, gossip sync, PoS consensus\n\u2022 Risk Engine \u2014 auto-classification (public / internal / sensitive)',
      'about-econ': 'Token: OAS\n\nPricing: Bonding curve (reserve ratio 0.35) \u2014 more buyers = higher price\nShares: Early buyers earn more (diminishing: 100% \u2192 80% \u2192 60% \u2192 40%)\nRights multiplier: original 1.0x / co_creation 0.9x / licensed 0.7x / collection 0.3x\nStaking: Validators stake OAS to produce blocks and earn rewards\nBlock reward: 4.0 OAS (mainnet), halving every ~1M blocks\nEscrow: Funds locked before execution, released after quality verification',
      'about-update': 'Update:\n  pip install --upgrade oasyce\n\nBuild from source:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\nRun tests:\n  python -m pytest tests/ -v\n\nContribute: Fork \u2192 Branch \u2192 PR (see CONTRIBUTING.md)',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Full protocol design and economics paper',
      'link-docs': 'Protocol Overview',
      'link-docs-d': 'Technical reference, API, and architecture',
      'link-github-project': 'GitHub (Project)',
      'link-github-project-d': 'Specs, docs, and roadmap',
      'link-github-engine': 'GitHub (Engine)',
      'link-github-engine-d': 'Plugin engine source code',
      'link-discord': 'Discord Community',
      'link-discord-d': 'Chat, support, and governance',
      'link-contact': 'Contact',
    },
    zh: {
      'pg-register-title': '注册数据资产',
      'pg-register-desc': '确立文件的归属权。注册后，其他代理可以发现、报价和购买访问权限。',
      'pg-trade-title': '交易',
      'pg-trade-desc': '报价并购买数据资产份额。购买即获得访问权和收益分成。',
      'pg-assets-title': '我的资产',
      'pg-assets-desc': '管理已注册的数据资产。点击任意资产查看详情。',
      'pg-agents-title': '代理协议',
      'pg-agents-desc': '在 AHRP 网络注册你的代理，发现数据提供者，执行交易。',
      'pg-network-title': '网络',
      'pg-network-desc': '节点状态与验证者信息。',
      'reg-path-ph': '文件路径',
      'drop-text': '拖拽文件到这里，或 <label for="file-pick" class="drop-link">浏览选择</label>',
      'drop-hint': '注册你的文件，在 Oasyce 网络上确立数据归属权',
      'hint-file': '已从拖入的文件自动填写',
      'hint-owner': '数据所有者。留空则默认使用你的节点 ID。',
      'hint-tags': '帮助其他代理发现你的资产。用逗号分隔关键词。',
      'optional': '可选',
      'reg-owner-ph': '所有者名称或代理 ID',
      'reg-tags-ph': '标签，用逗号分隔',
      'lbl-rights-type': '权利类型',
      'lbl-co-creators': '共创者',
      'hint-co-creators': '至少2个共创者，份额合计100%',
      'rights-original': '原创', 'rights-co_creation': '共创', 'rights-licensed': '授权转售', 'rights-collection': '个人收藏',
      'disputed': '争议中', 'dispute-btn': '发起争议', 'dispute-reason-ph': '争议原因', 'dispute-submit': '提交', 'delisted': '已下架', 'dispute-resolved': '已裁决', 'dispute-dismissed': '已驳回', 'remedy-delist': '下架', 'remedy-transfer': '转移所有权', 'remedy-rights_correction': '更正权利', 'remedy-share_adjustment': '调整份额', 'drop-hint-unified': '拖入文件或文件夹，或点击选择', 'pick-file': '文件', 'pick-folder': '文件夹', 'register-data': '注册数据', 'publish-cap': '发布能力', 'cap-name': '名称', 'cap-provider': '提供者', 'cap-base-price': '基础价格 (OAS)', 'cap-published': '已发布',
      'reg-btn': '注册',
      'buy-asset-ph': '粘贴资产 ID',
      'quote-btn': '报价',
      'buy-btn': '购买',
      'card-buy': '购买份额',
      'hint-buy-asset': '从资产页复制，或从数据创建者处获取。',
      'hint-buy-amount': '你愿意花多少 OAS。',
      'card-portfolio': '持仓',
      'card-stake': '质押',
      'stake-node-ph': '验证者节点 ID',
      'stake-btn': '质押',
      'search-ph': '按 ID 或标签搜索...',
      'card-announce': '注册代理',
      'announce-btn': '广播',
      'card-discover': '发现代理',
      'find-btn': '查找',
      'card-tx': '交易流程',
      'accept-btn': '接受并创建',
      'deliver-btn': '交付',
      'confirm-btn': '确认并结算',
      'card-node': '节点',
      'card-validators': '验证者',
      'card-watermark': '水印',
      'embed-btn': '嵌入',
      'trace-btn': '追溯',
      'lookup-btn': '查询',
      'lbl-file': '文件路径',
      'lbl-owner': '所有者',
      'lbl-tags': '标签',
      'lbl-asset-id': '资产 ID',
      'lbl-amount': '数量（OAS）',
      'lbl-node-id': '节点 ID',
      'empty-assets': '暂无资产。前往 <strong>注册</strong> 添加你的第一个资产。',
      'empty-portfolio': '暂无持仓',
      'stat-assets': '资产',
      'stat-blocks': '区块',
      'stat-watermarks': '水印',
      'lang-btn': 'En',
      'card-identity': '你的身份',
      'no-identity': '未找到密钥。运行 <code>oasyce start</code> 生成你的身份。',
      'id-hint': '这是你在 Oasyce 网络上的唯一身份。你注册的每个资产都会用你的私钥进行密码学签名。',
      'id-backup': '&#9888; 请备份 <code>~/.oasyce/keys/</code> 目录 —— 丢失密钥意味着永久失去所有已注册资产的控制权。',
      'copied': '已复制',
      'auto-default': '自动',
      'loading-identity': '加载中...',
      'about-title': '关于 Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'tab-overview': '概览',
      'tab-start': '快速开始',
      'tab-arch': '技术架构',
      'tab-econ': '经济模型',
      'tab-update': '维护更新',
      'tab-links': '链接',
      'about-how': 'Oasyce 是一个去中心化协议，AI 代理在其中自主注册、发现、许可和结算数据权利。数据所有者注册文件并获得加密来源证明证书 (PoPc)。AI 代理通过 Recall-Rank 管道发现数据，通过联合曲线协商价格，并使用托管保护的 OAS 代币进行结算。',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # 验证安装\n3. oasyce start           # 启动节点 + 仪表盘\n4. 浏览器打开 http://localhost:8420',
      'about-arch': '核心层级:\n\u2022 Schema Registry \u2014 统一验证 data/capability/oracle/identity 四种资产\n\u2022 引擎管道 \u2014 扫描 \u2192 分类 \u2192 元数据 \u2192 PoPc 证书 \u2192 注册\n\u2022 发现引擎 \u2014 Recall (广召回) \u2192 Rank (信任+经济) + 反馈循环\n\u2022 结算引擎 \u2014 联合曲线定价、托管、份额分配\n\u2022 访问控制 \u2014 L0 元数据 / L1 采样 / L2 计算 / L3 完整\n\u2022 P2P 网络 \u2014 Ed25519 身份、gossip 同步、PoS 共识\n\u2022 风险引擎 \u2014 自动分级 (public / internal / sensitive)',
      'about-econ': '代币: OAS\n\n定价: 联合曲线 (储备率 0.35) \u2014 买家越多价格越高\n份额: 早期买家获利更多 (递减: 100% \u2192 80% \u2192 60% \u2192 40%)\n权利系数: 原创 1.0x / 共创 0.9x / 授权 0.7x / 收藏 0.3x\n质押: 验证者质押 OAS 出块并获得奖励\n区块奖励: 4.0 OAS (主网)，每约 100 万块减半\n托管: 执行前锁定资金，质量验证后释放',
      'about-update': '更新:\n  pip install --upgrade oasyce\n\n从源码构建:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\n运行测试:\n  python -m pytest tests/ -v\n\n贡献: Fork \u2192 Branch \u2192 PR (详见 CONTRIBUTING.md)',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '完整协议设计与经济模型论文',
      'link-docs': '协议概览',
      'link-docs-d': '技术参考、API 与架构',
      'link-github-project': 'GitHub (项目)',
      'link-github-project-d': '规范、文档与路线图',
      'link-github-engine': 'GitHub (引擎)',
      'link-github-engine-d': '插件引擎源代码',
      'link-discord': 'Discord 社区',
      'link-discord-d': '聊天、支持与治理',
      'link-contact': '联系我们',
    }
  };

  function applyLang() {
    var t = _t[_lang];
    // Nav links
    document.querySelectorAll('.nav-link').forEach(function(el){
      el.textContent = el.getAttribute('data-'+_lang) || el.textContent;
    });
    // Lang button
    document.getElementById('lang-btn').textContent = t['lang-btn'];
    // Page titles & descs
    ['register','trade','assets','agents','network'].forEach(function(pg){
      var title = document.querySelector('#pg-'+pg+' .page-title');
      var desc = document.querySelector('#pg-'+pg+' .page-desc');
      if(title) title.textContent = t['pg-'+pg+'-title'] || title.textContent;
      if(desc) desc.textContent = t['pg-'+pg+'-desc'] || desc.textContent;
    });
    // Stat labels
    var statLabels = document.querySelectorAll('.stat-l');
    if(statLabels[0]) statLabels[0].textContent = t['stat-assets'];
    if(statLabels[1]) statLabels[1].textContent = t['stat-blocks'];
    if(statLabels[2]) statLabels[2].textContent = t['stat-watermarks'];
    // Buttons
    document.getElementById('reg-btn').textContent = t['reg-btn'];
    document.getElementById('quote-btn').textContent = t['quote-btn'];
    document.getElementById('buy-btn').textContent = t['buy-btn'];
    document.getElementById('stake-btn').textContent = t['stake-btn'];
    document.getElementById('ahrp-announce-btn').textContent = t['announce-btn'];
    document.getElementById('ahrp-find-btn').textContent = t['find-btn'];
    document.getElementById('tx-accept-btn').textContent = t['accept-btn'];
    document.getElementById('tx-deliver-btn').textContent = t['deliver-btn'];
    document.getElementById('tx-confirm-btn').textContent = t['confirm-btn'];
    document.getElementById('emb-btn').textContent = t['embed-btn'];
    document.getElementById('fp-trace-btn').textContent = t['trace-btn'];
    document.getElementById('fp-list-btn').textContent = t['lookup-btn'];
    // Placeholders
    document.getElementById('reg-path').placeholder = t['reg-path-ph'];
    document.getElementById('reg-owner').placeholder = t['reg-owner-ph'];
    document.getElementById('reg-tags').placeholder = t['reg-tags-ph'];
    document.getElementById('buy-asset').placeholder = t['buy-asset-ph'];
    document.getElementById('stake-node').placeholder = t['stake-node-ph'];
    document.getElementById('asset-search').placeholder = t['search-ph'];
    // Card titles
    var cardTitles = document.querySelectorAll('.card-title');
    var cardMap = ['card-buy','card-portfolio','card-stake','card-announce','card-discover','card-tx','card-node','','card-watermark'];
    cardTitles.forEach(function(el,i){if(cardMap[i]&&t[cardMap[i]])el.textContent=t[cardMap[i]];});
    // Field labels
    var labels = document.querySelectorAll('.field-label');


  }

  // Lang toggle
  document.getElementById('lang-btn').addEventListener('click', function(){
    _lang = _lang === 'en' ? 'zh' : 'en';
    applyLang();
  });

  // About panel — tabbed info hub for all audiences
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'<span class="about-version">'+t['about-version']+'</span></h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<div class="about-tabs">'+
        '<button class="about-tab active" data-about-tab="overview">'+t['tab-overview']+'</button>'+
        '<button class="about-tab" data-about-tab="start">'+t['tab-start']+'</button>'+
        '<button class="about-tab" data-about-tab="arch">'+t['tab-arch']+'</button>'+
        '<button class="about-tab" data-about-tab="econ">'+t['tab-econ']+'</button>'+
        '<button class="about-tab" data-about-tab="update">'+t['tab-update']+'</button>'+
        '<button class="about-tab" data-about-tab="links">'+t['tab-links']+'</button>'+
      '</div>'+
      '<div class="about-section active" data-about-section="overview">'+
        '<p>'+t['about-how']+'</p>'+
      '</div>'+
      '<div class="about-section" data-about-section="start">'+
        '<pre>'+t['about-quickstart']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="arch">'+
        '<pre>'+t['about-arch']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="econ">'+
        '<pre>'+t['about-econ']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="update">'+
        '<pre>'+t['about-update']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="links">'+
        '<ul class="about-links">'+
          '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github-project']+'</div><div class="link-desc">'+t['link-github-project-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine" target="_blank"><div><div class="link-label">'+t['link-github-engine']+'</div><div class="link-desc">'+t['link-github-engine-d']+'</div></div></a></li>'+
          '<li><a href="https://discord.gg/oasyce" target="_blank"><div><div class="link-label">'+t['link-discord']+'</div><div class="link-desc">'+t['link-discord-d']+'</div></div></a></li>'+
        '</ul>'+
        '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>'+
      '</div>';
    document.body.appendChild(overlay);
    // Tab switching
    overlay.querySelectorAll('.about-tab').forEach(function(tab){
      tab.addEventListener('click',function(){
        overlay.querySelectorAll('.about-tab').forEach(function(t){t.classList.remove('active');});
        overlay.querySelectorAll('.about-section').forEach(function(s){s.classList.remove('active');});
        tab.classList.add('active');
        var sec=overlay.querySelector('[data-about-section="'+tab.dataset.aboutTab+'"]');
        if(sec)sec.classList.add('active');
      });
    });
  });


  try{var saved=localStorage.getItem('oasyce-lang');if(saved)_lang=saved;}catch(e){}
  applyLang();

  loadStatus();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Register';btn.disabled=false;});

  /* ── Quote & Buy ──────────── */
  document.getElementById('quote-btn').addEventListener('click',async function(){var aid=document.getElementById('buy-asset').value.trim();var amt=document.getElementById('buy-amount').value.trim()||'10';var div=document.getElementById('buy-result');if(!aid){div.innerHTML='<p class="err">Enter asset ID</p>';return;}var r=await api('/api/quote?asset_id='+encodeURIComponent(aid)+'&amount='+amt);if(!r||r.error){div.innerHTML='<p class="err">'+esc(r?r.error:'Failed')+'</p>';return;}div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Pay</span><span class="kv-v">'+r.payment+' OAS</span></div><div class="kv"><span class="kv-k">Get</span><span class="kv-v">'+r.tokens+' tokens</span></div><div class="kv"><span class="kv-k">Impact</span><span class="kv-v">'+r.impact_pct+'%</span></div><div class="kv"><span class="kv-k">Burned</span><span class="kv-v">'+r.burn+' OAS</span></div></div>';});

  document.getElementById('buy-btn').addEventListener('click',async function(){if(!confirm('Confirm purchase?'))return;var btn=this;btn.textContent='Buying...';btn.disabled=true;var aid=document.getElementById('buy-asset').value.trim();var amt=document.getElementById('buy-amount').value.trim()||'10';var div=document.getElementById('buy-result');if(!aid){div.innerHTML='<p class="err">Enter asset ID</p>';btn.textContent='Buy';btn.disabled=false;return;}try{var r=await postApi('/api/buy',{asset_id:aid,buyer:(window.__oasyce_wallet||'anonymous'),amount:parseFloat(amt)});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Tokens</span><span class="kv-v ok">'+r.tokens+'</span></div><div class="kv"><span class="kv-k">New price</span><span class="kv-v">'+r.price_after+' OAS</span></div></div>';toast('Purchased');loadPortfolio();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Buy';btn.disabled=false;});

  /* ── Portfolio ──────────── */
  async function loadPortfolio(){var list=await api('/api/portfolio?buyer='+(window.__oasyce_wallet||'anonymous'))||[];var c=document.getElementById('portfolio-list');if(!list.length){c.innerHTML='<div class="empty">No holdings yet</div>';return;}var h='';list.forEach(function(x){h+='<div class="p-row"><span class="p-id">'+esc(trunc(x.asset_id,24))+'</span><span class="p-v">'+x.shares+' shares &middot; '+x.value_oas+' OAS</span></div>';});c.innerHTML=h;}

  /* ── Stake ──────────── */
  document.getElementById('stake-btn').addEventListener('click',async function(){var btn=this;btn.textContent='Staking...';btn.disabled=true;var nid=document.getElementById('stake-node').value.trim();var amt=document.getElementById('stake-amount').value.trim()||'10000';var div=document.getElementById('stake-result');if(!nid){div.innerHTML='<p class="err">Enter node ID</p>';btn.textContent='Stake';btn.disabled=false;return;}try{var r=await postApi('/api/stake',{node_id:nid,amount:parseFloat(amt)});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Staked</span><span class="kv-v">'+r.total_stake+' OAS</span></div></div>';toast('Staked');loadStakes();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Stake';btn.disabled=false;});
  async function loadStakes(){var list=await api('/api/stakes')||[];var sec=document.getElementById('stakes-card');if(!list.length){sec.style.display='none';return;}sec.style.display='block';var h='';list.forEach(function(s){h+='<div class="stk-item"><span class="stk-id">'+esc(trunc(s.validator_id,20))+'</span><span class="stk-a">'+s.total+' OAS</span></div>';});document.getElementById('stakes-list').innerHTML=h;}

  /* ── Watermark ──────────── */
  document.getElementById('emb-btn').addEventListener('click',async function(){var btn=this;btn.textContent='Embedding...';btn.disabled=true;var aid=document.getElementById('emb-asset').value.trim();var caller=document.getElementById('emb-caller').value.trim();var content=document.getElementById('emb-content').value;var div=document.getElementById('emb-result');if(!aid||!caller||!content){div.innerHTML='<p class="err">Fill all fields</p>';btn.textContent='Embed';btn.disabled=false;return;}try{var r=await postApi('/api/fingerprint/embed',{asset_id:aid,caller_id:caller,content:content});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Fingerprint</span><span class="kv-v">'+esc(trunc(r.fingerprint,24))+'</span></div></div><textarea readonly style="width:100%;min-height:60px;margin-top:8px;color:var(--success);">'+esc(r.watermarked_content)+'</textarea>';toast('Embedded');// ── Drop Zone ──
  var dropZone = document.getElementById('drop-zone');
  var filePick = document.getElementById('file-pick');
  var regFields = document.getElementById('reg-fields');
  var dropFileInfo = document.getElementById('drop-file-info');
  var dropText = document.getElementById('drop-text');
  var _droppedPath = '';

  function formatSize(bytes){
    if(bytes<1024)return bytes+' B';
    if(bytes<1048576)return(bytes/1024).toFixed(1)+' KB';
    return(bytes/1048576).toFixed(1)+' MB';
  }

  function handleFile(file){
    _droppedPath = file.name;
    // Try to get full path (only works in some browsers via webkitRelativePath)
    if(file.path) _droppedPath = file.path;
    else if(file.webkitRelativePath) _droppedPath = file.webkitRelativePath;

    document.getElementById('reg-path').value = _droppedPath;

    // Auto-generate tags from file extension and name
    var ext = file.name.split('.').pop().toLowerCase();
    var autoTags = [];
    if(['csv','json','xml','parquet','sqlite','db'].indexOf(ext)!==-1) autoTags.push('dataset');
    if(['jpg','jpeg','png','gif','webp','svg','bmp'].indexOf(ext)!==-1) autoTags.push('image');
    if(['mp4','mov','avi','mkv'].indexOf(ext)!==-1) autoTags.push('video');
    if(['mp3','wav','flac','ogg'].indexOf(ext)!==-1) autoTags.push('audio');
    if(['pdf','doc','docx','txt','md'].indexOf(ext)!==-1) autoTags.push('document');
    if(['py','js','ts','go','rs','java','c','cpp'].indexOf(ext)!==-1) autoTags.push('code');
    if(ext) autoTags.push(ext);
    document.getElementById('reg-tags').value = autoTags.join(', ');

    // Show file info in drop zone
    dropZone.classList.add('has-file');
    dropFileInfo.style.display = 'flex';
    dropFileInfo.innerHTML = '<div><div class="drop-file-name">'+esc(file.name)+'</div><div class="drop-file-size">'+formatSize(file.size)+'</div></div><button class="drop-file-remove" onclick="clearFile()">&times;</button>';
    dropText.style.display = 'none';
    document.querySelector('.drop-icon').style.display = 'none';
    document.querySelector('.drop-hint').style.display = 'none';

    // Show form fields
    regFields.style.display = 'block';
  }

  window.clearFile = function(){
    _droppedPath = '';
    document.getElementById('reg-path').value = '';
    document.getElementById('reg-tags').value = '';
    dropZone.classList.remove('has-file');
    dropFileInfo.style.display = 'none';
    dropFileInfo.innerHTML = '';
    dropText.style.display = '';
    document.querySelector('.drop-icon').style.display = '';
    document.querySelector('.drop-hint').style.display = '';
    regFields.style.display = 'none';
    filePick.value = '';
  };

  // Drag events
  ['dragenter','dragover'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.add('over');});
  });
  ['dragleave','drop'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.remove('over');});
  });
  dropZone.addEventListener('drop', function(e){
    var files = e.dataTransfer.files;
    if(files.length > 0) handleFile(files[0]);
  });
  dropZone.addEventListener('click', function(e){
    if(e.target.tagName !== 'BUTTON' && e.target.tagName !== 'LABEL' && !dropZone.classList.contains('has-file')){
      filePick.click();
    }
  });
  filePick.addEventListener('change', function(){
    if(this.files.length > 0) handleFile(this.files[0]);
  });

  // ── i18n ──
  var _lang = (navigator.language||'').startsWith('zh') ? 'zh' : 'en';
  var _t = {
    en: {
      'pg-register-title': 'Register a data asset',
      'pg-register-desc': 'Claim ownership of a file. Once registered, other agents can discover, quote, and purchase access rights.',
      'pg-trade-title': 'Trade',
      'pg-trade-desc': 'Quote and purchase shares in data assets. Buy to gain access rights and revenue share.',
      'pg-assets-title': 'Your Assets',
      'pg-assets-desc': 'Manage registered data assets. Click any asset for details.',
      'pg-agents-title': 'Agent Protocol',
      'pg-agents-desc': 'Register your agent on the AHRP network, discover data providers, and execute transactions.',
      'pg-network-title': 'Network',
      'pg-network-desc': 'Node status and validator information.',
      'reg-path-ph': '/path/to/your/file',
      'drop-text': 'Drag a file here, or <label for="file-pick" class="drop-link">browse</label>',
      'drop-hint': 'Register your file to claim ownership on the Oasyce network',
      'hint-file': 'Auto-filled from your dropped file',
      'hint-owner': 'Who owns this data? Defaults to your node ID if left blank.',
      'hint-tags': 'Help others find your asset. Comma-separated keywords.',
      'optional': 'optional',
      'reg-owner-ph': 'Your name or agent ID',
      'reg-tags-ph': 'medical, imaging, dicom',
      'reg-btn': 'Register',
      'buy-asset-ph': 'Paste asset ID',
      'quote-btn': 'Quote',
      'buy-btn': 'Buy',
      'card-buy': 'Buy Shares',
      'hint-buy-asset': 'Copy from the Assets tab or from the creator who shared it with you.',
      'hint-buy-amount': 'How much to spend.',
      'card-portfolio': 'Portfolio',
      'card-stake': 'Stake',
      'stake-node-ph': 'Validator node ID',
      'stake-btn': 'Stake',
      'search-ph': 'Search by ID or tag...',
      'card-announce': 'Announce Agent',
      'announce-btn': 'Announce',
      'card-discover': 'Discover Agents',
      'find-btn': 'Find',
      'card-tx': 'Transaction',
      'accept-btn': 'Accept & Create',
      'deliver-btn': 'Deliver',
      'confirm-btn': 'Confirm & Settle',
      'card-node': 'Node',
      'card-validators': 'Validators',
      'card-watermark': 'Watermark',
      'embed-btn': 'Embed',
      'trace-btn': 'Trace',
      'lookup-btn': 'Lookup',
      'lbl-file': 'File path',
      'lbl-owner': 'Owner',
      'lbl-tags': 'Tags',
      'lbl-rights-type': 'Rights type',
      'lbl-co-creators': 'Co-creators',
      'hint-co-creators': 'At least 2 co-creators, shares must total 100%',
      'rights-original': 'Original', 'rights-co_creation': 'Co-creation', 'rights-licensed': 'Licensed', 'rights-collection': 'Collection',
      'disputed': 'Disputed', 'dispute-btn': 'File dispute', 'dispute-reason-ph': 'Reason for dispute', 'dispute-submit': 'Submit', 'delisted': 'Delisted', 'dispute-resolved': 'Resolved', 'dispute-dismissed': 'Dismissed', 'remedy-delist': 'Delist', 'remedy-transfer': 'Transfer', 'remedy-rights_correction': 'Correct rights', 'remedy-share_adjustment': 'Adjust shares', 'drop-hint-unified': 'Drop file or folder, or click to select', 'pick-file': 'File', 'pick-folder': 'Folder', 'register-data': 'Register data', 'publish-cap': 'Publish capability', 'cap-name': 'Name', 'cap-provider': 'Provider', 'cap-base-price': 'Base price (OAS)', 'cap-published': 'Published',
      'lbl-asset-id': 'Asset ID',
      'lbl-amount': 'Amount (OAS)',
      'lbl-node-id': 'Node ID',
      'empty-assets': 'No assets yet. Go to <strong>Register</strong> to add your first.',
      'empty-portfolio': 'No holdings yet',
      'stat-assets': 'Assets',
      'stat-blocks': 'Blocks',
      'stat-watermarks': 'Watermarks',
      'lang-btn': '中',
      'card-identity': 'Your Identity',
      'no-identity': 'No identity found. Run <code>oasyce start</code> to generate your keys.',
      'id-hint': 'This is your unique identity on the Oasyce network. Every asset you register is cryptographically signed with your private key.',
      'id-backup': '&#9888; Back up <code>~/.oasyce/keys/</code> — if you lose your keys, you lose access to all your registered assets.',
      'copied': 'Copied',
      'auto-default': 'auto',
      'loading-identity': 'Loading...',
      'about-title': 'About Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'tab-overview': 'Overview',
      'tab-start': 'Quick Start',
      'tab-arch': 'Architecture',
      'tab-econ': 'Economics',
      'tab-update': 'Maintain',
      'tab-links': 'Links',
      'about-how': 'Oasyce is a decentralized protocol where AI agents autonomously register, discover, license, and settle data rights. Data owners register files and receive a cryptographic proof-of-provenance certificate (PoPc). AI agents discover data via a Recall-Rank pipeline, negotiate prices through bonding curves, and settle transactions with escrow-protected OAS tokens.',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # verify setup\n3. oasyce start           # launch node + dashboard\n4. Open http://localhost:8420',
      'about-arch': 'Core Layers:\n\u2022 Schema Registry \u2014 unified validation for data/capability/oracle/identity\n\u2022 Engine Pipeline \u2014 Scan \u2192 Classify \u2192 Metadata \u2192 PoPc Certificate \u2192 Register\n\u2022 Discovery \u2014 Recall (broad retrieval) \u2192 Rank (trust + economics) + feedback loop\n\u2022 Settlement \u2014 bonding curve pricing, escrow, share distribution\n\u2022 Access Control \u2014 L0 metadata / L1 sample / L2 compute / L3 full\n\u2022 P2P Network \u2014 Ed25519 identity, gossip sync, PoS consensus\n\u2022 Risk Engine \u2014 auto-classification (public / internal / sensitive)',
      'about-econ': 'Token: OAS\n\nPricing: Bonding curve (reserve ratio 0.35) \u2014 more buyers = higher price\nShares: Early buyers earn more (diminishing: 100% \u2192 80% \u2192 60% \u2192 40%)\nRights multiplier: original 1.0x / co_creation 0.9x / licensed 0.7x / collection 0.3x\nStaking: Validators stake OAS to produce blocks and earn rewards\nBlock reward: 4.0 OAS (mainnet), halving every ~1M blocks\nEscrow: Funds locked before execution, released after quality verification',
      'about-update': 'Update:\n  pip install --upgrade oasyce\n\nBuild from source:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\nRun tests:\n  python -m pytest tests/ -v\n\nContribute: Fork \u2192 Branch \u2192 PR (see CONTRIBUTING.md)',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Full protocol design and economics paper',
      'link-docs': 'Protocol Overview',
      'link-docs-d': 'Technical reference, API, and architecture',
      'link-github-project': 'GitHub (Project)',
      'link-github-project-d': 'Specs, docs, and roadmap',
      'link-github-engine': 'GitHub (Engine)',
      'link-github-engine-d': 'Plugin engine source code',
      'link-discord': 'Discord Community',
      'link-discord-d': 'Chat, support, and governance',
      'link-contact': 'Contact',
    },
    zh: {
      'pg-register-title': '注册数据资产',
      'pg-register-desc': '确立文件的归属权。注册后，其他代理可以发现、报价和购买访问权限。',
      'pg-trade-title': '交易',
      'pg-trade-desc': '报价并购买数据资产份额。购买即获得访问权和收益分成。',
      'pg-assets-title': '我的资产',
      'pg-assets-desc': '管理已注册的数据资产。点击任意资产查看详情。',
      'pg-agents-title': '代理协议',
      'pg-agents-desc': '在 AHRP 网络注册你的代理，发现数据提供者，执行交易。',
      'pg-network-title': '网络',
      'pg-network-desc': '节点状态与验证者信息。',
      'reg-path-ph': '文件路径',
      'drop-text': '拖拽文件到这里，或 <label for="file-pick" class="drop-link">浏览选择</label>',
      'drop-hint': '注册你的文件，在 Oasyce 网络上确立数据归属权',
      'hint-file': '已从拖入的文件自动填写',
      'hint-owner': '数据所有者。留空则默认使用你的节点 ID。',
      'hint-tags': '帮助其他代理发现你的资产。用逗号分隔关键词。',
      'optional': '可选',
      'reg-owner-ph': '所有者名称或代理 ID',
      'reg-tags-ph': '标签，用逗号分隔',
      'lbl-rights-type': '权利类型',
      'lbl-co-creators': '共创者',
      'hint-co-creators': '至少2个共创者，份额合计100%',
      'rights-original': '原创', 'rights-co_creation': '共创', 'rights-licensed': '授权转售', 'rights-collection': '个人收藏',
      'disputed': '争议中', 'dispute-btn': '发起争议', 'dispute-reason-ph': '争议原因', 'dispute-submit': '提交', 'delisted': '已下架', 'dispute-resolved': '已裁决', 'dispute-dismissed': '已驳回', 'remedy-delist': '下架', 'remedy-transfer': '转移所有权', 'remedy-rights_correction': '更正权利', 'remedy-share_adjustment': '调整份额', 'drop-hint-unified': '拖入文件或文件夹，或点击选择', 'pick-file': '文件', 'pick-folder': '文件夹', 'register-data': '注册数据', 'publish-cap': '发布能力', 'cap-name': '名称', 'cap-provider': '提供者', 'cap-base-price': '基础价格 (OAS)', 'cap-published': '已发布',
      'reg-btn': '注册',
      'buy-asset-ph': '粘贴资产 ID',
      'quote-btn': '报价',
      'buy-btn': '购买',
      'card-buy': '购买份额',
      'hint-buy-asset': '从资产页复制，或从数据创建者处获取。',
      'hint-buy-amount': '你愿意花多少 OAS。',
      'card-portfolio': '持仓',
      'card-stake': '质押',
      'stake-node-ph': '验证者节点 ID',
      'stake-btn': '质押',
      'search-ph': '按 ID 或标签搜索...',
      'card-announce': '注册代理',
      'announce-btn': '广播',
      'card-discover': '发现代理',
      'find-btn': '查找',
      'card-tx': '交易流程',
      'accept-btn': '接受并创建',
      'deliver-btn': '交付',
      'confirm-btn': '确认并结算',
      'card-node': '节点',
      'card-validators': '验证者',
      'card-watermark': '水印',
      'embed-btn': '嵌入',
      'trace-btn': '追溯',
      'lookup-btn': '查询',
      'lbl-file': '文件路径',
      'lbl-owner': '所有者',
      'lbl-tags': '标签',
      'lbl-asset-id': '资产 ID',
      'lbl-amount': '数量（OAS）',
      'lbl-node-id': '节点 ID',
      'empty-assets': '暂无资产。前往 <strong>注册</strong> 添加你的第一个资产。',
      'empty-portfolio': '暂无持仓',
      'stat-assets': '资产',
      'stat-blocks': '区块',
      'stat-watermarks': '水印',
      'lang-btn': 'En',
      'card-identity': '你的身份',
      'no-identity': '未找到密钥。运行 <code>oasyce start</code> 生成你的身份。',
      'id-hint': '这是你在 Oasyce 网络上的唯一身份。你注册的每个资产都会用你的私钥进行密码学签名。',
      'id-backup': '&#9888; 请备份 <code>~/.oasyce/keys/</code> 目录 —— 丢失密钥意味着永久失去所有已注册资产的控制权。',
      'copied': '已复制',
      'auto-default': '自动',
      'loading-identity': '加载中...',
      'about-title': '关于 Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'tab-overview': '概览',
      'tab-start': '快速开始',
      'tab-arch': '技术架构',
      'tab-econ': '经济模型',
      'tab-update': '维护更新',
      'tab-links': '链接',
      'about-how': 'Oasyce 是一个去中心化协议，AI 代理在其中自主注册、发现、许可和结算数据权利。数据所有者注册文件并获得加密来源证明证书 (PoPc)。AI 代理通过 Recall-Rank 管道发现数据，通过联合曲线协商价格，并使用托管保护的 OAS 代币进行结算。',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # 验证安装\n3. oasyce start           # 启动节点 + 仪表盘\n4. 浏览器打开 http://localhost:8420',
      'about-arch': '核心层级:\n\u2022 Schema Registry \u2014 统一验证 data/capability/oracle/identity 四种资产\n\u2022 引擎管道 \u2014 扫描 \u2192 分类 \u2192 元数据 \u2192 PoPc 证书 \u2192 注册\n\u2022 发现引擎 \u2014 Recall (广召回) \u2192 Rank (信任+经济) + 反馈循环\n\u2022 结算引擎 \u2014 联合曲线定价、托管、份额分配\n\u2022 访问控制 \u2014 L0 元数据 / L1 采样 / L2 计算 / L3 完整\n\u2022 P2P 网络 \u2014 Ed25519 身份、gossip 同步、PoS 共识\n\u2022 风险引擎 \u2014 自动分级 (public / internal / sensitive)',
      'about-econ': '代币: OAS\n\n定价: 联合曲线 (储备率 0.35) \u2014 买家越多价格越高\n份额: 早期买家获利更多 (递减: 100% \u2192 80% \u2192 60% \u2192 40%)\n权利系数: 原创 1.0x / 共创 0.9x / 授权 0.7x / 收藏 0.3x\n质押: 验证者质押 OAS 出块并获得奖励\n区块奖励: 4.0 OAS (主网)，每约 100 万块减半\n托管: 执行前锁定资金，质量验证后释放',
      'about-update': '更新:\n  pip install --upgrade oasyce\n\n从源码构建:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\n运行测试:\n  python -m pytest tests/ -v\n\n贡献: Fork \u2192 Branch \u2192 PR (详见 CONTRIBUTING.md)',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '完整协议设计与经济模型论文',
      'link-docs': '协议概览',
      'link-docs-d': '技术参考、API 与架构',
      'link-github-project': 'GitHub (项目)',
      'link-github-project-d': '规范、文档与路线图',
      'link-github-engine': 'GitHub (引擎)',
      'link-github-engine-d': '插件引擎源代码',
      'link-discord': 'Discord 社区',
      'link-discord-d': '聊天、支持与治理',
      'link-contact': '联系我们',
    }
  };

  function applyLang() {
    var t = _t[_lang];
    // Nav links
    document.querySelectorAll('.nav-link').forEach(function(el){
      el.textContent = el.getAttribute('data-'+_lang) || el.textContent;
    });
    // Lang button
    document.getElementById('lang-btn').textContent = t['lang-btn'];
    // Page titles & descs
    ['register','trade','assets','agents','network'].forEach(function(pg){
      var title = document.querySelector('#pg-'+pg+' .page-title');
      var desc = document.querySelector('#pg-'+pg+' .page-desc');
      if(title) title.textContent = t['pg-'+pg+'-title'] || title.textContent;
      if(desc) desc.textContent = t['pg-'+pg+'-desc'] || desc.textContent;
    });
    // Stat labels
    var statLabels = document.querySelectorAll('.stat-l');
    if(statLabels[0]) statLabels[0].textContent = t['stat-assets'];
    if(statLabels[1]) statLabels[1].textContent = t['stat-blocks'];
    if(statLabels[2]) statLabels[2].textContent = t['stat-watermarks'];
    // Buttons
    document.getElementById('reg-btn').textContent = t['reg-btn'];
    document.getElementById('quote-btn').textContent = t['quote-btn'];
    document.getElementById('buy-btn').textContent = t['buy-btn'];
    document.getElementById('stake-btn').textContent = t['stake-btn'];
    document.getElementById('ahrp-announce-btn').textContent = t['announce-btn'];
    document.getElementById('ahrp-find-btn').textContent = t['find-btn'];
    document.getElementById('tx-accept-btn').textContent = t['accept-btn'];
    document.getElementById('tx-deliver-btn').textContent = t['deliver-btn'];
    document.getElementById('tx-confirm-btn').textContent = t['confirm-btn'];
    document.getElementById('emb-btn').textContent = t['embed-btn'];
    document.getElementById('fp-trace-btn').textContent = t['trace-btn'];
    document.getElementById('fp-list-btn').textContent = t['lookup-btn'];
    // Placeholders
    document.getElementById('reg-path').placeholder = t['reg-path-ph'];
    document.getElementById('reg-owner').placeholder = t['reg-owner-ph'];
    document.getElementById('reg-tags').placeholder = t['reg-tags-ph'];
    document.getElementById('buy-asset').placeholder = t['buy-asset-ph'];
    document.getElementById('stake-node').placeholder = t['stake-node-ph'];
    document.getElementById('asset-search').placeholder = t['search-ph'];
    // Card titles
    var cardTitles = document.querySelectorAll('.card-title');
    var cardMap = ['card-buy','card-portfolio','card-stake','card-announce','card-discover','card-tx','card-node','','card-watermark'];
    cardTitles.forEach(function(el,i){if(cardMap[i]&&t[cardMap[i]])el.textContent=t[cardMap[i]];});
    // Field labels
    var labels = document.querySelectorAll('.field-label');


  }

  // Lang toggle
  document.getElementById('lang-btn').addEventListener('click', function(){
    _lang = _lang === 'en' ? 'zh' : 'en';
    applyLang();
  });

  // About panel — tabbed info hub for all audiences
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'<span class="about-version">'+t['about-version']+'</span></h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<div class="about-tabs">'+
        '<button class="about-tab active" data-about-tab="overview">'+t['tab-overview']+'</button>'+
        '<button class="about-tab" data-about-tab="start">'+t['tab-start']+'</button>'+
        '<button class="about-tab" data-about-tab="arch">'+t['tab-arch']+'</button>'+
        '<button class="about-tab" data-about-tab="econ">'+t['tab-econ']+'</button>'+
        '<button class="about-tab" data-about-tab="update">'+t['tab-update']+'</button>'+
        '<button class="about-tab" data-about-tab="links">'+t['tab-links']+'</button>'+
      '</div>'+
      '<div class="about-section active" data-about-section="overview">'+
        '<p>'+t['about-how']+'</p>'+
      '</div>'+
      '<div class="about-section" data-about-section="start">'+
        '<pre>'+t['about-quickstart']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="arch">'+
        '<pre>'+t['about-arch']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="econ">'+
        '<pre>'+t['about-econ']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="update">'+
        '<pre>'+t['about-update']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="links">'+
        '<ul class="about-links">'+
          '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github-project']+'</div><div class="link-desc">'+t['link-github-project-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine" target="_blank"><div><div class="link-label">'+t['link-github-engine']+'</div><div class="link-desc">'+t['link-github-engine-d']+'</div></div></a></li>'+
          '<li><a href="https://discord.gg/oasyce" target="_blank"><div><div class="link-label">'+t['link-discord']+'</div><div class="link-desc">'+t['link-discord-d']+'</div></div></a></li>'+
        '</ul>'+
        '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>'+
      '</div>';
    document.body.appendChild(overlay);
    // Tab switching
    overlay.querySelectorAll('.about-tab').forEach(function(tab){
      tab.addEventListener('click',function(){
        overlay.querySelectorAll('.about-tab').forEach(function(t){t.classList.remove('active');});
        overlay.querySelectorAll('.about-section').forEach(function(s){s.classList.remove('active');});
        tab.classList.add('active');
        var sec=overlay.querySelector('[data-about-section="'+tab.dataset.aboutTab+'"]');
        if(sec)sec.classList.add('active');
      });
    });
  });


  try{var saved=localStorage.getItem('oasyce-lang');if(saved)_lang=saved;}catch(e){}
  applyLang();

  loadStatus();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Embed';btn.disabled=false;});
  document.getElementById('fp-trace-btn').addEventListener('click',async function(){var fp=document.getElementById('fp-input').value.trim();if(!fp)return;var r=await api('/api/trace?fp='+encodeURIComponent(fp));var div=document.getElementById('fp-trace-result');if(!r||r.error){div.innerHTML='<p class="err">Not found</p>';}else{div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Asset</span><span class="kv-v">'+esc(r.asset_id)+'</span></div><div class="kv"><span class="kv-k">Buyer</span><span class="kv-v">'+esc(r.caller_id)+'</span></div><div class="kv"><span class="kv-k">When</span><span class="kv-v">'+timeAgo(r.timestamp||r.created_at)+'</span></div></div>';}});
  document.getElementById('fp-list-btn').addEventListener('click',async function(){var aid=document.getElementById('fp-asset-input').value.trim();if(!aid)return;var list=await api('/api/fingerprints?asset_id='+encodeURIComponent(aid));var c=document.getElementById('fp-dist-list');if(!list||!list.length){c.innerHTML='<p class="err">None found</p>';return;}var h='';list.forEach(function(r){h+='<div class="p-row"><span class="p-id" style="font-size:11px;">'+esc(trunc(r.fingerprint,18))+'</span><span class="p-v">'+esc(r.caller_id)+' &middot; '+timeAgo(r.timestamp)+'</span></div>';});c.innerHTML=h;});

  /* ── AHRP ──────────── */
  document.getElementById('ahrp-announce-btn').addEventListener('click',async function(){var btn=this;btn.textContent='Announcing...';btn.disabled=true;var div=document.getElementById('ahrp-announce-result');var levels=[];document.querySelectorAll('.chk-g input:checked').forEach(function(cb){levels.push(cb.value);});var payload={agent_id:document.getElementById('ahrp-agent-id').value.trim(),public_key:document.getElementById('ahrp-pub-key').value.trim(),reputation:parseFloat(document.getElementById('ahrp-reputation').value)||10,stake:parseFloat(document.getElementById('ahrp-stake').value)||100,capabilities:[{capability_id:document.getElementById('ahrp-cap-id').value.trim(),tags:document.getElementById('ahrp-cap-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean),description:document.getElementById('ahrp-cap-desc').value.trim(),price_floor:parseFloat(document.getElementById('ahrp-cap-price').value)||1.0,origin_type:document.getElementById('ahrp-cap-origin').value,access_levels:levels}]};var d=await postApi('/ahrp/v1/announce',payload);if(d&&!d.error){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Status</span><span class="kv-v ok">Announced</span></div></div>';toast('Agent announced');}else{div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>';}btn.textContent='Announce';btn.disabled=false;});

  document.getElementById('ahrp-find-btn').addEventListener('click',async function(){var btn=this;btn.textContent='Searching...';btn.disabled=true;var c=document.getElementById('ahrp-matches');var payload={description:document.getElementById('ahrp-search-desc').value.trim(),tags:document.getElementById('ahrp-search-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean),min_reputation:parseFloat(document.getElementById('ahrp-search-rep').value)||0,max_price:parseFloat(document.getElementById('ahrp-search-price').value)||1000,required_access_level:document.getElementById('ahrp-search-access').value};var d=await postApi('/ahrp/v1/request',payload);var matches=d?(d.matches||d.results||[]):[];if(!matches.length){c.innerHTML='<div class="empty">No matches found</div>';}else{var h='';matches.forEach(function(m){var score=Math.round((m.score||0)*100);h+='<div class="m-card"><div class="m-top"><span class="m-agent">'+esc(m.agent_id||'')+' / '+esc(m.capability_id||'')+'</span><span class="m-origin">'+esc(m.origin_type||'')+'</span></div><div class="m-bar"><div class="m-bar-fill" style="width:'+score+'%"></div></div><div class="m-bot"><span>'+score+'% match</span><span>'+esc(m.price_floor||0)+' OAS</span></div></div>';});c.innerHTML=h;}btn.textContent='Find';btn.disabled=false;});

  /* ── TX Pipeline ──────────── */
  var _steps=['request','offer','accept','deliver','confirm'],_rating=5;
  function updatePipe(step){for(var i=0;i<_steps.length;i++){var el=document.getElementById('tx-s-'+_steps[i]);el.className='pipe-s';if(i<step)el.className='pipe-s done';else if(i===step)el.className='pipe-s active';}for(var j=1;j<=4;j++){document.getElementById('tx-l-'+j).className=j<=step?'pipe-line done':'pipe-line';}}
  var stars=document.querySelectorAll('#star-rating span');stars.forEach(function(s){s.addEventListener('click',function(){_rating=parseInt(this.getAttribute('data-v'));stars.forEach(function(x){x.className=parseInt(x.getAttribute('data-v'))<=_rating?'lit':'';});});});stars.forEach(function(s){s.className=parseInt(s.getAttribute('data-v'))<=_rating?'lit':'';});

  document.getElementById('tx-accept-btn').addEventListener('click',async function(){var btn=this;btn.textContent='Creating...';btn.disabled=true;var div=document.getElementById('tx-accept-result');updatePipe(0);var payload={buyer_id:document.getElementById('tx-buyer').value.trim(),seller_id:document.getElementById('tx-seller').value.trim(),capability_id:document.getElementById('tx-cap-id').value.trim(),price_oas:parseFloat(document.getElementById('tx-price').value)||10};await new Promise(function(r){setTimeout(r,200);});updatePipe(1);await new Promise(function(r){setTimeout(r,200);});var d=await postApi('/ahrp/v1/accept',payload);if(d&&!d.error){var txId=d.tx_id||d.transaction_id||'';document.getElementById('tx-deliver-id').value=txId;document.getElementById('tx-confirm-id').value=txId;updatePipe(2);div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Transaction</span><span class="kv-v">'+esc(txId)+'</span></div></div>';}else{div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>';updatePipe(0);}btn.textContent='Accept & Create';btn.disabled=false;});
  document.getElementById('tx-deliver-btn').addEventListener('click',async function(){var btn=this;btn.textContent='Delivering...';btn.disabled=true;var div=document.getElementById('tx-deliver-result');var d=await postApi('/ahrp/v1/deliver',{tx_id:document.getElementById('tx-deliver-id').value.trim(),content_hash:document.getElementById('tx-content-hash').value.trim()});if(d&&!d.error){updatePipe(3);div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Status</span><span class="kv-v ok">Delivered</span></div></div>';}else{div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>';}btn.textContent='Deliver';btn.disabled=false;});
  document.getElementById('tx-confirm-btn').addEventListener('click',async function(){var btn=this;btn.textContent='Settling...';btn.disabled=true;var div=document.getElementById('tx-confirm-result');var d=await postApi('/ahrp/v1/confirm',{tx_id:document.getElementById('tx-confirm-id').value.trim(),rating:_rating});if(d&&!d.error){updatePipe(4);div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Status</span><span class="kv-v ok">Settled</span></div><div class="kv"><span class="kv-k">Rating</span><span class="kv-v">'+_rating+'/5</span></div></div>';toast('Transaction settled');}else{div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>';}btn.textContent='Confirm & Settle';btn.disabled=false;});
  updatePipe(0);

  /* ── Init ──────────── */
  // ── Drop Zone ──
  var dropZone = document.getElementById('drop-zone');
  var filePick = document.getElementById('file-pick');
  var regFields = document.getElementById('reg-fields');
  var dropFileInfo = document.getElementById('drop-file-info');
  var dropText = document.getElementById('drop-text');
  var _droppedPath = '';

  function formatSize(bytes){
    if(bytes<1024)return bytes+' B';
    if(bytes<1048576)return(bytes/1024).toFixed(1)+' KB';
    return(bytes/1048576).toFixed(1)+' MB';
  }

  function handleFile(file){
    _droppedPath = file.name;
    // Try to get full path (only works in some browsers via webkitRelativePath)
    if(file.path) _droppedPath = file.path;
    else if(file.webkitRelativePath) _droppedPath = file.webkitRelativePath;

    document.getElementById('reg-path').value = _droppedPath;

    // Auto-generate tags from file extension and name
    var ext = file.name.split('.').pop().toLowerCase();
    var autoTags = [];
    if(['csv','json','xml','parquet','sqlite','db'].indexOf(ext)!==-1) autoTags.push('dataset');
    if(['jpg','jpeg','png','gif','webp','svg','bmp'].indexOf(ext)!==-1) autoTags.push('image');
    if(['mp4','mov','avi','mkv'].indexOf(ext)!==-1) autoTags.push('video');
    if(['mp3','wav','flac','ogg'].indexOf(ext)!==-1) autoTags.push('audio');
    if(['pdf','doc','docx','txt','md'].indexOf(ext)!==-1) autoTags.push('document');
    if(['py','js','ts','go','rs','java','c','cpp'].indexOf(ext)!==-1) autoTags.push('code');
    if(ext) autoTags.push(ext);
    document.getElementById('reg-tags').value = autoTags.join(', ');

    // Show file info in drop zone
    dropZone.classList.add('has-file');
    dropFileInfo.style.display = 'flex';
    dropFileInfo.innerHTML = '<div><div class="drop-file-name">'+esc(file.name)+'</div><div class="drop-file-size">'+formatSize(file.size)+'</div></div><button class="drop-file-remove" onclick="clearFile()">&times;</button>';
    dropText.style.display = 'none';
    document.querySelector('.drop-icon').style.display = 'none';
    document.querySelector('.drop-hint').style.display = 'none';

    // Show form fields
    regFields.style.display = 'block';
  }

  window.clearFile = function(){
    _droppedPath = '';
    document.getElementById('reg-path').value = '';
    document.getElementById('reg-tags').value = '';
    dropZone.classList.remove('has-file');
    dropFileInfo.style.display = 'none';
    dropFileInfo.innerHTML = '';
    dropText.style.display = '';
    document.querySelector('.drop-icon').style.display = '';
    document.querySelector('.drop-hint').style.display = '';
    regFields.style.display = 'none';
    filePick.value = '';
  };

  // Drag events
  ['dragenter','dragover'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.add('over');});
  });
  ['dragleave','drop'].forEach(function(evt){
    dropZone.addEventListener(evt, function(e){e.preventDefault();e.stopPropagation();dropZone.classList.remove('over');});
  });
  dropZone.addEventListener('drop', function(e){
    var files = e.dataTransfer.files;
    if(files.length > 0) handleFile(files[0]);
  });
  dropZone.addEventListener('click', function(e){
    if(e.target.tagName !== 'BUTTON' && e.target.tagName !== 'LABEL' && !dropZone.classList.contains('has-file')){
      filePick.click();
    }
  });
  filePick.addEventListener('change', function(){
    if(this.files.length > 0) handleFile(this.files[0]);
  });

  // ── i18n ──
  var _lang = (navigator.language||'').startsWith('zh') ? 'zh' : 'en';
  var _t = {
    en: {
      'pg-register-title': 'Register a data asset',
      'pg-register-desc': 'Claim ownership of a file. Once registered, other agents can discover, quote, and purchase access rights.',
      'pg-trade-title': 'Trade',
      'pg-trade-desc': 'Quote and purchase shares in data assets. Buy to gain access rights and revenue share.',
      'pg-assets-title': 'Your Assets',
      'pg-assets-desc': 'Manage registered data assets. Click any asset for details.',
      'pg-agents-title': 'Agent Protocol',
      'pg-agents-desc': 'Register your agent on the AHRP network, discover data providers, and execute transactions.',
      'pg-network-title': 'Network',
      'pg-network-desc': 'Node status and validator information.',
      'reg-path-ph': '/path/to/your/file',
      'drop-text': 'Drag a file here, or <label for="file-pick" class="drop-link">browse</label>',
      'drop-hint': 'Register your file to claim ownership on the Oasyce network',
      'hint-file': 'Auto-filled from your dropped file',
      'hint-owner': 'Who owns this data? Defaults to your node ID if left blank.',
      'hint-tags': 'Help others find your asset. Comma-separated keywords.',
      'optional': 'optional',
      'reg-owner-ph': 'Your name or agent ID',
      'reg-tags-ph': 'medical, imaging, dicom',
      'reg-btn': 'Register',
      'buy-asset-ph': 'Paste asset ID',
      'quote-btn': 'Quote',
      'buy-btn': 'Buy',
      'card-buy': 'Buy Shares',
      'hint-buy-asset': 'Copy from the Assets tab or from the creator who shared it with you.',
      'hint-buy-amount': 'How much to spend.',
      'card-portfolio': 'Portfolio',
      'card-stake': 'Stake',
      'stake-node-ph': 'Validator node ID',
      'stake-btn': 'Stake',
      'search-ph': 'Search by ID or tag...',
      'card-announce': 'Announce Agent',
      'announce-btn': 'Announce',
      'card-discover': 'Discover Agents',
      'find-btn': 'Find',
      'card-tx': 'Transaction',
      'accept-btn': 'Accept & Create',
      'deliver-btn': 'Deliver',
      'confirm-btn': 'Confirm & Settle',
      'card-node': 'Node',
      'card-validators': 'Validators',
      'card-watermark': 'Watermark',
      'embed-btn': 'Embed',
      'trace-btn': 'Trace',
      'lookup-btn': 'Lookup',
      'lbl-file': 'File path',
      'lbl-owner': 'Owner',
      'lbl-tags': 'Tags',
      'lbl-rights-type': 'Rights type',
      'lbl-co-creators': 'Co-creators',
      'hint-co-creators': 'At least 2 co-creators, shares must total 100%',
      'rights-original': 'Original', 'rights-co_creation': 'Co-creation', 'rights-licensed': 'Licensed', 'rights-collection': 'Collection',
      'disputed': 'Disputed', 'dispute-btn': 'File dispute', 'dispute-reason-ph': 'Reason for dispute', 'dispute-submit': 'Submit', 'delisted': 'Delisted', 'dispute-resolved': 'Resolved', 'dispute-dismissed': 'Dismissed', 'remedy-delist': 'Delist', 'remedy-transfer': 'Transfer', 'remedy-rights_correction': 'Correct rights', 'remedy-share_adjustment': 'Adjust shares', 'drop-hint-unified': 'Drop file or folder, or click to select', 'pick-file': 'File', 'pick-folder': 'Folder', 'register-data': 'Register data', 'publish-cap': 'Publish capability', 'cap-name': 'Name', 'cap-provider': 'Provider', 'cap-base-price': 'Base price (OAS)', 'cap-published': 'Published',
      'lbl-asset-id': 'Asset ID',
      'lbl-amount': 'Amount (OAS)',
      'lbl-node-id': 'Node ID',
      'empty-assets': 'No assets yet. Go to <strong>Register</strong> to add your first.',
      'empty-portfolio': 'No holdings yet',
      'stat-assets': 'Assets',
      'stat-blocks': 'Blocks',
      'stat-watermarks': 'Watermarks',
      'lang-btn': '中',
      'card-identity': 'Your Identity',
      'no-identity': 'No identity found. Run <code>oasyce start</code> to generate your keys.',
      'id-hint': 'This is your unique identity on the Oasyce network. Every asset you register is cryptographically signed with your private key.',
      'id-backup': '&#9888; Back up <code>~/.oasyce/keys/</code> — if you lose your keys, you lose access to all your registered assets.',
      'copied': 'Copied',
      'auto-default': 'auto',
      'loading-identity': 'Loading...',
      'about-title': 'About Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'tab-overview': 'Overview',
      'tab-start': 'Quick Start',
      'tab-arch': 'Architecture',
      'tab-econ': 'Economics',
      'tab-update': 'Maintain',
      'tab-links': 'Links',
      'about-how': 'Oasyce is a decentralized protocol where AI agents autonomously register, discover, license, and settle data rights. Data owners register files and receive a cryptographic proof-of-provenance certificate (PoPc). AI agents discover data via a Recall-Rank pipeline, negotiate prices through bonding curves, and settle transactions with escrow-protected OAS tokens.',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # verify setup\n3. oasyce start           # launch node + dashboard\n4. Open http://localhost:8420',
      'about-arch': 'Core Layers:\n\u2022 Schema Registry \u2014 unified validation for data/capability/oracle/identity\n\u2022 Engine Pipeline \u2014 Scan \u2192 Classify \u2192 Metadata \u2192 PoPc Certificate \u2192 Register\n\u2022 Discovery \u2014 Recall (broad retrieval) \u2192 Rank (trust + economics) + feedback loop\n\u2022 Settlement \u2014 bonding curve pricing, escrow, share distribution\n\u2022 Access Control \u2014 L0 metadata / L1 sample / L2 compute / L3 full\n\u2022 P2P Network \u2014 Ed25519 identity, gossip sync, PoS consensus\n\u2022 Risk Engine \u2014 auto-classification (public / internal / sensitive)',
      'about-econ': 'Token: OAS\n\nPricing: Bonding curve (reserve ratio 0.35) \u2014 more buyers = higher price\nShares: Early buyers earn more (diminishing: 100% \u2192 80% \u2192 60% \u2192 40%)\nRights multiplier: original 1.0x / co_creation 0.9x / licensed 0.7x / collection 0.3x\nStaking: Validators stake OAS to produce blocks and earn rewards\nBlock reward: 4.0 OAS (mainnet), halving every ~1M blocks\nEscrow: Funds locked before execution, released after quality verification',
      'about-update': 'Update:\n  pip install --upgrade oasyce\n\nBuild from source:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\nRun tests:\n  python -m pytest tests/ -v\n\nContribute: Fork \u2192 Branch \u2192 PR (see CONTRIBUTING.md)',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Full protocol design and economics paper',
      'link-docs': 'Protocol Overview',
      'link-docs-d': 'Technical reference, API, and architecture',
      'link-github-project': 'GitHub (Project)',
      'link-github-project-d': 'Specs, docs, and roadmap',
      'link-github-engine': 'GitHub (Engine)',
      'link-github-engine-d': 'Plugin engine source code',
      'link-discord': 'Discord Community',
      'link-discord-d': 'Chat, support, and governance',
      'link-contact': 'Contact',
    },
    zh: {
      'pg-register-title': '注册数据资产',
      'pg-register-desc': '确立文件的归属权。注册后，其他代理可以发现、报价和购买访问权限。',
      'pg-trade-title': '交易',
      'pg-trade-desc': '报价并购买数据资产份额。购买即获得访问权和收益分成。',
      'pg-assets-title': '我的资产',
      'pg-assets-desc': '管理已注册的数据资产。点击任意资产查看详情。',
      'pg-agents-title': '代理协议',
      'pg-agents-desc': '在 AHRP 网络注册你的代理，发现数据提供者，执行交易。',
      'pg-network-title': '网络',
      'pg-network-desc': '节点状态与验证者信息。',
      'reg-path-ph': '文件路径',
      'drop-text': '拖拽文件到这里，或 <label for="file-pick" class="drop-link">浏览选择</label>',
      'drop-hint': '注册你的文件，在 Oasyce 网络上确立数据归属权',
      'hint-file': '已从拖入的文件自动填写',
      'hint-owner': '数据所有者。留空则默认使用你的节点 ID。',
      'hint-tags': '帮助其他代理发现你的资产。用逗号分隔关键词。',
      'optional': '可选',
      'reg-owner-ph': '所有者名称或代理 ID',
      'reg-tags-ph': '标签，用逗号分隔',
      'lbl-rights-type': '权利类型',
      'lbl-co-creators': '共创者',
      'hint-co-creators': '至少2个共创者，份额合计100%',
      'rights-original': '原创', 'rights-co_creation': '共创', 'rights-licensed': '授权转售', 'rights-collection': '个人收藏',
      'disputed': '争议中', 'dispute-btn': '发起争议', 'dispute-reason-ph': '争议原因', 'dispute-submit': '提交', 'delisted': '已下架', 'dispute-resolved': '已裁决', 'dispute-dismissed': '已驳回', 'remedy-delist': '下架', 'remedy-transfer': '转移所有权', 'remedy-rights_correction': '更正权利', 'remedy-share_adjustment': '调整份额', 'drop-hint-unified': '拖入文件或文件夹，或点击选择', 'pick-file': '文件', 'pick-folder': '文件夹', 'register-data': '注册数据', 'publish-cap': '发布能力', 'cap-name': '名称', 'cap-provider': '提供者', 'cap-base-price': '基础价格 (OAS)', 'cap-published': '已发布',
      'reg-btn': '注册',
      'buy-asset-ph': '粘贴资产 ID',
      'quote-btn': '报价',
      'buy-btn': '购买',
      'card-buy': '购买份额',
      'hint-buy-asset': '从资产页复制，或从数据创建者处获取。',
      'hint-buy-amount': '你愿意花多少 OAS。',
      'card-portfolio': '持仓',
      'card-stake': '质押',
      'stake-node-ph': '验证者节点 ID',
      'stake-btn': '质押',
      'search-ph': '按 ID 或标签搜索...',
      'card-announce': '注册代理',
      'announce-btn': '广播',
      'card-discover': '发现代理',
      'find-btn': '查找',
      'card-tx': '交易流程',
      'accept-btn': '接受并创建',
      'deliver-btn': '交付',
      'confirm-btn': '确认并结算',
      'card-node': '节点',
      'card-validators': '验证者',
      'card-watermark': '水印',
      'embed-btn': '嵌入',
      'trace-btn': '追溯',
      'lookup-btn': '查询',
      'lbl-file': '文件路径',
      'lbl-owner': '所有者',
      'lbl-tags': '标签',
      'lbl-asset-id': '资产 ID',
      'lbl-amount': '数量（OAS）',
      'lbl-node-id': '节点 ID',
      'empty-assets': '暂无资产。前往 <strong>注册</strong> 添加你的第一个资产。',
      'empty-portfolio': '暂无持仓',
      'stat-assets': '资产',
      'stat-blocks': '区块',
      'stat-watermarks': '水印',
      'lang-btn': 'En',
      'card-identity': '你的身份',
      'no-identity': '未找到密钥。运行 <code>oasyce start</code> 生成你的身份。',
      'id-hint': '这是你在 Oasyce 网络上的唯一身份。你注册的每个资产都会用你的私钥进行密码学签名。',
      'id-backup': '&#9888; 请备份 <code>~/.oasyce/keys/</code> 目录 —— 丢失密钥意味着永久失去所有已注册资产的控制权。',
      'copied': '已复制',
      'auto-default': '自动',
      'loading-identity': '加载中...',
      'about-title': '关于 Oasyce',
      'about-version': 'v1.5.0',
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'tab-overview': '概览',
      'tab-start': '快速开始',
      'tab-arch': '技术架构',
      'tab-econ': '经济模型',
      'tab-update': '维护更新',
      'tab-links': '链接',
      'about-how': 'Oasyce 是一个去中心化协议，AI 代理在其中自主注册、发现、许可和结算数据权利。数据所有者注册文件并获得加密来源证明证书 (PoPc)。AI 代理通过 Recall-Rank 管道发现数据，通过联合曲线协商价格，并使用托管保护的 OAS 代币进行结算。',
      'about-quickstart': '1. pip install oasyce\n2. oasyce doctor          # 验证安装\n3. oasyce start           # 启动节点 + 仪表盘\n4. 浏览器打开 http://localhost:8420',
      'about-arch': '核心层级:\n\u2022 Schema Registry \u2014 统一验证 data/capability/oracle/identity 四种资产\n\u2022 引擎管道 \u2014 扫描 \u2192 分类 \u2192 元数据 \u2192 PoPc 证书 \u2192 注册\n\u2022 发现引擎 \u2014 Recall (广召回) \u2192 Rank (信任+经济) + 反馈循环\n\u2022 结算引擎 \u2014 联合曲线定价、托管、份额分配\n\u2022 访问控制 \u2014 L0 元数据 / L1 采样 / L2 计算 / L3 完整\n\u2022 P2P 网络 \u2014 Ed25519 身份、gossip 同步、PoS 共识\n\u2022 风险引擎 \u2014 自动分级 (public / internal / sensitive)',
      'about-econ': '代币: OAS\n\n定价: 联合曲线 (储备率 0.35) \u2014 买家越多价格越高\n份额: 早期买家获利更多 (递减: 100% \u2192 80% \u2192 60% \u2192 40%)\n权利系数: 原创 1.0x / 共创 0.9x / 授权 0.7x / 收藏 0.3x\n质押: 验证者质押 OAS 出块并获得奖励\n区块奖励: 4.0 OAS (主网)，每约 100 万块减半\n托管: 执行前锁定资金，质量验证后释放',
      'about-update': '更新:\n  pip install --upgrade oasyce\n\n从源码构建:\n  git clone <engine-repo>\n  cd Oasyce_Claw_Plugin_Engine && pip install -e .\n\n运行测试:\n  python -m pytest tests/ -v\n\n贡献: Fork \u2192 Branch \u2192 PR (详见 CONTRIBUTING.md)',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '完整协议设计与经济模型论文',
      'link-docs': '协议概览',
      'link-docs-d': '技术参考、API 与架构',
      'link-github-project': 'GitHub (项目)',
      'link-github-project-d': '规范、文档与路线图',
      'link-github-engine': 'GitHub (引擎)',
      'link-github-engine-d': '插件引擎源代码',
      'link-discord': 'Discord 社区',
      'link-discord-d': '聊天、支持与治理',
      'link-contact': '联系我们',
    }
  };

  function applyLang() {
    var t = _t[_lang];
    // Nav links
    document.querySelectorAll('.nav-link').forEach(function(el){
      el.textContent = el.getAttribute('data-'+_lang) || el.textContent;
    });
    // Lang button
    document.getElementById('lang-btn').textContent = t['lang-btn'];
    // Page titles & descs
    ['register','trade','assets','agents','network'].forEach(function(pg){
      var title = document.querySelector('#pg-'+pg+' .page-title');
      var desc = document.querySelector('#pg-'+pg+' .page-desc');
      if(title) title.textContent = t['pg-'+pg+'-title'] || title.textContent;
      if(desc) desc.textContent = t['pg-'+pg+'-desc'] || desc.textContent;
    });
    // Stat labels
    var statLabels = document.querySelectorAll('.stat-l');
    if(statLabels[0]) statLabels[0].textContent = t['stat-assets'];
    if(statLabels[1]) statLabels[1].textContent = t['stat-blocks'];
    if(statLabels[2]) statLabels[2].textContent = t['stat-watermarks'];
    // Buttons
    document.getElementById('reg-btn').textContent = t['reg-btn'];
    document.getElementById('quote-btn').textContent = t['quote-btn'];
    document.getElementById('buy-btn').textContent = t['buy-btn'];
    document.getElementById('stake-btn').textContent = t['stake-btn'];
    document.getElementById('ahrp-announce-btn').textContent = t['announce-btn'];
    document.getElementById('ahrp-find-btn').textContent = t['find-btn'];
    document.getElementById('tx-accept-btn').textContent = t['accept-btn'];
    document.getElementById('tx-deliver-btn').textContent = t['deliver-btn'];
    document.getElementById('tx-confirm-btn').textContent = t['confirm-btn'];
    document.getElementById('emb-btn').textContent = t['embed-btn'];
    document.getElementById('fp-trace-btn').textContent = t['trace-btn'];
    document.getElementById('fp-list-btn').textContent = t['lookup-btn'];
    // Placeholders
    document.getElementById('reg-path').placeholder = t['reg-path-ph'];
    document.getElementById('reg-owner').placeholder = t['reg-owner-ph'];
    document.getElementById('reg-tags').placeholder = t['reg-tags-ph'];
    document.getElementById('buy-asset').placeholder = t['buy-asset-ph'];
    document.getElementById('stake-node').placeholder = t['stake-node-ph'];
    document.getElementById('asset-search').placeholder = t['search-ph'];
    // Card titles
    var cardTitles = document.querySelectorAll('.card-title');
    var cardMap = ['card-buy','card-portfolio','card-stake','card-announce','card-discover','card-tx','card-node','','card-watermark'];
    cardTitles.forEach(function(el,i){if(cardMap[i]&&t[cardMap[i]])el.textContent=t[cardMap[i]];});
    // Field labels
    var labels = document.querySelectorAll('.field-label');


  }

  // Lang toggle
  document.getElementById('lang-btn').addEventListener('click', function(){
    _lang = _lang === 'en' ? 'zh' : 'en';
    applyLang();
  });

  // About panel — tabbed info hub for all audiences
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'<span class="about-version">'+t['about-version']+'</span></h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<div class="about-tabs">'+
        '<button class="about-tab active" data-about-tab="overview">'+t['tab-overview']+'</button>'+
        '<button class="about-tab" data-about-tab="start">'+t['tab-start']+'</button>'+
        '<button class="about-tab" data-about-tab="arch">'+t['tab-arch']+'</button>'+
        '<button class="about-tab" data-about-tab="econ">'+t['tab-econ']+'</button>'+
        '<button class="about-tab" data-about-tab="update">'+t['tab-update']+'</button>'+
        '<button class="about-tab" data-about-tab="links">'+t['tab-links']+'</button>'+
      '</div>'+
      '<div class="about-section active" data-about-section="overview">'+
        '<p>'+t['about-how']+'</p>'+
      '</div>'+
      '<div class="about-section" data-about-section="start">'+
        '<pre>'+t['about-quickstart']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="arch">'+
        '<pre>'+t['about-arch']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="econ">'+
        '<pre>'+t['about-econ']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="update">'+
        '<pre>'+t['about-update']+'</pre>'+
      '</div>'+
      '<div class="about-section" data-about-section="links">'+
        '<ul class="about-links">'+
          '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github-project']+'</div><div class="link-desc">'+t['link-github-project-d']+'</div></div></a></li>'+
          '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine" target="_blank"><div><div class="link-label">'+t['link-github-engine']+'</div><div class="link-desc">'+t['link-github-engine-d']+'</div></div></a></li>'+
          '<li><a href="https://discord.gg/oasyce" target="_blank"><div><div class="link-label">'+t['link-discord']+'</div><div class="link-desc">'+t['link-discord-d']+'</div></div></a></li>'+
        '</ul>'+
        '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>'+
      '</div>';
    document.body.appendChild(overlay);
    // Tab switching
    overlay.querySelectorAll('.about-tab').forEach(function(tab){
      tab.addEventListener('click',function(){
        overlay.querySelectorAll('.about-tab').forEach(function(t){t.classList.remove('active');});
        overlay.querySelectorAll('.about-section').forEach(function(s){s.classList.remove('active');});
        tab.classList.add('active');
        var sec=overlay.querySelector('[data-about-section="'+tab.dataset.aboutTab+'"]');
        if(sec)sec.classList.add('active');
      });
    });
  });


  try{var saved=localStorage.getItem('oasyce-lang');if(saved)_lang=saved;}catch(e){}
  applyLang();

  loadStatus();
  setInterval(loadStatus,30000);
})();
</script>
</body>
</html>"""


# ── GUI class ────────────────────────────────────────────────────────


class OasyceGUI:
    """Zero-dependency web dashboard for Oasyce nodes."""

    def __init__(
        self,
        config: Optional[Config] = None,
        ledger: Optional[Ledger] = None,
        host: str = "127.0.0.1",
        port: int = 8420,
    ):
        self._config = config or Config.from_env()
        if ledger is not None:
            self._ledger = ledger
        else:
            self._ledger = Ledger(self._config.db_path)
        self._host = host
        self._port = port

    def run(self) -> None:
        global _ledger, _config, _api_token
        _ledger = self._ledger
        _config = self._config

        # Generate API token for this session
        _api_token = secrets.token_urlsafe(32)
        token_path = os.path.join(self._config.data_dir, "api_token")
        os.makedirs(self._config.data_dir, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(_api_token)
        os.chmod(token_path, 0o600)

        # Fix sqlite3 for multi-threaded server
        import sqlite3

        if hasattr(_ledger, "_conn") and _ledger._conn:
            db_path = _ledger.db_path
            _ledger._conn.close()
            _ledger._conn = sqlite3.connect(db_path, check_same_thread=False)
            _ledger._conn.row_factory = sqlite3.Row
            _ledger._conn.execute("PRAGMA journal_mode=WAL")

        import socket

        class _ReusableHTTPServer(ThreadingMixIn, HTTPServer):
            allow_reuse_address = True
            daemon_threads = True

            def server_bind(self):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except (AttributeError, OSError):
                    pass
                super().server_bind()

        # Try binding to the requested port, fall back to alternatives
        server = None
        bound_port = self._port
        for attempt_port in [self._port] + list(range(self._port + 1, self._port + 10)):
            try:
                server = _ReusableHTTPServer((self._host, attempt_port), _Handler)
                bound_port = attempt_port
                break
            except OSError:
                if attempt_port == self._port:
                    print(f"⚠️  Port {self._port} is busy, trying alternatives...")
                continue

        if server is None:
            print(f"❌ Could not bind to any port in range {self._port}-{self._port + 9}.")
            print(f"   Try: oasyce gui --port <available_port>")
            return

        if bound_port != self._port:
            print(f"⚠️  Port {self._port} was busy, using {bound_port} instead.")
        print(f"Oasyce Dashboard running on http://127.0.0.1:{bound_port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down dashboard.")
            server.server_close()


if __name__ == "__main__":
    OasyceGUI().run()

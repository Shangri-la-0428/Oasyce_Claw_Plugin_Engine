"""
Oasyce Web Dashboard — zero-dependency SPA served via Python stdlib.

Serves on port 8420. All HTML/CSS/JS is embedded in this single file.
Reads chain data from the local Ledger database.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import mimetypes
import os
import re
import secrets
import sqlite3
import struct
import threading
import time
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from socketserver import ThreadingMixIn
from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError

from oasyce.config import Config
from oasyce.storage.ledger import Ledger
from oasyce.fingerprint import FingerprintRegistry

logger = logging.getLogger(__name__)

# C3: Maximum POST body size (10 MB)
MAX_POST_BODY = 10 * 1024 * 1024


# ── Shared state (set by OasyceGUI before server starts) ─────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DASHBOARD_DIR = os.path.join(_PROJECT_ROOT, "dashboard", "dist")

_ledger: Optional[Ledger] = None
_config: Optional[Config] = None
_settlement: Any = None
_facade: Any = None
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
_feedback_db_conn: Any = None

# M3: Locks for lazy-init globals
_init_lock = threading.Lock()
_facade_lock = threading.Lock()
_cap_lock = threading.Lock()
_delivery_lock = threading.Lock()
_discovery_lock = threading.Lock()
_staking_lock = threading.Lock()
_skills_lock = threading.Lock()

# C2: Thread pool for PoW computation
_pow_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pow")


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


def _get_feedback_db():
    """Lazy-init feedback SQLite database."""
    global _feedback_db_conn
    if _feedback_db_conn is None:
        data_dir = _config.data_dir if _config else os.path.join(os.path.expanduser("~"), ".oasyce")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "feedback.db")
        _feedback_db_conn = sqlite3.connect(db_path, check_same_thread=False)
        _feedback_db_conn.row_factory = sqlite3.Row
        _feedback_db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                feedback_id TEXT PRIMARY KEY,
                type        TEXT NOT NULL DEFAULT 'bug',
                message     TEXT NOT NULL,
                context     TEXT DEFAULT '{}',
                agent_id    TEXT DEFAULT '',
                status      TEXT DEFAULT 'open',
                created_at  REAL NOT NULL
            )
        """
        )
        _feedback_db_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback (created_at DESC)"
        )
        _feedback_db_conn.commit()
    return _feedback_db_conn


def _forward_feedback_webhook(fb: dict):
    """Best-effort forward feedback to webhook URL (Discord/Slack)."""
    url = os.getenv("OASYCE_FEEDBACK_WEBHOOK", "")
    if not url:
        return
    try:
        import urllib.request
        label = {"bug": "🐛 Bug", "suggestion": "💡 Suggestion", "other": "📝 Other"}.get(fb.get("type", ""), "📝")
        text = f"**{label}** from `{fb.get('agent_id', 'anonymous')}`\n{fb['message']}"
        payload = json.dumps({"content": text}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        logger.debug("Feedback webhook forwarding failed", exc_info=True)


def _forward_feedback_github(fb: dict):
    """Best-effort create GitHub issue from feedback."""
    token = os.getenv("OASYCE_GITHUB_TOKEN", "")
    repo = os.getenv("OASYCE_GITHUB_REPO", "")
    if not token or not repo:
        return
    try:
        import urllib.request
        label_map = {"bug": "bug", "suggestion": "enhancement", "other": "feedback"}
        title = fb["message"][:80]
        if len(fb["message"]) > 80:
            title += "…"
        body_parts = [
            f"**Type:** {fb.get('type', 'bug')}",
            f"**Agent:** `{fb.get('agent_id', 'anonymous')}`",
            f"**Feedback ID:** `{fb.get('feedback_id', '')}`",
            "",
            fb["message"],
        ]
        ctx = fb.get("context")
        if ctx and ctx != "{}":
            body_parts += ["", "### Context", f"```json\n{ctx}\n```"]
        payload = json.dumps({
            "title": title,
            "body": "\n".join(body_parts),
            "labels": [label_map.get(fb.get("type", ""), "feedback")],
        }).encode("utf-8")
        url = f"https://api.github.com/repos/{repo}/issues"
        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        })
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read().decode("utf-8")).get("html_url", "")
    except Exception:
        logger.debug("GitHub issue creation failed", exc_info=True)
        return None


def _default_identity() -> str:
    """Return the wallet address if available, otherwise 'anonymous'."""
    try:
        from oasyce.identity import Wallet

        return Wallet.get_address() or "anonymous"
    except Exception:
        logger.debug("Failed to get wallet address", exc_info=True)
        return "anonymous"


# ── Security: API token + rate limiting ──────────────────────────────
_api_token: str = ""

# Rate limiter: {ip: [(timestamp, ...)] }
_rate_limits: Dict[str, list] = defaultdict(list)
_rate_lock = threading.Lock()
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 60  # max requests per window for mutating endpoints

# Anti-wash-trading cooldown: {(buyer, asset_id): last_buy_timestamp}
_buy_cooldowns: Dict[tuple, float] = {}
_buy_lock = threading.Lock()
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
    with _rate_lock:
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
    """Return the settlement engine shared with the facade (single source of truth)."""
    global _settlement
    if _settlement is None:
        _settlement = _get_facade()._get_settlement()
    return _settlement


def _ensure_init():
    """Auto-initialize _config and _ledger if not set by DashboardServer.run()."""
    global _config, _ledger
    with _init_lock:
        if _config is None:
            from oasyce.config import Config
            _config = Config.from_env()
        if _ledger is None:
            _ledger = Ledger(_config.db_path)


def _get_facade():
    global _facade
    if _facade is not None:
        return _facade
    with _facade_lock:
        if _facade is None:
            _ensure_init()
            from oasyce.services.facade import OasyceServiceFacade

            _facade = OasyceServiceFacade(
                config=_config,
                ledger=_ledger,
            )
    return _facade


_query_view = None


def _get_query():
    """Read-only facade view for GET handlers — cannot call buy/sell/register."""
    global _query_view
    if _query_view is None:
        from oasyce.services.facade import OasyceQuery

        _query_view = OasyceQuery(_get_facade())
    return _query_view


def _get_staking():
    global _staking
    if _staking is not None:
        return _staking
    with _staking_lock:
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
    if _delivery_protocol is not None:
        return _delivery_protocol, _delivery_registry, _delivery_escrow
    with _delivery_lock:
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
    if _cap_registry is not None:
        return _cap_registry, _cap_escrow, _cap_shares, _cap_engine
    with _cap_lock:
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
    if _skills is not None:
        return _skills
    with _skills_lock:
        if _skills is None:
            _ensure_init()
            from oasyce.skills.agent_skills import OasyceSkills

            _skills = OasyceSkills(_config)
    return _skills


def _get_discovery():
    global _discovery
    if _discovery is not None:
        return _discovery
    with _discovery_lock:
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
                            "intents": m.tags,
                            "semantic_vector": m.semantic_vector,
                            "base_price": m.pricing.base_price if m.pricing else 1.0,
                        }
                        for m in caps
                    ]
                except Exception:
                    logger.debug("Failed to list capabilities for discovery", exc_info=True)
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


# C1: Multipart parser to replace deprecated cgi.FieldStorage (removed in Python 3.13)

class _MultipartFile:
    """A single file from a multipart upload."""
    __slots__ = ("filename", "file")
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.file = BytesIO(data)


class _MultipartForm:
    """Minimal multipart/form-data parser (stdlib only, no cgi)."""

    def __init__(self, handler: BaseHTTPRequestHandler, content_type: str):
        self._fields: Dict[str, list] = defaultdict(list)
        self._files: Dict[str, list] = defaultdict(list)
        # Extract boundary
        m = re.search(r'boundary=([^\s;]+)', content_type)
        if not m:
            return
        boundary = m.group(1).encode("utf-8")
        length = int(handler.headers.get("Content-Length", 0))
        raw = handler.rfile.read(length) if length else b""
        # Parse parts
        delimiter = b"--" + boundary
        parts = raw.split(delimiter)
        for part in parts[1:]:  # skip preamble
            if part.startswith(b"--"):
                break  # epilogue
            if b"\r\n\r\n" not in part:
                continue
            header_block, body = part.split(b"\r\n\r\n", 1)
            if body.endswith(b"\r\n"):
                body = body[:-2]
            headers_str = header_block.decode("utf-8", errors="replace")
            disp_match = re.search(r'name="([^"]*)"', headers_str)
            if not disp_match:
                continue
            name = disp_match.group(1)
            fname_match = re.search(r'filename="([^"]*)"', headers_str)
            if fname_match:
                fname = fname_match.group(1)
                self._files[name].append(_MultipartFile(fname, body))
            else:
                self._fields[name].append(body.decode("utf-8", errors="replace"))

    def getfirst(self, name: str, default: str = "") -> str:
        vals = self._fields.get(name, [])
        return vals[0] if vals else default

    def get_file(self, name: str) -> Optional[_MultipartFile]:
        files = self._files.get(name, [])
        return files[0] if files else None

    def get_files(self, name: str) -> list:
        return self._files.get(name, [])

    def __contains__(self, name: str) -> bool:
        return name in self._fields or name in self._files


def _serve_static(handler, file_path):
    """Serve a static file from dashboard/dist/"""
    canonical = os.path.realpath(file_path)
    dashboard_canonical = os.path.realpath(DASHBOARD_DIR)
    if not canonical.startswith(dashboard_canonical + os.sep) and canonical != dashboard_canonical:
        handler.send_error(403)
        return
    if not os.path.isfile(file_path):
        handler.send_error(404)
        return
    mime, _ = mimetypes.guess_type(file_path)
    if mime is None:
        mime = "application/octet-stream"
    # L4: add charset for text types
    if mime and mime.startswith("text/") and "charset" not in mime:
        mime += "; charset=utf-8"
    with open(file_path, "rb") as f:
        body = f.read()
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "public, max-age=31536000, immutable")
    handler.end_headers()
    handler.wfile.write(body)


# Files served from project root for agent discovery (llms.txt, openapi.yaml)
_AGENT_DISCOVERY_FILES: Dict[str, str] = {
    "/llms.txt": "llms.txt",
    "/openapi.yaml": "openapi.yaml",
    "/.well-known/ai-plugin.json": os.path.join(".well-known", "ai-plugin.json"),
}

def _serve_project_file(handler, filename):
    """Serve a file from the project root directory."""
    file_path = os.path.join(_PROJECT_ROOT, filename)
    canonical = os.path.realpath(file_path)
    root_canonical = os.path.realpath(_PROJECT_ROOT)
    if not canonical.startswith(root_canonical + os.sep):
        handler.send_error(403)
        return
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
    handler.send_header("Cache-Control", "public, max-age=300")
    handler.end_headers()
    handler.wfile.write(body)


# ── API helpers ──────────────────────────────────────────────────────


def _api_status() -> Dict[str, Any]:
    if not _config:
        return {"error": "not initialized"}
    q = _get_query()
    result = q.query_chain_status()
    if not result.success:
        return {"error": result.error or "not initialized"}
    data = result.data
    node_id = (_config.public_key or "unknown")[:16]
    return {
        "node_id": node_id,
        "host": _config.node_host,
        "port": _config.node_port,
        "chain_height": data.get("chain_height", 0),
        "total_assets": data.get("total_assets", 0),
        "total_blocks": data.get("chain_height", 0),
        "total_distributions": data.get("total_distributions", 0),
        **{k: data[k] for k in ("total_burned", "protocol_fees_collected", "burn_rate_pct", "protocol_fee_pct") if k in data},
    }


def _api_blocks(limit: int = 20) -> list:
    return _get_query().query_blocks(limit=limit).data or []


def _api_block(n: int) -> Optional[Dict[str, Any]]:
    result = _get_query().query_block(n)
    return result.data if result.success else None


def _api_assets() -> list:
    return _get_query().query_assets().data or []


def _api_fingerprints(asset_id: str) -> list:
    return _get_query().query_fingerprints(asset_id).data or []


def _api_trace(fp: str) -> Optional[Dict[str, Any]]:
    result = _get_query().query_trace(fp)
    return result.data if result.success else None


def _api_stakes() -> list:
    return _get_query().query_stakes().data or []


# ── Capability API helpers ───────────────────────────────────────────


def _api_capabilities() -> list:
    """List all registered capabilities (merged from both registries)."""
    registry, _, shares, _ = _get_cap_stack()
    seen_ids: set = set()
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
        seen_ids.add(m.capability_id)

    # Merge delivery registry entries (capabilities registered via GUI)
    try:
        for ep in _api_delivery_endpoints():
            cid = ep.get("capability_id", "")
            if cid and cid not in seen_ids:
                results.append(
                    {
                        "asset_type": "capability",
                        "asset_id": cid,
                        "name": ep.get("name", ""),
                        "description": ep.get("description", ""),
                        "version": "1.0.0",
                        "provider": ep.get("provider_id", ""),
                        "tags": ep.get("tags", []),
                        "status": ep.get("status", "active"),
                        "spot_price": round(ep.get("price_per_call", 0) / 1e8, 6),
                        "created_at": ep.get("created_at", 0),
                        "input_schema": ep.get("input_schema", {}),
                        "output_schema": ep.get("output_schema", {}),
                    }
                )
                seen_ids.add(cid)
    except Exception:
        logger.debug("Delivery registry unavailable during capability listing", exc_info=True)

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
    {"ok": False, "error": "AHRP node not running. Start with: oas serve"}
).encode("utf-8")


def _proxy_ahrp(handler: BaseHTTPRequestHandler, method: str, path: str, body: bytes = b"") -> None:
    # Sanitize: reject path traversal and non-AHRP paths
    from posixpath import normpath
    clean = normpath(path)
    if ".." in clean or not clean.startswith("/ahrp/"):
        handler.send_response(400)
        msg = b'{"error":"invalid proxy path"}'
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(msg)))
        handler.end_headers()
        handler.wfile.write(msg)
        return
    url = _AHRP_CORE_BASE + clean
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
            try:
                limit = int(qs.get("limit", ["20"])[0])
            except (ValueError, TypeError):
                return _json_response(self, {"error": "invalid limit"}, 400)
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
            try:
                limit = int(qs.get("limit", ["10"])[0])
            except (ValueError, TypeError):
                return _json_response(self, {"error": "invalid limit"}, 400)
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

        # /api/staking — frontend expects {validators: [{id, staked, reputation}]}
        if path == "/api/staking":
            stakes = _api_stakes()
            validators = [
                {"id": s["validator_id"], "staked": s["total"], "reputation": 50}
                for s in stakes
            ]
            return _json_response(self, {"validators": validators})

        # /api/shares — frontend expects [{asset_id, shares, avg_price}]
        if path == "/api/shares":
            owner = qs.get("owner", [_default_identity()])[0]
            q = _get_query()
            result = q.get_portfolio(owner)
            holdings = []
            if result.success:
                for h in result.data.get("holdings", []):
                    holdings.append({
                        "asset_id": h["asset_id"],
                        "shares": round(h["tokens"], 4),
                        "avg_price": round(h["value_oas"] / h["tokens"], 6) if h["tokens"] > 0 else 0,
                    })
            return _json_response(self, holdings)

        # /api/fingerprint/distributions — trace watermark distribution for an asset
        if path == "/api/fingerprint/distributions":
            asset_id = qs.get("asset_id", [""])[0]
            if not asset_id:
                return _json_response(self, {"error": "asset_id required"}, 400)
            result = _get_query().query_fingerprints(asset_id)
            fps = result.data if result.success else []
            return _json_response(self, {"asset_id": asset_id, "distributions": fps})

        # ── Capability routes (GET) ──────────────────────────────
        if path == "/api/capabilities":
            try:
                return _json_response(self, _api_capabilities())
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, 500)

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
            try:
                limit = int(qs.get("limit", ["50"])[0])
            except (ValueError, TypeError):
                return _json_response(self, {"error": "invalid limit"}, 400)
            return _json_response(self, _api_delivery_endpoints(provider, tag, limit))

        if path == "/api/delivery/earnings":
            provider = qs.get("provider", [None])[0]
            consumer = qs.get("consumer", [None])[0]
            return _json_response(self, _api_delivery_earnings(provider, consumer))

        if path == "/api/delivery/invocations":
            consumer = qs.get("consumer", [None])[0]
            provider = qs.get("provider", [None])[0]
            try:
                limit = int(qs.get("limit", ["20"])[0])
            except (ValueError, TypeError):
                return _json_response(self, {"error": "invalid limit"}, 400)
            return _json_response(self, _api_delivery_invocations(consumer, provider, limit))

        # Asset detail
        m = re.match(r"^/api/asset/([^/]+)$", path)
        if m:
            aid = m.group(1)
            result = _get_query().get_asset(aid)
            if not result.success:
                return _json_response(self, {"error": result.error or "not found"}, 404)
            return _json_response(self, result.data)

        # ── Tiered access quote (L0-L3 bond pricing) — via shared facade ──
        if path == "/api/access/quote":
            asset_id = qs.get("asset_id", [""])[0]
            buyer = qs.get("buyer", [_default_identity()])[0]
            if not asset_id:
                return _json_response(self, {"error": "asset_id required"}, 400)
            try:
                q = _get_query()
                result = q.access_quote(asset_id, buyer)
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
                        "reputation": result.data.get("reputation", 0),
                        "max_access_level": result.data.get("max_access_level", "L0"),
                        "risk_level": result.data.get("risk_level", "low"),
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # Sell quote (read-only preview)
        if path == "/api/sell/quote":
            asset_id = qs.get("asset_id", [""])[0]
            seller = qs.get("seller", [_default_identity()])[0]
            try:
                tokens = float(qs.get("tokens", ["0"])[0])
            except (ValueError, TypeError):
                return _json_response(self, {"error": "invalid tokens value"}, 400)
            if not asset_id:
                return _json_response(self, {"error": "asset_id required"}, 400)
            if tokens <= 0:
                return _json_response(self, {"error": "tokens must be positive"}, 400)
            try:
                result = _get_query().sell_quote(asset_id, seller, tokens)
                if not result.success:
                    return _json_response(self, {"error": result.error}, 400)
                d = result.data
                return _json_response(self, {
                    "payout_oas": round(d.get("payout_oas", 0), 6),
                    "protocol_fee": round(d.get("protocol_fee", 0), 6),
                    "burn_amount": round(d.get("burn_amount", 0), 6),
                    "price_impact_pct": round(d.get("price_impact_pct", 0), 2),
                })
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # Bancor quote
        if path == "/api/quote":
            asset_id = qs.get("asset_id", [""])[0]
            try:
                amount = float(qs.get("amount", ["10"])[0])
            except (ValueError, TypeError):
                return _json_response(self, {"error": "invalid amount"}, 400)
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

                result = _get_query().quote(asset_id, amount)
                if not result.success:
                    return _json_response(self, {"error": result.error}, 400)

                d = result.data
                price_before = round(d.get("spot_price_before", 0), 6)
                price_after = round(d.get("spot_price_after", 0), 6)

                # Floor price: enforce manual_price as minimum
                if asset_price_model == "floor" and asset_manual_price is not None:
                    floor = float(asset_manual_price)
                    price_before = max(price_before, floor)
                    price_after = max(price_after, floor)

                resp = {
                    "asset_id": d.get("asset_id", asset_id),
                    "payment": d.get("payment_oas", 0),
                    "tokens": round(d.get("equity_minted", 0), 4),
                    "price_before": price_before,
                    "price_after": price_after,
                    "impact_pct": round(d.get("price_impact_pct", 0), 2),
                    "fee": round(d.get("protocol_fee", 0), 4),
                    "burn": round(d.get("burn_amount", 0), 4),
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
            result = _get_query().get_portfolio(buyer)
            holdings = []
            if result.success:
                for h in result.data.get("holdings", []):
                    holdings.append({
                        "asset_id": h["asset_id"],
                        "shares": round(h["tokens"], 4),
                        "equity_pct": h.get("pct", 0),
                        "access_level": h.get("access_level") or "—",
                        "spot_price": round(h["value_oas"] / h["tokens"], 6) if h["tokens"] > 0 else 0,
                        "value_oas": round(h["value_oas"], 4),
                    })
            return _json_response(self, holdings)

        # Transaction history
        if path == "/api/transactions":
            result = _get_query().query_transactions(limit=50)
            txs = result.data if result.success else []
            return _json_response(self, list(reversed(txs)))

        if path == "/api/asset/versions":
            aid = qs.get("asset_id", [None])[0]
            if not aid:
                return _json_response(self, {"error": "asset_id required"}, 400)
            facade = _get_facade()
            if not facade:
                return _json_response(self, {"error": "service unavailable"}, 503)
            result = facade.get_asset_versions(aid)
            if result.success:
                # Flatten for frontend: [{version, timestamp}, ...]
                raw = result.data.get("versions", [])
                flat = []
                for v in raw:
                    ts = v.get("created_at", "")
                    # Convert SQLite datetime string to unix seconds
                    try:
                        t = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        unix = int(t.timestamp())
                    except (ValueError, AttributeError):
                        unix = 0
                    flat.append({"version": v.get("version", 0), "timestamp": unix})
                return _json_response(self, flat)
            return _json_response(self, {"ok": False, "error": result.error}, 400)

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
                        asset_owner = _ledger.get_asset_owner(r.asset_id)
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
                logger.debug("Delivery stack unavailable for earnings", exc_info=True)

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
                    logger.debug("Failed to read peers.json", exc_info=True)

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
            try:
                status_filter = qs.get("status", [None])[0]
                task_type = qs.get("type", [None])[0]
                try:
                    limit = int(qs.get("limit", ["20"])[0])
                except (ValueError, TypeError):
                    return _json_response(self, {"error": "invalid limit"}, 400)
                tasks = engine.list_tasks(status=status_filter, task_type=task_type, limit=limit)
                return _json_response(self, {"tasks": [t.to_dict() for t in tasks]})
            finally:
                engine.close()

        if path == "/api/work/stats":
            if not _config:
                return _json_response(self, {"error": "not initialized"}, 503)
            from oasyce.services.work_value import WorkValueEngine
            from oasyce.config import load_or_create_node_identity

            db_path = os.path.join(_config.data_dir, "work.db")
            engine = WorkValueEngine(db_path=db_path)
            try:
                _priv, node_id = load_or_create_node_identity(_config.data_dir)
                node_id_short = node_id[:16]
                global_s = engine.global_stats()
                worker_s = engine.worker_stats(node_id_short)
                return _json_response(self, {"global": global_s, "worker": worker_s})
            finally:
                engine.close()

        # ── Auth token (localhost only) ──────────────────────────
        if path == "/api/auth/token":
            client_ip = self.client_address[0]
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                return _json_response(self, {"error": "forbidden"}, 403)
            return _json_response(self, {"token": _api_token})

        # ── Config ───────────────────────────────────────────────
        if path == "/api/config":
            if not _config:
                return _json_response(self, {"error": "not initialized"}, 503)
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

            inbox = ConfirmationInbox(data_dir=_config.data_dir if _config else None)
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
            try:
                from oasyce.services.inbox import ConfirmationInbox

                inbox = ConfirmationInbox(data_dir=_config.data_dir if _config else None)
                return _json_response(
                    self,
                    {
                        "trust_level": inbox.get_trust_level(),
                        "auto_threshold": inbox.get_auto_threshold(),
                    },
                )
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, 500)

        # Consensus & governance GET routes moved to Go chain
        consensus_get_paths = (
            "/api/consensus/status", "/api/consensus/validators", "/api/consensus/rewards",
            "/api/governance/proposals", "/api/governance/params", "/api/consensus/slashing",
            "/api/consensus/sync",
        )
        if path in consensus_get_paths or path.startswith("/api/governance/proposal/"):
            return _json_response(self, {"error": "Consensus features moved to Go chain. Use oasyced CLI."}, 501)

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
            try:
                from oasyce.services.scheduler import get_scheduler

                data_dir = _config.data_dir if _config else None
                scheduler = get_scheduler(data_dir)
                return _json_response(self, scheduler.status())
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, 500)

        if path == "/api/agent/config":
            try:
                from oasyce.services.scheduler import get_scheduler

                data_dir = _config.data_dir if _config else None
                scheduler = get_scheduler(data_dir)
                return _json_response(self, scheduler.get_config().to_dict())
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, 500)

        if path == "/api/agent/history":
            from oasyce.services.scheduler import get_scheduler

            data_dir = _config.data_dir if _config else None
            scheduler = get_scheduler(data_dir)
            try:
                limit = int(qs.get("limit", ["10"])[0])
            except (ValueError, TypeError):
                return _json_response(self, {"error": "invalid limit"}, 400)
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
                logger.debug("Balance query failed for %s", address, exc_info=True)
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
            row = _ledger.get_asset(asset_id)
            # Also check capabilities
            cap_detail = None
            if not row:
                try:
                    cap_detail = _api_capability_detail(asset_id)
                except Exception:
                    logger.debug("Capability detail lookup failed for %s", asset_id, exc_info=True)
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

            # L1+ : verify buyer holds required equity access level
            buyer = qs.get("buyer", [""])[0] or qs.get("agent", [""])[0]
            if not buyer:
                return _json_response(
                    self, {"error": "buyer or agent param required for L1+ preview"}, 400
                )
            q = _get_query()
            if q:
                level_map = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
                required = level_map.get(level_str, 0)
                try:
                    equity_result = q.access_quote(asset_id, buyer)
                    if equity_result.success:
                        max_level = equity_result.data.get("max_level", 0)
                        if isinstance(max_level, str):
                            max_level = level_map.get(max_level, 0)
                        if max_level < required:
                            return _json_response(
                                self,
                                {"error": f"Insufficient access: you have L{max_level}, need {level_str}"},
                                403,
                            )
                except Exception:
                    logger.debug("Equity check unavailable for preview (dev mode)", exc_info=True)

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
                        logger.debug("CSV preview read failed for %s", file_path, exc_info=True)
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
                        logger.debug("Text preview read failed for %s", file_path, exc_info=True)
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

        # ── Disputes API (GET) — routed through facade ─────────────
        if path == "/api/disputes":
            buyer = qs.get("buyer", [""])[0]
            if not buyer:
                return _json_response(self, {"error": "buyer param required"}, 400)
            q = _get_query()
            result = q.query_disputes(buyer=buyer)
            if not result.success:
                return _json_response(self, {"error": result.error}, 500)
            return _json_response(self, {"disputes": result.data})

        m = re.match(r"^/api/dispute/detail/(.+)$", path)
        if m:
            dispute_id = m.group(1)
            q = _get_query()
            result = q.query_disputes(dispute_id=dispute_id)
            if not result.success:
                return _json_response(self, {"error": result.error}, 404)
            return _json_response(self, result.data)

        # ── Notifications API (GET) ───────────────────────────────
        if path == "/api/notifications":
            address = qs.get("address", [""])[0]
            if not address:
                return _json_response(self, {"error": "address param required"}, 400)
            unread_only = qs.get("unread_only", ["false"])[0].lower() == "true"
            try:
                limit = int(qs.get("limit", ["50"])[0])
            except (ValueError, TypeError):
                return _json_response(self, {"error": "invalid limit"}, 400)
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

        # ── Feedback (GET) ──────────────────────────────────────────
        if path == "/api/feedback":
            try:
                db = _get_feedback_db()
                status_filter = qs.get("status", [""])[0]
                type_filter = qs.get("type", [""])[0]
                try:
                    limit = int(qs.get("limit", ["50"])[0])
                except (ValueError, TypeError):
                    limit = 50
                sql = "SELECT * FROM feedback"
                params: list = []
                clauses: list = []
                if status_filter:
                    clauses.append("status = ?")
                    params.append(status_filter)
                if type_filter:
                    clauses.append("type = ?")
                    params.append(type_filter)
                if clauses:
                    sql += " WHERE " + " AND ".join(clauses)
                sql += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)
                rows = db.execute(sql, params).fetchall()
                items = [dict(r) for r in rows]
                return _json_response(self, {"feedback": items})
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)

        # ── Leakage budget query (GET) ────────────────────────────
        if path == "/api/leakage":
            agent_id = qs.get("agent_id", [""])[0]
            asset_id = qs.get("asset_id", [""])[0]
            if not agent_id or not asset_id:
                return _json_response(self, {"error": "agent_id and asset_id required"}, 400)
            q = _get_query()
            result = q.query_leakage(agent_id, asset_id)
            if not result.success:
                return _json_response(self, {"error": result.error}, 500)
            return _json_response(self, result.data)

        # ── Cache stats (GET) ─────────────────────────────────────
        if path == "/api/cache/stats":
            q = _get_query()
            result = q.query_cache_stats()
            if not result.success:
                return _json_response(self, {"error": result.error}, 500)
            return _json_response(self, result.data)

        # ── Task Market (GET) ────────────────────────────────────
        if path == "/api/tasks":
            cap = qs.get("capability", [""])[0]
            q = _get_query()
            caps = [c.strip() for c in cap.split(",") if c.strip()] if cap else None
            result = q.query_tasks(capabilities=caps)
            if not result.success:
                return _json_response(self, {"error": result.error}, 500)
            return _json_response(self, {"tasks": result.data})

        m = re.match(r"^/api/task/([^/]+)$", path)
        if m:
            task_id = m.group(1)
            q = _get_query()
            result = q.query_task(task_id)
            if not result.success:
                return _json_response(self, {"error": result.error}, 404)
            return _json_response(self, result.data)

        # ── Agent discovery files (llms.txt, openapi.yaml) ──────
        if path in _AGENT_DISCOVERY_FILES:
            return _serve_project_file(self, _AGENT_DISCOVERY_FILES[path])

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

        # SPA not built — return simple error
        self.send_response(503)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Dashboard not built. Run: cd dashboard && npm run build")

    # ── POST handler: Identity routes ────────────────────────────
    def _handle_identity(self, path, body, content_type):
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

                # Gate: must complete PoW registration first
                from pathlib import Path as _FcPath

                onboard_path = _FcPath(data_dir) / "onboarding_state.json"
                _registered = set()
                if onboard_path.exists():
                    try:
                        _registered = set(
                            json.loads(onboard_path.read_text()).get("registered", [])
                        )
                    except (json.JSONDecodeError, OSError):
                        pass
                if address not in _registered:
                    return _json_response(
                        self,
                        {"ok": False, "error": "Complete registration first"},
                        403,
                    )

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

        if path == "/api/onboarding/register":
            from oasyce.identity import Wallet as _OnbWallet

            address = _OnbWallet.get_address() if _OnbWallet.exists() else None
            if not address:
                return _json_response(
                    self,
                    {"ok": False, "error": "no wallet — create one first"},
                    400,
                )

            try:
                from oasyce.services.faucet import Faucet as _OnbFaucet
                from oasyce.config import get_data_dir, NetworkMode

                data_dir = _config.data_dir if _config else get_data_dir(NetworkMode.TESTNET)
                faucet = _OnbFaucet(data_dir)

                # Check if already registered (has any balance from onboarding)
                from pathlib import Path as _ObPath
                onboard_state_path = _ObPath(data_dir) / "onboarding_state.json"
                registered_addrs: set = set()
                if onboard_state_path.exists():
                    try:
                        ob_data = json.loads(onboard_state_path.read_text())
                        registered_addrs = set(ob_data.get("registered", []))
                    except (json.JSONDecodeError, OSError):
                        pass

                if address in registered_addrs:
                    return _json_response(
                        self,
                        {"ok": False, "error": "Already registered"},
                        409,
                    )

                # PoW parameters — match chain defaults
                POW_DIFFICULTY = 16  # leading zero bits
                AIRDROP_AMOUNT = 20.0  # OAS

                # C2: run PoW in thread pool to avoid blocking request thread
                def _mine_pow(addr: str, difficulty: int):
                    addr_bytes = addr.encode("utf-8")
                    nonce = 0
                    attempts = 0
                    while True:
                        data = addr_bytes + struct.pack("<Q", nonce)
                        h = hashlib.sha256(data).digest()
                        attempts += 1
                        # Count leading zero bits
                        zeros = 0
                        for b in h:
                            if b == 0:
                                zeros += 8
                            else:
                                zeros += 8 - b.bit_length()
                                break
                        if zeros >= difficulty:
                            return nonce, attempts
                        nonce += 1

                future = _pow_executor.submit(_mine_pow, address, POW_DIFFICULTY)
                try:
                    nonce, attempts = future.result(timeout=30)
                except Exception:
                    return _json_response(
                        self, {"ok": False, "error": "PoW computation timed out"}, 504,
                    )

                # H7: credit via public method if available, else fallback
                if hasattr(faucet, "credit"):
                    faucet.credit(address, AIRDROP_AMOUNT)
                else:
                    faucet._balances[address] = faucet._balances.get(address, 0.0) + AIRDROP_AMOUNT
                    faucet._save()

                # Record registration
                registered_addrs.add(address)
                onboard_state_path.parent.mkdir(parents=True, exist_ok=True)
                onboard_state_path.write_text(json.dumps({"registered": list(registered_addrs)}, indent=2))

                new_balance = faucet.balance(address)

                return _json_response(
                    self,
                    {
                        "ok": True,
                        "amount": AIRDROP_AMOUNT,
                        "new_balance": new_balance,
                        "attempts": attempts,
                        "nonce": nonce,
                    },
                )
            except Exception as exc:
                return _json_response(self, {"ok": False, "error": str(exc)}, 500)

        if path == "/api/identity/export":
            try:
                from oasyce.identity import Wallet
                w = Wallet.load()
                key_data = w.export_key() if hasattr(w, "export_key") else {"address": w.address, "public_key": w.public_key_hex}
                return _json_response(self, {"ok": True, **key_data})
            except Exception as e:
                return _json_response(self, {"ok": False, "error": str(e)}, 400)

        if path == "/api/identity/import":
            key_json = body.get("key_data", "")
            try:
                from oasyce.identity import Wallet
                if not Wallet.exists():
                    return _json_response(self, {"ok": False, "error": "no wallet to import into"}, 400)
                w = Wallet.load()
                if hasattr(w, "import_key"):
                    w.import_key(key_json)
                else:
                    return _json_response(self, {"ok": False, "error": "import not supported"}, 501)
                return _json_response(self, {"ok": True, "address": w.address})
            except Exception as e:
                return _json_response(self, {"ok": False, "error": str(e)}, 400)

        return None

    # ── POST handler: Asset routes ───────────────────────────────
    def _handle_assets(self, path, body, content_type):
        if path == "/api/register":
            try:
                # Gate: wallet must exist
                from oasyce.identity import Wallet as _RegWallet

                if not _RegWallet.exists():
                    return _json_response(
                        self,
                        {"error": "no wallet — create one first via /api/identity/create"},
                        400,
                    )

                # ── multipart upload ──
                if "multipart/form-data" in content_type:
                    form = _MultipartForm(self, content_type)
                    file_item = form.get_file("file")
                    if file_item is None or not getattr(file_item, "filename", None):
                        return _json_response(self, {"error": "file required"}, 400)

                    upload_dir = os.path.join(os.path.expanduser("~"), ".oasyce", "uploads")
                    os.makedirs(upload_dir, exist_ok=True)
                    safe_name = re.sub(r"[^\w.\-]", "_", file_item.filename)
                    dest = os.path.join(upload_dir, f"{int(time.time())}_{safe_name}")
                    with open(dest, "wb") as f:
                        f.write(file_item.file.read())

                    fp = dest
                    owner = form.getfirst("owner", _default_identity())
                    tags_raw = form.getfirst("tags", "")
                    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
                    rights_type = form.getfirst("rights_type", "original")
                    co_creators_raw = form.getfirst("co_creators", "")
                    try:
                        co_creators = json.loads(co_creators_raw) if co_creators_raw else None
                    except (json.JSONDecodeError, ValueError):
                        return _json_response(self, {"error": "invalid co_creators JSON"}, 400)
                    price_model = form.getfirst("price_model", "auto")
                    price_raw = form.getfirst("price", "")
                    manual_price = float(price_raw) if price_raw else None
                else:
                    # legacy JSON fallback — body already parsed at top of do_POST
                    fp = body.get("file_path", "")
                    owner = body.get("owner", _default_identity())
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

                if rights_type == "co_creation":
                    if not co_creators or len(co_creators) < 2:
                        return _json_response(
                            self,
                            {"error": "co_creation requires at least 2 co_creators"},
                            400,
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

                # Check for duplicate file hash
                file_hash = file_info.get("file_hash", "")
                if file_hash and _ledger:
                    for existing in _ledger.list_assets():
                        if existing.get("file_hash") == file_hash:
                            return _json_response(
                                self,
                                {
                                    "error": f"Duplicate: file already registered as {existing.get('asset_id', 'unknown')}",
                                    "existing_asset_id": existing.get("asset_id"),
                                },
                                409,
                            )

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
                asset_id = signed.get("asset_id", "")
                if _get_facade()._strict_chain_mode():
                    from oasyce.bridge.core_bridge import bridge_register

                    try:
                        chain_result = bridge_register(signed, creator=owner)
                    except Exception as chain_exc:
                        return _json_response(
                            self,
                            {
                                "error": f"Chain unavailable: {chain_exc}. "
                                "Start the chain with 'oasyced start' or disable strict mode "
                                "(unset OASYCE_STRICT_CHAIN) to register locally.",
                                "chain_required": True,
                            },
                            503,
                        )
                    if not chain_result.get("valid"):
                        return _json_response(
                            self,
                            {
                                "error": chain_result.get("error")
                                or chain_result.get("reason")
                                or "Chain registration failed",
                                "chain_required": True,
                            },
                            502,
                        )
                    asset_id = chain_result.get("core_asset_id", "")
                    if not asset_id:
                        return _json_response(
                            self,
                            {"error": "Chain registration returned no asset_id"},
                            502,
                        )
                    signed["asset_id"] = asset_id
                skills.register_data_asset_skill(signed, file_path=fp)
                return _json_response(
                    self,
                    {
                        "ok": True,
                        "asset_id": asset_id or signed.get("asset_id", ""),
                        "file_hash": file_info.get("file_hash", ""),
                        "owner": owner,
                        "price_model": price_model,
                        "rights_type": rights_type,
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/register-bundle":
            try:
                if "multipart/form-data" not in content_type:
                    return _json_response(self, {"error": "multipart/form-data required"}, 400)
                form = _MultipartForm(self, content_type)
                # Collect all files from multipart
                file_items = form.get_files("files")
                file_items = [f for f in file_items if getattr(f, "filename", None)]
                if not file_items:
                    return _json_response(self, {"error": "no files provided"}, 400)

                bundle_name = form.getfirst("name", f"bundle_{int(time.time())}")
                owner = form.getfirst("owner", _default_identity())
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
                asset_id = signed.get("asset_id", "")
                if _get_facade()._strict_chain_mode():
                    from oasyce.bridge.core_bridge import bridge_register

                    try:
                        chain_result = bridge_register(signed, creator=owner)
                    except Exception as chain_exc:
                        return _json_response(
                            self,
                            {
                                "error": f"Chain unavailable: {chain_exc}. "
                                "Start the chain with 'oasyced start' or disable strict mode "
                                "(unset OASYCE_STRICT_CHAIN) to register locally.",
                                "chain_required": True,
                            },
                            503,
                        )
                    if not chain_result.get("valid"):
                        return _json_response(
                            self,
                            {
                                "error": chain_result.get("error")
                                or chain_result.get("reason")
                                or "Chain registration failed",
                                "chain_required": True,
                            },
                            502,
                        )
                    asset_id = chain_result.get("core_asset_id", "")
                    if not asset_id:
                        return _json_response(
                            self,
                            {"error": "Chain registration returned no asset_id"},
                            502,
                        )
                    signed["asset_id"] = asset_id
                skills.register_data_asset_skill(signed, file_path=zip_path)
                return _json_response(
                    self,
                    {
                        "ok": True,
                        "asset_id": asset_id or signed.get("asset_id", ""),
                        "file_hash": file_info.get("file_hash", ""),
                        "owner": owner,
                        "bundle_name": bundle_name,
                        "tags": tags,
                        "file_count": len(file_items),
                        "file_names": [getattr(fi, "filename", "") for fi in file_items],
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/re-register":
            try:
                aid = body.get("asset_id", "")
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if not _ledger:
                    return _json_response(self, {"error": "not initialized"}, 503)
                meta = _ledger.get_asset_metadata(aid)
                if meta is None:
                    return _json_response(self, {"error": "asset not found"}, 404)
                caller = _default_identity()
                if meta.get("owner") and meta["owner"] != caller:
                    return _json_response(self, {"error": "not authorized"}, 403)
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

                versions.append(
                    {
                        "version": new_version,
                        "file_hash": new_hash,
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    }
                )
                meta["versions"] = versions
                meta["file_hash"] = new_hash
                _ledger.set_asset_metadata(aid, meta)
                return _json_response(
                    self, {"ok": True, "version": new_version, "file_hash": new_hash}
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/delist":
            try:
                aid = body.get("asset_id", "")
                owner = body.get("owner") or _default_identity()
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                facade = _get_facade()
                result = facade.delist_asset(aid, owner)
                if not result.success:
                    return _json_response(self, {"error": result.error}, 400)
                return _json_response(self, {"ok": True, "asset_id": aid, "delisted": True})
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/asset/update":
            aid = body.get("asset_id", "")
            new_tags = body.get("tags", [])
            if not _ledger:
                return _json_response(self, {"error": "ledger not initialized"}, 503)
            meta = _ledger.get_asset_metadata(aid)
            if meta is None:
                return _json_response(self, {"error": "not found"}, 404)
            caller = _default_identity()
            if meta.get("owner") and meta["owner"] != caller:
                return _json_response(self, {"error": "not authorized"}, 403)
            if not _ledger.update_asset_metadata(aid, {"tags": new_tags}):
                return _json_response(self, {"error": "update failed"}, 500)
            return _json_response(self, {"ok": True, "asset_id": aid, "tags": new_tags})

        if path == "/api/asset/shutdown":
            aid = body.get("asset_id", "")
            owner = body.get("owner", "") or _default_identity()
            facade = _get_facade()
            if not facade:
                return _json_response(self, {"error": "service unavailable"}, 503)
            result = facade.initiate_shutdown(aid, owner, "gui")
            if result.success:
                return _json_response(self, {"ok": True, **result.data})
            return _json_response(self, {"ok": False, "error": result.error}, 400)

        if path == "/api/asset/terminate":
            aid = body.get("asset_id", "")
            sender = body.get("sender", "") or _default_identity()
            facade = _get_facade()
            if not facade:
                return _json_response(self, {"error": "service unavailable"}, 503)
            result = facade.finalize_termination(aid, sender, "gui")
            if result.success:
                return _json_response(self, {"ok": True, **result.data})
            return _json_response(self, {"ok": False, "error": result.error}, 400)

        if path == "/api/asset/claim":
            aid = body.get("asset_id", "")
            holder = body.get("holder", "") or _default_identity()
            facade = _get_facade()
            if not facade:
                return _json_response(self, {"error": "service unavailable"}, 503)
            result = facade.claim_termination(aid, holder, "gui")
            if result.success:
                return _json_response(self, {"ok": True, **result.data})
            return _json_response(self, {"ok": False, "error": result.error}, 400)

        return None

    # ── POST handler: Trading routes ─────────────────────────────
    def _handle_trading(self, path, body, content_type):
        if path == "/api/buy":
            try:
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
                with _buy_lock:
                    last_buy = _buy_cooldowns.get(cooldown_key, 0)
                    if time.time() - last_buy < BUY_COOLDOWN_SECONDS:
                        remaining = int(BUY_COOLDOWN_SECONDS - (time.time() - last_buy))
                        return _json_response(self, {"error": f"cooldown: wait {remaining}s"}, 429)
                # UNAVAILABLE check: verify file exists and hash matches
                if not _ledger:
                    return _json_response(self, {"error": "not initialized"}, 503)
                asset_meta = _ledger.get_asset_metadata(aid)
                if asset_meta is not None:
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
                        # M4: skip expensive hash if file size/mtime unchanged
                        need_hash = True
                        try:
                            st = os.stat(a_file_path)
                            cached_size = asset_meta.get("_cached_size")
                            cached_mtime = asset_meta.get("_cached_mtime")
                            if cached_size == st.st_size and cached_mtime == st.st_mtime:
                                need_hash = False
                        except OSError:
                            pass

                        if need_hash:
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
                            # Cache mtime/size for next check
                            try:
                                st = os.stat(a_file_path)
                                _ledger.update_asset_metadata(aid, {
                                    "_cached_size": st.st_size,
                                    "_cached_mtime": st.st_mtime,
                                })
                            except Exception:
                                pass
                facade = _get_facade()
                result = facade.buy(aid, buyer, amount)
                if not result.success:
                    return _json_response(self, {"error": result.error}, 400)

                d = result.data
                settled = d.get("settled", False)
                if settled:
                    with _buy_lock:
                        _buy_cooldowns[cooldown_key] = time.time()
                    # Send purchase notification to buyer
                    try:
                        quote_data = d.get("quote") or {}
                        shares = round(quote_data.get("equity_minted", 0), 4)
                        ns = _get_notification_service()
                        ns.notify(
                            buyer,
                            "PURCHASE",
                            f"Purchased {shares} shares of {aid[:12]}...",
                            {"asset_id": aid, "shares": shares},
                        )
                        # Send sale notification to asset owner
                        if _ledger:
                            _asset_owner = _ledger.get_asset_owner(aid)
                            if _asset_owner:
                                ns.notify(
                                    _asset_owner,
                                    "SALE",
                                    f"Your asset {aid[:12]}... was purchased by {buyer[:12]}...",
                                    {"asset_id": aid, "buyer": buyer},
                                )
                    except Exception:
                        logger.debug("Purchase notification failed", exc_info=True)

                quote_data = d.get("quote") or {}
                resp = {
                    "ok": settled,
                    "receipt_id": d.get("receipt_id", ""),
                }
                resp["tokens"] = round(quote_data.get("equity_minted", 0), 4)
                resp["price_after"] = round(quote_data.get("spot_price_after", 0), 6)
                # equity balance from pool (use settlement engine for pool state lookup)
                se = _get_settlement()
                pool = se.get_pool(aid)
                resp["equity_balance"] = round(pool.equity.get(buyer, 0), 4) if pool else 0
                resp["error"] = None
                return _json_response(self, resp)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/sell":
            try:
                aid = body.get("asset_id", "")
                seller = body.get("seller") or _default_identity()
                tokens = float(body.get("tokens", 0))
                max_slippage = body.get("max_slippage")
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if tokens <= 0:
                    return _json_response(self, {"error": "tokens must be positive"}, 400)
                facade = _get_facade()
                result = facade.sell(aid, seller, tokens, max_slippage=max_slippage)
                if not result.success:
                    return _json_response(self, {"error": result.error}, 400)
                d = result.data
                return _json_response(self, {
                    "ok": True,
                    "payout_oas": round(d.get("payout_oas", 0), 6),
                    "protocol_fee": round(d.get("protocol_fee", 0), 6),
                    "burn_amount": round(d.get("burn_amount", 0), 6),
                    "receipt_id": d.get("receipt_id", ""),
                })
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/access/buy":
            try:
                aid = body.get("asset_id", "")
                buyer = body.get("buyer") or _default_identity()
                level_str = body.get("level", "L1")
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if level_str not in ("L0", "L1", "L2", "L3"):
                    return _json_response(self, {"error": "invalid level"}, 400)

                facade = _get_facade()

                # Pre-check: buyer must have enough balance for the bond
                bond_oas = 0.0
                try:
                    quote_result = facade.access_quote(aid, buyer)
                    if quote_result.success:
                        for lv in quote_result.data.get("levels", []):
                            if lv["level"] == level_str:
                                bond_oas = lv.get("bond_oas", 0.0)
                                break
                        if bond_oas > 0:
                            from oasyce.config import get_data_dir, NetworkMode
                            _bd = _config.data_dir if _config else get_data_dir(NetworkMode.TESTNET)
                            _faucet = Faucet(_bd)
                            bal = _faucet.balance(buyer)
                            if bal < bond_oas:
                                return _json_response(self, {
                                    "error": f"Insufficient balance: {bal:.2f} OAS < {bond_oas:.2f} OAS required"
                                }, 400)
                except Exception:
                    logger.debug("Pre-quote for access buy failed", exc_info=True)

                result = facade.access_buy(aid, buyer, level_str, pre_quoted_bond=bond_oas)

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
                    logger.debug("Access notification failed", exc_info=True)

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

        if path == "/api/stake":
            try:
                node_id = body.get("node_id", "")
                amount = float(body.get("amount", 0))
                if not node_id or amount <= 0:
                    return _json_response(self, {"error": "node_id and amount required"}, 400)
                staker = _default_identity()
                if not _ledger:
                    return _json_response(self, {"error": "ledger not initialized"}, 503)
                _ledger.update_stake(node_id, staker, amount)
                # Read back total
                stakes = _ledger.get_stakes_summary()
                total = next(
                    (s["total"] for s in stakes if s["validator_id"] == node_id), amount
                )
                return _json_response(
                    self,
                    {
                        "ok": True,
                        "node_id": node_id,
                        "total_stake": total,
                    },
                )
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        return None

    # ── POST handler: Dispute routes ─────────────────────────────
    def _handle_disputes(self, path, body, content_type):
        if path == "/api/dispute":
            try:
                aid = body.get("asset_id", "")
                reason = body.get("reason", "").strip()
                invocation_id = body.get("invocation_id") or None
                consumer_id = body.get("consumer_id") or _default_identity()
                if not aid and not invocation_id:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if not reason:
                    return _json_response(self, {"error": "reason required"}, 400)

                # Check for existing active dispute
                if aid and _ledger:
                    meta = _ledger.get_asset_metadata(aid)
                    if meta and meta.get("disputed") and meta.get("dispute_status") == "open":
                        return _json_response(
                            self,
                            {"error": "An active dispute already exists for this asset"},
                            409,
                        )

                facade = _get_facade()
                result = facade.dispute(
                    asset_id=aid,
                    consumer_id=consumer_id,
                    reason=reason,
                    invocation_id=invocation_id,
                )
                if not result.success:
                    return _json_response(self, {"error": result.error}, 400)
                return _json_response(self, result.data)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/dispute/resolve":
            try:
                aid = body.get("asset_id", "")
                remedy = body.get("remedy", "")
                details = body.get("details", {})
                dispute_id = body.get("dispute_id", "")

                if not aid and not dispute_id:
                    return _json_response(self, {"error": "asset_id or dispute_id required"}, 400)

                facade = _get_facade()
                result = facade.resolve_dispute(
                    dispute_id=dispute_id,
                    asset_id=aid,
                    remedy=remedy,
                    details=details,
                )
                if not result.success:
                    return _json_response(self, {"error": result.error}, 400)
                return _json_response(self, result.data)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

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
                    logger.debug("Dispute notification failed", exc_info=True)
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

        if path == "/api/jury/vote":
            try:
                dispute_id = body.get("dispute_id", "")
                juror = body.get("juror") or _default_identity()
                verdict = body.get("verdict", "")
                if not dispute_id or verdict not in ("uphold", "reject"):
                    return _json_response(
                        self,
                        {"error": "dispute_id and verdict (uphold|reject) required"},
                        400,
                    )
                # Map GUI verdict names to facade expected values
                verdict_map = {"uphold": "consumer", "reject": "provider"}
                facade = _get_facade()
                result = facade.jury_vote(
                    dispute_id=dispute_id,
                    juror_id=juror,
                    verdict=verdict_map[verdict],
                )
                if result.success:
                    return _json_response(self, {
                        "ok": True,
                        "dispute_id": dispute_id,
                        "juror": juror,
                        "verdict": verdict,
                        "recorded": True,
                        "data": result.data,
                    })
                else:
                    return _json_response(self, {"ok": False, "error": result.error}, 400)
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/evidence/submit":
            dispute_id = body.get("dispute_id", "")
            submitter = body.get("submitter", "") or _default_identity()
            evidence_hash = body.get("evidence_hash", "")
            evidence_type = body.get("evidence_type", "document")
            weight = body.get("weight", 1.0)
            description = body.get("description", "")
            facade = _get_facade()
            if not facade:
                return _json_response(self, {"error": "service unavailable"}, 503)
            result = facade.submit_evidence(
                dispute_id, submitter, evidence_hash, evidence_type,
                weight, description, "gui",
            )
            if result.success:
                return _json_response(self, {"ok": True, **result.data})
            return _json_response(self, {"ok": False, "error": result.error}, 400)

        return None

    # ── POST handler: Node routes ────────────────────────────────
    def _handle_node(self, path, body, content_type):
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

        return None

    # ── POST handler: Capability routes ──────────────────────────
    def _handle_capabilities(self, path, body, content_type):
        if path == "/api/capability/register":
            result = _api_capability_register(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        if path == "/api/capability/invoke":
            result = _api_capability_invoke(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        if path == "/api/delivery/register":
            result = _api_delivery_register(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        if path == "/api/delivery/invoke":
            result = _api_delivery_invoke(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        return None

    # ── POST handler: Consensus routes ───────────────────────────
    def _handle_consensus(self, path, body, content_type):
        # Consensus features (delegate, undelegate, governance) moved to Go chain.
        # Use oasyced CLI for consensus operations.
        consensus_paths = (
            "/api/consensus/mempool/submit", "/api/consensus/delegate",
            "/api/consensus/undelegate", "/api/governance/propose", "/api/governance/vote",
        )
        if path in consensus_paths:
            return _json_response(self, {"error": "Consensus features moved to Go chain. Use oasyced CLI."}, 501)
        return None

    # ── POST handler: Fingerprint routes ─────────────────────────
    def _handle_fingerprint(self, path, body, content_type):
        if path == "/api/fingerprint/embed":
            try:
                from oasyce.fingerprint.engine import FingerprintEngine

                engine = FingerprintEngine(_config.signing_key if _config else "key")
                aid = body.get("asset_id", "")
                caller = body.get("caller_id", "")
                content = body.get("content", "")
                file_path = body.get("file_path", "")
                # Accept file_path as alternative to content
                if file_path and not content:
                    # H2: restrict file reads to home directory
                    resolved_fp = os.path.realpath(file_path)
                    home_dir = os.path.expanduser("~")
                    if not resolved_fp.startswith(home_dir):
                        return _json_response(self, {"error": "file path not allowed"}, 403)
                    if not os.path.isfile(resolved_fp):
                        return _json_response(self, {"error": "file not found"}, 404)
                    with open(resolved_fp, "r", errors="replace") as fp:
                        content = fp.read()
                    if not aid:
                        aid = os.path.basename(file_path)
                if not all([aid, caller, content]):
                    return _json_response(
                        self, {"error": "asset_id, caller_id, and content (or file_path) required"}, 400
                    )
                fp = engine.generate_fingerprint(aid, caller, int(time.time()))
                watermarked = engine.embed_text(content, fp)
                if _ledger:
                    registry = FingerprintRegistry(_ledger)
                    registry.record_distribution(aid, caller, fp, int(time.time()))
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

        if path == "/api/fingerprint/extract":
            try:
                from oasyce.fingerprint.engine import FingerprintEngine

                file_path = body.get("file_path", "")
                content = body.get("content", "")
                fingerprint = None

                if file_path:
                    # H2: restrict file reads to home directory
                    resolved_fp = os.path.realpath(file_path)
                    home_dir = os.path.expanduser("~")
                    if not resolved_fp.startswith(home_dir):
                        return _json_response(
                            self, {"ok": False, "error": "file path not allowed"}, 403
                        )
                    if not os.path.isfile(resolved_fp):
                        return _json_response(
                            self, {"ok": False, "error": "file not found"}, 404
                        )
                    # H3: use context manager to avoid file handle leak
                    with open(resolved_fp, "rb") as f:
                        raw = f.read()
                    try:
                        text = raw.decode("utf-8")
                        fingerprint = FingerprintEngine.extract_text(text)
                    except UnicodeDecodeError:
                        fingerprint = FingerprintEngine.extract_binary(raw)
                elif content:
                    fingerprint = FingerprintEngine.extract_text(content)
                else:
                    return _json_response(
                        self,
                        {"ok": False, "error": "file_path or content required"},
                        400,
                    )

                if fingerprint:
                    return _json_response(
                        self, {"ok": True, "fingerprint": fingerprint}
                    )
                else:
                    return _json_response(
                        self, {"ok": False, "error": "no fingerprint found"}
                    )
            except Exception as e:
                return _json_response(self, {"ok": False, "error": str(e)}, 400)

        return None

    # ── POST handler: Automation routes ──────────────────────────
    def _handle_automation(self, path, body, content_type):
        if path.startswith("/api/inbox/") and path.endswith("/approve"):
            item_id = path.split("/")[-2]
            from oasyce.services.inbox import ConfirmationInbox

            inbox = ConfirmationInbox(data_dir=_config.data_dir if _config else None)
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

            inbox = ConfirmationInbox(data_dir=_config.data_dir if _config else None)
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

            inbox = ConfirmationInbox(data_dir=_config.data_dir if _config else None)
            try:
                changes = body or {}
                item = inbox.edit(item_id, changes)
                return _json_response(
                    self, {"ok": True, "item_id": item.item_id, "status": item.status}
                )
            except (KeyError, ValueError) as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/inbox/trust":
            try:
                from oasyce.services.inbox import ConfirmationInbox

                inbox = ConfirmationInbox(data_dir=_config.data_dir if _config else None)
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
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, 500)

        if path == "/api/scan":
            from oasyce.services.scanner import AssetScanner
            from oasyce.services.inbox import ConfirmationInbox

            scan_path = body.get("path", ".") if body else "."
            resolved_scan = os.path.realpath(scan_path)
            home_dir = os.path.expanduser("~")
            if not resolved_scan.startswith(home_dir):
                return _json_response(
                    self, {"error": "scan path must be under home directory"}, 403
                )
            scanner = AssetScanner()
            results = scanner.scan_directory(scan_path)
            inbox = ConfirmationInbox(data_dir=_config.data_dir if _config else None)
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

        if path == "/api/agent/config":
            try:
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
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, 500)

        if path == "/api/agent/run":
            try:
                from oasyce.services.scheduler import get_scheduler

                data_dir = _config.data_dir if _config else None
                scheduler = get_scheduler(data_dir)
                result = scheduler.run_once()
                return _json_response(self, result.to_dict())
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, 500)

        if path == "/api/notifications/read":
            try:
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
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, 500)

        return None

    # ── POST handler: Advanced routes ────────────────────────────
    def _handle_advanced(self, path, body, content_type):
        if path == "/api/leakage/reset":
            agent_id = body.get("agent_id", "")
            asset_id = body.get("asset_id", "")
            if not agent_id or not asset_id:
                return _json_response(self, {"error": "agent_id and asset_id required"}, 400)
            facade = _get_facade()
            result = facade.reset_leakage(agent_id, asset_id)
            if not result.success:
                return _json_response(self, {"error": result.error}, 500)
            return _json_response(self, result.data)

        if path == "/api/cache/purge":
            facade = _get_facade()
            result = facade.purge_cache()
            if not result.success:
                return _json_response(self, {"error": result.error}, 500)
            return _json_response(self, result.data)

        if path == "/api/contribution/prove":
            file_path = body.get("file_path", "")
            creator_key = body.get("creator_key", "")
            if not file_path or not creator_key:
                return _json_response(self, {"error": "file_path and creator_key required"}, 400)
            facade = _get_facade()
            result = facade.query_contribution(file_path, creator_key, body.get("source_type", "manual"))
            if not result.success:
                return _json_response(self, {"error": result.error}, 500)
            return _json_response(self, result.data)

        if path == "/api/contribution/verify":
            cert = body.get("certificate", {})
            file_path = body.get("file_path", "")
            if not cert or not file_path:
                return _json_response(self, {"error": "certificate and file_path required"}, 400)
            facade = _get_facade()
            result = facade.verify_contribution(cert, file_path)
            if not result.success:
                return _json_response(self, {"error": result.error}, 500)
            return _json_response(self, result.data)

        if path == "/api/task/post":
            facade = _get_facade()
            result = facade.post_task(
                requester_id=body.get("requester_id", _default_identity()),
                description=body.get("description", ""),
                budget=float(body.get("budget", 0)),
                deadline_seconds=int(body.get("deadline_seconds", 3600)),
                required_capabilities=body.get("required_capabilities", []),
                selection_strategy=body.get("selection_strategy", "weighted_score"),
                min_reputation=float(body.get("min_reputation", 0)),
            )
            if not result.success:
                return _json_response(self, {"error": result.error}, 400)
            return _json_response(self, result.data)

        m = re.match(r"^/api/task/([^/]+)/bid$", path)
        if m:
            task_id = m.group(1)
            facade = _get_facade()
            result = facade.submit_task_bid(
                task_id=task_id,
                agent_id=body.get("agent_id", _default_identity()),
                price=float(body.get("price", 0)),
                estimated_seconds=int(body.get("estimated_seconds", 0)),
                capability_proof=body.get("capability_proof", {}),
                reputation_score=float(body.get("reputation_score", 0)),
            )
            if not result.success:
                return _json_response(self, {"error": result.error}, 400)
            return _json_response(self, result.data)

        m = re.match(r"^/api/task/([^/]+)/select$", path)
        if m:
            task_id = m.group(1)
            facade = _get_facade()
            result = facade.select_task_winner(task_id, agent_id=body.get("agent_id", ""))
            if not result.success:
                return _json_response(self, {"error": result.error}, 400)
            return _json_response(self, result.data)

        m = re.match(r"^/api/task/([^/]+)/complete$", path)
        if m:
            task_id = m.group(1)
            facade = _get_facade()
            result = facade.complete_task(task_id)
            if not result.success:
                return _json_response(self, {"error": result.error}, 400)
            return _json_response(self, result.data)

        m = re.match(r"^/api/task/([^/]+)/cancel$", path)
        if m:
            task_id = m.group(1)
            facade = _get_facade()
            result = facade.cancel_task(task_id)
            if not result.success:
                return _json_response(self, {"error": result.error}, 400)
            return _json_response(self, result.data)

        return None

    def _handle_feedback(self, path, body, content_type):
        if path == "/api/feedback":
            message = (body.get("message") or "").strip()
            if not message:
                return _json_response(self, {"error": "message required"}, 400)
            fb_type = body.get("type", "bug")
            if fb_type not in ("bug", "suggestion", "other"):
                fb_type = "bug"
            agent_id = body.get("agent_id", "anonymous")
            context_str = json.dumps(body.get("context", {})) if isinstance(body.get("context"), dict) else str(body.get("context", "{}"))
            feedback_id = f"FB_{secrets.token_hex(8)}"
            now = time.time()
            try:
                db = _get_feedback_db()
                db.execute(
                    "INSERT INTO feedback (feedback_id, type, message, context, agent_id, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, 'open', ?)",
                    (feedback_id, fb_type, message, context_str, agent_id, now),
                )
                db.commit()
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 500)
            fb = {"feedback_id": feedback_id, "type": fb_type, "message": message,
                  "context": context_str, "agent_id": agent_id}
            _forward_feedback_webhook(fb)
            github_url = _forward_feedback_github(fb)
            result = {"ok": True, "feedback_id": feedback_id}
            if github_url:
                result["github_issue"] = github_url
            return _json_response(self, result)
        return None

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

        # C3: enforce maximum POST body size
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return _json_response(self, {"error": "invalid Content-Length"}, 400)
        if length > MAX_POST_BODY:
            return _json_response(self, {"error": "request body too large"}, 413)

        # Pre-parse JSON body for non-multipart routes
        body: dict = {}
        if "application/json" in content_type:
            try:
                body = json.loads(self.rfile.read(length)) if length else {}
            except (json.JSONDecodeError, ValueError):
                return _json_response(self, {"error": "invalid JSON body"}, 400)

        # Dispatch to handler
        for handler in [
            self._handle_identity,
            self._handle_assets,
            self._handle_trading,
            self._handle_disputes,
            self._handle_feedback,
            self._handle_node,
            self._handle_capabilities,
            self._handle_consensus,
            self._handle_fingerprint,
            self._handle_automation,
            self._handle_advanced,
        ]:
            result = handler(path, body, content_type)
            if result is not None:
                return result

        # ── AHRP proxy (POST) ────────────────────────────────────
        if path.startswith("/ahrp/"):
            raw = json.dumps(body).encode("utf-8") if body else b""
            return _proxy_ahrp(self, "POST", self.path, raw)

        return _json_response(self, {"error": "not found"}, 404)


    def do_OPTIONS(self):
        """M8: Handle CORS preflight for localhost origins."""
        origin = self.headers.get("Origin", "")
        localhost_patterns = ("http://localhost:", "http://127.0.0.1:", "http://[::1]:")
        allowed = any(origin.startswith(p) for p in localhost_patterns)
        self.send_response(204)
        if allowed:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self):
        # ── Auth check ──
        if not _check_auth(self):
            return _json_response(self, {"error": "unauthorized"}, 401)
        client_ip = self.client_address[0]
        if not _check_rate_limit(client_ip):
            return _json_response(self, {"error": "rate limit exceeded"}, 429)

        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        m = re.match(r"^/api/asset/([^/]+)$", path)
        if m:
            aid = m.group(1)
            caller = _default_identity()
            facade = _get_facade()
            result = facade.delete_asset(aid, owner=caller)
            if result.success:
                return _json_response(self, {"ok": True, "deleted": aid})
            else:
                return _json_response(self, {"ok": False, "error": result.error}, 400)
        return _json_response(self, {"error": "not found"}, 404)


# ── Legacy _INDEX_HTML removed — React SPA in dashboard/dist/ ────────
# Run `cd dashboard && npm run build` to generate the SPA.
# If dist/index.html is missing, the server returns a 503 with instructions.




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
        if hasattr(_ledger, "reconnect"):
            _ledger.reconnect()

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
            print(f"   Try: oas start --port <available_port>")
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

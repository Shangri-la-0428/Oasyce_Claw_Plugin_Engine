"""
Oasyce Web Dashboard — zero-dependency SPA served via Python stdlib.

Serves on port 8420. All HTML/CSS/JS is embedded in this single file.
Reads chain data from the local Ledger database.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import URLError

from oasyce_plugin.config import Config
from oasyce_plugin.storage.ledger import Ledger
from oasyce_plugin.fingerprint import FingerprintRegistry


# ── Shared state (set by OasyceGUI before server starts) ─────────────
DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'dashboard', 'dist')

_ledger: Optional[Ledger] = None
_config: Optional[Config] = None
_settlement: Any = None
_staking: Any = None
_skills: Any = None
_cap_registry: Any = None
_cap_escrow: Any = None
_cap_shares: Any = None
_cap_engine: Any = None


def _get_settlement():
    global _settlement
    if _settlement is None:
        from oasyce_plugin.services.settlement.engine import SettlementEngine
        _settlement = SettlementEngine()
    return _settlement


def _get_staking():
    global _staking
    if _staking is None:
        from oasyce_plugin.services.staking import StakingEngine
        _staking = StakingEngine()
    return _staking


def _get_cap_stack():
    """Lazy-init capability stack (registry + escrow + shares + engine)."""
    global _cap_registry, _cap_escrow, _cap_shares, _cap_engine
    if _cap_registry is None:
        from oasyce_core.capabilities.registry import CapabilityRegistry
        from oasyce_core.capabilities.escrow import EscrowManager
        from oasyce_core.capabilities.shares import ShareLedger
        from oasyce_core.capabilities.invocation import CapabilityInvocationEngine
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
        from oasyce_plugin.skills.agent_skills import OasyceSkills
        _skills = OasyceSkills(_config)
    return _skills


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
        mime = 'application/octet-stream'
    with open(file_path, 'rb') as f:
        body = f.read()
    handler.send_response(200)
    handler.send_header('Content-Type', mime)
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'public, max-age=31536000, immutable')
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
        results.append({
            "asset_id": r["asset_id"],
            "owner": r["owner"],
            "tags": meta.get("tags", []),
            "created_at": r["created_at"],
        })
    # Attach spot price from settlement engine where available
    se = _get_settlement()
    for r in results:
        aid = r['asset_id']
        if aid in se.pools:
            pool = se.pools[aid]
            if pool.supply > 0:
                r['spot_price'] = round(pool.reserve_balance / (pool.supply * pool.config.reserve_ratio), 6)
        if 'spot_price' not in r:
            r['spot_price'] = None
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
        results.append({
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
        })
    return results


def _api_capability_detail(cap_id: str) -> Optional[Dict[str, Any]]:
    """Get capability detail by ID."""
    registry, _, shares, _ = _get_cap_stack()
    m = registry.get(cap_id)
    if m is None:
        return None
    reserve = shares.pool_reserve(cap_id)
    supply = shares.total_supply(cap_id)
    spot = round(reserve / (supply * m.pricing.reserve_ratio), 6) if supply > 0 and m.pricing.reserve_ratio > 0 else 0.0
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
    from oasyce_core.capabilities.manifest import (
        CapabilityManifest, PricingConfig, StakingConfig, QualityPolicy, ExecutionLimits,
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
    consumer = body.get("consumer", "gui_user")
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
        result = engine.submit_result(handle.invocation_id, {
            "result": "Executed successfully",
            "execution_time_ms": 150,
        })
        return {
            "ok": True,
            "invocation_id": handle.invocation_id,
            "price": round(handle.price, 6),
            "shares_minted": round(result.mint_result.shares_minted, 4) if result.mint_result else 0,
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
            spot = round(reserve / (supply * m.pricing.reserve_ratio), 6) if supply > 0 and m.pricing.reserve_ratio > 0 else 0.0
            holdings.append({
                "capability_id": m.capability_id,
                "name": m.name,
                "shares": round(bal, 4),
                "spot_price": spot,
                "value_oas": round(bal * spot, 4),
            })
    return holdings


_AHRP_CORE_BASE = "http://localhost:8000"
_AHRP_UNREACHABLE = json.dumps(
    {"ok": False, "error": "AHRP node not running. Start with: oasyce serve"}
).encode("utf-8")


def _proxy_ahrp(handler: BaseHTTPRequestHandler, method: str, path: str,
                body: bytes = b"") -> None:
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
            holder = qs.get("holder", ["gui_user"])[0]
            return _json_response(self, _api_capability_shares(holder))

        m = re.match(r"^/api/capability/(.+)$", path)
        if m:
            detail = _api_capability_detail(m.group(1))
            if detail is None:
                return _json_response(self, {"error": "not found"}, 404)
            return _json_response(self, detail)

        # Asset detail
        m = re.match(r"^/api/asset/(.+)$", path)
        if m:
            aid = m.group(1)
            assert _ledger
            row = _ledger._conn.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (aid,)
            ).fetchone()
            if not row:
                return _json_response(self, {"error": "not found"}, 404)
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            return _json_response(self, {
                "asset_id": row["asset_id"], "owner": row["owner"],
                "metadata": meta, "created_at": row["created_at"],
            })

        # Bancor quote
        if path == "/api/quote":
            asset_id = qs.get("asset_id", [""])[0]
            amount = float(qs.get("amount", ["10"])[0])
            if not asset_id:
                return _json_response(self, {"error": "asset_id required"}, 400)
            try:
                se = _get_settlement()
                if asset_id not in se.pools:
                    se.register_asset(asset_id, "protocol")
                q = se.quote(asset_id, amount)
                return _json_response(self, {
                    "asset_id": q.asset_id, "payment": q.payment_oas,
                    "tokens": round(q.equity_minted, 4),
                    "price_before": round(q.spot_price_before, 6),
                    "price_after": round(q.spot_price_after, 6),
                    "impact_pct": round(q.price_impact_pct, 2),
                    "fee": round(q.protocol_fee, 4),
                    "burn": round(q.burn_amount, 4),
                })
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # Portfolio (holdings)
        if path == "/api/portfolio":
            buyer = qs.get("buyer", ["gui_user"])[0]
            se = _get_settlement()
            holdings = []
            for asset_id, pool in se.pools.items():
                balance = pool.equity.get(buyer, 0)
                if balance > 0:
                    spot = round(pool.reserve_balance / (pool.supply * pool.config.reserve_ratio), 6) if pool.supply > 0 else 0
                    holdings.append({
                        "asset_id": asset_id,
                        "shares": round(balance, 4),
                        "spot_price": spot,
                        "value_oas": round(balance * spot, 4),
                    })
            return _json_response(self, holdings)

        # Transaction history
        if path == "/api/transactions":
            se = _get_settlement()
            txs = []
            if hasattr(se, "receipts"):
                for r in se.receipts[-50:]:
                    txs.append({
                        "receipt_id": r.receipt_id,
                        "asset_id": r.asset_id,
                        "buyer": r.buyer_id,
                        "amount": r.quote.payment_oas,
                        "tokens": round(r.quote.equity_minted, 4),
                        "status": r.status.value,
                        "timestamp": r.timestamp,
                    })
            return _json_response(self, list(reversed(txs)))

        # ── AHRP proxy (GET) ─────────────────────────────────────
        if path.startswith("/ahrp/"):
            return _proxy_ahrp(self, "GET", self.path)

        # ── Config ───────────────────────────────────────────────
        if path == "/api/config":
            assert _config
            return _json_response(self, {
                "public_key": _config.public_key,
                "owner": _config.owner,
                "node_host": _config.node_host,
                "node_port": _config.node_port,
            })

        # ── Static files from dashboard/dist/ ────────────────────
        if path.startswith('/assets/'):
            file_path = os.path.join(DASHBOARD_DIR, path.lstrip('/'))
            return _serve_static(self, file_path)

        if path == '/favicon.svg' or path == '/icons.svg':
            file_path = os.path.join(DASHBOARD_DIR, path.lstrip('/'))
            return _serve_static(self, file_path)

        # ── SPA fallback — serve index.html for all routes ───────
        index_path = os.path.join(DASHBOARD_DIR, 'index.html')
        if os.path.isfile(index_path):
            return _serve_static(self, index_path)

        # Fallback to legacy embedded HTML if dist/ not built
        return _html_response(self, _INDEX_HTML)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/register":
            try:
                skills = _get_skills()
                fp = body.get("file_path", "")
                owner = body.get("owner", _config.owner if _config else "unknown")
                tags = body.get("tags", [])
                if not fp:
                    return _json_response(self, {"error": "file_path required"}, 400)
                file_info = skills.scan_data_skill(fp)
                metadata = skills.generate_metadata_skill(file_info, tags, owner)
                signed = skills.create_certificate_skill(metadata)
                result = skills.register_data_asset_skill(signed)
                return _json_response(self, {
                    "ok": True, "asset_id": signed.get("asset_id", ""),
                    "file_hash": file_info.get("file_hash", ""),
                })
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/buy":
            try:
                se = _get_settlement()
                aid = body.get("asset_id", "")
                buyer = body.get("buyer", "anonymous")
                amount = float(body.get("amount", 10))
                if not aid:
                    return _json_response(self, {"error": "asset_id required"}, 400)
                if aid not in se.pools:
                    se.register_asset(aid, "protocol")
                receipt = se.execute(aid, buyer, amount)
                return _json_response(self, {
                    "ok": receipt.status.value == "SETTLED",
                    "receipt_id": receipt.receipt_id,
                    "tokens": round(receipt.quote.equity_minted, 4),
                    "price_after": round(receipt.quote.spot_price_after, 6),
                    "equity_balance": round(receipt.equity_balance, 4),
                    "error": receipt.error,
                })
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
                return _json_response(self, {
                    "ok": True, "node_id": v.node_id,
                    "total_stake": v.stake, "status": v.status.value,
                })
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        # ── Capability routes (POST) ─────────────────────────────
        if path == "/api/capability/register":
            result = _api_capability_register(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        if path == "/api/capability/invoke":
            result = _api_capability_invoke(body)
            status = 200 if result.get("ok") else 400
            return _json_response(self, result, status)

        if path == "/api/fingerprint/embed":
            try:
                from oasyce_plugin.fingerprint.engine import FingerprintEngine
                engine = FingerprintEngine(_config.signing_key if _config else "key")
                aid = body.get("asset_id", "")
                caller = body.get("caller_id", "")
                content = body.get("content", "")
                if not all([aid, caller, content]):
                    return _json_response(self, {"error": "asset_id, caller_id, content required"}, 400)
                import time
                fp = engine.generate_fingerprint(aid, caller, int(time.time()))
                watermarked = engine.embed_text(content, fp)
                if _ledger:
                    registry = FingerprintRegistry(_ledger)
                    registry.record_distribution(aid, caller, fp, int(time.time()))
                return _json_response(self, {
                    "ok": True, "fingerprint": fp,
                    "watermarked_content": watermarked,
                })
            except Exception as e:
                return _json_response(self, {"error": str(e)}, 400)

        if path == "/api/asset/update":
            aid = body.get("asset_id", "")
            new_tags = body.get("tags", [])
            assert _ledger
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

        # ── AHRP proxy (POST) ────────────────────────────────────
        if path.startswith("/ahrp/"):
            raw = json.dumps(body).encode("utf-8") if body else b""
            return _proxy_ahrp(self, "POST", self.path, raw)

        return _json_response(self, {"error": "not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        m = re.match(r"^/api/asset/(.+)$", path)
        if m:
            aid = m.group(1)
            assert _ledger
            row = _ledger._conn.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (aid,)
            ).fetchone()
            if not row:
                return _json_response(self, {"error": "Asset not found"}, 404)
            _ledger._conn.execute("DELETE FROM assets WHERE asset_id = ?", (aid,))
            _ledger._conn.execute(
                "DELETE FROM fingerprint_records WHERE asset_id = ?", (aid,)
            )
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
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Protocol design and economics',
      'link-docs': 'Documentation',
      'link-docs-d': 'Technical reference and API',
      'link-github': 'GitHub',
      'link-github-d': 'Source code and contributions',
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
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '协议设计与经济模型',
      'link-docs': '技术文档',
      'link-docs-d': '技术参考与 API',
      'link-github': 'GitHub',
      'link-github-d': '源代码与贡献',
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

  // About panel
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'</h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<ul class="about-links">'+
        '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github']+'</div><div class="link-desc">'+t['link-github-d']+'</div></div></a></li>'+
      '</ul>'+
      '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>';
    document.body.appendChild(overlay);
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
    o.innerHTML='<div class="modal" onclick="event.stopPropagation()">'+
      '<button class="modal-x" onclick="document.getElementById(\'modal-bg\').remove()">&times;</button>'+
      '<h3>Asset Detail</h3>'+
      '<div class="kv"><span class="kv-k">ID</span><span class="kv-v" style="cursor:pointer;font-size:11px;" onclick="navigator.clipboard.writeText(\''+esc(asset.asset_id)+'\');toast(\'Copied\')">'+esc(asset.asset_id)+' &#128203;</span></div>'+
      '<div class="kv"><span class="kv-k">Owner</span><span class="kv-v">'+esc(asset.owner)+'</span></div>'+
      '<div class="kv"><span class="kv-k">Created</span><span class="kv-v">'+timeAgo(asset.created_at)+'</span></div>'+
      '<div class="kv"><span class="kv-k">Price</span><span class="kv-v">'+(asset.spot_price!=null?asset.spot_price+' OAS':'&mdash;')+'</span></div>'+
      '<div class="kv"><span class="kv-k">Tags</span><span class="kv-v">'+(tags||'&mdash;')+'</span></div>'+
      '<div style="margin-top:16px;display:flex;gap:8px;">'+
        '<input type="text" id="m-tags" value="'+(asset.tags||[]).join(', ')+'" placeholder="Edit tags...">'+
        '<button class="btn btn-ghost btn-sm" onclick="editTags(\''+esc(asset.asset_id)+'\')">Save</button>'+
      '</div>'+
      '<button class="btn btn-danger btn-full" style="margin-top:10px;" onclick="if(confirm(\'Delete this asset?\')){deleteAsset(\''+esc(asset.asset_id)+'\');document.getElementById(\'modal-bg\').remove();}">Delete</button>'+
    '</div>';
    o.addEventListener('click',function(e){if(e.target===o)o.remove();});
    document.body.appendChild(o);
  }

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
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Protocol design and economics',
      'link-docs': 'Documentation',
      'link-docs-d': 'Technical reference and API',
      'link-github': 'GitHub',
      'link-github-d': 'Source code and contributions',
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
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '协议设计与经济模型',
      'link-docs': '技术文档',
      'link-docs-d': '技术参考与 API',
      'link-github': 'GitHub',
      'link-github-d': '源代码与贡献',
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

  // About panel
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'</h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<ul class="about-links">'+
        '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github']+'</div><div class="link-desc">'+t['link-github-d']+'</div></div></a></li>'+
      '</ul>'+
      '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>';
    document.body.appendChild(overlay);
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
      h+='<div class="a-row" onclick=\'showD('+JSON.stringify(a).replace(/\x27/g,"&#39;")+')\'>'+
        '<div class="a-info"><div class="a-id">'+esc(trunc(a.asset_id,32))+'</div><div class="a-meta">'+esc(a.owner)+' &middot; '+timeAgo(a.created_at)+(tags?' &middot; '+tags:'')+'</div></div>'+
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
  document.getElementById('reg-btn').addEventListener('click',async function(){var btn=this;btn.textContent='Registering...';btn.disabled=true;var fp=document.getElementById('reg-path').value.trim();var owner=document.getElementById('reg-owner').value.trim();var tags=document.getElementById('reg-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean);var div=document.getElementById('reg-result');try{var r=await postApi('/api/register',{file_path:fp,owner:owner||undefined,tags:tags});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Asset ID</span><span class="kv-v" style="font-size:11px;">'+esc(r.asset_id)+'</span></div></div>';toast('Asset registered');_all=[];// ── Drop Zone ──
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
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Protocol design and economics',
      'link-docs': 'Documentation',
      'link-docs-d': 'Technical reference and API',
      'link-github': 'GitHub',
      'link-github-d': 'Source code and contributions',
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
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '协议设计与经济模型',
      'link-docs': '技术文档',
      'link-docs-d': '技术参考与 API',
      'link-github': 'GitHub',
      'link-github-d': '源代码与贡献',
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

  // About panel
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'</h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<ul class="about-links">'+
        '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github']+'</div><div class="link-desc">'+t['link-github-d']+'</div></div></a></li>'+
      '</ul>'+
      '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>';
    document.body.appendChild(overlay);
  });


  try{var saved=localStorage.getItem('oasyce-lang');if(saved)_lang=saved;}catch(e){}
  applyLang();

  loadStatus();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Register';btn.disabled=false;});

  /* ── Quote & Buy ──────────── */
  document.getElementById('quote-btn').addEventListener('click',async function(){var aid=document.getElementById('buy-asset').value.trim();var amt=document.getElementById('buy-amount').value.trim()||'10';var div=document.getElementById('buy-result');if(!aid){div.innerHTML='<p class="err">Enter asset ID</p>';return;}var r=await api('/api/quote?asset_id='+encodeURIComponent(aid)+'&amount='+amt);if(!r||r.error){div.innerHTML='<p class="err">'+esc(r?r.error:'Failed')+'</p>';return;}div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Pay</span><span class="kv-v">'+r.payment+' OAS</span></div><div class="kv"><span class="kv-k">Get</span><span class="kv-v">'+r.tokens+' tokens</span></div><div class="kv"><span class="kv-k">Impact</span><span class="kv-v">'+r.impact_pct+'%</span></div><div class="kv"><span class="kv-k">Burned</span><span class="kv-v">'+r.burn+' OAS</span></div></div>';});

  document.getElementById('buy-btn').addEventListener('click',async function(){if(!confirm('Confirm purchase?'))return;var btn=this;btn.textContent='Buying...';btn.disabled=true;var aid=document.getElementById('buy-asset').value.trim();var amt=document.getElementById('buy-amount').value.trim()||'10';var div=document.getElementById('buy-result');if(!aid){div.innerHTML='<p class="err">Enter asset ID</p>';btn.textContent='Buy';btn.disabled=false;return;}try{var r=await postApi('/api/buy',{asset_id:aid,buyer:'gui_user',amount:parseFloat(amt)});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Tokens</span><span class="kv-v ok">'+r.tokens+'</span></div><div class="kv"><span class="kv-k">New price</span><span class="kv-v">'+r.price_after+' OAS</span></div></div>';toast('Purchased');loadPortfolio();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Buy';btn.disabled=false;});

  /* ── Portfolio ──────────── */
  async function loadPortfolio(){var list=await api('/api/portfolio?buyer=gui_user')||[];var c=document.getElementById('portfolio-list');if(!list.length){c.innerHTML='<div class="empty">No holdings yet</div>';return;}var h='';list.forEach(function(x){h+='<div class="p-row"><span class="p-id">'+esc(trunc(x.asset_id,24))+'</span><span class="p-v">'+x.shares+' shares &middot; '+x.value_oas+' OAS</span></div>';});c.innerHTML=h;}

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
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Protocol design and economics',
      'link-docs': 'Documentation',
      'link-docs-d': 'Technical reference and API',
      'link-github': 'GitHub',
      'link-github-d': 'Source code and contributions',
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
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '协议设计与经济模型',
      'link-docs': '技术文档',
      'link-docs-d': '技术参考与 API',
      'link-github': 'GitHub',
      'link-github-d': '源代码与贡献',
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

  // About panel
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'</h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<ul class="about-links">'+
        '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github']+'</div><div class="link-desc">'+t['link-github-d']+'</div></div></a></li>'+
      '</ul>'+
      '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>';
    document.body.appendChild(overlay);
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
      'about-desc': 'The data-rights clearing network for the machine economy. Agents autonomously register, license, settle, and enforce data rights.',
      'link-intro': 'Introduction',
      'link-intro-d': 'What is Oasyce and why it matters',
      'link-whitepaper': 'Whitepaper',
      'link-whitepaper-d': 'Protocol design and economics',
      'link-docs': 'Documentation',
      'link-docs-d': 'Technical reference and API',
      'link-github': 'GitHub',
      'link-github-d': 'Source code and contributions',
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
      'about-desc': '面向机器经济的数据权利清算网络。代理自主注册、许可、结算和执行数据权利。',
      'link-intro': '项目介绍',
      'link-intro-d': '什么是 Oasyce，为什么重要',
      'link-whitepaper': '白皮书',
      'link-whitepaper-d': '协议设计与经济模型',
      'link-docs': '技术文档',
      'link-docs-d': '技术参考与 API',
      'link-github': 'GitHub',
      'link-github-d': '源代码与贡献',
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

  // About panel
  document.getElementById('about-btn').addEventListener('click', function(){
    var ex=document.getElementById('about-overlay');if(ex){ex.remove();return;}
    var t = _t[_lang];
    var overlay=document.createElement('div');overlay.id='about-overlay';
    overlay.innerHTML='<div class="about-overlay" onclick="document.getElementById(\'about-overlay\').remove()"></div>'+
      '<div class="about-panel">'+
      '<button class="about-close" onclick="document.getElementById(\'about-overlay\').remove()">&times;</button>'+
      '<h3>'+t['about-title']+'</h3>'+
      '<p>'+t['about-desc']+'</p>'+
      '<ul class="about-links">'+
        '<li><a href="https://oasyce.com" target="_blank"><div><div class="link-label">'+t['link-intro']+'</div><div class="link-desc">'+t['link-intro-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank"><div><div class="link-label">'+t['link-whitepaper']+'</div><div class="link-desc">'+t['link-whitepaper-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank"><div><div class="link-label">'+t['link-docs']+'</div><div class="link-desc">'+t['link-docs-d']+'</div></div></a></li>'+
        '<li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank"><div><div class="link-label">'+t['link-github']+'</div><div class="link-desc">'+t['link-github-d']+'</div></div></a></li>'+
      '</ul>'+
      '<div class="about-contact">'+t['link-contact']+'<br><a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a></div>'+
      '</div>';
    document.body.appendChild(overlay);
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
        host: str = "0.0.0.0",
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
        global _ledger, _config
        _ledger = self._ledger
        _config = self._config

        import socket
        class _ReusableHTTPServer(HTTPServer):
            allow_reuse_address = True
            def server_bind(self):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                super().server_bind()

        server = _ReusableHTTPServer((self._host, self._port), _Handler)
        print(f"Oasyce Dashboard running on http://127.0.0.1:{self._port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down dashboard.")
            server.server_close()


if __name__ == "__main__":
    OasyceGUI().run()

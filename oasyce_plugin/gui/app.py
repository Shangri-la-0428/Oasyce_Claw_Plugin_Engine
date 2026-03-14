"""
Oasyce Web Dashboard — zero-dependency SPA served via Python stdlib.

Serves on port 8420. All HTML/CSS/JS is embedded in this single file.
Reads chain data from the local Ledger database.
"""

from __future__ import annotations

import json
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
_ledger: Optional[Ledger] = None
_config: Optional[Config] = None
_settlement: Any = None
_staking: Any = None
_skills: Any = None


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

        # ── SPA ──────────────────────────────────────────────────
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
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: #0a0a0a;
  color: #e0e0e0;
  font-family: ui-monospace, 'SF Mono', 'Cascadia Code', 'Fira Code', 'Menlo', monospace;
  font-size: 14px;
  line-height: 1.7;
  letter-spacing: 0.01em;
  -webkit-font-smoothing: antialiased;
}

/* ── Layout ──────────────────────────────────────────────── */
.wrap {
  max-width: 640px;
  margin: 0 auto;
  padding: 0 20px 80px;
}

/* ── Top Bar ─────────────────────────────────────────────── */
.top-bar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(10,10,10,0.88);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid #333;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.top-bar-brand {
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  letter-spacing: 5px;
  text-transform: uppercase;
}
.top-bar-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4ade80;
  margin-left: 8px;
  vertical-align: middle;
}
.top-bar-dot.off { background: #555; }

/* ── Hero ────────────────────────────────────────────────── */
.hero {
  text-align: center;
  padding: 56px 0 40px;
}
.hero-num {
  font-size: 48px;
  font-weight: 200;
  color: #fff;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.hero-label {
  font-size: 13px;
  color: #666;
  margin-top: 8px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
}
.hero-sub {
  display: flex;
  justify-content: center;
  gap: 48px;
  margin-top: 32px;
}
.hero-sub-item { text-align: center; }
.hero-sub-num {
  font-size: 22px;
  font-weight: 300;
  color: #bbb;
  font-variant-numeric: tabular-nums;
}
.hero-sub-label {
  font-size: 11px;
  color: #555;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-top: 2px;
}

/* ── Sections ────────────────────────────────────────────── */
.section {
  border-top: 1px solid #282828;
  padding: 32px 0;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  padding: 0 4px;
}
.section-title {
  font-size: 11px;
  font-weight: 500;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 3px;
}
.section-toggle {
  font-size: 12px;
  color: #555;
  transition: transform 0.2s ease;
  line-height: 1;
}
.section-toggle.open { transform: rotate(90deg); }
.section-body {
  overflow: hidden;
  transition: max-height 0.4s ease, opacity 0.3s ease;
  max-height: 0;
  opacity: 0;
}
.section-body.open {
  max-height: 4000px;
  opacity: 1;
}
.section-content {
  padding-top: 24px;
}

/* ── Inputs ──────────────────────────────────────────────── */
input[type="text"], input[type="number"], select, textarea {
  width: 100%;
  height: 44px;
  font-size: 14px;
  background: transparent;
  border: none;
  border-bottom: 1px solid #2a2a2a;
  border-radius: 0;
  color: #e0e0e0;
  padding: 0 14px;
  outline: none;
  transition: border-color 0.2s;
  font-family: inherit;
}
select { border: 1px solid #2a2a2a; border-radius: 0; }
input:focus, select:focus, textarea:focus { border-bottom-color: #666; }
input::placeholder, textarea::placeholder { color: #444; }
textarea { height: auto; min-height: 80px; padding: 10px 12px; resize: vertical; border: 1px solid #2a2a2a; }

.input-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.input-row input, .input-row select { flex: 1; }

/* ── Buttons ─────────────────────────────────────────────── */
.btn {
  height: 44px;
  font-size: 14px;
  font-weight: 500;
  background: #141414;
  color: #aaa;
  border: 1px solid #333;
  border-radius: 0;
  padding: 0 20px;
  cursor: pointer;
  transition: all 0.2s;
  width: 100%;
  font-family: inherit;
}
.btn:hover { background: #1a1a1a; border-color: #555; color: #fff; box-shadow: 1px 1px 0 #333; }

/* ── Asset List ──────────────────────────────────────────── */
.asset-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 0;
  border-bottom: 1px dotted #222;
  cursor: pointer;
  transition: opacity 0.2s;
}
.asset-item:hover { opacity: 0.7; }
.asset-item:last-child { border-bottom: none; }
.asset-left { flex: 1; min-width: 0; }
.asset-id {
  font-family: inherit;
  font-size: 13px;
  color: #ccc;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.asset-meta-line {
  font-size: 12px;
  color: #555;
  margin-top: 2px;
}
.asset-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  margin-left: 16px;
}
.asset-price {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 13px;
  color: #888;
}
.asset-delete-btn {
  width: 28px;
  height: 28px;
  border: none;
  background: transparent;
  color: #444;
  font-size: 16px;
  cursor: pointer;
  border-radius: 0;
  opacity: 0;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}
.asset-item:hover .asset-delete-btn { opacity: 1; }
.asset-delete-btn:hover { color: #f87171; background: #1a1a1a; }

/* ── Tags ────────────────────────────────────────────────── */
.pill {
  display: inline-block;
  height: 18px;
  line-height: 18px;
  padding: 0 6px;
  font-size: 10px;
  border: 1px solid #333;
  border-radius: 0;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-right: 4px;
}

/* ── Key-Value Rows ──────────────────────────────────────── */
.kv-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 8px 0;
  border-bottom: 1px dotted #222;
  font-size: 13px;
}
.kv-row:last-child { border-bottom: none; }
.kv-key { color: #555; }
.kv-val {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 13px;
  color: #ccc;
  text-align: right;
  word-break: break-all;
  max-width: 60%;
}

/* ── Result Box ──────────────────────────────────────────── */
.result-box {
  background: #0d0d0d;
  border: 1px solid #333;
  border-radius: 0;
  padding: 16px;
  margin-top: 16px;
}

/* ── Modal ────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.8);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.2s ease;
}
.modal {
  background: #111;
  border: 1px solid #333;
  border-radius: 0;
  box-shadow: 3px 3px 0 #000;
  max-width: 480px;
  width: 90%;
  max-height: 80vh;
  overflow-y: auto;
  padding: 32px;
  position: relative;
}
.modal-close {
  position: absolute;
  top: 16px;
  right: 16px;
  background: none;
  border: none;
  color: #555;
  font-size: 16px;
  cursor: pointer;
}
.modal-close:hover { color: #fff; }
.modal h3 {
  font-size: 14px;
  font-weight: 500;
  color: #fff;
  margin-bottom: 20px;
}

/* ── Toast ────────────────────────────────────────────────── */
.toast-container {
  position: fixed;
  top: 60px;
  right: 20px;
  z-index: 300;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toast {
  background: #141414;
  border: 1px solid #2a2a2a;
  border-radius: 0;
  padding: 10px 14px;
  font-size: 12px;
  color: #ccc;
  animation: toastIn 0.25s ease, toastOut 0.25s ease 2.7s forwards;
  max-width: 300px;
}
.toast.error { border-color: #f8717144; color: #f87171; }

/* ── Empty State ─────────────────────────────────────────── */
.empty {
  text-align: center;
  color: #444;
  padding: 40px 16px;
  font-size: 14px;
}
.empty code {
  background: #141414;
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 13px;
  color: #888;
  font-family: ui-monospace, 'SF Mono', monospace;
}

/* ── Status Text ─────────────────────────────────────────── */
.ok { color: #4ade80; }
.err { color: #f87171; margin-top: 12px; font-size: 14px; }

/* ── Portfolio Table ─────────────────────────────────────── */
.port-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid #141414;
  font-size: 13px;
}
.port-row:last-child { border-bottom: none; }
.port-asset {
  font-family: ui-monospace, 'SF Mono', monospace;
  color: #ccc;
}
.port-val { color: #888; }

/* ── AHRP Match Cards ────────────────────────────────────── */
.match-card {
  padding: 14px 0;
  border-bottom: 1px solid #141414;
}
.match-card:last-child { border-bottom: none; }
.match-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.match-agent {
  font-family: ui-monospace, 'SF Mono', monospace;
  color: #ccc;
}
.match-origin {
  font-size: 11px;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.match-bar {
  width: 100%;
  height: 2px;
  background: #1a1a1a;
  border-radius: 0;
  margin: 6px 0;
}
.match-bar-fill {
  height: 100%;
  border-radius: 1px;
  background: #555;
}
.match-bottom {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #555;
}

/* ── Transaction Pipeline ─────────────────────────────────── */
.tx-pipeline {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  margin: 24px 0;
}
.tx-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
}
.tx-dot {
  width: 8px;
  height: 8px;
  border-radius: 0;
  border: 1.5px solid #333;
  background: transparent;
  transition: all 0.3s ease;
}
.tx-step.done .tx-dot { background: #fff; border-color: #fff; }
.tx-step.active .tx-dot { border-color: #888; }
.tx-line {
  width: 32px;
  height: 1px;
  background: #222;
  margin-bottom: 18px;
  transition: background 0.3s ease;
}
.tx-line.done { background: #555; }
.tx-step-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #444;
  transition: color 0.3s ease;
}
.tx-step.done .tx-step-label { color: #888; }
.tx-step.active .tx-step-label { color: #ccc; }

/* ── Star Rating ─────────────────────────────────────────── */
.star-rating {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
}
.star-rating span {
  font-size: 20px;
  cursor: pointer;
  color: #333;
  transition: color 0.15s;
  user-select: none;
}
.star-rating span.lit { color: #fff; }

/* ── Checkbox group ──────────────────────────────────────── */
.checkbox-group {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #888;
  cursor: pointer;
}
.checkbox-group input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: #666;
}

/* ── Network Info ────────────────────────────────────────── */
.net-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 24px;
  font-size: 13px;
}
.net-key { color: #555; }
.net-val {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 13px;
  color: #888;
  text-align: right;
}

.stake-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #141414;
  font-size: 13px;
}
.stake-item:last-child { border-bottom: none; }
.stake-id {
  font-family: ui-monospace, 'SF Mono', monospace;
  color: #888;
}
.stake-amount {
  font-family: ui-monospace, 'SF Mono', monospace;
  color: #ccc;
}

/* ── Animations ──────────────────────────────────────────── */
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes toastIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toastOut { from { opacity: 1; } to { opacity: 0; } }

/* ── Responsive ──────────────────────────────────────────── */
@media (max-width: 640px) {
  .wrap { padding: 0 16px 64px; }
  .hero-num { font-size: 44px; }
  .hero-sub { gap: 24px; }
  .input-row { flex-direction: column; }
  .net-grid { grid-template-columns: 1fr; }
  .net-val { text-align: left; }
  .kv-row { flex-direction: column; gap: 2px; }
  .kv-val { text-align: left; max-width: 100%; }
}
</style>
</head>
<body>

<div class="top-bar">
  <span class="top-bar-brand">Oasyce</span>
  <span class="top-bar-dot" id="status-dot"></span>
</div>

<div class="wrap">

  <!-- Hero: one big number -->
  <div class="hero">
    <div class="hero-num" id="stat-assets">—</div>
    <div class="hero-label">Assets Registered</div>
    <div class="hero-sub">
      <div class="hero-sub-item">
        <div class="hero-sub-num" id="stat-blocks">—</div>
        <div class="hero-sub-label">Blocks</div>
      </div>
      <div class="hero-sub-item">
        <div class="hero-sub-num" id="stat-dists">—</div>
        <div class="hero-sub-label">Watermarks</div>
      </div>
    </div>
  </div>

  <!-- ═══ Assets ═══ -->
  <div class="section" id="sec-assets">
    <div class="section-header" onclick="toggleSection('assets')">
      <span class="section-title">Your Assets</span>
      <span class="section-toggle open" id="toggle-assets">▸</span>
    </div>
    <div class="section-body open" id="body-assets">
      <div class="section-content">
        <input type="text" id="asset-search" placeholder="Search..." style="margin-bottom:16px;">
        <div id="assets-list"></div>
      </div>
    </div>
  </div>

  <!-- ═══ Register ═══ -->
  <div class="section" id="sec-register">
    <div class="section-header" onclick="toggleSection('register')">
      <span class="section-title">Register</span>
      <span class="section-toggle" id="toggle-register">▸</span>
    </div>
    <div class="section-body" id="body-register">
      <div class="section-content">
        <div class="input-row"><input type="text" id="reg-path" placeholder="File path"></div>
        <div class="input-row">
          <input type="text" id="reg-owner" placeholder="Owner">
          <input type="text" id="reg-tags" placeholder="Tags (comma-separated)">
        </div>
        <button class="btn" id="reg-btn">Register</button>
        <div id="reg-result"></div>
      </div>
    </div>
  </div>

  <!-- ═══ Trade ═══ -->
  <div class="section" id="sec-trade">
    <div class="section-header" onclick="toggleSection('trade')">
      <span class="section-title">Trade</span>
      <span class="section-toggle" id="toggle-trade">▸</span>
    </div>
    <div class="section-body" id="body-trade">
      <div class="section-content">
        <div class="input-row">
          <input type="text" id="buy-asset" placeholder="Asset ID">
          <input type="text" id="buy-amount" placeholder="Amount (OAS)" value="10" style="max-width:120px;">
        </div>
        <div class="input-row" style="gap:8px;">
          <button class="btn" id="quote-btn" style="flex:1;">Quote</button>
          <button class="btn" id="buy-btn" style="flex:1;">Buy</button>
        </div>
        <div id="buy-result"></div>
      </div>
    </div>
  </div>

  <!-- ═══ Portfolio ═══ -->
  <div class="section" id="sec-portfolio">
    <div class="section-header" onclick="toggleSection('portfolio')">
      <span class="section-title">Portfolio</span>
      <span class="section-toggle" id="toggle-portfolio">▸</span>
    </div>
    <div class="section-body" id="body-portfolio">
      <div class="section-content" id="portfolio-list"></div>
    </div>
  </div>

  <!-- ═══ Watermark ═══ -->
  <div class="section" id="sec-watermark">
    <div class="section-header" onclick="toggleSection('watermark')">
      <span class="section-title">Watermark</span>
      <span class="section-toggle" id="toggle-watermark">▸</span>
    </div>
    <div class="section-body" id="body-watermark">
      <div class="section-content">
        <div class="input-row">
          <input type="text" id="emb-asset" placeholder="Asset ID">
          <input type="text" id="emb-caller" placeholder="Buyer ID">
        </div>
        <textarea id="emb-content" placeholder="Content to watermark..."></textarea>
        <button class="btn" id="emb-btn" style="margin-top:8px;">Embed</button>
        <div id="emb-result"></div>

        <div style="border-top:1px solid #1a1a1a;margin-top:24px;padding-top:24px;">
          <div class="input-row">
            <input type="text" id="fp-input" placeholder="Trace a fingerprint...">
            <button class="btn" id="fp-trace-btn" style="max-width:100px;">Trace</button>
          </div>
          <div id="fp-trace-result"></div>
        </div>

        <div style="border-top:1px solid #1a1a1a;margin-top:24px;padding-top:24px;">
          <div class="input-row">
            <input type="text" id="fp-asset-input" placeholder="Look up by asset ID...">
            <button class="btn" id="fp-list-btn" style="max-width:100px;">Look up</button>
          </div>
          <div id="fp-dist-list"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- ═══ Stake ═══ -->
  <div class="section" id="sec-stake">
    <div class="section-header" onclick="toggleSection('stake')">
      <span class="section-title">Stake</span>
      <span class="section-toggle" id="toggle-stake">▸</span>
    </div>
    <div class="section-body" id="body-stake">
      <div class="section-content">
        <div class="input-row">
          <input type="text" id="stake-node" placeholder="Node ID">
          <input type="text" id="stake-amount" placeholder="Amount (OAS)" value="10000" style="max-width:140px;">
        </div>
        <button class="btn" id="stake-btn">Stake</button>
        <div id="stake-result"></div>
      </div>
    </div>
  </div>

  <!-- ═══ AHRP ═══ -->
  <div class="section" id="sec-ahrp">
    <div class="section-header" onclick="toggleSection('ahrp')">
      <span class="section-title">Agent Protocol (AHRP)</span>
      <span class="section-toggle" id="toggle-ahrp">▸</span>
    </div>
    <div class="section-body" id="body-ahrp">
      <div class="section-content">

        <!-- Register Agent -->
        <div style="margin-bottom:24px;">
          <div style="font-size:12px;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">Register Agent</div>
          <div class="input-row">
            <input type="text" id="ahrp-agent-id" placeholder="Agent ID">
            <input type="text" id="ahrp-pub-key" placeholder="Public key">
          </div>
          <div class="input-row">
            <input type="number" id="ahrp-reputation" placeholder="Reputation" value="10">
            <input type="number" id="ahrp-stake" placeholder="Stake" value="100">
          </div>
          <div class="input-row">
            <input type="text" id="ahrp-cap-id" placeholder="Capability ID">
            <input type="text" id="ahrp-cap-tags" placeholder="Tags">
          </div>
          <div class="input-row">
            <input type="text" id="ahrp-cap-desc" placeholder="Description" style="flex:2;">
            <input type="number" id="ahrp-cap-price" placeholder="Price floor" value="1.0">
          </div>
          <div class="input-row">
            <select id="ahrp-cap-origin">
              <option value="human">human</option>
              <option value="sensor">sensor</option>
              <option value="curated">curated</option>
              <option value="synthetic">synthetic</option>
            </select>
          </div>
          <div class="checkbox-group">
            <label><input type="checkbox" value="L0" checked> L0</label>
            <label><input type="checkbox" value="L1" checked> L1</label>
            <label><input type="checkbox" value="L2"> L2</label>
            <label><input type="checkbox" value="L3"> L3</label>
          </div>
          <button class="btn" id="ahrp-announce-btn">Announce</button>
          <div id="ahrp-announce-result"></div>
        </div>

        <!-- Discover -->
        <div style="border-top:1px solid #1a1a1a;padding-top:24px;margin-bottom:24px;">
          <div style="font-size:12px;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">Discover</div>
          <div class="input-row">
            <input type="text" id="ahrp-search-desc" placeholder="What data do you need?" style="flex:2;">
            <input type="text" id="ahrp-search-tags" placeholder="Tags">
          </div>
          <div class="input-row">
            <input type="number" id="ahrp-search-rep" placeholder="Min reputation" value="5">
            <input type="number" id="ahrp-search-price" placeholder="Max price" value="100">
            <select id="ahrp-search-access">
              <option value="L0">L0</option><option value="L1">L1</option>
              <option value="L2">L2</option><option value="L3">L3</option>
            </select>
          </div>
          <button class="btn" id="ahrp-find-btn">Find</button>
          <div id="ahrp-matches" style="margin-top:16px;"></div>
        </div>

        <!-- Transaction Flow -->
        <div style="border-top:1px solid #1a1a1a;padding-top:24px;">
          <div style="font-size:12px;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;">Transaction</div>

          <div class="tx-pipeline" id="tx-pipeline">
            <div class="tx-step" id="tx-step-request"><div class="tx-dot"></div><div class="tx-step-label">Request</div></div>
            <div class="tx-line" id="tx-line-1"></div>
            <div class="tx-step" id="tx-step-offer"><div class="tx-dot"></div><div class="tx-step-label">Offer</div></div>
            <div class="tx-line" id="tx-line-2"></div>
            <div class="tx-step" id="tx-step-accept"><div class="tx-dot"></div><div class="tx-step-label">Accept</div></div>
            <div class="tx-line" id="tx-line-3"></div>
            <div class="tx-step" id="tx-step-deliver"><div class="tx-dot"></div><div class="tx-step-label">Deliver</div></div>
            <div class="tx-line" id="tx-line-4"></div>
            <div class="tx-step" id="tx-step-confirm"><div class="tx-dot"></div><div class="tx-step-label">Confirm</div></div>
          </div>

          <div class="input-row">
            <input type="text" id="tx-buyer" placeholder="Buyer ID">
            <input type="text" id="tx-seller" placeholder="Seller ID">
          </div>
          <div class="input-row">
            <input type="text" id="tx-cap-id" placeholder="Capability ID">
            <input type="number" id="tx-price" placeholder="Price" value="10">
          </div>
          <button class="btn" id="tx-accept-btn">Accept & Create</button>
          <div id="tx-accept-result"></div>

          <div style="border-top:1px solid #1a1a1a;margin-top:20px;padding-top:20px;">
            <div class="input-row">
              <input type="text" id="tx-deliver-id" placeholder="Transaction ID">
              <input type="text" id="tx-content-hash" placeholder="Content hash">
            </div>
            <button class="btn" id="tx-deliver-btn">Deliver</button>
            <div id="tx-deliver-result"></div>
          </div>

          <div style="border-top:1px solid #1a1a1a;margin-top:20px;padding-top:20px;">
            <div class="input-row">
              <input type="text" id="tx-confirm-id" placeholder="Transaction ID">
            </div>
            <div class="star-rating" id="star-rating">
              <span data-v="1">&#x2605;</span>
              <span data-v="2">&#x2605;</span>
              <span data-v="3">&#x2605;</span>
              <span data-v="4">&#x2605;</span>
              <span data-v="5">&#x2605;</span>
            </div>
            <button class="btn" id="tx-confirm-btn">Confirm & Settle</button>
            <div id="tx-confirm-result"></div>
          </div>
        </div>

      </div>
    </div>
  </div>

  <!-- ═══ Network ═══ -->
  <div class="section" id="sec-network">
    <div class="section-header" onclick="toggleSection('network')">
      <span class="section-title">Network</span>
      <span class="section-toggle" id="toggle-network">▸</span>
    </div>
    <div class="section-body" id="body-network">
      <div class="section-content">
        <div class="net-grid" id="net-info"></div>
        <div id="stakes-section" style="display:none;margin-top:20px;padding-top:20px;border-top:1px solid #1a1a1a;">
          <div id="stakes-list"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- Footer -->
  <div style="text-align:center;font-size:10px;color:#333;padding:48px 0 0;letter-spacing:3px;text-transform:uppercase;">Oasyce Protocol · 2026</div>

</div>

<script>
(function() {

  /* ── Helpers ──────────────────────────────────────────── */
  function esc(s) {
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }
  function trunc(s, n) { n=n||16; return s&&s.length>n ? s.slice(0,n)+'\u2026' : (s||''); }
  function timeAgo(ts) {
    if (!ts) return '';
    var then = typeof ts==='number' ? (ts>1e12?new Date(ts):new Date(ts*1000)) : new Date(ts);
    var d = Math.floor((Date.now()-then.getTime())/1000);
    if (d<0) d=0;
    if (d<60) return d+'s';
    if (d<3600) return Math.floor(d/60)+'m';
    if (d<86400) return Math.floor(d/3600)+'h';
    return Math.floor(d/86400)+'d';
  }
  async function api(p) { try { return (await fetch(p)).json(); } catch(e) { return null; } }
  async function postApi(p, b) { try { return (await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})).json(); } catch(e) { return {error:e.message}; } }

  /* ── Toast ───────────────────────────────────────────── */
  function toast(msg, type) {
    var c = document.getElementById('toast-container');
    if (!c) { c=document.createElement('div'); c.id='toast-container'; c.className='toast-container'; document.body.appendChild(c); }
    var el=document.createElement('div');
    el.className='toast'+(type==='error'?' error':'');
    el.textContent=msg;
    c.appendChild(el);
    setTimeout(function(){el.remove();},3000);
  }

  /* ── Section Toggle ──────────────────────────────────── */
  window.toggleSection = function(name) {
    var body = document.getElementById('body-'+name);
    var toggle = document.getElementById('toggle-'+name);
    var isOpen = body.classList.contains('open');
    body.classList.toggle('open');
    toggle.classList.toggle('open');
  };

  /* ── Modal ───────────────────────────────────────────── */
  function showAssetModal(asset) {
    var existing = document.getElementById('modal-overlay');
    if (existing) existing.remove();
    var overlay = document.createElement('div');
    overlay.id = 'modal-overlay';
    overlay.className = 'modal-overlay';
    var tags = (asset.tags||[]).map(function(t){return '<span class="pill">'+esc(t)+'</span>';}).join(' ');
    overlay.innerHTML = '<div class="modal" onclick="event.stopPropagation()">'+
      '<button class="modal-close" onclick="document.getElementById(\'modal-overlay\').remove()">&times;</button>'+
      '<h3>Asset Detail</h3>'+
      '<div class="kv-row"><span class="kv-key">ID</span><span class="kv-val" style="cursor:pointer;font-size:12px;" onclick="navigator.clipboard.writeText(\''+esc(asset.asset_id)+'\')">'+esc(asset.asset_id)+' &#x1f4cb;</span></div>'+
      '<div class="kv-row"><span class="kv-key">Owner</span><span class="kv-val">'+esc(asset.owner)+'</span></div>'+
      '<div class="kv-row"><span class="kv-key">Created</span><span class="kv-val">'+timeAgo(asset.created_at)+'</span></div>'+
      '<div class="kv-row"><span class="kv-key">Price</span><span class="kv-val">'+(asset.spot_price!=null?asset.spot_price+' OAS':'—')+'</span></div>'+
      '<div class="kv-row"><span class="kv-key">Tags</span><span class="kv-val">'+(tags||'—')+'</span></div>'+
      '<div style="margin-top:16px;display:flex;gap:8px;">'+
        '<input type="text" id="modal-edit-tags" value="'+(asset.tags||[]).join(', ')+'" placeholder="Edit tags..." style="flex:1;">'+
        '<button class="btn" style="width:auto;padding:0 16px;" onclick="editTags(\''+esc(asset.asset_id)+'\')">Save</button>'+
      '</div>'+
      '<button class="btn" style="margin-top:12px;color:#f87171;border-color:#f8717133;" onclick="if(confirm(\'Delete this asset?\')){deleteAsset(\''+esc(asset.asset_id)+'\');document.getElementById(\'modal-overlay\').remove();}">Delete Asset</button>'+
    '</div>';
    overlay.addEventListener('click', function(e) { if(e.target===overlay) overlay.remove(); });
    document.body.appendChild(overlay);
  }

  window.editTags = async function(aid) {
    var input = document.getElementById('modal-edit-tags');
    var tags = input.value.split(',').map(function(t){return t.trim();}).filter(Boolean);
    var r = await postApi('/api/asset/update', {asset_id:aid,tags:tags});
    if (r && r.ok) { toast('Tags updated'); loadAssets(); } else { toast(r?r.error:'Failed','error'); }
  };

  window.deleteAsset = async function(aid) {
    if (!confirm('Delete this asset permanently?')) return;
    try {
      var r = await fetch('/api/asset/'+aid, {method:'DELETE'});
      var d = await r.json();
      if (d.ok) { toast('Asset deleted'); loadAssets(); loadStatus(); }
      else { toast(d.error||'Failed','error'); }
    } catch(e) { toast(e.message,'error'); }
  };

  /* ── Load Status ─────────────────────────────────────── */
  async function loadStatus() {
    var d = await api('/api/status');
    var dot = document.getElementById('status-dot');
    if (!d) { dot.className='top-bar-dot off'; return; }
    dot.className='top-bar-dot';
    document.getElementById('stat-assets').textContent = d.total_assets;
    document.getElementById('stat-blocks').textContent = d.total_blocks;
    document.getElementById('stat-dists').textContent = d.total_distributions;
    var ni=document.getElementById('net-info');
    ni.innerHTML='<span class="net-key">Node</span><span class="net-val">'+esc(d.node_id)+'</span>'+
      '<span class="net-key">Address</span><span class="net-val">'+esc(d.host)+':'+esc(d.port)+'</span>'+
      '<span class="net-key">Height</span><span class="net-val">'+esc(d.chain_height)+'</span>';
  }

  /* ── Assets ──────────────────────────────────────────── */
  var _allAssets = [];
  async function loadAssets() {
    _allAssets = await api('/api/assets') || [];
    renderAssets(_allAssets);
  }
  function renderAssets(list) {
    var c = document.getElementById('assets-list');
    if (!list.length) { c.innerHTML='<div class="empty">No assets yet. Register with <code>oasyce register &lt;file&gt;</code></div>'; return; }
    var html='';
    list.forEach(function(a) {
      var tags = (a.tags||[]).map(function(t){return '<span class="pill">'+esc(t)+'</span>';}).join('');
      html += '<div class="asset-item" onclick=\'showAssetDetail('+JSON.stringify(a).replace(/'/g,"&#39;")+')\'>'+
        '<div class="asset-left">'+
          '<div class="asset-id">'+esc(trunc(a.asset_id,28))+'</div>'+
          '<div class="asset-meta-line">'+esc(a.owner)+' · '+timeAgo(a.created_at)+(tags?' · '+tags:'')+'</div>'+
        '</div>'+
        '<div class="asset-right">'+
          (a.spot_price!=null?'<span class="asset-price">'+a.spot_price+'</span>':'')+
          '<button class="asset-delete-btn" title="Delete" onclick="event.stopPropagation();deleteAsset(\''+esc(a.asset_id)+'\')">&times;</button>'+
        '</div>'+
      '</div>';
    });
    c.innerHTML=html;
  }
  window.showAssetDetail = function(a) { showAssetModal(a); };

  document.getElementById('asset-search').addEventListener('input', function(e) {
    var q=e.target.value.toLowerCase();
    if(!q){renderAssets(_allAssets);return;}
    renderAssets(_allAssets.filter(function(a){
      return (a.asset_id||'').toLowerCase().indexOf(q)!==-1 ||
        (a.tags||[]).some(function(t){return t.toLowerCase().indexOf(q)!==-1;});
    }));
  });

  /* ── Register ────────────────────────────────────────── */
  document.getElementById('reg-btn').addEventListener('click', async function() {
    var btn=this; btn.textContent='...'; btn.disabled=true;
    var fp=document.getElementById('reg-path').value.trim();
    var owner=document.getElementById('reg-owner').value.trim();
    var tags=document.getElementById('reg-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean);
    var div=document.getElementById('reg-result');
    try {
      var r=await postApi('/api/register',{file_path:fp,owner:owner||undefined,tags:tags});
      if(r.ok){
        div.innerHTML='<div class="result-box"><div class="kv-row"><span class="kv-key">Asset ID</span><span class="kv-val">'+esc(r.asset_id)+'</span></div></div>';
        toast('Registered'); loadAssets(); loadStatus();
      } else { div.innerHTML='<p class="err">'+esc(r.error)+'</p>'; }
    } catch(e) { div.innerHTML='<p class="err">'+esc(e.message)+'</p>'; }
    btn.textContent='Register'; btn.disabled=false;
  });

  /* ── Quote & Buy ─────────────────────────────────────── */
  document.getElementById('quote-btn').addEventListener('click', async function() {
    var aid=document.getElementById('buy-asset').value.trim();
    var amt=document.getElementById('buy-amount').value.trim()||'10';
    var div=document.getElementById('buy-result');
    if(!aid){div.innerHTML='<p class="err">Enter an asset ID</p>';return;}
    var r=await api('/api/quote?asset_id='+encodeURIComponent(aid)+'&amount='+amt);
    if(!r||r.error){div.innerHTML='<p class="err">'+esc(r?r.error:'Failed')+'</p>';return;}
    div.innerHTML='<div class="result-box">'+
      '<div class="kv-row"><span class="kv-key">You pay</span><span class="kv-val">'+r.payment+' OAS</span></div>'+
      '<div class="kv-row"><span class="kv-key">You get</span><span class="kv-val">'+r.tokens+' tokens</span></div>'+
      '<div class="kv-row"><span class="kv-key">Impact</span><span class="kv-val">'+r.impact_pct+'%</span></div>'+
      '<div class="kv-row"><span class="kv-key">Burned</span><span class="kv-val">'+r.burn+' OAS</span></div>'+
      '</div>';
  });

  document.getElementById('buy-btn').addEventListener('click', async function() {
    if(!confirm('Confirm purchase?')) return;
    var btn=this; btn.textContent='...'; btn.disabled=true;
    var aid=document.getElementById('buy-asset').value.trim();
    var amt=document.getElementById('buy-amount').value.trim()||'10';
    var div=document.getElementById('buy-result');
    if(!aid){div.innerHTML='<p class="err">Enter asset ID</p>';btn.textContent='Buy';btn.disabled=false;return;}
    try {
      var r=await postApi('/api/buy',{asset_id:aid,buyer:'gui_user',amount:parseFloat(amt)});
      if(r.ok){
        div.innerHTML='<div class="result-box"><div class="kv-row"><span class="kv-key">Tokens</span><span class="kv-val ok">'+r.tokens+'</span></div><div class="kv-row"><span class="kv-key">New price</span><span class="kv-val">'+r.price_after+' OAS</span></div></div>';
        toast('Purchase complete'); loadPortfolio();
      } else { div.innerHTML='<p class="err">'+esc(r.error)+'</p>'; }
    } catch(e) { div.innerHTML='<p class="err">'+esc(e.message)+'</p>'; }
    btn.textContent='Buy'; btn.disabled=false;
  });

  /* ── Portfolio ───────────────────────────────────────── */
  async function loadPortfolio() {
    var list = await api('/api/portfolio?buyer=gui_user') || [];
    var c = document.getElementById('portfolio-list');
    if (!list.length) { c.innerHTML='<div class="empty">No holdings yet</div>'; return; }
    var html='';
    list.forEach(function(h) {
      html+='<div class="port-row"><span class="port-asset">'+esc(trunc(h.asset_id,20))+'</span><span class="port-val">'+h.shares+' shares · '+h.value_oas+' OAS</span></div>';
    });
    c.innerHTML=html;
  }

  /* ── Watermark Embed ─────────────────────────────────── */
  document.getElementById('emb-btn').addEventListener('click', async function() {
    var btn=this; btn.textContent='...'; btn.disabled=true;
    var aid=document.getElementById('emb-asset').value.trim();
    var caller=document.getElementById('emb-caller').value.trim();
    var content=document.getElementById('emb-content').value;
    var div=document.getElementById('emb-result');
    if(!aid||!caller||!content){div.innerHTML='<p class="err">Fill all fields</p>';btn.textContent='Embed';btn.disabled=false;return;}
    try {
      var r=await postApi('/api/fingerprint/embed',{asset_id:aid,caller_id:caller,content:content});
      if(r.ok){
        div.innerHTML='<div class="result-box"><div class="kv-row"><span class="kv-key">Fingerprint</span><span class="kv-val">'+esc(trunc(r.fingerprint,28))+'</span></div></div>'+
          '<textarea readonly style="width:100%;min-height:80px;margin-top:8px;color:#4ade80;">'+esc(r.watermarked_content)+'</textarea>';
        toast('Watermark embedded'); loadStatus();
      } else { div.innerHTML='<p class="err">'+esc(r.error)+'</p>'; }
    } catch(e) { div.innerHTML='<p class="err">'+esc(e.message)+'</p>'; }
    btn.textContent='Embed'; btn.disabled=false;
  });

  /* ── Trace ───────────────────────────────────────────── */
  document.getElementById('fp-trace-btn').addEventListener('click', async function() {
    var fp=document.getElementById('fp-input').value.trim();
    if(!fp)return;
    var r=await api('/api/trace?fp='+encodeURIComponent(fp));
    var div=document.getElementById('fp-trace-result');
    if(!r||r.error){ div.innerHTML='<p class="err">Not found</p>'; }
    else {
      div.innerHTML='<div class="result-box">'+
        '<div class="kv-row"><span class="kv-key">Asset</span><span class="kv-val">'+esc(r.asset_id)+'</span></div>'+
        '<div class="kv-row"><span class="kv-key">Buyer</span><span class="kv-val">'+esc(r.caller_id)+'</span></div>'+
        '<div class="kv-row"><span class="kv-key">When</span><span class="kv-val">'+timeAgo(r.timestamp||r.created_at)+'</span></div>'+
        '</div>';
    }
  });

  document.getElementById('fp-list-btn').addEventListener('click', async function() {
    var aid=document.getElementById('fp-asset-input').value.trim();
    if(!aid)return;
    var list=await api('/api/fingerprints?asset_id='+encodeURIComponent(aid));
    var c=document.getElementById('fp-dist-list');
    if(!list||!list.length){c.innerHTML='<p class="err">No watermarks found</p>';return;}
    var html='';
    list.forEach(function(r){
      html+='<div class="port-row"><span class="port-asset" style="font-size:12px;">'+esc(trunc(r.fingerprint,20))+'</span><span class="port-val">'+esc(r.caller_id)+' · '+timeAgo(r.timestamp)+'</span></div>';
    });
    c.innerHTML=html;
  });

  /* ── Stake ───────────────────────────────────────────── */
  document.getElementById('stake-btn').addEventListener('click', async function() {
    var btn=this; btn.textContent='...'; btn.disabled=true;
    var nid=document.getElementById('stake-node').value.trim();
    var amt=document.getElementById('stake-amount').value.trim()||'10000';
    var div=document.getElementById('stake-result');
    if(!nid){div.innerHTML='<p class="err">Enter node ID</p>';btn.textContent='Stake';btn.disabled=false;return;}
    try {
      var r=await postApi('/api/stake',{node_id:nid,amount:parseFloat(amt)});
      if(r.ok){
        div.innerHTML='<div class="result-box"><div class="kv-row"><span class="kv-key">Staked</span><span class="kv-val">'+r.total_stake+' OAS</span></div></div>';
        toast('Staked'); loadStakes();
      } else { div.innerHTML='<p class="err">'+esc(r.error)+'</p>'; }
    } catch(e) { div.innerHTML='<p class="err">'+esc(e.message)+'</p>'; }
    btn.textContent='Stake'; btn.disabled=false;
  });

  async function loadStakes() {
    var list=await api('/api/stakes')||[];
    var sec=document.getElementById('stakes-section');
    if(!list.length){sec.style.display='none';return;}
    sec.style.display='block';
    var html='';
    list.forEach(function(s){html+='<div class="stake-item"><span class="stake-id">'+esc(trunc(s.validator_id,20))+'</span><span class="stake-amount">'+s.total+' OAS</span></div>';});
    document.getElementById('stakes-list').innerHTML=html;
  }

  /* ── AHRP ────────────────────────────────────────────── */
  document.getElementById('ahrp-announce-btn').addEventListener('click', async function() {
    var btn=this; btn.textContent='...'; btn.disabled=true;
    var div=document.getElementById('ahrp-announce-result');
    var levels=[];
    document.querySelectorAll('#sec-ahrp .checkbox-group input:checked').forEach(function(cb){levels.push(cb.value);});
    var payload={
      agent_id:document.getElementById('ahrp-agent-id').value.trim(),
      public_key:document.getElementById('ahrp-pub-key').value.trim(),
      reputation:parseFloat(document.getElementById('ahrp-reputation').value)||10,
      stake:parseFloat(document.getElementById('ahrp-stake').value)||100,
      capabilities:[{
        capability_id:document.getElementById('ahrp-cap-id').value.trim(),
        tags:document.getElementById('ahrp-cap-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean),
        description:document.getElementById('ahrp-cap-desc').value.trim(),
        price_floor:parseFloat(document.getElementById('ahrp-cap-price').value)||1.0,
        origin_type:document.getElementById('ahrp-cap-origin').value,
        access_levels:levels
      }]
    };
    var d=await postApi('/ahrp/v1/announce',payload);
    if(d&&!d.error){
      div.innerHTML='<div class="result-box"><div class="kv-row"><span class="kv-key">Status</span><span class="kv-val ok">Announced</span></div></div>';
      toast('Agent announced');
    } else { div.innerHTML='<p class="err">'+esc(d?d.error:'AHRP not reachable')+'</p>'; }
    btn.textContent='Announce'; btn.disabled=false;
  });

  document.getElementById('ahrp-find-btn').addEventListener('click', async function() {
    var btn=this; btn.textContent='...'; btn.disabled=true;
    var c=document.getElementById('ahrp-matches');
    var payload={
      description:document.getElementById('ahrp-search-desc').value.trim(),
      tags:document.getElementById('ahrp-search-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean),
      min_reputation:parseFloat(document.getElementById('ahrp-search-rep').value)||0,
      max_price:parseFloat(document.getElementById('ahrp-search-price').value)||1000,
      required_access_level:document.getElementById('ahrp-search-access').value
    };
    var d=await postApi('/ahrp/v1/request',payload);
    var matches=d?(d.matches||d.results||[]):[];
    if(!matches.length){c.innerHTML='<div class="empty">No matches</div>';}
    else {
      var html='';
      matches.forEach(function(m){
        var score=Math.round((m.score||0)*100);
        html+='<div class="match-card">'+
          '<div class="match-top"><span class="match-agent">'+esc(m.agent_id||'')+' / '+esc(m.capability_id||'')+'</span><span class="match-origin">'+esc(m.origin_type||'')+'</span></div>'+
          '<div class="match-bar"><div class="match-bar-fill" style="width:'+score+'%"></div></div>'+
          '<div class="match-bottom"><span>'+score+'%</span><span>'+esc(m.price_floor||0)+' OAS</span></div>'+
          '</div>';
      });
      c.innerHTML=html;
    }
    btn.textContent='Find'; btn.disabled=false;
  });

  /* ── TX Pipeline ─────────────────────────────────────── */
  var _txSteps=['request','offer','accept','deliver','confirm'];
  var _selectedRating=5;

  function updatePipeline(step) {
    for(var i=0;i<_txSteps.length;i++){
      var el=document.getElementById('tx-step-'+_txSteps[i]);
      el.className='tx-step';
      if(i<step)el.className='tx-step done';
      else if(i===step)el.className='tx-step active';
    }
    for(var j=1;j<=4;j++){
      var line=document.getElementById('tx-line-'+j);
      line.className=j<=step?'tx-line done':'tx-line';
    }
  }

  var stars=document.querySelectorAll('#star-rating span');
  stars.forEach(function(s){
    s.addEventListener('click',function(){
      _selectedRating=parseInt(this.getAttribute('data-v'));
      stars.forEach(function(x){x.className=parseInt(x.getAttribute('data-v'))<=_selectedRating?'lit':'';});
    });
  });
  stars.forEach(function(s){s.className=parseInt(s.getAttribute('data-v'))<=_selectedRating?'lit':'';});

  document.getElementById('tx-accept-btn').addEventListener('click', async function() {
    var btn=this; btn.textContent='...'; btn.disabled=true;
    var div=document.getElementById('tx-accept-result');
    updatePipeline(0);
    var payload={buyer_id:document.getElementById('tx-buyer').value.trim(),seller_id:document.getElementById('tx-seller').value.trim(),capability_id:document.getElementById('tx-cap-id').value.trim(),price_oas:parseFloat(document.getElementById('tx-price').value)||10};
    await new Promise(function(r){setTimeout(r,200);});
    updatePipeline(1);
    await new Promise(function(r){setTimeout(r,200);});
    var d=await postApi('/ahrp/v1/accept',payload);
    if(d&&!d.error){
      var txId=d.tx_id||d.transaction_id||'';
      document.getElementById('tx-deliver-id').value=txId;
      document.getElementById('tx-confirm-id').value=txId;
      updatePipeline(2);
      div.innerHTML='<div class="result-box"><div class="kv-row"><span class="kv-key">TX</span><span class="kv-val">'+esc(txId)+'</span></div></div>';
    } else { div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>'; updatePipeline(0); }
    btn.textContent='Accept & Create'; btn.disabled=false;
  });

  document.getElementById('tx-deliver-btn').addEventListener('click', async function() {
    var btn=this; btn.textContent='...'; btn.disabled=true;
    var div=document.getElementById('tx-deliver-result');
    var d=await postApi('/ahrp/v1/deliver',{tx_id:document.getElementById('tx-deliver-id').value.trim(),content_hash:document.getElementById('tx-content-hash').value.trim()});
    if(d&&!d.error){ updatePipeline(3); div.innerHTML='<div class="result-box"><div class="kv-row"><span class="kv-key">Status</span><span class="kv-val ok">Delivered</span></div></div>'; }
    else { div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>'; }
    btn.textContent='Deliver'; btn.disabled=false;
  });

  document.getElementById('tx-confirm-btn').addEventListener('click', async function() {
    var btn=this; btn.textContent='...'; btn.disabled=true;
    var div=document.getElementById('tx-confirm-result');
    var d=await postApi('/ahrp/v1/confirm',{tx_id:document.getElementById('tx-confirm-id').value.trim(),rating:_selectedRating});
    if(d&&!d.error){ updatePipeline(4); div.innerHTML='<div class="result-box"><div class="kv-row"><span class="kv-key">Status</span><span class="kv-val ok">Settled</span></div><div class="kv-row"><span class="kv-key">Rating</span><span class="kv-val">'+_selectedRating+'/5</span></div></div>'; toast('Transaction settled'); }
    else { div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>'; }
    btn.textContent='Confirm & Settle'; btn.disabled=false;
  });

  updatePipeline(0);

  /* ── Init ────────────────────────────────────────────── */
  loadStatus(); loadAssets(); loadStakes(); loadPortfolio();
  setInterval(loadStatus, 30000);

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

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

:root {
  --bg: #faf9f6;
  --bg-secondary: #f0efeb;
  --bg-tertiary: #e8e6e1;
  --text: #1a1a1a;
  --text-secondary: #6b6b6b;
  --text-tertiary: #999;
  --border: #e0ddd8;
  --border-hover: #c5c2bc;
  --accent: #1a1a1a;
  --success: #2d7d46;
  --error: #c53030;
  --surface: #fff;
  --surface-hover: #f5f4f1;
  --shadow: rgba(0,0,0,0.06);
  --overlay: rgba(255,255,255,0.85);
  --input-bg: #fff;
  --code-bg: #f5f4f1;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0c0c0c;
    --bg-secondary: #141414;
    --bg-tertiary: #1c1c1c;
    --text: #e8e6e1;
    --text-secondary: #888;
    --text-tertiary: #555;
    --border: #242424;
    --border-hover: #3a3a3a;
    --accent: #e8e6e1;
    --success: #4ade80;
    --error: #f87171;
    --surface: #161616;
    --surface-hover: #1c1c1c;
    --shadow: rgba(0,0,0,0.3);
    --overlay: rgba(12,12,12,0.85);
    --input-bg: #111;
    --code-bg: #1a1a1a;
  }
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, 'Söhne', 'Helvetica Neue', system-ui, sans-serif;
  font-size: 15px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  transition: background 0.3s ease, color 0.3s ease;
}

.wrap {
  max-width: 600px;
  margin: 0 auto;
  padding: 0 24px 120px;
}

/* ── Top Bar ──────────── */
.top-bar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--overlay);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.3s;
}
.brand {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: 0.08em;
}
.dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--success);
  margin-left: 10px;
  display: inline-block;
  vertical-align: middle;
}

/* ── Hero ──────────── */
.hero {
  text-align: center;
  padding: 64px 0 48px;
}
.hero-n {
  font-size: 64px;
  font-weight: 200;
  color: var(--text);
  line-height: 1;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}
.hero-l {
  font-size: 13px;
  color: var(--text-tertiary);
  margin-top: 8px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.hero-row {
  display: flex;
  justify-content: center;
  gap: 56px;
  margin-top: 40px;
}
.hero-item { text-align: center; }
.hero-item-n {
  font-size: 28px;
  font-weight: 300;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}
.hero-item-l {
  font-size: 11px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-top: 4px;
}

/* ── Sections ──────────── */
.sec {
  padding: 28px 0;
  border-top: 1px solid var(--border);
}
.sec-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
  padding: 4px 0;
}
.sec-t {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  letter-spacing: 0.06em;
}
.sec-arrow {
  font-size: 11px;
  color: var(--text-tertiary);
  transition: transform 0.25s ease;
  display: inline-block;
}
.sec-arrow.open { transform: rotate(90deg); }
.sec-body {
  max-height: 0;
  opacity: 0;
  overflow: hidden;
  transition: max-height 0.4s ease, opacity 0.3s ease;
}
.sec-body.open {
  max-height: 5000px;
  opacity: 1;
}
.sec-inner { padding-top: 20px; }

/* ── Inputs ──────────── */
input[type="text"], input[type="number"], select, textarea {
  width: 100%;
  height: 42px;
  font-size: 14px;
  font-family: inherit;
  background: var(--input-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 0 14px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
input:focus, select:focus, textarea:focus {
  border-color: var(--border-hover);
  box-shadow: 0 0 0 3px var(--shadow);
}
input::placeholder, textarea::placeholder { color: var(--text-tertiary); }
textarea {
  height: auto; min-height: 80px;
  padding: 12px 14px; resize: vertical;
}
.row { display: flex; gap: 8px; margin-bottom: 10px; }
.row > * { flex: 1; min-width: 0; }

/* ── Buttons ──────────── */
.btn {
  height: 42px;
  font-size: 14px;
  font-weight: 500;
  font-family: inherit;
  background: var(--accent);
  color: var(--bg);
  border: none;
  border-radius: 8px;
  padding: 0 20px;
  cursor: pointer;
  transition: opacity 0.15s;
  width: 100%;
}
.btn:hover { opacity: 0.85; }
.btn-ghost {
  background: transparent;
  color: var(--text);
  border: 1px solid var(--border);
}
.btn-ghost:hover { border-color: var(--border-hover); background: var(--surface-hover); opacity: 1; }
.btn-danger {
  background: transparent;
  color: var(--error);
  border: 1px solid var(--border);
}
.btn-danger:hover { border-color: var(--error); opacity: 1; }

/* ── Asset List ──────────── */
.a-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: opacity 0.15s;
}
.a-item:hover { opacity: 0.65; }
.a-item:last-child { border-bottom: none; }
.a-left { flex: 1; min-width: 0; }
.a-id {
  font-size: 13px;
  font-family: ui-monospace, 'SF Mono', monospace;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.a-meta {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 2px;
}
.a-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  margin-left: 16px;
}
.a-price {
  font-size: 13px;
  font-family: ui-monospace, 'SF Mono', monospace;
  color: var(--text-secondary);
}
.a-del {
  width: 28px; height: 28px;
  border: none; background: transparent;
  color: var(--text-tertiary);
  font-size: 14px; cursor: pointer;
  border-radius: 6px;
  opacity: 0;
  transition: all 0.15s;
  display: flex; align-items: center; justify-content: center;
}
.a-item:hover .a-del { opacity: 1; }
.a-del:hover { color: var(--error); background: var(--bg-secondary); }

/* ── Tags ──────────── */
.tag {
  display: inline-block;
  height: 18px; line-height: 18px;
  padding: 0 6px;
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-secondary);
  border-radius: 4px;
  margin-right: 4px;
}

/* ── KV ──────────── */
.kv {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  padding: 8px 0;
  font-size: 14px;
  border-bottom: 1px solid var(--border);
}
.kv:last-child { border-bottom: none; }
.kv-k { color: var(--text-secondary); }
.kv-v {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 13px;
  color: var(--text);
  text-align: right;
  word-break: break-all;
  max-width: 60%;
}

/* ── Result ──────────── */
.res {
  background: var(--bg-secondary);
  border-radius: 10px;
  padding: 16px;
  margin-top: 14px;
}

/* ── Modal ──────────── */
.modal-bg {
  position: fixed; inset: 0;
  background: var(--overlay);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  z-index: 200;
  display: flex; align-items: center; justify-content: center;
  animation: fadeIn 0.2s ease;
}
.modal {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  max-width: 460px; width: 90%;
  max-height: 80vh; overflow-y: auto;
  padding: 28px;
  position: relative;
  box-shadow: 0 24px 48px var(--shadow);
}
.modal-x {
  position: absolute; top: 14px; right: 14px;
  background: none; border: none;
  color: var(--text-tertiary);
  font-size: 18px; cursor: pointer;
}
.modal-x:hover { color: var(--text); }
.modal h3 {
  font-size: 16px; font-weight: 600;
  color: var(--text); margin-bottom: 18px;
}

/* ── Toast ──────────── */
.toast-c {
  position: fixed; top: 64px; right: 20px;
  z-index: 300;
  display: flex; flex-direction: column; gap: 8px;
}
.tst {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 13px;
  color: var(--text);
  box-shadow: 0 4px 12px var(--shadow);
  animation: toastIn 0.2s ease, toastOut 0.2s ease 2.8s forwards;
  max-width: 280px;
}
.tst.error { color: var(--error); }

/* ── Empty ──────────── */
.empty {
  text-align: center;
  color: var(--text-tertiary);
  padding: 40px 16px;
  font-size: 14px;
}
.empty code {
  background: var(--code-bg);
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 12px;
  font-family: ui-monospace, 'SF Mono', monospace;
  color: var(--text-secondary);
}

/* ── Status ──────────── */
.ok { color: var(--success); }
.err { color: var(--error); margin-top: 10px; font-size: 14px; }

/* ── Portfolio ──────────── */
.p-row {
  display: flex; align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
.p-row:last-child { border-bottom: none; }
.p-id { font-family: ui-monospace, 'SF Mono', monospace; color: var(--text); }
.p-v { color: var(--text-secondary); }

/* ── AHRP Matches ──────────── */
.m-card {
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
}
.m-card:last-child { border-bottom: none; }
.m-top { display: flex; justify-content: space-between; font-size: 13px; }
.m-agent { font-family: ui-monospace, 'SF Mono', monospace; color: var(--text); }
.m-origin { font-size: 11px; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; }
.m-bar { width: 100%; height: 3px; background: var(--bg-tertiary); border-radius: 2px; margin: 6px 0; }
.m-bar-fill { height: 100%; border-radius: 2px; background: var(--text-tertiary); }
.m-bot { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-tertiary); }

/* ── Pipeline ──────────── */
.pipe {
  display: flex; align-items: center; justify-content: center;
  gap: 0; margin: 20px 0;
}
.pipe-s { display: flex; flex-direction: column; align-items: center; gap: 5px; padding: 6px 10px; }
.pipe-d {
  width: 8px; height: 8px;
  border-radius: 50%;
  border: 1.5px solid var(--border);
  background: transparent;
  transition: all 0.3s;
}
.pipe-s.done .pipe-d { background: var(--text); border-color: var(--text); }
.pipe-s.active .pipe-d { border-color: var(--text-secondary); }
.pipe-line { width: 28px; height: 1px; background: var(--border); margin-bottom: 16px; }
.pipe-line.done { background: var(--text-tertiary); }
.pipe-l { font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-tertiary); }
.pipe-s.done .pipe-l { color: var(--text-secondary); }
.pipe-s.active .pipe-l { color: var(--text); }

/* ── Stars ──────────── */
.stars { display: flex; gap: 3px; margin-bottom: 12px; }
.stars span { font-size: 18px; cursor: pointer; color: var(--border); user-select: none; }
.stars span.lit { color: var(--text); }

/* ── Checkboxes ──────────── */
.chk-g { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
.chk-g label { display: flex; align-items: center; gap: 5px; font-size: 13px; color: var(--text-secondary); cursor: pointer; }

/* ── Net Grid ──────────── */
.ng { display: grid; grid-template-columns: 1fr 1fr; gap: 3px 20px; font-size: 13px; }
.ng-k { color: var(--text-tertiary); }
.ng-v { font-family: ui-monospace, 'SF Mono', monospace; font-size: 12px; color: var(--text-secondary); text-align: right; }

.stk-item { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
.stk-item:last-child { border-bottom: none; }
.stk-id { font-family: ui-monospace, 'SF Mono', monospace; color: var(--text-secondary); }
.stk-a { font-family: ui-monospace, 'SF Mono', monospace; color: var(--text); }

/* ── Sub-labels ──────────── */
.sub-l {
  font-size: 11px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 12px;
}
.divider { border-top: 1px solid var(--border); margin-top: 20px; padding-top: 20px; }

/* ── Animations ──────────── */
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes toastIn { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: translateY(0); } }
@keyframes toastOut { from { opacity: 1; } to { opacity: 0; } }

/* ── Responsive ──────────── */
@media (max-width: 600px) {
  .wrap { padding: 0 16px 80px; }
  .hero-n { font-size: 48px; }
  .hero-row { gap: 28px; }
  .row { flex-direction: column; }
  .ng { grid-template-columns: 1fr; }
  .ng-v { text-align: left; }
  .kv { flex-direction: column; gap: 2px; }
  .kv-v { text-align: left; max-width: 100%; }
}
</style>
</head>
<body>

<div class="top-bar">
  <span class="brand">Oasyce</span>
  <span class="dot" id="status-dot"></span>
</div>

<div class="wrap">

  <div class="hero">
    <div class="hero-n" id="stat-assets">&mdash;</div>
    <div class="hero-l">Assets Registered</div>
    <div class="hero-row">
      <div class="hero-item">
        <div class="hero-item-n" id="stat-blocks">&mdash;</div>
        <div class="hero-item-l">Blocks</div>
      </div>
      <div class="hero-item">
        <div class="hero-item-n" id="stat-dists">&mdash;</div>
        <div class="hero-item-l">Watermarks</div>
      </div>
    </div>
  </div>

  <!-- Assets -->
  <div class="sec"><div class="sec-head" onclick="T('assets')"><span class="sec-t">Assets</span><span class="sec-arrow open" id="arr-assets">&#x25B8;</span></div>
    <div class="sec-body open" id="bd-assets"><div class="sec-inner">
      <input type="text" id="asset-search" placeholder="Search assets...">
      <div id="assets-list" style="margin-top:12px;"></div>
    </div></div>
  </div>

  <!-- Register -->
  <div class="sec"><div class="sec-head" onclick="T('register')"><span class="sec-t">Register</span><span class="sec-arrow" id="arr-register">&#x25B8;</span></div>
    <div class="sec-body" id="bd-register"><div class="sec-inner">
      <div class="row"><input type="text" id="reg-path" placeholder="File path"></div>
      <div class="row"><input type="text" id="reg-owner" placeholder="Owner"><input type="text" id="reg-tags" placeholder="Tags (comma-separated)"></div>
      <button class="btn" id="reg-btn">Register</button>
      <div id="reg-result"></div>
    </div></div>
  </div>

  <!-- Trade -->
  <div class="sec"><div class="sec-head" onclick="T('trade')"><span class="sec-t">Trade</span><span class="sec-arrow" id="arr-trade">&#x25B8;</span></div>
    <div class="sec-body" id="bd-trade"><div class="sec-inner">
      <div class="row"><input type="text" id="buy-asset" placeholder="Asset ID"><input type="text" id="buy-amount" placeholder="Amount" value="10" style="max-width:110px;"></div>
      <div class="row"><button class="btn btn-ghost" id="quote-btn">Quote</button><button class="btn" id="buy-btn">Buy</button></div>
      <div id="buy-result"></div>
    </div></div>
  </div>

  <!-- Portfolio -->
  <div class="sec"><div class="sec-head" onclick="T('portfolio')"><span class="sec-t">Portfolio</span><span class="sec-arrow" id="arr-portfolio">&#x25B8;</span></div>
    <div class="sec-body" id="bd-portfolio"><div class="sec-inner" id="portfolio-list"></div></div>
  </div>

  <!-- Watermark -->
  <div class="sec"><div class="sec-head" onclick="T('watermark')"><span class="sec-t">Watermark</span><span class="sec-arrow" id="arr-watermark">&#x25B8;</span></div>
    <div class="sec-body" id="bd-watermark"><div class="sec-inner">
      <div class="row"><input type="text" id="emb-asset" placeholder="Asset ID"><input type="text" id="emb-caller" placeholder="Buyer ID"></div>
      <textarea id="emb-content" placeholder="Content to watermark..."></textarea>
      <button class="btn" id="emb-btn" style="margin-top:8px;">Embed</button>
      <div id="emb-result"></div>
      <div class="divider">
        <div class="row"><input type="text" id="fp-input" placeholder="Trace fingerprint..."><button class="btn btn-ghost" id="fp-trace-btn" style="max-width:90px;">Trace</button></div>
        <div id="fp-trace-result"></div>
      </div>
      <div class="divider">
        <div class="row"><input type="text" id="fp-asset-input" placeholder="Lookup by asset ID..."><button class="btn btn-ghost" id="fp-list-btn" style="max-width:90px;">Lookup</button></div>
        <div id="fp-dist-list"></div>
      </div>
    </div></div>
  </div>

  <!-- Stake -->
  <div class="sec"><div class="sec-head" onclick="T('stake')"><span class="sec-t">Stake</span><span class="sec-arrow" id="arr-stake">&#x25B8;</span></div>
    <div class="sec-body" id="bd-stake"><div class="sec-inner">
      <div class="row"><input type="text" id="stake-node" placeholder="Node ID"><input type="text" id="stake-amount" placeholder="Amount" value="10000" style="max-width:130px;"></div>
      <button class="btn" id="stake-btn">Stake</button>
      <div id="stake-result"></div>
    </div></div>
  </div>

  <!-- AHRP -->
  <div class="sec"><div class="sec-head" onclick="T('ahrp')"><span class="sec-t">Agent Protocol</span><span class="sec-arrow" id="arr-ahrp">&#x25B8;</span></div>
    <div class="sec-body" id="bd-ahrp"><div class="sec-inner">
      <div class="sub-l">Register Agent</div>
      <div class="row"><input type="text" id="ahrp-agent-id" placeholder="Agent ID"><input type="text" id="ahrp-pub-key" placeholder="Public key"></div>
      <div class="row"><input type="number" id="ahrp-reputation" placeholder="Reputation" value="10"><input type="number" id="ahrp-stake" placeholder="Stake" value="100"></div>
      <div class="row"><input type="text" id="ahrp-cap-id" placeholder="Capability ID"><input type="text" id="ahrp-cap-tags" placeholder="Tags"></div>
      <div class="row"><input type="text" id="ahrp-cap-desc" placeholder="Description" style="flex:2;"><input type="number" id="ahrp-cap-price" placeholder="Price floor" value="1.0"></div>
      <div class="row"><select id="ahrp-cap-origin"><option value="human">human</option><option value="sensor">sensor</option><option value="curated">curated</option><option value="synthetic">synthetic</option></select></div>
      <div class="chk-g"><label><input type="checkbox" value="L0" checked> L0</label><label><input type="checkbox" value="L1" checked> L1</label><label><input type="checkbox" value="L2"> L2</label><label><input type="checkbox" value="L3"> L3</label></div>
      <button class="btn" id="ahrp-announce-btn">Announce</button>
      <div id="ahrp-announce-result"></div>

      <div class="divider">
        <div class="sub-l">Discover</div>
        <div class="row"><input type="text" id="ahrp-search-desc" placeholder="What data do you need?" style="flex:2;"><input type="text" id="ahrp-search-tags" placeholder="Tags"></div>
        <div class="row"><input type="number" id="ahrp-search-rep" placeholder="Min reputation" value="5"><input type="number" id="ahrp-search-price" placeholder="Max price" value="100"><select id="ahrp-search-access"><option>L0</option><option>L1</option><option>L2</option><option>L3</option></select></div>
        <button class="btn btn-ghost" id="ahrp-find-btn">Find</button>
        <div id="ahrp-matches" style="margin-top:14px;"></div>
      </div>

      <div class="divider">
        <div class="sub-l">Transaction</div>
        <div class="pipe" id="tx-pipeline">
          <div class="pipe-s" id="tx-s-request"><div class="pipe-d"></div><div class="pipe-l">Request</div></div><div class="pipe-line" id="tx-l-1"></div>
          <div class="pipe-s" id="tx-s-offer"><div class="pipe-d"></div><div class="pipe-l">Offer</div></div><div class="pipe-line" id="tx-l-2"></div>
          <div class="pipe-s" id="tx-s-accept"><div class="pipe-d"></div><div class="pipe-l">Accept</div></div><div class="pipe-line" id="tx-l-3"></div>
          <div class="pipe-s" id="tx-s-deliver"><div class="pipe-d"></div><div class="pipe-l">Deliver</div></div><div class="pipe-line" id="tx-l-4"></div>
          <div class="pipe-s" id="tx-s-confirm"><div class="pipe-d"></div><div class="pipe-l">Confirm</div></div>
        </div>
        <div class="row"><input type="text" id="tx-buyer" placeholder="Buyer ID"><input type="text" id="tx-seller" placeholder="Seller ID"></div>
        <div class="row"><input type="text" id="tx-cap-id" placeholder="Capability ID"><input type="number" id="tx-price" placeholder="Price" value="10"></div>
        <button class="btn" id="tx-accept-btn">Accept &amp; Create</button>
        <div id="tx-accept-result"></div>
        <div class="divider">
          <div class="row"><input type="text" id="tx-deliver-id" placeholder="Transaction ID"><input type="text" id="tx-content-hash" placeholder="Content hash"></div>
          <button class="btn btn-ghost" id="tx-deliver-btn">Deliver</button>
          <div id="tx-deliver-result"></div>
        </div>
        <div class="divider">
          <div class="row"><input type="text" id="tx-confirm-id" placeholder="Transaction ID"></div>
          <div class="stars" id="star-rating"><span data-v="1">&#x2605;</span><span data-v="2">&#x2605;</span><span data-v="3">&#x2605;</span><span data-v="4">&#x2605;</span><span data-v="5">&#x2605;</span></div>
          <button class="btn" id="tx-confirm-btn">Confirm &amp; Settle</button>
          <div id="tx-confirm-result"></div>
        </div>
      </div>
    </div></div>
  </div>

  <!-- Network -->
  <div class="sec"><div class="sec-head" onclick="T('network')"><span class="sec-t">Network</span><span class="sec-arrow" id="arr-network">&#x25B8;</span></div>
    <div class="sec-body" id="bd-network"><div class="sec-inner">
      <div class="ng" id="net-info"></div>
      <div id="stakes-section" style="display:none;margin-top:16px;padding-top:16px;border-top:1px solid var(--border);"><div id="stakes-list"></div></div>
    </div></div>
  </div>

  <div style="text-align:center;font-size:11px;color:var(--text-tertiary);padding:56px 0 0;letter-spacing:0.08em;">Oasyce Protocol</div>
</div>

<script>
(function(){
  function esc(s){if(s==null)return'';var d=document.createElement('div');d.textContent=String(s);return d.innerHTML;}
  function trunc(s,n){n=n||16;return s&&s.length>n?s.slice(0,n)+'\u2026':(s||'');}
  function timeAgo(ts){if(!ts)return'';var then=typeof ts==='number'?(ts>1e12?new Date(ts):new Date(ts*1000)):new Date(ts);var d=Math.floor((Date.now()-then.getTime())/1000);if(d<0)d=0;if(d<60)return d+'s';if(d<3600)return Math.floor(d/60)+'m';if(d<86400)return Math.floor(d/3600)+'h';return Math.floor(d/86400)+'d';}
  async function api(p){try{return(await fetch(p)).json();}catch(e){return null;}}
  async function postApi(p,b){try{return(await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})).json();}catch(e){return{error:e.message};}}

  function toast(msg,type){
    var c=document.getElementById('toast-c');
    if(!c){c=document.createElement('div');c.id='toast-c';c.className='toast-c';document.body.appendChild(c);}
    var el=document.createElement('div');el.className='tst'+(type==='error'?' error':'');el.textContent=msg;c.appendChild(el);setTimeout(function(){el.remove();},3000);
  }

  window.T=function(name){
    var bd=document.getElementById('bd-'+name);
    var ar=document.getElementById('arr-'+name);
    bd.classList.toggle('open');ar.classList.toggle('open');
  };

  function showModal(asset){
    var ex=document.getElementById('modal-bg');if(ex)ex.remove();
    var o=document.createElement('div');o.id='modal-bg';o.className='modal-bg';
    var tags=(asset.tags||[]).map(function(t){return'<span class="tag">'+esc(t)+'</span>';}).join(' ');
    o.innerHTML='<div class="modal" onclick="event.stopPropagation()">'+
      '<button class="modal-x" onclick="document.getElementById(\'modal-bg\').remove()">&times;</button>'+
      '<h3>Asset</h3>'+
      '<div class="kv"><span class="kv-k">ID</span><span class="kv-v" style="cursor:pointer;font-size:11px;" onclick="navigator.clipboard.writeText(\''+esc(asset.asset_id)+'\');toast(\'Copied\')">'+esc(asset.asset_id)+' &#x1f4cb;</span></div>'+
      '<div class="kv"><span class="kv-k">Owner</span><span class="kv-v">'+esc(asset.owner)+'</span></div>'+
      '<div class="kv"><span class="kv-k">Created</span><span class="kv-v">'+timeAgo(asset.created_at)+'</span></div>'+
      '<div class="kv"><span class="kv-k">Price</span><span class="kv-v">'+(asset.spot_price!=null?asset.spot_price+' OAS':'&mdash;')+'</span></div>'+
      '<div class="kv"><span class="kv-k">Tags</span><span class="kv-v">'+(tags||'&mdash;')+'</span></div>'+
      '<div style="margin-top:16px;display:flex;gap:8px;">'+
        '<input type="text" id="m-tags" value="'+(asset.tags||[]).join(', ')+'" placeholder="Edit tags..." style="flex:1;">'+
        '<button class="btn btn-ghost" style="width:auto;padding:0 16px;" onclick="editTags(\''+esc(asset.asset_id)+'\')">Save</button>'+
      '</div>'+
      '<button class="btn btn-danger" style="margin-top:10px;" onclick="if(confirm(\'Delete this asset?\')){deleteAsset(\''+esc(asset.asset_id)+'\');document.getElementById(\'modal-bg\').remove();}">Delete</button>'+
    '</div>';
    o.addEventListener('click',function(e){if(e.target===o)o.remove();});
    document.body.appendChild(o);
  }
  window.toast=toast;
  window.editTags=async function(aid){var input=document.getElementById('m-tags');var tags=input.value.split(',').map(function(t){return t.trim();}).filter(Boolean);var r=await postApi('/api/asset/update',{asset_id:aid,tags:tags});if(r&&r.ok){toast('Tags updated');loadAssets();}else{toast(r?r.error:'Failed','error');}};
  window.deleteAsset=async function(aid){if(!confirm('Delete this asset permanently?'))return;try{var r=await fetch('/api/asset/'+aid,{method:'DELETE'});var d=await r.json();if(d.ok){toast('Deleted');loadAssets();loadStatus();}else{toast(d.error||'Failed','error');}}catch(e){toast(e.message,'error');}};

  async function loadStatus(){
    var d=await api('/api/status');if(!d)return;
    document.getElementById('stat-assets').textContent=d.total_assets;
    document.getElementById('stat-blocks').textContent=d.total_blocks;
    document.getElementById('stat-dists').textContent=d.total_distributions;
    var ni=document.getElementById('net-info');
    ni.innerHTML='<span class="ng-k">Node</span><span class="ng-v">'+esc(d.node_id)+'</span><span class="ng-k">Address</span><span class="ng-v">'+esc(d.host)+':'+esc(d.port)+'</span><span class="ng-k">Height</span><span class="ng-v">'+esc(d.chain_height)+'</span>';
  }

  var _all=[];
  async function loadAssets(){_all=await api('/api/assets')||[];renderA(_all);}
  function renderA(list){
    var c=document.getElementById('assets-list');
    if(!list.length){c.innerHTML='<div class="empty">No assets yet. Register with <code>oasyce register</code></div>';return;}
    var h='';list.forEach(function(a){
      var tags=(a.tags||[]).map(function(t){return'<span class="tag">'+esc(t)+'</span>';}).join('');
      h+='<div class="a-item" onclick=\'showD('+JSON.stringify(a).replace(/\x27/g,"&#39;")+')\'>'+
        '<div class="a-left"><div class="a-id">'+esc(trunc(a.asset_id,30))+'</div><div class="a-meta">'+esc(a.owner)+' &middot; '+timeAgo(a.created_at)+(tags?' &middot; '+tags:'')+'</div></div>'+
        '<div class="a-right">'+(a.spot_price!=null?'<span class="a-price">'+a.spot_price+'</span>':'')+
        '<button class="a-del" title="Delete" onclick="event.stopPropagation();deleteAsset(\''+esc(a.asset_id)+'\')">&times;</button></div></div>';
    });c.innerHTML=h;
  }
  window.showD=function(a){showModal(a);};
  document.getElementById('asset-search').addEventListener('input',function(e){var q=e.target.value.toLowerCase();if(!q){renderA(_all);return;}renderA(_all.filter(function(a){return(a.asset_id||'').toLowerCase().indexOf(q)!==-1||(a.tags||[]).some(function(t){return t.toLowerCase().indexOf(q)!==-1;});}));});

  document.getElementById('reg-btn').addEventListener('click',async function(){var btn=this;btn.textContent='...';btn.disabled=true;var fp=document.getElementById('reg-path').value.trim();var owner=document.getElementById('reg-owner').value.trim();var tags=document.getElementById('reg-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean);var div=document.getElementById('reg-result');try{var r=await postApi('/api/register',{file_path:fp,owner:owner||undefined,tags:tags});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Asset ID</span><span class="kv-v">'+esc(r.asset_id)+'</span></div></div>';toast('Registered');loadAssets();loadStatus();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Register';btn.disabled=false;});

  document.getElementById('quote-btn').addEventListener('click',async function(){var aid=document.getElementById('buy-asset').value.trim();var amt=document.getElementById('buy-amount').value.trim()||'10';var div=document.getElementById('buy-result');if(!aid){div.innerHTML='<p class="err">Enter asset ID</p>';return;}var r=await api('/api/quote?asset_id='+encodeURIComponent(aid)+'&amount='+amt);if(!r||r.error){div.innerHTML='<p class="err">'+esc(r?r.error:'Failed')+'</p>';return;}div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Pay</span><span class="kv-v">'+r.payment+' OAS</span></div><div class="kv"><span class="kv-k">Get</span><span class="kv-v">'+r.tokens+' tokens</span></div><div class="kv"><span class="kv-k">Impact</span><span class="kv-v">'+r.impact_pct+'%</span></div><div class="kv"><span class="kv-k">Burned</span><span class="kv-v">'+r.burn+' OAS</span></div></div>';});

  document.getElementById('buy-btn').addEventListener('click',async function(){if(!confirm('Confirm purchase?'))return;var btn=this;btn.textContent='...';btn.disabled=true;var aid=document.getElementById('buy-asset').value.trim();var amt=document.getElementById('buy-amount').value.trim()||'10';var div=document.getElementById('buy-result');if(!aid){div.innerHTML='<p class="err">Enter asset ID</p>';btn.textContent='Buy';btn.disabled=false;return;}try{var r=await postApi('/api/buy',{asset_id:aid,buyer:'gui_user',amount:parseFloat(amt)});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Tokens</span><span class="kv-v ok">'+r.tokens+'</span></div><div class="kv"><span class="kv-k">New price</span><span class="kv-v">'+r.price_after+' OAS</span></div></div>';toast('Purchased');loadPortfolio();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Buy';btn.disabled=false;});

  async function loadPortfolio(){var list=await api('/api/portfolio?buyer=gui_user')||[];var c=document.getElementById('portfolio-list');if(!list.length){c.innerHTML='<div class="empty">No holdings</div>';return;}var h='';list.forEach(function(x){h+='<div class="p-row"><span class="p-id">'+esc(trunc(x.asset_id,22))+'</span><span class="p-v">'+x.shares+' shares &middot; '+x.value_oas+' OAS</span></div>';});c.innerHTML=h;}

  document.getElementById('emb-btn').addEventListener('click',async function(){var btn=this;btn.textContent='...';btn.disabled=true;var aid=document.getElementById('emb-asset').value.trim();var caller=document.getElementById('emb-caller').value.trim();var content=document.getElementById('emb-content').value;var div=document.getElementById('emb-result');if(!aid||!caller||!content){div.innerHTML='<p class="err">Fill all fields</p>';btn.textContent='Embed';btn.disabled=false;return;}try{var r=await postApi('/api/fingerprint/embed',{asset_id:aid,caller_id:caller,content:content});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Fingerprint</span><span class="kv-v">'+esc(trunc(r.fingerprint,24))+'</span></div></div><textarea readonly style="width:100%;min-height:60px;margin-top:8px;color:var(--success);">'+esc(r.watermarked_content)+'</textarea>';toast('Embedded');loadStatus();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Embed';btn.disabled=false;});

  document.getElementById('fp-trace-btn').addEventListener('click',async function(){var fp=document.getElementById('fp-input').value.trim();if(!fp)return;var r=await api('/api/trace?fp='+encodeURIComponent(fp));var div=document.getElementById('fp-trace-result');if(!r||r.error){div.innerHTML='<p class="err">Not found</p>';}else{div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Asset</span><span class="kv-v">'+esc(r.asset_id)+'</span></div><div class="kv"><span class="kv-k">Buyer</span><span class="kv-v">'+esc(r.caller_id)+'</span></div><div class="kv"><span class="kv-k">When</span><span class="kv-v">'+timeAgo(r.timestamp||r.created_at)+'</span></div></div>';}});

  document.getElementById('fp-list-btn').addEventListener('click',async function(){var aid=document.getElementById('fp-asset-input').value.trim();if(!aid)return;var list=await api('/api/fingerprints?asset_id='+encodeURIComponent(aid));var c=document.getElementById('fp-dist-list');if(!list||!list.length){c.innerHTML='<p class="err">None found</p>';return;}var h='';list.forEach(function(r){h+='<div class="p-row"><span class="p-id" style="font-size:11px;">'+esc(trunc(r.fingerprint,18))+'</span><span class="p-v">'+esc(r.caller_id)+' &middot; '+timeAgo(r.timestamp)+'</span></div>';});c.innerHTML=h;});

  document.getElementById('stake-btn').addEventListener('click',async function(){var btn=this;btn.textContent='...';btn.disabled=true;var nid=document.getElementById('stake-node').value.trim();var amt=document.getElementById('stake-amount').value.trim()||'10000';var div=document.getElementById('stake-result');if(!nid){div.innerHTML='<p class="err">Enter node ID</p>';btn.textContent='Stake';btn.disabled=false;return;}try{var r=await postApi('/api/stake',{node_id:nid,amount:parseFloat(amt)});if(r.ok){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Staked</span><span class="kv-v">'+r.total_stake+' OAS</span></div></div>';toast('Staked');loadStakes();}else{div.innerHTML='<p class="err">'+esc(r.error)+'</p>';}}catch(e){div.innerHTML='<p class="err">'+esc(e.message)+'</p>';}btn.textContent='Stake';btn.disabled=false;});

  async function loadStakes(){var list=await api('/api/stakes')||[];var sec=document.getElementById('stakes-section');if(!list.length){sec.style.display='none';return;}sec.style.display='block';var h='';list.forEach(function(s){h+='<div class="stk-item"><span class="stk-id">'+esc(trunc(s.validator_id,20))+'</span><span class="stk-a">'+s.total+' OAS</span></div>';});document.getElementById('stakes-list').innerHTML=h;}

  document.getElementById('ahrp-announce-btn').addEventListener('click',async function(){var btn=this;btn.textContent='...';btn.disabled=true;var div=document.getElementById('ahrp-announce-result');var levels=[];document.querySelectorAll('.chk-g input:checked').forEach(function(cb){levels.push(cb.value);});var payload={agent_id:document.getElementById('ahrp-agent-id').value.trim(),public_key:document.getElementById('ahrp-pub-key').value.trim(),reputation:parseFloat(document.getElementById('ahrp-reputation').value)||10,stake:parseFloat(document.getElementById('ahrp-stake').value)||100,capabilities:[{capability_id:document.getElementById('ahrp-cap-id').value.trim(),tags:document.getElementById('ahrp-cap-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean),description:document.getElementById('ahrp-cap-desc').value.trim(),price_floor:parseFloat(document.getElementById('ahrp-cap-price').value)||1.0,origin_type:document.getElementById('ahrp-cap-origin').value,access_levels:levels}]};var d=await postApi('/ahrp/v1/announce',payload);if(d&&!d.error){div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Status</span><span class="kv-v ok">Announced</span></div></div>';toast('Announced');}else{div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>';}btn.textContent='Announce';btn.disabled=false;});

  document.getElementById('ahrp-find-btn').addEventListener('click',async function(){var btn=this;btn.textContent='...';btn.disabled=true;var c=document.getElementById('ahrp-matches');var payload={description:document.getElementById('ahrp-search-desc').value.trim(),tags:document.getElementById('ahrp-search-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean),min_reputation:parseFloat(document.getElementById('ahrp-search-rep').value)||0,max_price:parseFloat(document.getElementById('ahrp-search-price').value)||1000,required_access_level:document.getElementById('ahrp-search-access').value};var d=await postApi('/ahrp/v1/request',payload);var matches=d?(d.matches||d.results||[]):[];if(!matches.length){c.innerHTML='<div class="empty">No matches</div>';}else{var h='';matches.forEach(function(m){var score=Math.round((m.score||0)*100);h+='<div class="m-card"><div class="m-top"><span class="m-agent">'+esc(m.agent_id||'')+' / '+esc(m.capability_id||'')+'</span><span class="m-origin">'+esc(m.origin_type||'')+'</span></div><div class="m-bar"><div class="m-bar-fill" style="width:'+score+'%"></div></div><div class="m-bot"><span>'+score+'%</span><span>'+esc(m.price_floor||0)+' OAS</span></div></div>';});c.innerHTML=h;}btn.textContent='Find';btn.disabled=false;});

  var _steps=['request','offer','accept','deliver','confirm'],_rating=5;
  function updatePipe(step){for(var i=0;i<_steps.length;i++){var el=document.getElementById('tx-s-'+_steps[i]);el.className='pipe-s';if(i<step)el.className='pipe-s done';else if(i===step)el.className='pipe-s active';}for(var j=1;j<=4;j++){document.getElementById('tx-l-'+j).className=j<=step?'pipe-line done':'pipe-line';}}
  var stars=document.querySelectorAll('#star-rating span');stars.forEach(function(s){s.addEventListener('click',function(){_rating=parseInt(this.getAttribute('data-v'));stars.forEach(function(x){x.className=parseInt(x.getAttribute('data-v'))<=_rating?'lit':'';});});});stars.forEach(function(s){s.className=parseInt(s.getAttribute('data-v'))<=_rating?'lit':'';});

  document.getElementById('tx-accept-btn').addEventListener('click',async function(){var btn=this;btn.textContent='...';btn.disabled=true;var div=document.getElementById('tx-accept-result');updatePipe(0);var payload={buyer_id:document.getElementById('tx-buyer').value.trim(),seller_id:document.getElementById('tx-seller').value.trim(),capability_id:document.getElementById('tx-cap-id').value.trim(),price_oas:parseFloat(document.getElementById('tx-price').value)||10};await new Promise(function(r){setTimeout(r,200);});updatePipe(1);await new Promise(function(r){setTimeout(r,200);});var d=await postApi('/ahrp/v1/accept',payload);if(d&&!d.error){var txId=d.tx_id||d.transaction_id||'';document.getElementById('tx-deliver-id').value=txId;document.getElementById('tx-confirm-id').value=txId;updatePipe(2);div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">TX</span><span class="kv-v">'+esc(txId)+'</span></div></div>';}else{div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>';updatePipe(0);}btn.textContent='Accept & Create';btn.disabled=false;});

  document.getElementById('tx-deliver-btn').addEventListener('click',async function(){var btn=this;btn.textContent='...';btn.disabled=true;var div=document.getElementById('tx-deliver-result');var d=await postApi('/ahrp/v1/deliver',{tx_id:document.getElementById('tx-deliver-id').value.trim(),content_hash:document.getElementById('tx-content-hash').value.trim()});if(d&&!d.error){updatePipe(3);div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Status</span><span class="kv-v ok">Delivered</span></div></div>';}else{div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>';}btn.textContent='Deliver';btn.disabled=false;});

  document.getElementById('tx-confirm-btn').addEventListener('click',async function(){var btn=this;btn.textContent='...';btn.disabled=true;var div=document.getElementById('tx-confirm-result');var d=await postApi('/ahrp/v1/confirm',{tx_id:document.getElementById('tx-confirm-id').value.trim(),rating:_rating});if(d&&!d.error){updatePipe(4);div.innerHTML='<div class="res"><div class="kv"><span class="kv-k">Status</span><span class="kv-v ok">Settled</span></div><div class="kv"><span class="kv-k">Rating</span><span class="kv-v">'+_rating+'/5</span></div></div>';toast('Settled');}else{div.innerHTML='<p class="err">'+esc(d?d.error:'Failed')+'</p>';}btn.textContent='Confirm & Settle';btn.disabled=false;});

  updatePipe(0);loadStatus();loadAssets();loadStakes();loadPortfolio();setInterval(loadStatus,30000);
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

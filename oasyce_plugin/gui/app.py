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
<title>Oasyce Dashboard</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: #0a0a0a;
  color: #e8e8e8;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 16px;
  line-height: 1.6;
}

/* ── Top Nav ─────────────────────────────────────────────── */
.top-nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(10,10,10,0.92);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid #252525;
  padding: 0 20px;
  display: flex;
  align-items: center;
  height: 52px;
  gap: 24px;
}
.nav-brand {
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 1px;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.nav-links { display: flex; gap: 4px; }
.nav-links a {
  color: #888;
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  padding: 6px 14px;
  border-radius: 8px;
  transition: color 0.2s, background 0.2s;
}
.nav-links a:hover { color: #e8e8e8; background: #1a1a1a; }
.nav-links a.active { color: #fff; background: #1f1f1f; }

.wrap {
  max-width: 720px;
  margin: 0 auto;
  padding: 32px 20px 64px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

/* Fade-in animation */
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.fade { animation: fadeIn 0.3s ease both; }
.fade:nth-child(2) { animation-delay: 0.05s; }
.fade:nth-child(3) { animation-delay: 0.1s; }
.fade:nth-child(4) { animation-delay: 0.15s; }
.fade:nth-child(5) { animation-delay: 0.2s; }

/* Cards */
.card {
  background: #141414;
  border: 1px solid #252525;
  border-radius: 12px;
  padding: 24px;
}
.card h2 {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 16px;
  color: #fff;
}

/* Hero status */
.hero {
  text-align: center;
  padding: 40px 24px 32px;
}
.hero h1 {
  font-size: 28px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 8px;
  letter-spacing: 0.5px;
}
.status-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 8px;
  vertical-align: middle;
}
.status-dot.online { background: #22c55e; box-shadow: 0 0 8px #22c55e66; }
.status-dot.offline { background: #ef4444; box-shadow: 0 0 8px #ef444466; }
.status-label {
  font-size: 16px;
  color: #999;
  vertical-align: middle;
}

/* Stats grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 24px;
}
.stat-card {
  background: #141414;
  border: 1px solid #252525;
  border-radius: 12px;
  padding: 20px 16px;
  text-align: center;
}
.stat-icon { font-size: 24px; margin-bottom: 6px; }
.stat-num {
  font-size: 36px;
  font-weight: 700;
  font-family: ui-monospace, 'SF Mono', monospace;
  line-height: 1.1;
}
.stat-num.green { color: #22c55e; }
.stat-num.blue { color: #3b82f6; }
.stat-num.amber { color: #f59e0b; }
.stat-label {
  font-size: 14px;
  color: #888;
  margin-top: 4px;
}

/* Inputs and buttons */
input[type="text"], input[type="number"], select {
  width: 100%;
  height: 48px;
  font-size: 16px;
  background: #1a1a1a;
  border: 1px solid #333;
  border-radius: 10px;
  color: #e8e8e8;
  padding: 0 16px;
  outline: none;
  transition: border-color 0.2s;
}
input[type="text"]:focus, input[type="number"]:focus, select:focus { border-color: #3b82f6; }
input[type="text"]::placeholder, input[type="number"]::placeholder { color: #555; }
select { cursor: pointer; }
select option { background: #1a1a1a; color: #e8e8e8; }

.btn {
  height: 48px;
  font-size: 16px;
  font-weight: 500;
  background: #3b82f6;
  color: #fff;
  border: none;
  border-radius: 10px;
  padding: 0 24px;
  cursor: pointer;
  transition: background 0.2s;
  white-space: nowrap;
}
.btn:hover { background: #2563eb; }

.input-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.input-row input, .input-row select { flex: 1; }

/* Asset list */
.asset-item {
  background: #1a1a1a;
  border: 1px solid #252525;
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 10px;
}
.asset-id {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 14px;
  color: #3b82f6;
  word-break: break-all;
}
.asset-owner {
  font-size: 14px;
  color: #888;
  margin-top: 2px;
}
.asset-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.pill {
  display: inline-block;
  height: 24px;
  line-height: 24px;
  padding: 0 10px;
  font-size: 12px;
  background: #222;
  border: 1px solid #444;
  border-radius: 20px;
  color: #ccc;
}
.time-ago {
  font-size: 13px;
  color: #666;
  margin-left: auto;
}

.empty-state {
  text-align: center;
  color: #666;
  padding: 32px 16px;
  font-size: 15px;
  line-height: 1.8;
}
.empty-state code {
  background: #1a1a1a;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 14px;
  color: #3b82f6;
  font-family: ui-monospace, 'SF Mono', monospace;
}

/* Trace result */
.trace-result {
  background: #1a1a1a;
  border: 1px solid #252525;
  border-radius: 10px;
  padding: 16px;
  margin-top: 12px;
}
.trace-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid #222;
  font-size: 15px;
}
.trace-row:last-child { border-bottom: none; }
.trace-key { color: #888; }
.trace-val {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 14px;
  color: #e8e8e8;
  text-align: right;
  word-break: break-all;
  max-width: 60%;
}

/* Distribution list */
.dist-item {
  background: #1a1a1a;
  border: 1px solid #252525;
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 8px;
  font-size: 14px;
}
.dist-item .mono {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 13px;
  color: #3b82f6;
  word-break: break-all;
}
.dist-item .meta {
  color: #888;
  font-size: 13px;
  margin-top: 4px;
}

/* Network section */
.net-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 24px;
  font-size: 15px;
}
.net-key { color: #888; }
.net-val {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 14px;
  text-align: right;
}

.stake-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #222;
  font-size: 15px;
}
.stake-item:last-child { border-bottom: none; }
.stake-id {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 14px;
  color: #e8e8e8;
}
.stake-amount {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-weight: 600;
  color: #22c55e;
}

/* Footer */
.footer {
  text-align: center;
  font-size: 13px;
  color: #444;
  padding-bottom: 24px;
}

/* Separator */
.sep { margin-top: 20px; padding-top: 20px; border-top: 1px solid #252525; }

/* Error / status text */
.err { color: #ef4444; margin-top: 12px; font-size: 15px; }
.ok { color: #22c55e; }

/* ── AHRP Section ────────────────────────────────────────── */
.ahrp-header {
  text-align: center;
  margin-bottom: 8px;
}
.ahrp-header h2 {
  font-size: 22px;
  font-weight: 700;
  background: linear-gradient(135deg, #3b82f6, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 4px;
}
.ahrp-header p { color: #666; font-size: 14px; }

/* AHRP Stats Bar */
.ahrp-stats-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 0;
}
.ahrp-stat {
  background: #1a1a1a;
  border: 1px solid #252525;
  border-radius: 10px;
  padding: 14px 10px;
  text-align: center;
}
.ahrp-stat-num {
  font-size: 24px;
  font-weight: 700;
  font-family: ui-monospace, 'SF Mono', monospace;
  line-height: 1.1;
  color: #6366f1;
}
.ahrp-stat-label {
  font-size: 11px;
  color: #666;
  margin-top: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* AHRP Checkboxes */
.checkbox-group {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  color: #ccc;
  cursor: pointer;
}
.checkbox-group input[type="checkbox"] {
  width: 18px;
  height: 18px;
  accent-color: #6366f1;
  cursor: pointer;
}

/* AHRP Match Cards */
.match-card {
  background: #1a1a1a;
  border: 1px solid #252525;
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 10px;
}
.match-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.match-agent {
  font-family: ui-monospace, 'SF Mono', monospace;
  font-size: 14px;
  color: #3b82f6;
}
.origin-badge {
  display: inline-block;
  height: 22px;
  line-height: 22px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 600;
  border-radius: 20px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.origin-human { background: #22c55e22; color: #22c55e; border: 1px solid #22c55e44; }
.origin-sensor { background: #3b82f622; color: #3b82f6; border: 1px solid #3b82f644; }
.origin-curated { background: #f59e0b22; color: #f59e0b; border: 1px solid #f59e0b44; }
.origin-synthetic { background: #8b5cf622; color: #8b5cf6; border: 1px solid #8b5cf644; }
.match-score-bar {
  width: 100%;
  height: 6px;
  background: #252525;
  border-radius: 3px;
  overflow: hidden;
  margin: 8px 0;
}
.match-score-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, #3b82f6, #22c55e);
  transition: width 0.6s ease;
}
.match-details {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #888;
}

/* ── Transaction Pipeline ─────────────────────────────────── */
.tx-pipeline {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  margin: 20px 0;
  flex-wrap: wrap;
}
.tx-step {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 16px 12px;
  min-width: 90px;
  position: relative;
}
.tx-step-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: #1a1a1a;
  border: 2px solid #333;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  transition: all 0.5s ease;
  position: relative;
  z-index: 1;
}
.tx-step.done .tx-step-circle {
  background: #22c55e22;
  border-color: #22c55e;
  box-shadow: 0 0 16px #22c55e44;
}
.tx-step.active .tx-step-circle {
  background: #3b82f622;
  border-color: #3b82f6;
  box-shadow: 0 0 16px #3b82f644;
  animation: pulse-step 2s infinite;
}
@keyframes pulse-step {
  0%, 100% { box-shadow: 0 0 16px #3b82f644; }
  50% { box-shadow: 0 0 28px #3b82f666; }
}
.tx-step-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #555;
  transition: color 0.5s ease;
}
.tx-step.done .tx-step-label { color: #22c55e; }
.tx-step.active .tx-step-label { color: #3b82f6; }
.tx-arrow {
  font-size: 20px;
  color: #333;
  margin: 0 -2px;
  padding-bottom: 20px;
  transition: color 0.5s ease;
}
.tx-arrow.done { color: #22c55e; }

/* Star rating */
.star-rating {
  display: flex;
  gap: 4px;
  margin-bottom: 16px;
}
.star-rating span {
  font-size: 28px;
  cursor: pointer;
  color: #333;
  transition: color 0.15s, transform 0.15s;
  user-select: none;
}
.star-rating span:hover { transform: scale(1.2); }
.star-rating span.lit { color: #f59e0b; }

/* Responsive */
@media (max-width: 640px) {
  .wrap { padding: 20px 14px 48px; gap: 24px; }
  .stats-grid { grid-template-columns: 1fr; }
  .stat-num { font-size: 28px; }
  .net-grid { grid-template-columns: 1fr; }
  .net-val { text-align: left; }
  .trace-row { flex-direction: column; gap: 2px; }
  .trace-val { text-align: left; max-width: 100%; }
  .input-row { flex-direction: column; }
  .ahrp-stats-bar { grid-template-columns: repeat(2, 1fr); }
  .tx-pipeline { gap: 0; }
  .tx-step { min-width: 60px; padding: 10px 6px; }
  .tx-step-circle { width: 40px; height: 40px; font-size: 16px; }
  .top-nav { gap: 12px; }
}

/* ── Modal ────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed; top:0; left:0; right:0; bottom:0;
  background: rgba(0,0,0,0.7); backdrop-filter: blur(4px);
  z-index: 200; display:flex; align-items:center; justify-content:center;
}
.modal {
  background: #141414; border: 1px solid #333; border-radius: 16px;
  max-width: 560px; width: 90%; max-height: 80vh; overflow-y: auto;
  padding: 32px; position: relative;
}
.modal-close {
  position: absolute; top: 16px; right: 16px; background: none;
  border: none; color: #888; font-size: 24px; cursor: pointer;
}
.modal-close:hover { color: #fff; }
.modal h3 { font-size: 18px; font-weight: 600; color: #fff; margin-bottom: 16px; }
.modal-row { display:flex; justify-content:space-between; padding:8px 0; border-bottom:1px solid #222; font-size:14px; }
.modal-row:last-child { border-bottom:none; }
.modal-key { color:#888; }
.modal-val { font-family:ui-monospace,'SF Mono',monospace; font-size:13px; color:#e8e8e8; text-align:right; word-break:break-all; max-width:60%; cursor:pointer; }
.modal-val:hover { color:#3b82f6; }

/* ── Toast ────────────────────────────────────────────────── */
.toast-container {
  position: fixed; top: 64px; right: 20px; z-index: 300;
  display: flex; flex-direction: column; gap: 8px;
}
.toast {
  background: #1a1a1a; border: 1px solid #333; border-radius: 10px;
  padding: 14px 20px; font-size: 14px; color: #e8e8e8;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  animation: toastIn 0.3s ease, toastOut 0.3s ease 2.7s forwards;
  max-width: 340px;
}
.toast.success { border-color: #22c55e; }
.toast.error { border-color: #ef4444; }
@keyframes toastIn { from { opacity:0; transform:translateX(40px); } to { opacity:1; transform:translateX(0); } }
@keyframes toastOut { from { opacity:1; } to { opacity:0; } }

/* ── Delete button on asset cards ─────────────────────────── */
.asset-item { position: relative; cursor: pointer; transition: border-color 0.2s; }
.asset-item:hover { border-color: #3b82f6; }
.asset-delete-btn {
  position: absolute; top: 12px; right: 12px;
  background: none; border: 1px solid #ef444444; border-radius: 6px;
  color: #ef4444; font-size: 14px; cursor: pointer;
  width: 28px; height: 28px; display: flex; align-items: center; justify-content: center;
  opacity: 0; transition: opacity 0.2s;
}
.asset-item:hover .asset-delete-btn { opacity: 1; }
.asset-delete-btn:hover { background: #ef444422; }

/* ── Price badge ──────────────────────────────────────────── */
.price-badge {
  display: inline-block; height: 24px; line-height: 24px;
  padding: 0 10px; font-size: 12px; font-weight: 600;
  font-family: ui-monospace, 'SF Mono', monospace;
  background: #22c55e18; border: 1px solid #22c55e44;
  border-radius: 20px; color: #22c55e;
}
.price-badge.none { background: #33333344; border-color: #444; color: #666; }

/* ── Portfolio table ──────────────────────────────────────── */
.portfolio-table { width:100%; border-collapse:collapse; font-size:14px; }
.portfolio-table th { text-align:left; color:#888; font-weight:500; padding:8px 4px; border-bottom:1px solid #333; font-size:13px; text-transform:uppercase; letter-spacing:0.5px; }
.portfolio-table td { padding:10px 4px; border-bottom:1px solid #1f1f1f; }
.portfolio-table td.mono { font-family:ui-monospace,'SF Mono',monospace; font-size:13px; color:#3b82f6; }
.portfolio-table td.num { font-family:ui-monospace,'SF Mono',monospace; text-align:right; }
.portfolio-table td.green { color:#22c55e; }

/* ── Transaction list ─────────────────────────────────────── */
.tx-item {
  background:#1a1a1a; border:1px solid #252525; border-radius:10px;
  padding:12px 16px; margin-bottom:8px; font-size:14px;
  display:flex; justify-content:space-between; align-items:center;
}
.tx-item-left { display:flex; flex-direction:column; gap:2px; }
.tx-item-id { font-family:ui-monospace,'SF Mono',monospace; font-size:13px; color:#3b82f6; }
.tx-item-detail { font-size:13px; color:#888; }
.tx-item-right { text-align:right; }
.tx-item-tokens { font-family:ui-monospace,'SF Mono',monospace; font-weight:600; color:#22c55e; }
.tx-item-status { font-size:12px; color:#888; }

/* Edit tags inline */
.tag-edit-row { display:flex; gap:8px; margin-top:12px; }
.tag-edit-row input { flex:1; height:36px; font-size:14px; background:#1a1a1a; border:1px solid #333; border-radius:8px; color:#e8e8e8; padding:0 12px; outline:none; }
.tag-edit-row input:focus { border-color:#3b82f6; }
.tag-edit-row button { height:36px; font-size:13px; padding:0 16px; border:none; border-radius:8px; cursor:pointer; font-weight:500; }
</style>
</head>
<body>

<!-- ── Navigation Bar ──────────────────────────────────────── -->
<nav class="top-nav">
  <span class="nav-brand">OASYCE</span>
  <div class="nav-links">
    <a href="/" class="active">Dashboard</a>
    <a href="http://localhost:8421" target="_blank">Explorer</a>
  </div>
</nav>

<div class="wrap">

  <!-- Section 1: Hero Status -->
  <div class="hero card fade" id="hero">
    <h1>Oasyce</h1>
    <div id="status-indicator">
      <span class="status-dot online"></span>
      <span class="status-label">Online</span>
    </div>
    <div class="stats-grid" id="stats-grid">
      <div class="stat-card">
        <div class="stat-icon">&#x1f4e6;</div>
        <div class="stat-num green" id="stat-assets">--</div>
        <div class="stat-label">Assets registered</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">&#x26d3;</div>
        <div class="stat-num blue" id="stat-blocks">--</div>
        <div class="stat-label">Blocks mined</div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">&#x1f512;</div>
        <div class="stat-num amber" id="stat-dists">--</div>
        <div class="stat-label">Watermarks issued</div>
      </div>
    </div>
  </div>

  <!-- Section 2: Quick Actions -->
  <div class="card fade" style="display:flex;gap:10px;flex-wrap:wrap;justify-content:center;">
    <button class="btn" onclick="document.getElementById('register-section').scrollIntoView({behavior:'smooth'})" style="flex:1;min-width:120px;">&#x1f4e6; Register</button>
    <button class="btn" onclick="document.getElementById('buy-section').scrollIntoView({behavior:'smooth'})" style="flex:1;min-width:120px;background:#22c55e;">&#x1f4b0; Buy</button>
    <button class="btn" onclick="document.getElementById('embed-section').scrollIntoView({behavior:'smooth'})" style="flex:1;min-width:120px;background:#f59e0b;color:#000;">&#x1f512; Watermark</button>
    <button class="btn" onclick="document.getElementById('stake-section').scrollIntoView({behavior:'smooth'})" style="flex:1;min-width:120px;background:#8b5cf6;">&#x26d3; Stake</button>
    <button class="btn" onclick="document.getElementById('ahrp-section').scrollIntoView({behavior:'smooth'})" style="flex:1;min-width:120px;background:linear-gradient(135deg,#3b82f6,#6366f1);">&#x1f91d; AHRP</button>
  </div>

  <!-- Section 2b: My Portfolio -->
  <div class="card fade" id="portfolio-section">
    <h2>My portfolio</h2>
    <div id="portfolio-list"></div>
  </div>

  <!-- Section 3: Your Assets -->
  <div class="card fade" id="assets-section">
    <h2>Your assets</h2>
    <input type="text" id="asset-search" placeholder="Search your assets...">
    <div id="assets-list" style="margin-top: 16px;"></div>
  </div>

  <!-- Section 3b: Register Asset -->
  <div class="card fade" id="register-section">
    <h2>Register a file</h2>
    <div class="input-row"><input type="text" id="reg-path" placeholder="File path (e.g. /Users/you/report.pdf)"></div>
    <div class="input-row">
      <input type="text" id="reg-owner" placeholder="Owner name" style="flex:1;">
      <input type="text" id="reg-tags" placeholder="Tags (comma-separated)" style="flex:1;">
    </div>
    <button class="btn" id="reg-btn" style="width:100%;">Register</button>
    <div id="reg-result"></div>
  </div>

  <!-- Section 3b2: Recent Transactions -->
  <div class="card fade" id="tx-history-section">
    <h2>Recent transactions</h2>
    <div id="tx-history-list"></div>
  </div>

  <!-- Section 3c: Buy Data -->
  <div class="card fade" id="buy-section">
    <h2>Buy data access</h2>
    <div class="input-row">
      <input type="text" id="buy-asset" placeholder="Asset ID">
      <input type="text" id="buy-amount" placeholder="Amount (OAS)" value="10" style="max-width:120px;">
    </div>
    <div style="display:flex;gap:10px;">
      <button class="btn" id="quote-btn" style="flex:1;background:#333;">Get quote</button>
      <button class="btn" id="buy-btn" style="flex:1;">Buy</button>
    </div>
    <div id="buy-result"></div>
  </div>

  <!-- Section 3d: Embed Watermark -->
  <div class="card fade" id="embed-section">
    <h2>Embed a watermark</h2>
    <div class="input-row">
      <input type="text" id="emb-asset" placeholder="Asset ID" style="flex:1;">
      <input type="text" id="emb-caller" placeholder="Buyer ID" style="flex:1;">
    </div>
    <textarea id="emb-content" placeholder="Paste the content to watermark..." style="width:100%;min-height:120px;font-size:16px;background:#1a1a1a;border:1px solid #333;border-radius:10px;color:#e8e8e8;padding:16px;font-family:ui-monospace,monospace;resize:vertical;outline:none;"></textarea>
    <button class="btn" id="emb-btn" style="width:100%;margin-top:10px;background:#f59e0b;color:#000;">Embed watermark</button>
    <div id="emb-result"></div>
  </div>

  <!-- Section 4: Watermark Tracker -->
  <div class="card fade" id="trace-section">
    <h2>Trace a watermark</h2>
    <div class="input-row">
      <input type="text" id="fp-input" placeholder="Paste a watermark fingerprint...">
      <button class="btn" id="fp-trace-btn">Trace</button>
    </div>
    <div id="fp-trace-result"></div>

    <div class="sep">
      <h2>Look up by asset</h2>
      <div class="input-row">
        <input type="text" id="fp-asset-input" placeholder="Paste an asset ID...">
        <button class="btn" id="fp-list-btn">Look up</button>
      </div>
      <div id="fp-dist-list"></div>
    </div>
  </div>

  <!-- Section 6: Stake OAS -->
  <div class="card fade" id="stake-section">
    <h2>Stake OAS</h2>
    <p style="color:#888;font-size:14px;margin-bottom:12px;">Stake OAS to become a node operator and earn block rewards + transaction fees.</p>
    <div class="input-row">
      <input type="text" id="stake-node" placeholder="Your node ID" style="flex:1;">
      <input type="text" id="stake-amount" placeholder="Amount (OAS)" value="10000" style="max-width:140px;">
    </div>
    <button class="btn" id="stake-btn" style="width:100%;background:#8b5cf6;">Stake</button>
    <div id="stake-result"></div>
  </div>

  <!-- ══════════════════════════════════════════════════════════
       AHRP — Agent Handshake & Routing Protocol
       ══════════════════════════════════════════════════════════ -->
  <div id="ahrp-section">

    <div class="card fade">
      <div class="ahrp-header">
        <h2>Agent Handshake &amp; Routing Protocol</h2>
        <p>Register agents, discover capabilities, and execute verified data transactions</p>
      </div>

      <!-- AHRP Network Stats Bar -->
      <div class="ahrp-stats-bar" id="ahrp-stats-bar">
        <div class="ahrp-stat">
          <div class="ahrp-stat-num" id="ahrp-stat-agents">--</div>
          <div class="ahrp-stat-label">Agents</div>
        </div>
        <div class="ahrp-stat">
          <div class="ahrp-stat-num" id="ahrp-stat-caps">--</div>
          <div class="ahrp-stat-label">Capabilities</div>
        </div>
        <div class="ahrp-stat">
          <div class="ahrp-stat-num" id="ahrp-stat-txs">--</div>
          <div class="ahrp-stat-label">Transactions</div>
        </div>
        <div class="ahrp-stat">
          <div class="ahrp-stat-num" id="ahrp-stat-vol">--</div>
          <div class="ahrp-stat-label">Volume (OAS)</div>
        </div>
      </div>
    </div>

    <!-- (a) Agent Registration Panel -->
    <div class="card fade" id="ahrp-register">
      <h2>Register Agent</h2>
      <div class="input-row">
        <input type="text" id="ahrp-agent-id" placeholder="Agent ID" style="flex:1;">
        <input type="text" id="ahrp-pub-key" placeholder="Public key" style="flex:1;">
      </div>
      <div class="input-row">
        <input type="number" id="ahrp-reputation" placeholder="Reputation" value="10" style="flex:1;">
        <input type="number" id="ahrp-stake" placeholder="Stake (OAS)" value="100" style="flex:1;">
      </div>
      <div class="sep" style="margin-top:8px;padding-top:16px;">
        <h2 style="font-size:16px;">Capability</h2>
        <div class="input-row">
          <input type="text" id="ahrp-cap-id" placeholder="Capability ID" style="flex:1;">
          <input type="text" id="ahrp-cap-tags" placeholder="Tags (comma-sep)" style="flex:1;">
        </div>
        <div class="input-row">
          <input type="text" id="ahrp-cap-desc" placeholder="Description" style="flex:2;">
          <input type="number" id="ahrp-cap-price" placeholder="Price floor" value="1.0" style="flex:1;">
        </div>
        <div class="input-row">
          <select id="ahrp-cap-origin" style="flex:1;">
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
      </div>
      <button class="btn" id="ahrp-announce-btn" style="width:100%;background:linear-gradient(135deg,#3b82f6,#6366f1);">Announce Agent</button>
      <div id="ahrp-announce-result"></div>
    </div>

    <!-- (b) Discovery & Matching Panel -->
    <div class="card fade" id="ahrp-discover">
      <h2>Discover Capabilities</h2>
      <div class="input-row">
        <input type="text" id="ahrp-search-desc" placeholder="Description (what data do you need?)" style="flex:2;">
        <input type="text" id="ahrp-search-tags" placeholder="Tags" style="flex:1;">
      </div>
      <div class="input-row">
        <input type="number" id="ahrp-search-rep" placeholder="Min reputation" value="5" style="flex:1;">
        <input type="number" id="ahrp-search-price" placeholder="Max price" value="100" style="flex:1;">
        <select id="ahrp-search-access" style="flex:1;">
          <option value="L0">L0</option>
          <option value="L1">L1</option>
          <option value="L2">L2</option>
          <option value="L3">L3</option>
        </select>
      </div>
      <button class="btn" id="ahrp-find-btn" style="width:100%;background:#333;">Find Matches</button>
      <div id="ahrp-matches" style="margin-top:16px;"></div>
    </div>

    <!-- (c) Transaction Flow Panel -->
    <div class="card fade" id="ahrp-tx-flow">
      <h2>Transaction Flow</h2>

      <!-- Visual Pipeline -->
      <div class="tx-pipeline" id="tx-pipeline">
        <div class="tx-step" id="tx-step-request">
          <div class="tx-step-circle">&#x1f4e8;</div>
          <div class="tx-step-label">Request</div>
        </div>
        <div class="tx-arrow" id="tx-arrow-1">&#x25b6;</div>
        <div class="tx-step" id="tx-step-offer">
          <div class="tx-step-circle">&#x1f4cb;</div>
          <div class="tx-step-label">Offer</div>
        </div>
        <div class="tx-arrow" id="tx-arrow-2">&#x25b6;</div>
        <div class="tx-step" id="tx-step-accept">
          <div class="tx-step-circle">&#x2705;</div>
          <div class="tx-step-label">Accept</div>
        </div>
        <div class="tx-arrow" id="tx-arrow-3">&#x25b6;</div>
        <div class="tx-step" id="tx-step-deliver">
          <div class="tx-step-circle">&#x1f4e6;</div>
          <div class="tx-step-label">Deliver</div>
        </div>
        <div class="tx-arrow" id="tx-arrow-4">&#x25b6;</div>
        <div class="tx-step" id="tx-step-confirm">
          <div class="tx-step-circle">&#x2b50;</div>
          <div class="tx-step-label">Confirm</div>
        </div>
      </div>

      <!-- Accept -->
      <div class="sep">
        <h2 style="font-size:16px;">1. Accept a deal</h2>
        <div class="input-row">
          <input type="text" id="tx-buyer" placeholder="Buyer ID" style="flex:1;">
          <input type="text" id="tx-seller" placeholder="Seller ID" style="flex:1;">
        </div>
        <div class="input-row">
          <input type="text" id="tx-cap-id" placeholder="Capability ID" style="flex:1;">
          <input type="number" id="tx-price" placeholder="Price (OAS)" value="10" style="flex:1;">
        </div>
        <button class="btn" id="tx-accept-btn" style="width:100%;">Accept &amp; Create Transaction</button>
        <div id="tx-accept-result"></div>
      </div>

      <!-- Deliver -->
      <div class="sep">
        <h2 style="font-size:16px;">2. Deliver content</h2>
        <div class="input-row">
          <input type="text" id="tx-deliver-id" placeholder="Transaction ID (auto-filled)" style="flex:2;">
          <input type="text" id="tx-content-hash" placeholder="Content hash" style="flex:1;">
        </div>
        <button class="btn" id="tx-deliver-btn" style="width:100%;background:#22c55e;">Deliver</button>
        <div id="tx-deliver-result"></div>
      </div>

      <!-- Confirm -->
      <div class="sep">
        <h2 style="font-size:16px;">3. Confirm &amp; rate</h2>
        <div class="input-row">
          <input type="text" id="tx-confirm-id" placeholder="Transaction ID (auto-filled)" style="flex:1;">
        </div>
        <div class="star-rating" id="star-rating">
          <span data-v="1">&#x2605;</span>
          <span data-v="2">&#x2605;</span>
          <span data-v="3">&#x2605;</span>
          <span data-v="4">&#x2605;</span>
          <span data-v="5">&#x2605;</span>
        </div>
        <button class="btn" id="tx-confirm-btn" style="width:100%;background:#f59e0b;color:#000;">Confirm &amp; Settle</button>
        <div id="tx-confirm-result"></div>
      </div>
    </div>

  </div><!-- /ahrp-section -->

  <!-- Section 7: Network -->
  <div class="card fade" id="network-section">
    <h2>Network</h2>
    <div class="net-grid" id="net-info"></div>
    <div id="stakes-section" style="display:none;" class="sep">
      <h2 style="margin-bottom:12px;">Node operators</h2>
      <div id="stakes-list"></div>
    </div>
  </div>

  <!-- Footer -->
  <div class="footer fade">Oasyce Protocol v1.2.0 &middot; MIT License</div>

</div>

<script>
(function() {

  // ── Helpers ──────────────────────────────────────────────────
  function esc(s) {
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }

  function trunc(s, n) {
    n = n || 16;
    return s && s.length > n ? s.slice(0, n) + '\u2026' : (s || '');
  }

  function timeAgo(ts) {
    if (!ts) return '';
    var then;
    if (typeof ts === 'number') {
      then = ts > 1e12 ? new Date(ts) : new Date(ts * 1000);
    } else {
      then = new Date(ts);
    }
    var diff = Math.floor((Date.now() - then.getTime()) / 1000);
    if (diff < 0) diff = 0;
    if (diff < 60) return diff + ' sec ago';
    if (diff < 3600) return Math.floor(diff / 60) + ' min ago';
    if (diff < 86400) return Math.floor(diff / 3600) + ' hours ago';
    return Math.floor(diff / 86400) + ' days ago';
  }

  async function api(path) {
    try {
      var r = await fetch(path);
      return r.json();
    } catch(e) {
      return null;
    }
  }

  async function postApi(path, body) {
    try {
      var r = await fetch(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      return r.json();
    } catch(e) {
      return {ok:false,error:e.message};
    }
  }

  // ── Toast notifications ────────────────────────────────────
  function toast(msg, type) {
    type = type || 'success';
    var container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }
    var el = document.createElement('div');
    el.className = 'toast ' + type;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(function() { el.remove(); }, 3000);
  }

  // ── Confirm dialog ─────────────────────────────────────────
  function confirmAction(msg) {
    return new Promise(function(resolve) {
      resolve(window.confirm(msg));
    });
  }

  // ── Delete asset ───────────────────────────────────────────
  async function deleteAsset(aid) {
    var ok = await confirmAction('Delete asset ' + aid.slice(0,16) + '...? This cannot be undone.');
    if (!ok) return;
    try {
      var r = await fetch('/api/asset/' + encodeURIComponent(aid), {method:'DELETE'});
      var d = await r.json();
      if (d.ok) {
        toast('Asset deleted');
        closeModal();
        loadAssets(); loadStatus(); loadPortfolio();
      } else { toast(d.error || 'Failed to delete', 'error'); }
    } catch(e) { toast(e.message, 'error'); }
  }

  // ── Asset detail modal ─────────────────────────────────────
  function closeModal() {
    var overlay = document.getElementById('modal-overlay');
    if (overlay) overlay.remove();
  }

  async function showAssetModal(aid) {
    var d = await api('/api/asset/' + encodeURIComponent(aid));
    if (!d || d.error) { toast('Asset not found', 'error'); return; }
    var q = await api('/api/quote?asset_id=' + encodeURIComponent(aid) + '&amount=1');
    var priceStr = (q && !q.error) ? q.price_before + ' OAS' : 'N/A';
    var meta = d.metadata || {};
    var tags = meta.tags || [];

    var overlay = document.createElement('div');
    overlay.id = 'modal-overlay';
    overlay.className = 'modal-overlay';
    overlay.addEventListener('click', function(e) { if (e.target === overlay) closeModal(); });

    var tagsHtml = tags.map(function(t){ return '<span class="pill">' + esc(t) + '</span>'; }).join(' ') || '<span style="color:#666;">None</span>';
    var metaRows = '';
    Object.keys(meta).forEach(function(k) {
      if (k === 'tags') return;
      metaRows += '<div class="modal-row"><span class="modal-key">' + esc(k) + '</span><span class="modal-val">' + esc(typeof meta[k] === 'object' ? JSON.stringify(meta[k]) : meta[k]) + '</span></div>';
    });

    overlay.innerHTML = '<div class="modal">' +
      '<button class="modal-close" onclick="closeModal()">&times;</button>' +
      '<h3>Asset details</h3>' +
      '<div class="modal-row"><span class="modal-key">Asset ID</span><span class="modal-val" title="Click to copy" onclick="navigator.clipboard.writeText(\'' + esc(d.asset_id) + '\');toast(\'Copied!\')">' + esc(d.asset_id) + '</span></div>' +
      '<div class="modal-row"><span class="modal-key">Owner</span><span class="modal-val">' + esc(d.owner) + '</span></div>' +
      '<div class="modal-row"><span class="modal-key">Created</span><span class="modal-val">' + esc(d.created_at) + '</span></div>' +
      '<div class="modal-row"><span class="modal-key">Spot price</span><span class="modal-val" style="color:#22c55e;">' + esc(priceStr) + '</span></div>' +
      '<div class="modal-row"><span class="modal-key">Tags</span><span class="modal-val" style="display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;">' + tagsHtml + '</span></div>' +
      metaRows +
      '<div id="modal-tag-edit"></div>' +
      '<div style="display:flex;gap:10px;margin-top:20px;">' +
        '<button class="btn" style="flex:1;background:#333;font-size:14px;height:40px;" onclick="showEditTags(\'' + esc(d.asset_id) + '\',\'' + esc(tags.join(',')) + '\')">Edit tags</button>' +
        '<button class="btn" style="flex:1;background:#ef4444;font-size:14px;height:40px;" onclick="deleteAsset(\'' + esc(d.asset_id) + '\')">Delete</button>' +
      '</div>' +
      '</div>';
    document.body.appendChild(overlay);
  }

  // ── Edit tags in modal ─────────────────────────────────────
  function showEditTags(aid, currentTags) {
    var container = document.getElementById('modal-tag-edit');
    if (!container) return;
    container.innerHTML = '<div class="tag-edit-row">' +
      '<input type="text" id="modal-tag-input" value="' + esc(currentTags) + '" placeholder="tag1, tag2, ...">' +
      '<button style="background:#3b82f6;color:#fff;" onclick="saveEditTags(\'' + esc(aid) + '\')">Save</button>' +
      '<button style="background:#333;color:#888;" onclick="document.getElementById(\'modal-tag-edit\').innerHTML=\'\'">Cancel</button>' +
      '</div>';
    document.getElementById('modal-tag-input').focus();
  }

  async function saveEditTags(aid) {
    var input = document.getElementById('modal-tag-input');
    if (!input) return;
    var tags = input.value.split(',').map(function(t){return t.trim();}).filter(Boolean);
    var d = await postApi('/api/asset/update', {asset_id: aid, tags: tags});
    if (d && d.ok) {
      toast('Tags updated');
      closeModal();
      loadAssets();
    } else { toast(d ? d.error : 'Failed', 'error'); }
  }

  // Make modal functions global
  window.closeModal = closeModal;
  window.showAssetModal = showAssetModal;
  window.deleteAsset = deleteAsset;
  window.showEditTags = showEditTags;
  window.saveEditTags = saveEditTags;
  window.toast = toast;

  // ── Load status ──────────────────────────────────────────────
  async function loadStatus() {
    var d = await api('/api/status');
    if (!d) {
      document.querySelector('.status-dot').className = 'status-dot offline';
      document.querySelector('.status-label').textContent = 'Offline';
      return;
    }

    document.querySelector('.status-dot').className = 'status-dot online';
    document.querySelector('.status-label').textContent = 'Online';

    document.getElementById('stat-assets').textContent = d.total_assets;
    document.getElementById('stat-blocks').textContent = d.total_blocks;
    document.getElementById('stat-dists').textContent = d.total_distributions;

    // Network info
    var ni = document.getElementById('net-info');
    ni.innerHTML =
      '<span class="net-key">Node ID</span><span class="net-val">' + esc(d.node_id) + '</span>' +
      '<span class="net-key">Address</span><span class="net-val">' + esc(d.host) + ':' + esc(d.port) + '</span>' +
      '<span class="net-key">Blocks mined</span><span class="net-val">' + esc(d.chain_height) + '</span>';
  }

  // ── Load assets ──────────────────────────────────────────────
  var _allAssets = [];

  async function loadAssets() {
    _allAssets = await api('/api/assets') || [];
    renderAssets(_allAssets);
  }

  function renderAssets(list) {
    var container = document.getElementById('assets-list');
    if (!list.length) {
      container.innerHTML = '<div class="empty-state">No assets yet.<br>Register your first file with: <code>oasyce register &lt;file&gt;</code></div>';
      return;
    }
    var html = '';
    list.forEach(function(a) {
      var tags = (a.tags || []).map(function(t) { return '<span class="pill">' + esc(t) + '</span>'; }).join('');
      var priceHtml = a.spot_price != null
        ? '<span class="price-badge">' + a.spot_price + ' OAS</span>'
        : '<span class="price-badge none">Not listed</span>';
      html += '<div class="asset-item" onclick="showAssetModal(\'' + esc(a.asset_id) + '\')">' +
        '<button class="asset-delete-btn" title="Delete" onclick="event.stopPropagation();deleteAsset(\'' + esc(a.asset_id) + '\')">&times;</button>' +
        '<div class="asset-id">' + esc(trunc(a.asset_id, 24)) + '</div>' +
        '<div class="asset-owner">' + esc(a.owner) + '</div>' +
        '<div class="asset-meta">' + tags + priceHtml + '<span class="time-ago">' + timeAgo(a.created_at) + '</span></div>' +
        '</div>';
    });
    container.innerHTML = html;
  }

  document.getElementById('asset-search').addEventListener('input', function(e) {
    var q = e.target.value.toLowerCase();
    if (!q) { renderAssets(_allAssets); return; }
    renderAssets(_allAssets.filter(function(a) {
      return (a.asset_id || '').toLowerCase().indexOf(q) !== -1 ||
        (a.tags || []).some(function(t) { return t.toLowerCase().indexOf(q) !== -1; });
    }));
  });

  // ── Trace fingerprint ───────────────────────────────────────
  document.getElementById('fp-trace-btn').addEventListener('click', async function() {
    var fp = document.getElementById('fp-input').value.trim();
    if (!fp) return;
    var r = await api('/api/trace?fp=' + encodeURIComponent(fp));
    var div = document.getElementById('fp-trace-result');
    if (!r || r.error) {
      div.innerHTML = '<p class="err">Not found. Check the fingerprint and try again.</p>';
    } else {
      div.innerHTML = '<div class="trace-result">' +
        '<div class="trace-row"><span class="trace-key">Asset</span><span class="trace-val">' + esc(r.asset_id) + '</span></div>' +
        '<div class="trace-row"><span class="trace-key">Bought by</span><span class="trace-val">' + esc(r.caller_id) + '</span></div>' +
        '<div class="trace-row"><span class="trace-key">Fingerprint</span><span class="trace-val">' + esc(trunc(r.fingerprint, 24)) + '</span></div>' +
        '<div class="trace-row"><span class="trace-key">When</span><span class="trace-val">' + timeAgo(r.timestamp || r.created_at) + '</span></div>' +
        '</div>';
    }
  });

  // ── List distributions ──────────────────────────────────────
  document.getElementById('fp-list-btn').addEventListener('click', async function() {
    var aid = document.getElementById('fp-asset-input').value.trim();
    if (!aid) return;
    var list = await api('/api/fingerprints?asset_id=' + encodeURIComponent(aid));
    var container = document.getElementById('fp-dist-list');
    if (!list || !list.length) {
      container.innerHTML = '<p class="err">No watermarks found for this asset.</p>';
      return;
    }
    var html = '';
    list.forEach(function(r) {
      html += '<div class="dist-item">' +
        '<div class="mono">' + esc(trunc(r.fingerprint, 24)) + '</div>' +
        '<div class="meta">' + esc(r.caller_id) + ' &middot; ' + timeAgo(r.timestamp) + '</div>' +
        '</div>';
    });
    container.innerHTML = html;
  });

  // ── Load stakes ─────────────────────────────────────────────
  async function loadStakes() {
    var list = await api('/api/stakes') || [];
    var sec = document.getElementById('stakes-section');
    if (!list.length) { sec.style.display = 'none'; return; }
    sec.style.display = 'block';
    var html = '';
    list.forEach(function(s) {
      html += '<div class="stake-item">' +
        '<span class="stake-id">' + esc(trunc(s.validator_id, 20)) + '</span>' +
        '<span class="stake-amount">' + s.total + ' OAS</span>' +
        '</div>';
    });
    document.getElementById('stakes-list').innerHTML = html;
  }

  // ── Load portfolio ──────────────────────────────────────────
  async function loadPortfolio() {
    var list = await api('/api/portfolio?buyer=gui_user') || [];
    var container = document.getElementById('portfolio-list');
    if (!list.length) {
      container.innerHTML = '<div class="empty-state">No holdings yet. Buy data access to see your portfolio.</div>';
      return;
    }
    var html = '<table class="portfolio-table"><thead><tr><th>Asset</th><th style="text-align:right;">Shares</th><th style="text-align:right;">Price</th><th style="text-align:right;">Value</th></tr></thead><tbody>';
    list.forEach(function(h) {
      html += '<tr>' +
        '<td class="mono">' + esc(trunc(h.asset_id, 16)) + '</td>' +
        '<td class="num">' + h.shares + '</td>' +
        '<td class="num">' + h.spot_price + ' OAS</td>' +
        '<td class="num green">' + h.value_oas + ' OAS</td>' +
        '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
  }

  // ── Load transaction history ───────────────────────────────
  async function loadTransactions() {
    var list = await api('/api/transactions') || [];
    var container = document.getElementById('tx-history-list');
    if (!list.length) {
      container.innerHTML = '<div class="empty-state">No transactions yet.</div>';
      return;
    }
    var html = '';
    list.forEach(function(tx) {
      html += '<div class="tx-item">' +
        '<div class="tx-item-left">' +
          '<span class="tx-item-id">' + esc(trunc(tx.receipt_id, 16)) + '</span>' +
          '<span class="tx-item-detail">' + esc(trunc(tx.asset_id, 16)) + ' &middot; ' + esc(tx.buyer) + '</span>' +
        '</div>' +
        '<div class="tx-item-right">' +
          '<div class="tx-item-tokens">+' + tx.tokens + ' tokens</div>' +
          '<div class="tx-item-status">' + esc(tx.status) + '</div>' +
        '</div>' +
        '</div>';
    });
    container.innerHTML = html;
  }

  // ── Register ─────────────────────────────────────────────
  document.getElementById('reg-btn').addEventListener('click', async function() {
    var btn = this; btn.textContent = 'Working...'; btn.disabled = true;
    var fp = document.getElementById('reg-path').value.trim();
    var owner = document.getElementById('reg-owner').value.trim();
    var tags = document.getElementById('reg-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean);
    var div = document.getElementById('reg-result');
    try {
      var r = await fetch('/api/register', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_path:fp,owner:owner||undefined,tags:tags})});
      var d = await r.json();
      if (d.ok) {
        div.innerHTML = '<div class="trace-result" style="border-color:#22c55e;margin-top:12px;"><div class="trace-row"><span class="trace-key">Asset ID</span><span class="trace-val">' + esc(d.asset_id) + '</span></div><div class="trace-row"><span class="trace-key">File hash</span><span class="trace-val">' + esc(trunc(d.file_hash,24)) + '</span></div></div>';
        toast('Asset registered successfully');
        loadAssets(); loadStatus();
      } else { div.innerHTML = '<p class="err">' + esc(d.error) + '</p>'; toast(d.error, 'error'); }
    } catch(e) { div.innerHTML = '<p class="err">' + esc(e.message) + '</p>'; }
    btn.textContent = 'Register'; btn.disabled = false;
  });

  // ── Quote & Buy ─────────────────────────────────────────────
  document.getElementById('quote-btn').addEventListener('click', async function() {
    var aid = document.getElementById('buy-asset').value.trim();
    var amount = document.getElementById('buy-amount').value.trim() || '10';
    var div = document.getElementById('buy-result');
    if (!aid) { div.innerHTML = '<p class="err">Enter an asset ID</p>'; return; }
    var r = await api('/api/quote?asset_id=' + encodeURIComponent(aid) + '&amount=' + amount);
    if (!r || r.error) { div.innerHTML = '<p class="err">' + esc(r ? r.error : 'Failed') + '</p>'; return; }
    div.innerHTML = '<div class="trace-result" style="margin-top:12px;">' +
      '<div class="trace-row"><span class="trace-key">You pay</span><span class="trace-val">' + r.payment + ' OAS</span></div>' +
      '<div class="trace-row"><span class="trace-key">You get</span><span class="trace-val">' + r.tokens + ' tokens</span></div>' +
      '<div class="trace-row"><span class="trace-key">Price before</span><span class="trace-val">' + r.price_before + ' OAS</span></div>' +
      '<div class="trace-row"><span class="trace-key">Price after</span><span class="trace-val">' + r.price_after + ' OAS</span></div>' +
      '<div class="trace-row"><span class="trace-key">Price impact</span><span class="trace-val">' + r.impact_pct + '%</span></div>' +
      '<div class="trace-row"><span class="trace-key">Protocol fee</span><span class="trace-val">' + r.fee + ' OAS</span></div>' +
      '<div class="trace-row"><span class="trace-key">Burned</span><span class="trace-val" style="color:#ef4444;">' + r.burn + ' OAS</span></div>' +
      '</div>';
  });

  document.getElementById('buy-btn').addEventListener('click', async function() {
    var btn = this;
    var aid = document.getElementById('buy-asset').value.trim();
    var amount = document.getElementById('buy-amount').value.trim() || '10';
    var div = document.getElementById('buy-result');
    if (!aid) { div.innerHTML = '<p class="err">Enter an asset ID</p>'; return; }
    var ok = await confirmAction('Buy ' + amount + ' OAS of asset ' + aid.slice(0,16) + '...?');
    if (!ok) return;
    btn.textContent = 'Working...'; btn.disabled = true;
    try {
      var r = await fetch('/api/buy', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:aid,buyer:'gui_user',amount:parseFloat(amount)})});
      var d = await r.json();
      if (d.ok) {
        div.innerHTML = '<div class="trace-result" style="border-color:#22c55e;margin-top:12px;">' +
          '<div class="trace-row"><span class="trace-key">Receipt</span><span class="trace-val">' + esc(d.receipt_id) + '</span></div>' +
          '<div class="trace-row"><span class="trace-key">Tokens received</span><span class="trace-val" style="color:#22c55e;">' + d.tokens + '</span></div>' +
          '<div class="trace-row"><span class="trace-key">New price</span><span class="trace-val">' + d.price_after + ' OAS</span></div>' +
          '<div class="trace-row"><span class="trace-key">Your equity</span><span class="trace-val">' + d.equity_balance + '</span></div>' +
          '</div>';
        toast('Purchase successful! ' + d.tokens + ' tokens received');
        loadPortfolio(); loadTransactions(); loadAssets();
      } else { div.innerHTML = '<p class="err">' + esc(d.error) + '</p>'; toast(d.error, 'error'); }
    } catch(e) { div.innerHTML = '<p class="err">' + esc(e.message) + '</p>'; toast(e.message, 'error'); }
    btn.textContent = 'Buy'; btn.disabled = false;
  });

  // ── Embed watermark ─────────────────────────────────────────
  document.getElementById('emb-btn').addEventListener('click', async function() {
    var btn = this; btn.textContent = 'Working...'; btn.disabled = true;
    var aid = document.getElementById('emb-asset').value.trim();
    var caller = document.getElementById('emb-caller').value.trim();
    var content = document.getElementById('emb-content').value;
    var div = document.getElementById('emb-result');
    if (!aid || !caller || !content) { div.innerHTML = '<p class="err">Fill in all fields</p>'; btn.textContent='Embed watermark';btn.disabled=false; return; }
    try {
      var r = await fetch('/api/fingerprint/embed', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:aid,caller_id:caller,content:content})});
      var d = await r.json();
      if (d.ok) {
        div.innerHTML = '<div class="trace-result" style="border-color:#f59e0b;margin-top:12px;">' +
          '<div class="trace-row"><span class="trace-key">Fingerprint</span><span class="trace-val">' + esc(trunc(d.fingerprint,32)) + '</span></div>' +
          '</div>' +
          '<textarea readonly style="width:100%;min-height:100px;font-size:14px;background:#1a1a1a;border:1px solid #333;border-radius:10px;color:#22c55e;padding:16px;font-family:ui-monospace,monospace;margin-top:10px;">' + esc(d.watermarked_content) + '</textarea>';
        loadStatus();
      } else { div.innerHTML = '<p class="err">' + esc(d.error) + '</p>'; }
    } catch(e) { div.innerHTML = '<p class="err">' + esc(e.message) + '</p>'; }
    btn.textContent = 'Embed watermark'; btn.disabled = false;
  });

  // ── Stake ───────────────────────────────────────────────────
  document.getElementById('stake-btn').addEventListener('click', async function() {
    var btn = this; btn.textContent = 'Working...'; btn.disabled = true;
    var nodeId = document.getElementById('stake-node').value.trim();
    var amount = document.getElementById('stake-amount').value.trim() || '10000';
    var div = document.getElementById('stake-result');
    if (!nodeId) { div.innerHTML = '<p class="err">Enter your node ID</p>'; btn.textContent='Stake';btn.disabled=false; return; }
    try {
      var r = await fetch('/api/stake', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({node_id:nodeId,amount:parseFloat(amount)})});
      var d = await r.json();
      if (d.ok) {
        div.innerHTML = '<div class="trace-result" style="border-color:#8b5cf6;margin-top:12px;">' +
          '<div class="trace-row"><span class="trace-key">Node</span><span class="trace-val">' + esc(d.node_id) + '</span></div>' +
          '<div class="trace-row"><span class="trace-key">Total staked</span><span class="trace-val" style="color:#22c55e;">' + d.total_stake + ' OAS</span></div>' +
          '<div class="trace-row"><span class="trace-key">Status</span><span class="trace-val">' + esc(d.status) + '</span></div>' +
          '</div>';
        toast('Staked ' + d.total_stake + ' OAS');
        loadStakes();
      } else { div.innerHTML = '<p class="err">' + esc(d.error) + '</p>'; toast(d.error, 'error'); }
    } catch(e) { div.innerHTML = '<p class="err">' + esc(e.message) + '</p>'; }
    btn.textContent = 'Stake'; btn.disabled = false;
  });

  // ═══════════════════════════════════════════════════════════
  // AHRP — Agent Handshake & Routing Protocol
  // ═══════════════════════════════════════════════════════════

  // ── AHRP Stats (auto-refresh) ──────────────────────────────
  async function loadAhrpStats() {
    var d = await api('/ahrp/v1/stats');
    if (!d || d.error) {
      document.getElementById('ahrp-stat-agents').textContent = '--';
      document.getElementById('ahrp-stat-caps').textContent = '--';
      document.getElementById('ahrp-stat-txs').textContent = '--';
      document.getElementById('ahrp-stat-vol').textContent = '--';
      return;
    }
    document.getElementById('ahrp-stat-agents').textContent = d.registered_agents || d.agents || 0;
    document.getElementById('ahrp-stat-caps').textContent = d.active_capabilities || d.capabilities || 0;
    document.getElementById('ahrp-stat-txs').textContent = d.completed_transactions || d.transactions || 0;
    document.getElementById('ahrp-stat-vol').textContent = d.total_volume || d.volume || 0;
  }

  // ── Announce Agent ─────────────────────────────────────────
  document.getElementById('ahrp-announce-btn').addEventListener('click', async function() {
    var btn = this; btn.textContent = 'Announcing...'; btn.disabled = true;
    var div = document.getElementById('ahrp-announce-result');
    var accessLevels = [];
    document.querySelectorAll('#ahrp-register .checkbox-group input:checked').forEach(function(cb) {
      accessLevels.push(cb.value);
    });
    var payload = {
      agent_id: document.getElementById('ahrp-agent-id').value.trim(),
      public_key: document.getElementById('ahrp-pub-key').value.trim(),
      reputation: parseFloat(document.getElementById('ahrp-reputation').value) || 10,
      stake: parseFloat(document.getElementById('ahrp-stake').value) || 100,
      capabilities: [{
        capability_id: document.getElementById('ahrp-cap-id').value.trim(),
        tags: document.getElementById('ahrp-cap-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean),
        description: document.getElementById('ahrp-cap-desc').value.trim(),
        price_floor: parseFloat(document.getElementById('ahrp-cap-price').value) || 1.0,
        origin_type: document.getElementById('ahrp-cap-origin').value,
        access_levels: accessLevels
      }]
    };
    var d = await postApi('/ahrp/v1/announce', payload);
    if (d && d.ok !== false && !d.error) {
      var caps = d.capabilities_indexed || d.capabilities || 0;
      var pending = d.pending_matches || 0;
      div.innerHTML = '<div class="trace-result" style="border-color:#6366f1;margin-top:12px;">' +
        '<div class="trace-row"><span class="trace-key">Status</span><span class="trace-val ok">Announced</span></div>' +
        '<div class="trace-row"><span class="trace-key">Capabilities indexed</span><span class="trace-val">' + esc(caps) + '</span></div>' +
        '<div class="trace-row"><span class="trace-key">Pending matches</span><span class="trace-val">' + esc(pending) + '</span></div>' +
        '</div>';
      loadAhrpStats();
    } else {
      div.innerHTML = '<p class="err">' + esc(d ? d.error : 'AHRP node not reachable') + '</p>';
    }
    btn.textContent = 'Announce Agent'; btn.disabled = false;
  });

  // ── Find Matches ───────────────────────────────────────────
  document.getElementById('ahrp-find-btn').addEventListener('click', async function() {
    var btn = this; btn.textContent = 'Searching...'; btn.disabled = true;
    var container = document.getElementById('ahrp-matches');
    var payload = {
      description: document.getElementById('ahrp-search-desc').value.trim(),
      tags: document.getElementById('ahrp-search-tags').value.split(',').map(function(t){return t.trim();}).filter(Boolean),
      min_reputation: parseFloat(document.getElementById('ahrp-search-rep').value) || 0,
      max_price: parseFloat(document.getElementById('ahrp-search-price').value) || 1000,
      required_access_level: document.getElementById('ahrp-search-access').value
    };
    var d = await postApi('/ahrp/v1/request', payload);
    if (d && d.error) {
      container.innerHTML = '<p class="err">' + esc(d.error) + '</p>';
    } else {
      var matches = d ? (d.matches || d.results || []) : [];
      if (!matches.length) {
        container.innerHTML = '<div class="empty-state">No matching capabilities found. Try broader criteria.</div>';
      } else {
        var html = '';
        matches.forEach(function(m) {
          var score = Math.round((m.score || 0) * 100);
          var origin = m.origin_type || 'unknown';
          var originClass = 'origin-' + origin;
          html += '<div class="match-card">' +
            '<div class="match-card-header">' +
              '<span class="match-agent">' + esc(m.agent_id || '') + ' / ' + esc(m.capability_id || '') + '</span>' +
              '<span class="origin-badge ' + originClass + '">' + esc(origin) + '</span>' +
            '</div>' +
            '<div class="match-score-bar"><div class="match-score-fill" style="width:' + score + '%;"></div></div>' +
            '<div class="match-details">' +
              '<span>Score: ' + score + '%</span>' +
              '<span>Floor: ' + esc(m.price_floor || 0) + ' OAS</span>' +
            '</div>' +
          '</div>';
        });
        container.innerHTML = html;
      }
    }
    btn.textContent = 'Find Matches'; btn.disabled = false;
  });

  // ── Transaction Pipeline State ─────────────────────────────
  var _txState = { step: 0, tx_id: '' };
  var _txSteps = ['request','offer','accept','deliver','confirm'];
  var _selectedRating = 5;

  function updatePipeline(step) {
    _txState.step = step;
    for (var i = 0; i < _txSteps.length; i++) {
      var el = document.getElementById('tx-step-' + _txSteps[i]);
      el.className = 'tx-step';
      if (i < step) el.className = 'tx-step done';
      else if (i === step) el.className = 'tx-step active';
    }
    for (var j = 1; j <= 4; j++) {
      var arrow = document.getElementById('tx-arrow-' + j);
      arrow.className = j <= step ? 'tx-arrow done' : 'tx-arrow';
    }
  }

  // Star rating interaction
  var stars = document.querySelectorAll('#star-rating span');
  stars.forEach(function(star) {
    star.addEventListener('click', function() {
      _selectedRating = parseInt(this.getAttribute('data-v'));
      stars.forEach(function(s) {
        s.className = parseInt(s.getAttribute('data-v')) <= _selectedRating ? 'lit' : '';
      });
    });
    star.addEventListener('mouseenter', function() {
      var v = parseInt(this.getAttribute('data-v'));
      stars.forEach(function(s) {
        s.className = parseInt(s.getAttribute('data-v')) <= v ? 'lit' : '';
      });
    });
  });
  document.getElementById('star-rating').addEventListener('mouseleave', function() {
    stars.forEach(function(s) {
      s.className = parseInt(s.getAttribute('data-v')) <= _selectedRating ? 'lit' : '';
    });
  });
  // Initialize stars
  stars.forEach(function(s) {
    s.className = parseInt(s.getAttribute('data-v')) <= _selectedRating ? 'lit' : '';
  });

  // ── Accept ─────────────────────────────────────────────────
  document.getElementById('tx-accept-btn').addEventListener('click', async function() {
    var btn = this; btn.textContent = 'Accepting...'; btn.disabled = true;
    var div = document.getElementById('tx-accept-result');
    updatePipeline(0); // request
    var payload = {
      buyer_id: document.getElementById('tx-buyer').value.trim(),
      seller_id: document.getElementById('tx-seller').value.trim(),
      capability_id: document.getElementById('tx-cap-id').value.trim(),
      price_oas: parseFloat(document.getElementById('tx-price').value) || 10
    };
    // Briefly show request step, then offer, then accept
    await new Promise(function(r){ setTimeout(r, 300); });
    updatePipeline(1); // offer
    await new Promise(function(r){ setTimeout(r, 300); });
    var d = await postApi('/ahrp/v1/accept', payload);
    if (d && !d.error) {
      _txState.tx_id = d.tx_id || d.transaction_id || '';
      document.getElementById('tx-deliver-id').value = _txState.tx_id;
      document.getElementById('tx-confirm-id').value = _txState.tx_id;
      updatePipeline(2); // accept done
      div.innerHTML = '<div class="trace-result" style="border-color:#22c55e;margin-top:12px;">' +
        '<div class="trace-row"><span class="trace-key">Transaction ID</span><span class="trace-val" style="color:#3b82f6;">' + esc(_txState.tx_id) + '</span></div>' +
        '<div class="trace-row"><span class="trace-key">State</span><span class="trace-val ok">Accepted</span></div>' +
        '</div>';
    } else {
      div.innerHTML = '<p class="err">' + esc(d ? d.error : 'Failed to connect') + '</p>';
      updatePipeline(0);
    }
    btn.textContent = 'Accept & Create Transaction'; btn.disabled = false;
  });

  // ── Deliver ────────────────────────────────────────────────
  document.getElementById('tx-deliver-btn').addEventListener('click', async function() {
    var btn = this; btn.textContent = 'Delivering...'; btn.disabled = true;
    var div = document.getElementById('tx-deliver-result');
    var txId = document.getElementById('tx-deliver-id').value.trim();
    var hash = document.getElementById('tx-content-hash').value.trim();
    var d = await postApi('/ahrp/v1/deliver', {tx_id: txId, content_hash: hash});
    if (d && !d.error) {
      updatePipeline(3); // deliver done
      div.innerHTML = '<div class="trace-result" style="border-color:#22c55e;margin-top:12px;">' +
        '<div class="trace-row"><span class="trace-key">State</span><span class="trace-val ok">Delivered</span></div>' +
        '<div class="trace-row"><span class="trace-key">Content hash</span><span class="trace-val">' + esc(trunc(hash, 24)) + '</span></div>' +
        '</div>';
    } else {
      div.innerHTML = '<p class="err">' + esc(d ? d.error : 'Failed') + '</p>';
    }
    btn.textContent = 'Deliver'; btn.disabled = false;
  });

  // ── Confirm ────────────────────────────────────────────────
  document.getElementById('tx-confirm-btn').addEventListener('click', async function() {
    var btn = this; btn.textContent = 'Confirming...'; btn.disabled = true;
    var div = document.getElementById('tx-confirm-result');
    var txId = document.getElementById('tx-confirm-id').value.trim();
    var d = await postApi('/ahrp/v1/confirm', {tx_id: txId, rating: _selectedRating});
    if (d && !d.error) {
      updatePipeline(4); // all done
      div.innerHTML = '<div class="trace-result" style="border-color:#f59e0b;margin-top:12px;">' +
        '<div class="trace-row"><span class="trace-key">State</span><span class="trace-val ok">' + esc(d.state || 'confirmed') + '</span></div>' +
        '<div class="trace-row"><span class="trace-key">Rating</span><span class="trace-val" style="color:#f59e0b;">' + _selectedRating + ' / 5</span></div>' +
        (d.settled_at ? '<div class="trace-row"><span class="trace-key">Settled at</span><span class="trace-val">' + esc(d.settled_at) + '</span></div>' : '') +
        '</div>';
      loadAhrpStats();
    } else {
      div.innerHTML = '<p class="err">' + esc(d ? d.error : 'Failed') + '</p>';
    }
    btn.textContent = 'Confirm & Settle'; btn.disabled = false;
  });

  // Initialize pipeline at step 0
  updatePipeline(0);

  // ── Auto refresh ────────────────────────────────────────────
  setInterval(loadStatus, 30000);
  setInterval(loadAhrpStats, 30000);

  // ── Init ─────────────────────────────────────────────────────
  loadStatus();
  loadAssets();
  loadPortfolio();
  loadTransactions();
  loadStakes();
  loadAhrpStats();

})();
</script>
</body>
</html>
"""


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

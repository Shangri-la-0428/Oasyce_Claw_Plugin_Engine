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

from oasyce_plugin.config import Config
from oasyce_plugin.storage.ledger import Ledger
from oasyce_plugin.fingerprint import FingerprintRegistry


# ── Shared state (set by OasyceGUI before server starts) ─────────────
_ledger: Optional[Ledger] = None
_config: Optional[Config] = None


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

        # ── SPA ──────────────────────────────────────────────────
        return _html_response(self, _INDEX_HTML)


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
input[type="text"] {
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
input[type="text"]:focus { border-color: #3b82f6; }
input[type="text"]::placeholder { color: #555; }

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
.input-row input { flex: 1; }

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
}
</style>
</head>
<body>

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

  <!-- Section 2: Your Assets -->
  <div class="card fade" id="assets-section">
    <h2>Your assets</h2>
    <input type="text" id="asset-search" placeholder="Search your assets...">
    <div id="assets-list" style="margin-top: 16px;"></div>
  </div>

  <!-- Section 3: Watermark Tracker -->
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

  <!-- Section 4: Network -->
  <div class="card fade" id="network-section">
    <h2>Network</h2>
    <div class="net-grid" id="net-info"></div>
    <div id="stakes-section" style="display:none;" class="sep">
      <h2 style="margin-bottom:12px;">Node operators</h2>
      <div id="stakes-list"></div>
    </div>
  </div>

  <!-- Footer -->
  <div class="footer fade">Oasyce Protocol v0.9.0 &middot; MIT License</div>

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
      html += '<div class="asset-item">' +
        '<div class="asset-id">' + esc(trunc(a.asset_id, 24)) + '</div>' +
        '<div class="asset-owner">' + esc(a.owner) + '</div>' +
        '<div class="asset-meta">' + tags + '<span class="time-ago">' + timeAgo(a.created_at) + '</span></div>' +
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

  // ── Init ─────────────────────────────────────────────────────
  loadStatus();
  loadAssets();
  loadStakes();

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

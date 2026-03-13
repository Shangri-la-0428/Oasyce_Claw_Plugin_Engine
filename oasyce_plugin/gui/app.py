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
body { background: #0a0a0a; color: #e0e0e0; font-family: system-ui, -apple-system, sans-serif; line-height: 1.5; }
a { color: #3b82f6; text-decoration: none; }
a:hover { text-decoration: underline; }
code, .mono { font-family: ui-monospace, 'SF Mono', 'Cascadia Code', monospace; }

/* Layout */
.container { max-width: 1200px; margin: 0 auto; padding: 0 16px; }
header { background: #111; border-bottom: 1px solid #333; padding: 12px 0; }
header .container { display: flex; align-items: center; justify-content: space-between; }
header h1 { font-size: 18px; font-weight: 600; letter-spacing: 0.5px; }
nav { display: flex; gap: 4px; }
nav button { background: none; border: 1px solid #333; color: #999; padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 13px; }
nav button:hover { color: #e0e0e0; border-color: #555; }
nav button.active { color: #e0e0e0; border-color: #e0e0e0; }
main { padding: 20px 0; }

/* Cards */
.card { background: #1a1a1a; border: 1px solid #333; border-radius: 4px; padding: 16px; margin-bottom: 12px; }
.card h2 { font-size: 14px; color: #999; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }

/* Stats row */
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
.stat { background: #1a1a1a; border: 1px solid #333; border-radius: 4px; padding: 14px; }
.stat .label { font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 1px; }
.stat .value { font-size: 22px; font-weight: 600; margin-top: 4px; font-family: ui-monospace, monospace; }
.stat .value.green { color: #22c55e; }
.stat .value.blue { color: #3b82f6; }
.stat .value.amber { color: #f59e0b; }

/* Tables */
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; color: #999; font-weight: 500; padding: 8px 10px; border-bottom: 1px solid #333; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
td { padding: 8px 10px; border-bottom: 1px solid #222; }
tr:nth-child(odd) td { background: #1a1a1a; }
tr:nth-child(even) td { background: #222; }
tr.clickable { cursor: pointer; }
tr.clickable:hover td { background: #2a2a2a; }
.truncate { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; vertical-align: middle; }

/* Forms */
.form-row { display: flex; gap: 8px; margin-bottom: 12px; }
input[type="text"] { background: #111; border: 1px solid #333; color: #e0e0e0; padding: 8px 12px; border-radius: 4px; font-size: 13px; font-family: ui-monospace, monospace; flex: 1; }
input[type="text"]::placeholder { color: #555; }
button.btn { background: #333; border: 1px solid #555; color: #e0e0e0; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-size: 13px; }
button.btn:hover { background: #444; }
button.btn-blue { background: #1e3a5f; border-color: #3b82f6; }
button.btn-blue:hover { background: #274b7a; }

/* Detail panel */
.detail { background: #111; border: 1px solid #333; border-radius: 4px; padding: 16px; margin-top: 12px; }
.detail pre { white-space: pre-wrap; word-break: break-all; font-size: 12px; }
.kv { display: grid; grid-template-columns: 140px 1fr; gap: 4px 12px; font-size: 13px; }
.kv .k { color: #999; }
.kv .v { font-family: ui-monospace, monospace; word-break: break-all; }

/* Tags */
.tag { display: inline-block; background: #222; border: 1px solid #444; border-radius: 3px; padding: 1px 6px; font-size: 11px; margin-right: 4px; }

/* Status */
.status-ok { color: #22c55e; }
.status-err { color: #ef4444; }

/* Section visibility */
.section { display: none; }
.section.active { display: block; }

/* Responsive */
@media (max-width: 640px) {
  nav { flex-wrap: wrap; }
  nav button { padding: 4px 10px; font-size: 12px; }
  .stats { grid-template-columns: 1fr 1fr; }
  .kv { grid-template-columns: 100px 1fr; }
  .truncate { max-width: 100px; }
}
</style>
</head>
<body>

<header>
  <div class="container">
    <h1>OASYCE</h1>
    <nav id="nav">
      <button data-section="dashboard" class="active">Dashboard</button>
      <button data-section="chain">Chain</button>
      <button data-section="assets">Assets</button>
      <button data-section="fingerprints">Fingerprints</button>
      <button data-section="staking">Staking</button>
    </nav>
  </div>
</header>

<main class="container">

  <!-- Dashboard -->
  <div id="s-dashboard" class="section active">
    <div id="node-info" class="card">
      <h2>Node Status</h2>
      <div class="kv" id="node-kv"></div>
    </div>
    <div class="stats" id="stats-grid"></div>
  </div>

  <!-- Chain Explorer -->
  <div id="s-chain" class="section">
    <div class="card">
      <h2>Recent Blocks</h2>
      <table><thead><tr><th>#</th><th>Hash</th><th>Txs</th><th>Timestamp</th></tr></thead><tbody id="blocks-tbody"></tbody></table>
    </div>
    <div id="block-detail" style="display:none" class="detail"></div>
  </div>

  <!-- Assets -->
  <div id="s-assets" class="section">
    <div class="card">
      <h2>Registered Assets</h2>
      <div class="form-row">
        <input type="text" id="asset-search" placeholder="Search by asset ID or tag...">
      </div>
      <table><thead><tr><th>Asset ID</th><th>Owner</th><th>Tags</th><th>Created</th></tr></thead><tbody id="assets-tbody"></tbody></table>
    </div>
  </div>

  <!-- Fingerprints -->
  <div id="s-fingerprints" class="section">
    <div class="card">
      <h2>Trace Fingerprint</h2>
      <div class="form-row">
        <input type="text" id="fp-input" placeholder="Paste fingerprint hex...">
        <button class="btn btn-blue" id="fp-trace-btn">Trace</button>
      </div>
      <div id="fp-trace-result"></div>
    </div>
    <div class="card">
      <h2>Distributions by Asset</h2>
      <div class="form-row">
        <input type="text" id="fp-asset-input" placeholder="Asset ID...">
        <button class="btn btn-blue" id="fp-list-btn">List</button>
      </div>
      <table><thead><tr><th>ID</th><th>Caller</th><th>Fingerprint</th><th>Timestamp</th></tr></thead><tbody id="fp-tbody"></tbody></table>
    </div>
  </div>

  <!-- Staking -->
  <div id="s-staking" class="section">
    <div class="card">
      <h2>Validator Stakes</h2>
      <table><thead><tr><th>Validator ID</th><th>Total Staked (OAS)</th></tr></thead><tbody id="stakes-tbody"></tbody></table>
    </div>
  </div>

</main>

<script>
(function() {
  // ── Navigation ───────────────────────────────────────────────
  const nav = document.getElementById('nav');
  const sections = document.querySelectorAll('.section');
  const buttons = nav.querySelectorAll('button');

  function switchSection(name) {
    sections.forEach(s => s.classList.remove('active'));
    buttons.forEach(b => b.classList.remove('active'));
    document.getElementById('s-' + name).classList.add('active');
    nav.querySelector('[data-section="'+name+'"]').classList.add('active');
    if (name === 'dashboard') loadDashboard();
    if (name === 'chain') loadBlocks();
    if (name === 'assets') loadAssets();
    if (name === 'staking') loadStakes();
  }

  nav.addEventListener('click', function(e) {
    if (e.target.tagName === 'BUTTON' && e.target.dataset.section) {
      switchSection(e.target.dataset.section);
    }
  });

  // ── Helpers ──────────────────────────────────────────────────
  function esc(s) {
    if (s == null) return '';
    var d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }
  function trunc(s, n) { n = n || 16; return s && s.length > n ? s.slice(0, n) + '...' : (s || ''); }

  async function api(path) {
    var r = await fetch(path);
    return r.json();
  }

  // ── Dashboard ────────────────────────────────────────────────
  async function loadDashboard() {
    var d = await api('/api/status');
    var kv = document.getElementById('node-kv');
    kv.innerHTML =
      '<span class="k">Node ID</span><span class="v">' + esc(d.node_id) + '</span>' +
      '<span class="k">Host</span><span class="v">' + esc(d.host) + ':' + esc(d.port) + '</span>' +
      '<span class="k">Chain Height</span><span class="v">' + esc(d.chain_height) + '</span>' +
      '<span class="k">Status</span><span class="v status-ok">Online</span>';

    var sg = document.getElementById('stats-grid');
    sg.innerHTML =
      '<div class="stat"><div class="label">Total Assets</div><div class="value green">' + d.total_assets + '</div></div>' +
      '<div class="stat"><div class="label">Total Blocks</div><div class="value blue">' + d.total_blocks + '</div></div>' +
      '<div class="stat"><div class="label">Distributions</div><div class="value amber">' + d.total_distributions + '</div></div>';
  }

  // ── Chain ────────────────────────────────────────────────────
  async function loadBlocks() {
    var blocks = await api('/api/blocks?limit=20');
    var tb = document.getElementById('blocks-tbody');
    tb.innerHTML = '';
    blocks.forEach(function(b) {
      var tr = document.createElement('tr');
      tr.className = 'clickable';
      tr.innerHTML =
        '<td>' + b.block_number + '</td>' +
        '<td><span class="mono truncate">' + esc(trunc(b.block_hash, 16)) + '</span></td>' +
        '<td>' + b.tx_count + '</td>' +
        '<td class="mono">' + esc(b.timestamp) + '</td>';
      tr.addEventListener('click', function() { loadBlockDetail(b.block_number); });
      tb.appendChild(tr);
    });
    document.getElementById('block-detail').style.display = 'none';
  }

  async function loadBlockDetail(n) {
    var b = await api('/api/block/' + n);
    if (b.error) return;
    var det = document.getElementById('block-detail');
    det.style.display = 'block';
    var html = '<h3 style="margin-bottom:10px;">Block #' + b.block_number + '</h3>' +
      '<div class="kv">' +
      '<span class="k">Hash</span><span class="v mono">' + esc(b.block_hash) + '</span>' +
      '<span class="k">Prev Hash</span><span class="v mono">' + esc(b.prev_hash) + '</span>' +
      '<span class="k">Merkle Root</span><span class="v mono">' + esc(b.merkle_root) + '</span>' +
      '<span class="k">Timestamp</span><span class="v">' + esc(b.timestamp) + '</span>' +
      '<span class="k">Tx Count</span><span class="v">' + b.tx_count + '</span>' +
      '</div>';

    if (b.transactions && b.transactions.length) {
      html += '<h4 style="margin:12px 0 8px;">Transactions</h4><table><thead><tr><th>TX ID</th><th>Type</th><th>Asset</th><th>Amount</th></tr></thead><tbody>';
      b.transactions.forEach(function(tx) {
        html += '<tr>' +
          '<td><span class="mono truncate">' + esc(trunc(tx.tx_id, 16)) + '</span></td>' +
          '<td>' + esc(tx.tx_type) + '</td>' +
          '<td><span class="mono truncate">' + esc(trunc(tx.asset_id, 16)) + '</span></td>' +
          '<td>' + (tx.amount != null ? tx.amount : '-') + '</td></tr>';
      });
      html += '</tbody></table>';
    }
    det.innerHTML = html;
  }

  // ── Assets ───────────────────────────────────────────────────
  var _allAssets = [];
  async function loadAssets() {
    _allAssets = await api('/api/assets');
    renderAssets(_allAssets);
  }
  function renderAssets(list) {
    var tb = document.getElementById('assets-tbody');
    tb.innerHTML = '';
    list.forEach(function(a) {
      var tags = (a.tags || []).map(function(t) { return '<span class="tag">' + esc(t) + '</span>'; }).join('');
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td><span class="mono truncate">' + esc(trunc(a.asset_id, 20)) + '</span></td>' +
        '<td>' + esc(a.owner) + '</td>' +
        '<td>' + tags + '</td>' +
        '<td class="mono">' + esc(a.created_at) + '</td>';
      tb.appendChild(tr);
    });
  }
  document.getElementById('asset-search').addEventListener('input', function(e) {
    var q = e.target.value.toLowerCase();
    if (!q) { renderAssets(_allAssets); return; }
    renderAssets(_allAssets.filter(function(a) {
      return (a.asset_id || '').toLowerCase().indexOf(q) !== -1 ||
        (a.tags || []).some(function(t) { return t.toLowerCase().indexOf(q) !== -1; });
    }));
  });

  // ── Fingerprints ─────────────────────────────────────────────
  document.getElementById('fp-trace-btn').addEventListener('click', async function() {
    var fp = document.getElementById('fp-input').value.trim();
    if (!fp) return;
    var r = await api('/api/trace?fp=' + encodeURIComponent(fp));
    var div = document.getElementById('fp-trace-result');
    if (r.error) {
      div.innerHTML = '<p class="status-err" style="margin-top:8px;">Not found</p>';
    } else {
      div.innerHTML = '<div class="detail" style="margin-top:8px;"><div class="kv">' +
        '<span class="k">Asset ID</span><span class="v mono">' + esc(r.asset_id) + '</span>' +
        '<span class="k">Caller ID</span><span class="v mono">' + esc(r.caller_id) + '</span>' +
        '<span class="k">Fingerprint</span><span class="v mono">' + esc(r.fingerprint) + '</span>' +
        '<span class="k">Timestamp</span><span class="v">' + esc(r.timestamp) + '</span>' +
        '<span class="k">Created</span><span class="v">' + esc(r.created_at) + '</span>' +
        '</div></div>';
    }
  });

  document.getElementById('fp-list-btn').addEventListener('click', async function() {
    var aid = document.getElementById('fp-asset-input').value.trim();
    if (!aid) return;
    var list = await api('/api/fingerprints?asset_id=' + encodeURIComponent(aid));
    var tb = document.getElementById('fp-tbody');
    tb.innerHTML = '';
    list.forEach(function(r) {
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td>' + r.id + '</td>' +
        '<td class="mono">' + esc(trunc(r.caller_id, 20)) + '</td>' +
        '<td><span class="mono truncate">' + esc(trunc(r.fingerprint, 16)) + '</span></td>' +
        '<td class="mono">' + esc(r.timestamp) + '</td>';
      tb.appendChild(tr);
    });
  });

  // ── Staking ──────────────────────────────────────────────────
  async function loadStakes() {
    var list = await api('/api/stakes');
    var tb = document.getElementById('stakes-tbody');
    tb.innerHTML = '';
    list.forEach(function(s) {
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td class="mono">' + esc(s.validator_id) + '</td>' +
        '<td>' + s.total + '</td>';
      tb.appendChild(tr);
    });
  }

  // ── Init ─────────────────────────────────────────────────────
  loadDashboard();
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

        server = HTTPServer((self._host, self._port), _Handler)
        print(f"Oasyce Dashboard running on http://127.0.0.1:{self._port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down dashboard.")
            server.server_close()


if __name__ == "__main__":
    OasyceGUI().run()

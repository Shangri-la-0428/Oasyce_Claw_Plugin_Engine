"""
Oasyce Block Explorer — zero-dependency web UI served via Python stdlib.

Serves on port 8421. Provides a network-wide view of blocks, transactions,
assets, validators, and node peers. Reads all data from the local ledger.
"""

from __future__ import annotations

import json
import re
import socket
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, parse_qs

from oasyce_plugin.config import Config
from oasyce_plugin.storage.ledger import Ledger


# ── Shared state (set by OasyceExplorer before server starts) ────────
_ledger: Optional[Ledger] = None
_config: Optional[Config] = None
_staking: Any = None


def _get_staking():
    global _staking
    if _staking is None:
        from oasyce_plugin.services.staking import StakingEngine
        _staking = StakingEngine()
    return _staking


def _json(handler: BaseHTTPRequestHandler, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _html(handler: BaseHTTPRequestHandler, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


# ── Data helpers ─────────────────────────────────────────────────────

def _chain_stats() -> Dict[str, Any]:
    assert _ledger and _config
    height = _ledger.get_chain_height()
    total_assets = _ledger._conn.execute("SELECT COUNT(*) AS c FROM assets").fetchone()["c"]
    total_tx = _ledger._conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"]
    latest = _ledger.get_latest_block()
    node_id = (_config.public_key or "unknown")[:16]

    # Peer count from peers.json
    import os
    peers_path = os.path.join(_config.data_dir, "peers.json")
    peer_count = 0
    if os.path.exists(peers_path):
        try:
            with open(peers_path) as f:
                peer_count = len(json.load(f))
        except Exception:
            pass

    return {
        "node_id": node_id,
        "chain_height": height,
        "total_assets": total_assets,
        "total_transactions": total_tx,
        "latest_block": latest,
        "peer_count": peer_count,
    }


def _blocks_page(page: int = 1, per_page: int = 20) -> List[Dict[str, Any]]:
    assert _ledger
    offset = (page - 1) * per_page
    rows = _ledger._conn.execute(
        "SELECT * FROM blocks ORDER BY block_number DESC LIMIT ? OFFSET ?",
        (per_page, offset),
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


def _block_detail(height: int) -> Optional[Dict[str, Any]]:
    assert _ledger
    return _ledger.get_block(height, include_tx=True)


def _tx_detail(tx_id: str) -> Optional[Dict[str, Any]]:
    assert _ledger
    row = _ledger._conn.execute(
        "SELECT * FROM transactions WHERE tx_id = ?", (tx_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    if d.get("metadata"):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d


def _all_assets() -> List[Dict[str, Any]]:
    assert _ledger
    rows = _ledger._conn.execute(
        "SELECT asset_id, owner, created_at FROM assets ORDER BY created_at DESC"
    ).fetchall()
    results = []
    for r in rows:
        results.append({
            "asset_id": r["asset_id"],
            "owner": r["owner"],
            "created_at": r["created_at"],
        })
    return results


def _all_validators() -> List[Dict[str, Any]]:
    se = _get_staking()
    result = []
    for vid, v in se.validators.items():
        result.append({
            "node_id": v.node_id,
            "public_key": v.public_key,
            "stake": v.stake,
            "status": v.status.value if hasattr(v.status, "value") else str(v.status),
            "blocks_produced": v.blocks_produced,
            "rewards_earned": v.rewards_earned,
            "slash_count": v.slash_count,
        })
    # Also include ledger-only stakes
    assert _ledger
    rows = _ledger._conn.execute(
        "SELECT validator_id, SUM(amount) AS total FROM stakes GROUP BY validator_id"
    ).fetchall()
    seen = {v["node_id"] for v in result}
    for r in rows:
        if r["validator_id"] not in seen:
            result.append({
                "node_id": r["validator_id"],
                "public_key": "",
                "stake": r["total"],
                "status": "active",
                "blocks_produced": 0,
                "rewards_earned": 0,
                "slash_count": 0,
            })
    return result


def _peer_list() -> List[Dict[str, Any]]:
    assert _config
    import os
    peers_path = os.path.join(_config.data_dir, "peers.json")
    if not os.path.exists(peers_path):
        return []
    try:
        with open(peers_path) as f:
            return json.load(f)
    except Exception:
        return []


def _mempool() -> List[Dict[str, Any]]:
    assert _ledger
    rows = _ledger._conn.execute(
        "SELECT * FROM transactions WHERE block_number IS NULL ORDER BY created_at DESC"
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("metadata"):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


# ── HTML Templates ───────────────────────────────────────────────────

_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
html { background: #0a0a0a; color: #e8e8e8; font-family: system-ui, -apple-system, sans-serif; }
a { color: #3b82f6; text-decoration: none; }
a:hover { text-decoration: underline; }

.wrap { max-width: 900px; margin: 0 auto; padding: 32px 20px 64px; }

/* Header */
.explorer-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 0; border-bottom: 1px solid #252525; margin-bottom: 32px;
}
.explorer-header h1 { font-size: 22px; font-weight: 700; color: #fff; letter-spacing: 0.5px; }
.explorer-header nav a { margin-left: 20px; font-size: 14px; color: #999; }
.explorer-header nav a:hover { color: #fff; }

/* Stats grid */
.stats-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 32px;
}
@media (max-width: 600px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
.stat-card {
  background: #141414; border: 1px solid #252525; border-radius: 12px;
  padding: 20px 16px; text-align: center;
}
.stat-num {
  font-size: 32px; font-weight: 700; line-height: 1.1;
  font-family: ui-monospace, 'SF Mono', monospace;
}
.stat-num.green { color: #22c55e; }
.stat-num.blue { color: #3b82f6; }
.stat-num.amber { color: #f59e0b; }
.stat-num.white { color: #fff; }
.stat-label { font-size: 13px; color: #888; margin-top: 4px; }

/* Card */
.card {
  background: #141414; border: 1px solid #252525; border-radius: 12px;
  padding: 24px; margin-bottom: 24px;
}
.card h2 { font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #fff; }

/* Table */
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; color: #888; font-weight: 500; padding: 8px 12px; border-bottom: 1px solid #252525; }
td { padding: 10px 12px; border-bottom: 1px solid #1a1a1a; color: #ccc; }
tr:hover td { background: #1a1a1a; }
.mono { font-family: ui-monospace, 'SF Mono', monospace; font-size: 13px; }
.hash { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: inline-block; }

/* Detail */
.detail-row { display: flex; padding: 10px 0; border-bottom: 1px solid #1a1a1a; }
.detail-label { width: 160px; color: #888; font-size: 14px; flex-shrink: 0; }
.detail-value { color: #e8e8e8; font-size: 14px; word-break: break-all; }

/* Badge */
.badge {
  display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
}
.badge-green { background: #22c55e22; color: #22c55e; }
.badge-amber { background: #f59e0b22; color: #f59e0b; }
.badge-red { background: #ef444422; color: #ef4444; }
.badge-gray { background: #88888822; color: #888; }

/* Pagination */
.pagination { display: flex; gap: 8px; margin-top: 16px; justify-content: center; }
.pagination a {
  padding: 6px 14px; background: #1a1a1a; border: 1px solid #333;
  border-radius: 8px; color: #ccc; font-size: 14px;
}
.pagination a:hover { background: #252525; text-decoration: none; }

/* Animation */
@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.fade { animation: fadeIn 0.3s ease both; }
"""


def _page_shell(title: str, body: str, refresh: bool = True) -> str:
    refresh_tag = '<meta http-equiv="refresh" content="10">' if refresh else ""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{refresh_tag}
<title>{title} — Oasyce Explorer</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="explorer-header">
    <h1>Oasyce Explorer</h1>
    <nav>
      <a href="/">Overview</a>
      <a href="/blocks">Blocks</a>
      <a href="/assets">Assets</a>
      <a href="/validators">Validators</a>
      <a href="/nodes">Nodes</a>
    </nav>
  </header>
  {body}
</div>
</body>
</html>"""


def _render_overview() -> str:
    stats = _chain_stats()
    latest = stats["latest_block"]
    latest_hash = latest["block_hash"][:16] + "..." if latest else "—"
    latest_num = latest["block_number"] if latest else "—"

    body = f"""\
<div class="stats-grid fade">
  <div class="stat-card">
    <div class="stat-num green">{stats['chain_height']}</div>
    <div class="stat-label">Chain Height</div>
  </div>
  <div class="stat-card">
    <div class="stat-num blue">{stats['total_transactions']}</div>
    <div class="stat-label">Transactions</div>
  </div>
  <div class="stat-card">
    <div class="stat-num amber">{stats['total_assets']}</div>
    <div class="stat-label">Assets</div>
  </div>
  <div class="stat-card">
    <div class="stat-num white">{stats['peer_count']}</div>
    <div class="stat-label">Peers</div>
  </div>
</div>

<div class="card fade">
  <h2>Latest Block</h2>
  <div class="detail-row">
    <div class="detail-label">Height</div>
    <div class="detail-value"><a href="/blocks/{latest_num}">#{latest_num}</a></div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Hash</div>
    <div class="detail-value mono">{latest_hash}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Node ID</div>
    <div class="detail-value mono">{stats['node_id']}</div>
  </div>
</div>

<div class="card fade">
  <h2>Recent Blocks</h2>
  {_render_blocks_table(_blocks_page(1, 5))}
  <div style="text-align:center; margin-top:12px;">
    <a href="/blocks">View all blocks &rarr;</a>
  </div>
</div>"""
    return _page_shell("Overview", body)


def _render_blocks_table(blocks: List[Dict[str, Any]]) -> str:
    if not blocks:
        return '<p style="color:#888;">No blocks yet.</p>'
    rows = ""
    for b in blocks:
        h = b["block_hash"][:16] + "..."
        rows += f"""\
<tr>
  <td><a href="/blocks/{b['block_number']}">#{b['block_number']}</a></td>
  <td class="mono"><span class="hash">{h}</span></td>
  <td>{b['tx_count']}</td>
  <td>{b['timestamp']}</td>
</tr>"""
    return f"""\
<table>
  <thead><tr><th>Height</th><th>Hash</th><th>Txs</th><th>Time</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _render_blocks_page(page: int) -> str:
    blocks = _blocks_page(page, 20)
    assert _ledger
    total = _ledger.get_chain_height()
    total_pages = max(1, (total + 19) // 20)

    pagination = '<div class="pagination">'
    if page > 1:
        pagination += f'<a href="/blocks?page={page - 1}">&laquo; Prev</a>'
    pagination += f'<span style="padding:6px 14px;color:#888;">Page {page} / {total_pages}</span>'
    if page < total_pages:
        pagination += f'<a href="/blocks?page={page + 1}">Next &raquo;</a>'
    pagination += "</div>"

    body = f"""\
<div class="card fade">
  <h2>Blocks</h2>
  {_render_blocks_table(blocks)}
  {pagination}
</div>"""
    return _page_shell("Blocks", body)


def _render_block_detail(height: int) -> Optional[str]:
    block = _block_detail(height)
    if block is None:
        return None

    tx_rows = ""
    txs = block.get("transactions", [])
    if txs:
        for tx in txs:
            tx_rows += f"""\
<tr>
  <td><a href="/tx/{tx['tx_id']}" class="mono"><span class="hash">{tx['tx_id'][:16]}...</span></a></td>
  <td><span class="badge badge-green">{tx['tx_type']}</span></td>
  <td>{tx.get('from_addr', '—')}</td>
  <td>{tx.get('amount', '—')}</td>
</tr>"""
    tx_table = f"""\
<table>
  <thead><tr><th>TX ID</th><th>Type</th><th>From</th><th>Amount</th></tr></thead>
  <tbody>{tx_rows}</tbody>
</table>""" if tx_rows else '<p style="color:#888;">No transactions in this block.</p>'

    body = f"""\
<div class="card fade">
  <h2>Block #{height}</h2>
  <div class="detail-row">
    <div class="detail-label">Block Hash</div>
    <div class="detail-value mono">{block.get('block_hash', '—')}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Previous Hash</div>
    <div class="detail-value mono">{block.get('prev_hash', '—')}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Merkle Root</div>
    <div class="detail-value mono">{block.get('merkle_root', '—')}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Timestamp</div>
    <div class="detail-value">{block.get('timestamp', '—')}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">TX Count</div>
    <div class="detail-value">{block.get('tx_count', 0)}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Nonce</div>
    <div class="detail-value mono">{block.get('nonce', '—')}</div>
  </div>
</div>

<div class="card fade">
  <h2>Transactions</h2>
  {tx_table}
</div>"""
    return _page_shell(f"Block #{height}", body)


def _render_tx_detail(tx_id: str) -> Optional[str]:
    tx = _tx_detail(tx_id)
    if tx is None:
        return None

    meta = tx.get("metadata", "")
    if isinstance(meta, dict):
        meta = json.dumps(meta, indent=2)

    body = f"""\
<div class="card fade">
  <h2>Transaction</h2>
  <div class="detail-row">
    <div class="detail-label">TX ID</div>
    <div class="detail-value mono">{tx['tx_id']}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Type</div>
    <div class="detail-value"><span class="badge badge-green">{tx.get('tx_type', '—')}</span></div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Asset</div>
    <div class="detail-value"><a href="/assets">{tx.get('asset_id', '—')}</a></div>
  </div>
  <div class="detail-row">
    <div class="detail-label">From</div>
    <div class="detail-value mono">{tx.get('from_addr', '—')}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">To</div>
    <div class="detail-value mono">{tx.get('to_addr', '—')}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Amount</div>
    <div class="detail-value">{tx.get('amount', '—')} OAS</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Block</div>
    <div class="detail-value">{tx.get('block_number', 'pending')}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Time</div>
    <div class="detail-value">{tx.get('created_at', '—')}</div>
  </div>
  <div class="detail-row">
    <div class="detail-label">Metadata</div>
    <div class="detail-value mono" style="white-space:pre-wrap;">{meta or '—'}</div>
  </div>
</div>"""
    return _page_shell("Transaction", body)


def _render_assets_page() -> str:
    assets = _all_assets()
    rows = ""
    for a in assets:
        rows += f"""\
<tr>
  <td class="mono"><span class="hash">{a['asset_id'][:20]}...</span></td>
  <td>{a['owner']}</td>
  <td>{a['created_at']}</td>
</tr>"""
    table = f"""\
<table>
  <thead><tr><th>Asset ID</th><th>Owner</th><th>Created</th></tr></thead>
  <tbody>{rows}</tbody>
</table>""" if rows else '<p style="color:#888;">No assets registered.</p>'

    body = f"""\
<div class="card fade">
  <h2>Registered Assets ({len(assets)})</h2>
  {table}
</div>"""
    return _page_shell("Assets", body)


def _render_validators_page() -> str:
    validators = _all_validators()

    rows = ""
    for v in validators:
        status = v["status"]
        badge_cls = {
            "active": "badge-green", "unbonding": "badge-amber",
            "slashed": "badge-red", "exited": "badge-gray",
        }.get(status, "badge-gray")
        rows += f"""\
<tr>
  <td class="mono"><span class="hash">{v['node_id'][:16]}...</span></td>
  <td>{v['stake']:,.2f} OAS</td>
  <td><span class="badge {badge_cls}">{status}</span></td>
  <td>{v['blocks_produced']}</td>
  <td>{v['rewards_earned']:,.2f}</td>
  <td>{v['slash_count']}</td>
</tr>"""
    table = f"""\
<table>
  <thead><tr><th>Node ID</th><th>Stake</th><th>Status</th><th>Blocks</th><th>Rewards</th><th>Slashes</th></tr></thead>
  <tbody>{rows}</tbody>
</table>""" if rows else '<p style="color:#888;">No validators registered.</p>'

    # Network stats
    se = _get_staking()
    ns = se.network_stats()

    body = f"""\
<div class="stats-grid fade" style="grid-template-columns: repeat(3, 1fr);">
  <div class="stat-card">
    <div class="stat-num green">{ns['active_validators']}</div>
    <div class="stat-label">Active Validators</div>
  </div>
  <div class="stat-card">
    <div class="stat-num blue">{ns['total_staked']:,.0f}</div>
    <div class="stat-label">Total Staked (OAS)</div>
  </div>
  <div class="stat-card">
    <div class="stat-num amber">{ns['total_rewards_distributed']:,.2f}</div>
    <div class="stat-label">Rewards Distributed</div>
  </div>
</div>

<div class="card fade">
  <h2>Validators ({ns['total_validators']})</h2>
  {table}
</div>"""
    return _page_shell("Validators", body)


def _render_nodes_page() -> str:
    peers = _peer_list()
    rows = ""
    for p in peers:
        nid = p.get("node_id", "—")
        host = p.get("host", "—")
        port = p.get("port", "—")
        rows += f"""\
<tr>
  <td class="mono"><span class="hash">{nid[:16]}{'...' if len(str(nid)) > 16 else ''}</span></td>
  <td>{host}</td>
  <td>{port}</td>
</tr>"""
    table = f"""\
<table>
  <thead><tr><th>Node ID</th><th>Host</th><th>Port</th></tr></thead>
  <tbody>{rows}</tbody>
</table>""" if rows else '<p style="color:#888;">No peers discovered yet.</p>'

    body = f"""\
<div class="card fade">
  <h2>Known Nodes ({len(peers)})</h2>
  {table}
</div>"""
    return _page_shell("Nodes", body)


# ── Request handler ──────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        # ── JSON API ─────────────────────────────────────────
        if path == "/api/chain":
            stats = _chain_stats()
            return _json(self, stats)

        if path == "/api/mempool":
            return _json(self, _mempool())

        # ── HTML pages ───────────────────────────────────────
        if path == "/":
            return _html(self, _render_overview())

        if path == "/blocks":
            page = int(qs.get("page", ["1"])[0])
            return _html(self, _render_blocks_page(page))

        m = re.match(r"^/blocks/(\d+)$", path)
        if m:
            result = _render_block_detail(int(m.group(1)))
            if result is None:
                self.send_error(404, "Block not found")
                return
            return _html(self, result)

        m = re.match(r"^/tx/(.+)$", path)
        if m:
            result = _render_tx_detail(m.group(1))
            if result is None:
                self.send_error(404, "Transaction not found")
                return
            return _html(self, result)

        if path == "/nodes":
            return _html(self, _render_nodes_page())

        if path == "/assets":
            return _html(self, _render_assets_page())

        if path == "/validators":
            return _html(self, _render_validators_page())

        self.send_error(404, "Not found")


# ── Server ───────────────────────────────────────────────────────────

class OasyceExplorer:
    """Zero-dependency block explorer for Oasyce nodes."""

    def __init__(
        self,
        config: Optional[Config] = None,
        ledger: Optional[Ledger] = None,
        host: str = "0.0.0.0",
        port: int = 8421,
    ):
        self._config = config or Config.from_env()
        self._ledger = ledger if ledger is not None else Ledger(self._config.db_path)
        self._host = host
        self._port = port

    def run(self) -> None:
        global _ledger, _config
        _ledger = self._ledger
        _config = self._config

        class _ReusableHTTPServer(HTTPServer):
            allow_reuse_address = True
            def server_bind(self):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                super().server_bind()

        server = _ReusableHTTPServer((self._host, self._port), _Handler)
        print(f"Oasyce Explorer running on http://127.0.0.1:{self._port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down explorer.")
            server.server_close()


if __name__ == "__main__":
    OasyceExplorer().run()

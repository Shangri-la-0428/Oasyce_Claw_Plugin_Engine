"""
HTTP JSON transport for block synchronization.

Provides:
  HTTPPeerTransport — client that talks to a remote sync server
  SyncServer        — lightweight HTTP server exposing sync endpoints

Endpoints:
  GET  /sync/info    → peer info (chain_id, height, genesis_hash)
  POST /sync/blocks  → fetch blocks by height range

Zero external dependencies — uses only stdlib (http.server, urllib).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from urllib.request import Request, urlopen
from urllib.error import URLError

from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    GetBlocksRequest,
    GetBlocksResponse,
    GetPeerInfoResponse,
    make_genesis_block,
)

if TYPE_CHECKING:
    from oasyce_plugin.consensus import ConsensusEngine


# ── Client ────────────────────────────────────────────────────────


class HTTPPeerTransport:
    """PeerTransport implementation over HTTP JSON.

    Satisfies the PeerTransport protocol from block_sync.py.
    """

    def __init__(self, base_url: str, timeout: float = 10.0):
        # Normalize: strip trailing slash
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    @property
    def address(self) -> str:
        return self._base_url

    def get_peer_info(self) -> GetPeerInfoResponse:
        data = self._get("/sync/info")
        return GetPeerInfoResponse.from_dict(data)

    def get_blocks(self, request: GetBlocksRequest) -> GetBlocksResponse:
        data = self._post("/sync/blocks", request.to_dict())
        return GetBlocksResponse.from_dict(data)

    # ── internal ──

    def _get(self, path: str) -> Dict[str, Any]:
        url = self._base_url + path
        req = Request(url, method="GET")
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode())

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = self._base_url + path
        payload = json.dumps(body).encode()
        req = Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        with urlopen(req, timeout=self._timeout) as resp:
            return json.loads(resp.read().decode())

    def __repr__(self) -> str:
        return f"HTTPPeerTransport({self._base_url!r})"


# ── Server ────────────────────────────────────────────────────────


class SyncServer:
    """Lightweight HTTP server that exposes block sync endpoints.

    Usage:
        server = SyncServer(engine, host="0.0.0.0", port=9528)
        server.start()       # non-blocking (runs in background thread)
        ...
        server.stop()
    """

    _DEFAULT_DB_PATH = os.path.join("~", ".oasyce", "blocks.db")

    def __init__(self, engine: ConsensusEngine,
                 host: str = "0.0.0.0", port: int = 9528,
                 block_store: Optional[List[Block]] = None,
                 db_path: Optional[str] = None):
        self._engine = engine
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        # Persistent block store backed by SQLite.
        # If db_path is explicitly ":memory:", use in-memory DB.
        if db_path is None:
            db_path = os.path.expanduser(self._DEFAULT_DB_PATH)
        if db_path != ":memory:":
            db_dir = os.path.dirname(db_path)
            os.makedirs(db_dir, exist_ok=True)
        self._db_path = db_path
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                height INTEGER PRIMARY KEY,
                hash TEXT,
                parent_hash TEXT,
                proposer TEXT,
                timestamp REAL,
                data TEXT
            )
        """)
        self._db.commit()

        # Seed from in-memory block_store if provided
        if block_store:
            for b in block_store:
                self._db_insert_block(b)

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def blocks(self) -> List[Block]:
        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM blocks ORDER BY height"
            ).fetchall()
        return [Block.from_dict(json.loads(r[0])) for r in rows]

    def add_block(self, block: Block) -> None:
        """Add a produced/synced block to the store."""
        with self._lock:
            self._db_insert_block(block)

    def _db_insert_block(self, block: Block) -> None:
        """Insert a block into SQLite (caller must hold lock or be in __init__)."""
        self._db.execute(
            "INSERT OR REPLACE INTO blocks (height, hash, parent_hash, proposer, timestamp, data) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                block.block_number,
                block.block_hash,
                block.prev_hash,
                block.proposer,
                block.timestamp,
                json.dumps(block.to_dict()),
            ),
        )
        self._db.commit()

    def start(self) -> None:
        """Start serving in a background daemon thread."""
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/sync/info":
                    server_ref._handle_info(self)
                elif self.path == "/sync/health":
                    self._json_response({"ok": True})
                else:
                    self._json_response({"error": "not found"}, 404)

            def do_POST(self):
                if self.path == "/sync/blocks":
                    server_ref._handle_blocks(self)
                else:
                    self._json_response({"error": "not found"}, 404)

            def _json_response(self, data, code=200):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass  # silence request logs

        self._httpd = HTTPServer((self._host, self._port), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            daemon=True,
            name=f"sync-server-{self._port}",
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
        if self._db:
            self._db.close()

    # ── Endpoint handlers ──

    def _handle_info(self, handler) -> None:
        with self._lock:
            row = self._db.execute("SELECT COALESCE(MAX(height), -1) FROM blocks").fetchone()
            height = row[0]
        genesis_hash = self._engine.get_genesis_hash()
        resp = GetPeerInfoResponse(
            chain_id=self._engine.chain_id,
            height=height,
            genesis_hash=genesis_hash,
        )
        body = json.dumps(resp.to_dict()).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _handle_blocks(self, handler) -> None:
        length = int(handler.headers.get("Content-Length", 0))
        raw = handler.rfile.read(length) if length else b"{}"
        try:
            req_data = json.loads(raw)
        except json.JSONDecodeError:
            body = json.dumps({"error": "invalid JSON"}).encode()
            handler.send_response(400)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return

        request = GetBlocksRequest.from_dict(req_data)

        with self._lock:
            rows = self._db.execute(
                "SELECT data FROM blocks WHERE height >= ? AND height <= ? "
                "ORDER BY height LIMIT ?",
                (request.from_height, request.to_height, request.limit),
            ).fetchall()
            result = [Block.from_dict(json.loads(r[0])) for r in rows]

        resp = GetBlocksResponse(blocks=result)
        body = json.dumps(resp.to_dict()).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

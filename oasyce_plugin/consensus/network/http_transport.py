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

    def __init__(self, engine: ConsensusEngine,
                 host: str = "0.0.0.0", port: int = 9528,
                 block_store: Optional[List[Block]] = None):
        self._engine = engine
        self._host = host
        self._port = port
        # Block store — append blocks as they are produced/synced.
        # In production, this should be backed by persistent storage.
        self._blocks: List[Block] = list(block_store or [])
        self._lock = threading.Lock()
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def blocks(self) -> List[Block]:
        with self._lock:
            return list(self._blocks)

    def add_block(self, block: Block) -> None:
        """Add a produced/synced block to the store."""
        with self._lock:
            self._blocks.append(block)

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

    # ── Endpoint handlers ──

    def _handle_info(self, handler) -> None:
        with self._lock:
            height = max((b.block_number for b in self._blocks), default=-1)
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
            result = []
            for b in self._blocks:
                if b.block_number < request.from_height:
                    continue
                if b.block_number > request.to_height:
                    continue
                result.append(b)
                if len(result) >= request.limit:
                    break
            result.sort(key=lambda b: b.block_number)

        resp = GetBlocksResponse(blocks=result)
        body = json.dumps(resp.to_dict()).encode()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

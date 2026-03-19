"""HTTP transport layer using aiohttp.

Each node exposes a ``POST /node/message`` endpoint to receive messages
and uses an HTTP client to send messages to peers.
"""

from __future__ import annotations

import asyncio
import logging
import json
from typing import Any, Callable, Awaitable, List, Optional, TYPE_CHECKING

from aiohttp import web, ClientSession, ClientTimeout

from oasyce.network.message import NetworkMessage

if TYPE_CHECKING:
    from oasyce.network.discovery import PeerDiscovery
    from oasyce.network.monitor import NodeMonitor

logger = logging.getLogger(__name__)

# Callback invoked when a message arrives.
OnMessageCallback = Callable[[NetworkMessage], Awaitable[None]]


class HttpTransport:
    """Minimal HTTP transport for Oasyce P2P messages."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9470,
        on_message: Optional[OnMessageCallback] = None,
        monitor: Optional[Any] = None,
        discovery: Optional[Any] = None,
    ) -> None:
        self.host = host
        self.port = port
        self._on_message = on_message
        self._monitor = monitor
        self._discovery = discovery
        self._ws_clients: List[web.WebSocketResponse] = []
        self._app = web.Application()
        self._app.router.add_post("/node/message", self._handle_message)
        self._app.router.add_get("/node/health", self._handle_health)
        self._app.router.add_get("/node/ws", self._handle_ws)
        self._app.router.add_get("/node/stats", self._handle_stats)
        self._app.router.add_get("/node/events", self._handle_events)
        self._app.router.add_get("/node/diag", self._handle_diagnostics)
        self._runner: Optional[web.AppRunner] = None
        self._session: Optional[ClientSession] = None

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the HTTP server."""
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("Transport listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Gracefully stop server and close client session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_message(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            msg = NetworkMessage.from_dict(data)
            if self._on_message:
                await self._on_message(msg)
            return web.json_response({"ok": True})
        except Exception as exc:
            logger.warning("Bad message received: %s", exc)
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_stats(self, _request: web.Request) -> web.Response:
        if self._monitor:
            return web.json_response(self._monitor.get_stats())
        return web.json_response({"error": "monitor not available"})

    async def _handle_events(self, request: web.Request) -> web.Response:
        if not self._monitor:
            return web.json_response({"error": "monitor not available"})
        event_type = request.query.get("type")
        count = int(request.query.get("count", "50"))
        return web.json_response(self._monitor.get_recent(count, event_type))

    async def _handle_diagnostics(self, request: web.Request) -> web.Response:
        result: dict = {
            "stats": self._monitor.get_stats() if self._monitor else {},
            "recent_errors": self._monitor.get_errors(10) if self._monitor else [],
            "peers": [],
        }
        if self._discovery:
            peers = await self._discovery.get_peer_addresses()
            result["peers"] = peers
        return web.json_response(result)

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        self._ws_clients.append(ws)
        logger.info("WebSocket client connected (%d total)", len(self._ws_clients))
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    # Clients can send subscribe filters in future
                    pass
                elif msg.type == web.WSMsgType.ERROR:
                    break
        finally:
            self._ws_clients.remove(ws)
            logger.info("WebSocket client disconnected (%d remaining)", len(self._ws_clients))
        return ws

    async def broadcast_event(self, event: dict) -> None:
        """Push an event to all connected WebSocket clients."""
        data = json.dumps(event)
        dead: List[web.WebSocketResponse] = []
        for ws in self._ws_clients:
            try:
                await ws.send_str(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._ws_clients.remove(ws)

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    def _get_session(self) -> ClientSession:
        if self._session is None or self._session.closed:
            self._session = ClientSession(
                timeout=ClientTimeout(total=5),
            )
        return self._session

    async def send_message(self, address: str, msg: NetworkMessage) -> bool:
        """POST a message to a peer at *address* (host:port).

        Returns True on success, False on any failure.
        """
        url = f"http://{address}/node/message"
        try:
            session = self._get_session()
            async with session.post(url, json=msg.to_dict()) as resp:
                return resp.status == 200
        except Exception as exc:
            logger.debug("Failed to send to %s: %s", address, exc)
            return False

#!/usr/bin/env python3
"""
Testnet faucet HTTP server.

Serves a simple JSON API for claiming testnet OAS tokens.
Rate-limited: one claim per address per 24 hours.

Usage:
    python3 scripts/run_faucet.py [--port 8421] [--data-dir ~/.oasyce-testnet]

Endpoints:
    POST /claim   {"address": "0xabc..."}  → claim tokens
    GET  /status                           → faucet status
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from oasyce.services.faucet import Faucet
from oasyce.utils import OAS_DECIMALS


class FaucetHandler(BaseHTTPRequestHandler):
    """HTTP handler for faucet requests."""

    faucet: Faucet = None  # set by server setup
    chain_id: str = "oasyce-testnet-1"
    total_claims: int = 0

    def _send_json(self, data: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/status":
            self._send_json(
                {
                    "chain_id": self.chain_id,
                    "faucet_enabled": True,
                    "drip_amount": Faucet.TESTNET_DRIP,
                    "drip_amount_units": int(Faucet.TESTNET_DRIP * OAS_DECIMALS),
                    "cooldown_seconds": Faucet.COOLDOWN,
                    "total_claims": FaucetHandler.total_claims,
                }
            )
        elif self.path == "/health":
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        if self.path != "/claim":
            self._send_json({"error": "not found"}, 404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json({"error": "missing request body"}, 400)
            return

        try:
            body = json.loads(self.rfile.read(content_length))
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, 400)
            return

        address = body.get("address", "").strip()
        if not address:
            self._send_json({"error": "address is required"}, 400)
            return

        if len(address) > 128:
            self._send_json({"error": "address too long"}, 400)
            return

        result = FaucetHandler.faucet.claim(address)
        if result["success"]:
            FaucetHandler.total_claims += 1
            self._send_json(result, 200)
        else:
            self._send_json(result, 429)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        """Structured log output."""
        print(f"[faucet] {self.address_string()} - {format % args}")


def main():
    parser = argparse.ArgumentParser(description="Oasyce Testnet Faucet Server")
    parser.add_argument("--port", type=int, default=8421, help="Listen port (default: 8421)")
    parser.add_argument("--host", default="0.0.0.0", help="Listen host (default: 0.0.0.0)")
    parser.add_argument("--data-dir", default=None, help="Data directory for faucet state")
    parser.add_argument("--chain-id", default="oasyce-testnet-1", help="Chain ID")
    args = parser.parse_args()

    data_dir = args.data_dir
    if data_dir is None:
        from oasyce.config import NetworkMode, get_data_dir

        data_dir = get_data_dir(NetworkMode.TESTNET)

    Path(data_dir).mkdir(parents=True, exist_ok=True)

    FaucetHandler.faucet = Faucet(data_dir)
    FaucetHandler.chain_id = args.chain_id

    server = HTTPServer((args.host, args.port), FaucetHandler)
    print(f"╔══════════════════════════════════════════════╗")
    print(f"║        Oasyce Testnet Faucet                 ║")
    print(f"╠══════════════════════════════════════════════╣")
    print(f"║  Endpoint:  http://{args.host}:{args.port}/claim")
    print(f"║  Status:    http://{args.host}:{args.port}/status")
    print(f"║  Chain:     {args.chain_id}")
    print(f"║  Drip:      {Faucet.TESTNET_DRIP:.0f} OAS per claim")
    print(f"║  Cooldown:  {Faucet.COOLDOWN // 3600}h")
    print(f"╚══════════════════════════════════════════════╝")
    print()
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nFaucet server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()

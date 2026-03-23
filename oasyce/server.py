"""
Oasyce Node -- Unified server that runs the complete protocol stack.

    oasyce serve --port 8000

Starts:
  /v1/*        -- PoPC business API (verify, submit, buy)
  /ahrp/v1/*   -- Agent Handshake & Routing Protocol
  /market/v1/* -- Task Market (competitive bidding)
  /explorer/*  -- Block Explorer UI
  /health      -- Node health check

Settlement and staking are delegated to the Cosmos chain via OasyceClient.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from oasyce.ahrp import AgentIdentity, AnnouncePayload, Capability
from oasyce.ahrp.executor import AHRPExecutor
from oasyce.ahrp.router import Router
from oasyce.ahrp.market import TaskMarket
from oasyce.chain_client import ChainClientError, OasyceClient


def create_app(
    node_id: str = "oasyce-node-0",
    testnet: bool = True,
) -> FastAPI:
    """Create and wire the complete Oasyce node."""

    app = FastAPI(
        title="Oasyce Node",
        description="Data Rights Clearing Network -- unified protocol server",
        version="0.3.0",
    )

    # -- Chain client (replaces local SettlementEngine / StakingEngine) --
    chain = OasyceClient()

    # -- AHRP executor (uses chain client for settlement) --
    executor = AHRPExecutor(chain_client=chain, require_signature=False)
    router = Router()
    market = TaskMarket(router=router, executor=executor)

    # Store on app state for access in routes
    app.state.chain = chain
    app.state.executor = executor
    app.state.router = router
    app.state.market = market
    app.state.node_id = node_id
    app.state.start_time = int(time.time())
    app.state.testnet = testnet

    # -- Mount AHRP API --
    try:
        from oasyce.ahrp.api import api as ahrp_api, init_api

        init_api(router, executor)
        app.include_router(ahrp_api)
    except ImportError:
        pass  # AHRP API optional

    # -- Mount PoPC API --
    try:
        from oasyce.api.main import app as popc_app

        for route in popc_app.routes:
            app.routes.append(route)
    except ImportError:
        pass  # PoPC API optional

    # -- Health & Status --
    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "node_id": node_id,
            "testnet": testnet,
            "chain_connected": chain.is_chain_mode,
            "uptime_seconds": int(time.time()) - app.state.start_time,
        }

    @app.get("/status")
    def status():
        return {
            "node_id": node_id,
            "testnet": testnet,
            "uptime_seconds": int(time.time()) - app.state.start_time,
            "chain_connected": chain.is_chain_mode,
            "ahrp": {
                "agents": len(executor.agents),
                "capabilities": sum(len(c) for c in executor.capabilities.values()),
                "transactions": len(executor.transactions),
            },
            "router": router.stats(),
            "market": market.stats(),
        }

    # -- Settlement API (delegated to chain) --
    from fastapi import Body

    @app.post("/v1/escrow/create")
    def create_escrow(body: Dict[str, Any] = Body(...)):
        """Create an escrow via the chain."""
        try:
            result = chain.chain.create_escrow(
                creator=body["creator"],
                provider=body["provider"],
                amount_uoas=int(body.get("amount_uoas", 0)),
                capability_id=body.get("capability_id", ""),
                asset_id=body.get("asset_id", ""),
            )
            return result
        except (ChainClientError, KeyError) as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.get("/v1/escrow/{escrow_id}")
    def get_escrow(escrow_id: str):
        """Query an escrow from the chain."""
        try:
            return chain.get_escrow(escrow_id)
        except ChainClientError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.get("/v1/bonding_curve/{asset_id}")
    def get_bonding_curve(asset_id: str):
        """Get bonding curve price from the chain."""
        try:
            return chain.get_bonding_curve_price(asset_id)
        except ChainClientError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    # -- Market API --
    @app.post("/market/v1/auction")
    def create_auction(body: Dict[str, Any] = Body(...)):
        """Create a competitive auction for a task."""
        from oasyce.ahrp import Need, RequestPayload

        need = Need(
            description=body.get("description", ""),
            tags=body.get("tags", []),
            min_reputation=body.get("min_reputation", 0.0),
        )
        request = RequestPayload(
            need=need,
            budget_oas=body.get("budget_oas", 0.0),
            request_id=body.get("request_id", f"req-{int(time.time())}"),
            deadline=body.get("deadline", 0),
        )
        auction = market.create_auction(
            request=request,
            requester_id=body.get("requester_id", "anonymous"),
            sla_ms=body.get("sla_ms", 5000),
        )
        return {"auction_id": request.request_id, "budget": auction.budget_oas}

    @app.post("/market/v1/bid")
    def submit_bid(body: Dict[str, Any] = Body(...)):
        """Submit a bid for an auction."""
        from oasyce.ahrp import OfferPayload

        try:
            offer = OfferPayload(
                request_id=body["auction_id"],
                capability_id=body.get("capability_id", ""),
                price_oas=body["price_oas"],
                offer_id=body.get("offer_id", f"off-{int(time.time())}"),
            )
            bid = market.submit_bid(body["auction_id"], offer, body["provider_id"])
            return {"bid_score": bid.score, "provider": bid.provider_id}
        except (ValueError, KeyError) as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.post("/market/v1/close/{auction_id}")
    def close_auction(auction_id: str):
        """Close auction and select winner."""
        try:
            winner = market.close_auction(auction_id)
            if winner:
                return {
                    "winner": winner.provider_id,
                    "price": winner.offer.price_oas,
                    "score": winner.score,
                }
            return {"winner": None}
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.post("/market/v1/execute/{auction_id}")
    def execute_winner(auction_id: str):
        """Execute winning bid -- lock escrow."""
        try:
            tx = market.execute_winner(auction_id)
            return {"tx_id": tx.tx_id, "state": tx.state.value}
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    @app.get("/market/v1/stats")
    def market_stats():
        return market.stats()

    return app


def main():
    """CLI entry point: oas serve"""
    parser = argparse.ArgumentParser(
        prog="oas",
        description="Oasyce Protocol Node -- Data Rights Clearing Network",
    )
    sub = parser.add_subparsers(dest="command")

    # serve command
    serve_parser = sub.add_parser("serve", help="Start the Oasyce node")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--node-id", default="oasyce-node-0")
    serve_parser.add_argument("--mainnet", action="store_true", help="Run in mainnet mode")

    # status command
    sub.add_parser("status", help="Check node status")

    # version command
    sub.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn

        app = create_app(
            node_id=args.node_id,
            testnet=not args.mainnet,
        )
        print(
            f"""
+----------------------------------------------+
|          Oasyce Protocol Node v0.3.0         |
+----------------------------------------------+
|  Node ID:  {args.node_id:<33}|
|  Network:  {"mainnet" if args.mainnet else "testnet":<33}|
|  Listen:   {args.host}:{args.port:<26}|
+----------------------------------------------+
|  Endpoints:                                  |
|    GET  /health          -- node health      |
|    GET  /status          -- full status      |
|    POST /ahrp/v1/*       -- agent protocol   |
|    POST /market/v1/*     -- task market      |
|    POST /v1/*            -- PoPC API         |
+----------------------------------------------+
"""
        )
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "version":
        print("oas 0.3.0")

    elif args.command == "status":
        import urllib.request
        import json

        try:
            resp = urllib.request.urlopen("http://127.0.0.1:8000/status")
            data = json.loads(resp.read())
            print(json.dumps(data, indent=2))
        except Exception as e:
            print(f"Node not running or unreachable: {e}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

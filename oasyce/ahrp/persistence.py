"""
AHRP Persistence Layer — SQLite-backed state for agents, transactions, escrows.

Ensures AHRP state survives node restarts. Write-through design: every state
mutation writes to SQLite immediately. On startup, state is loaded from disk.

Follows the same pattern as oasyce/storage/ledger.py:
  - WAL mode for concurrent readers
  - JSON text columns for complex objects
  - Thread-safe via threading.Lock
  - Unix timestamps
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from oasyce.ahrp import (
    AgentIdentity,
    Capability,
    Need,
    OfferPayload,
    RequestPayload,
)


class AHRPStore:
    """SQLite-backed persistence for AHRP executor/router/market state."""

    def __init__(self, db_path: str = ":memory:"):
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS ahrp_agents (
                    agent_id    TEXT PRIMARY KEY,
                    public_key  TEXT NOT NULL,
                    reputation  REAL DEFAULT 10.0,
                    stake       REAL DEFAULT 0.0,
                    metadata    TEXT DEFAULT '{}',
                    endpoints   TEXT DEFAULT '[]',
                    last_seen   INTEGER,
                    announce_count INTEGER DEFAULT 1,
                    created_at  INTEGER
                );

                CREATE TABLE IF NOT EXISTS ahrp_capabilities (
                    capability_id TEXT NOT NULL,
                    agent_id      TEXT NOT NULL,
                    tags          TEXT DEFAULT '[]',
                    description   TEXT DEFAULT '',
                    access_levels TEXT DEFAULT '["L0"]',
                    price_floor   REAL DEFAULT 0.0,
                    origin_type   TEXT DEFAULT 'human',
                    PRIMARY KEY (capability_id, agent_id),
                    FOREIGN KEY (agent_id) REFERENCES ahrp_agents(agent_id)
                );

                CREATE TABLE IF NOT EXISTS ahrp_transactions (
                    tx_id       TEXT PRIMARY KEY,
                    buyer       TEXT NOT NULL,
                    seller      TEXT NOT NULL,
                    state       TEXT NOT NULL,
                    offer_data  TEXT DEFAULT '{}',
                    accept_data TEXT DEFAULT '{}',
                    deliver_data TEXT DEFAULT '{}',
                    confirm_data TEXT DEFAULT '{}',
                    created_at  INTEGER,
                    updated_at  INTEGER
                );

                CREATE TABLE IF NOT EXISTS ahrp_escrows (
                    tx_id           TEXT PRIMARY KEY,
                    buyer           TEXT NOT NULL,
                    seller          TEXT NOT NULL,
                    amount_oas      REAL NOT NULL,
                    locked_at       INTEGER,
                    released        INTEGER DEFAULT 0,
                    chain_escrow_id TEXT DEFAULT '',
                    FOREIGN KEY (tx_id) REFERENCES ahrp_transactions(tx_id)
                );

                CREATE TABLE IF NOT EXISTS ahrp_auctions (
                    request_id    TEXT PRIMARY KEY,
                    requester_id  TEXT NOT NULL,
                    budget_oas    REAL NOT NULL,
                    deadline      INTEGER DEFAULT 0,
                    sla_ms        INTEGER DEFAULT 5000,
                    min_reputation REAL DEFAULT 0.0,
                    bidding_window_ms INTEGER DEFAULT 2000,
                    bids          TEXT DEFAULT '[]',
                    winner        TEXT DEFAULT '',
                    closed        INTEGER DEFAULT 0,
                    request_data  TEXT DEFAULT '{}',
                    created_at    INTEGER
                );

                CREATE TABLE IF NOT EXISTS ahrp_pending_requests (
                    request_id    TEXT PRIMARY KEY,
                    requester_id  TEXT NOT NULL,
                    need_data     TEXT DEFAULT '{}',
                    budget_oas    REAL DEFAULT 0.0,
                    deadline      INTEGER DEFAULT 0,
                    created_at    INTEGER,
                    matches_sent  INTEGER DEFAULT 0,
                    offers_data   TEXT DEFAULT '[]'
                );
            """)

    # ── Agent CRUD ────────────────────────────────────────────────────

    def save_agent(
        self,
        agent: AgentIdentity,
        endpoints: List[str],
        announce_count: int = 1,
    ) -> None:
        now = int(time.time())
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO ahrp_agents
                   (agent_id, public_key, reputation, stake, metadata,
                    endpoints, last_seen, announce_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                       (SELECT created_at FROM ahrp_agents WHERE agent_id = ?), ?
                   ))""",
                (
                    agent.agent_id, agent.public_key, agent.reputation,
                    agent.stake, json.dumps(agent.metadata),
                    json.dumps(endpoints), now, announce_count,
                    agent.agent_id, now,
                ),
            )

    def load_agents(self) -> Dict[str, Tuple[AgentIdentity, List[str], int]]:
        """Return {agent_id: (AgentIdentity, endpoints, announce_count)}."""
        result: Dict[str, Tuple[AgentIdentity, List[str], int]] = {}
        with self._lock:
            rows = self._conn.execute("SELECT * FROM ahrp_agents").fetchall()
        for r in rows:
            identity = AgentIdentity(
                agent_id=r["agent_id"],
                public_key=r["public_key"],
                reputation=r["reputation"],
                stake=r["stake"],
                metadata=json.loads(r["metadata"]),
            )
            endpoints = json.loads(r["endpoints"])
            result[r["agent_id"]] = (identity, endpoints, r["announce_count"])
        return result

    def delete_agent(self, agent_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM ahrp_capabilities WHERE agent_id = ?", (agent_id,))
            self._conn.execute("DELETE FROM ahrp_agents WHERE agent_id = ?", (agent_id,))

    # ── Capability CRUD ──────────────────────────────────────────────

    def save_capabilities(self, agent_id: str, caps: List[Capability]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM ahrp_capabilities WHERE agent_id = ?", (agent_id,)
            )
            for cap in caps:
                self._conn.execute(
                    """INSERT INTO ahrp_capabilities
                       (capability_id, agent_id, tags, description,
                        access_levels, price_floor, origin_type)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        cap.capability_id, agent_id,
                        json.dumps(cap.tags), cap.description,
                        json.dumps(cap.access_levels), cap.price_floor,
                        cap.origin_type,
                    ),
                )

    def load_capabilities(self) -> Dict[str, List[Capability]]:
        """Return {agent_id: [Capability, ...]}."""
        result: Dict[str, List[Capability]] = {}
        with self._lock:
            rows = self._conn.execute("SELECT * FROM ahrp_capabilities").fetchall()
        for r in rows:
            cap = Capability(
                capability_id=r["capability_id"],
                tags=json.loads(r["tags"]),
                description=r["description"],
                access_levels=json.loads(r["access_levels"]),
                price_floor=r["price_floor"],
                origin_type=r["origin_type"],
            )
            result.setdefault(r["agent_id"], []).append(cap)
        return result

    # ── Transaction CRUD ─────────────────────────────────────────────

    def save_transaction(
        self,
        tx_id: str,
        buyer: str,
        seller: str,
        state: str,
        offer_data: Optional[Dict] = None,
        accept_data: Optional[Dict] = None,
        deliver_data: Optional[Dict] = None,
        confirm_data: Optional[Dict] = None,
    ) -> None:
        now = int(time.time())
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO ahrp_transactions
                   (tx_id, buyer, seller, state, offer_data, accept_data,
                    deliver_data, confirm_data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                       (SELECT created_at FROM ahrp_transactions WHERE tx_id = ?), ?
                   ), ?)""",
                (
                    tx_id, buyer, seller, state,
                    json.dumps(offer_data or {}),
                    json.dumps(accept_data or {}),
                    json.dumps(deliver_data or {}),
                    json.dumps(confirm_data or {}),
                    tx_id, now, now,
                ),
            )

    def update_transaction_state(self, tx_id: str, state: str) -> None:
        now = int(time.time())
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE ahrp_transactions SET state = ?, updated_at = ? WHERE tx_id = ?",
                (state, now, tx_id),
            )

    def load_transactions(self) -> List[Dict[str, Any]]:
        """Return list of transaction dicts (for executor to reconstruct)."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM ahrp_transactions").fetchall()
        return [
            {
                "tx_id": r["tx_id"],
                "buyer": r["buyer"],
                "seller": r["seller"],
                "state": r["state"],
                "offer_data": json.loads(r["offer_data"]),
                "accept_data": json.loads(r["accept_data"]),
                "deliver_data": json.loads(r["deliver_data"]),
                "confirm_data": json.loads(r["confirm_data"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    # ── Escrow CRUD ──────────────────────────────────────────────────

    def save_escrow(
        self,
        tx_id: str,
        buyer: str,
        seller: str,
        amount_oas: float,
        locked_at: int,
        released: bool = False,
        chain_escrow_id: str = "",
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO ahrp_escrows
                   (tx_id, buyer, seller, amount_oas, locked_at, released, chain_escrow_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (tx_id, buyer, seller, amount_oas, locked_at,
                 1 if released else 0, chain_escrow_id),
            )

    def update_escrow_released(self, tx_id: str, released: bool) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE ahrp_escrows SET released = ? WHERE tx_id = ?",
                (1 if released else 0, tx_id),
            )

    def load_escrows(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM ahrp_escrows").fetchall()
        return [
            {
                "tx_id": r["tx_id"],
                "buyer": r["buyer"],
                "seller": r["seller"],
                "amount_oas": r["amount_oas"],
                "locked_at": r["locked_at"],
                "released": bool(r["released"]),
                "chain_escrow_id": r["chain_escrow_id"],
            }
            for r in rows
        ]

    # ── Auction CRUD ─────────────────────────────────────────────────

    def save_auction(
        self,
        request_id: str,
        requester_id: str,
        budget_oas: float,
        deadline: int,
        sla_ms: int = 5000,
        min_reputation: float = 0.0,
        bidding_window_ms: int = 2000,
        bids: Optional[List[Dict]] = None,
        winner: Optional[Dict] = None,
        closed: bool = False,
        request_data: Optional[Dict] = None,
    ) -> None:
        now = int(time.time())
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO ahrp_auctions
                   (request_id, requester_id, budget_oas, deadline, sla_ms,
                    min_reputation, bidding_window_ms, bids, winner, closed,
                    request_data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                       (SELECT created_at FROM ahrp_auctions WHERE request_id = ?), ?
                   ))""",
                (
                    request_id, requester_id, budget_oas, deadline, sla_ms,
                    min_reputation, bidding_window_ms,
                    json.dumps(bids or []),
                    json.dumps(winner) if winner else "",
                    1 if closed else 0,
                    json.dumps(request_data or {}),
                    request_id, now,
                ),
            )

    def update_auction_closed(
        self, request_id: str, winner: Optional[Dict], closed: bool
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE ahrp_auctions SET winner = ?, closed = ? WHERE request_id = ?",
                (json.dumps(winner) if winner else "", 1 if closed else 0, request_id),
            )

    def load_auctions(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM ahrp_auctions").fetchall()
        return [
            {
                "request_id": r["request_id"],
                "requester_id": r["requester_id"],
                "budget_oas": r["budget_oas"],
                "deadline": r["deadline"],
                "sla_ms": r["sla_ms"],
                "min_reputation": r["min_reputation"],
                "bidding_window_ms": r["bidding_window_ms"],
                "bids": json.loads(r["bids"]),
                "winner": json.loads(r["winner"]) if r["winner"] else None,
                "closed": bool(r["closed"]),
                "request_data": json.loads(r["request_data"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── Stats ─────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        with self._lock:
            agents = self._conn.execute("SELECT COUNT(*) FROM ahrp_agents").fetchone()[0]
            txs = self._conn.execute("SELECT COUNT(*) FROM ahrp_transactions").fetchone()[0]
            escrows = self._conn.execute("SELECT COUNT(*) FROM ahrp_escrows").fetchone()[0]
            auctions = self._conn.execute("SELECT COUNT(*) FROM ahrp_auctions").fetchone()[0]
        return {
            "agents": agents,
            "transactions": txs,
            "escrows": escrows,
            "auctions": auctions,
        }

    def close(self) -> None:
        self._conn.close()

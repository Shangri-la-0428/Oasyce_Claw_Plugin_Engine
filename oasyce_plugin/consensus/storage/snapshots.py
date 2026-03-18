"""
State snapshots — periodic materialization of event-derived stake state.

Snapshots accelerate stake queries by caching the cumulative result of
all stake_events up to a given block_height. Queries then only need to
replay events *after* the snapshot instead of scanning the full log.

Snapshots are an optional performance optimization — consensus correctness
does not depend on them. If no snapshot exists, queries fall back to
scanning all events from genesis.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from oasyce_plugin.consensus.state import ConsensusState

# Create a snapshot every N blocks.
SNAPSHOT_INTERVAL = 100


def ensure_snapshot_table(conn: sqlite3.Connection, lock: threading.Lock) -> None:
    """Create the state_snapshots table if it doesn't exist."""
    with lock, conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS state_snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                block_height  INTEGER NOT NULL UNIQUE,
                validator_states BLOB NOT NULL,
                stake_states     BLOB NOT NULL,
                created_at    INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_height
                ON state_snapshots(block_height);
        """)


def create_snapshot(state: ConsensusState, block_height: int) -> bool:
    """Materialize current stake state at *block_height* into a snapshot row.

    Reads all validators and computes per-(validator, delegator) stake
    from events up to *block_height*, then stores the result as JSON blobs.

    Returns True on success, False if a snapshot at this height already exists.
    """
    # 1. Gather validator metadata
    with state._lock:
        validators = state._conn.execute(
            "SELECT validator_id, status, jailed_until, commission_rate "
            "FROM validators"
        ).fetchall()

    validator_states: Dict[str, Dict[str, Any]] = {}
    for v in validators:
        validator_states[v["validator_id"]] = {
            "status": v["status"],
            "jailed_until": v["jailed_until"],
            "commission_rate": v["commission_rate"],
        }

    # 2. Compute per-validator total stake from events up to block_height.
    with state._lock:
        total_rows = state._conn.execute(
            """SELECT validator_id, COALESCE(SUM(
                CASE WHEN event_type IN ('register_self', 'delegate', 'reward')
                     THEN amount
                     WHEN event_type IN ('undelegate', 'slash', 'exit')
                     THEN -amount
                     ELSE 0
                END
            ), 0) AS total
            FROM stake_events
            WHERE block_height <= ?
            GROUP BY validator_id""",
            (block_height,),
        ).fetchall()

    # 3. Compute per-validator self-stake (register_self minus exit/slash on self).
    with state._lock:
        self_rows = state._conn.execute(
            """SELECT validator_id, COALESCE(SUM(
                CASE WHEN event_type = 'register_self' THEN amount
                     WHEN event_type = 'exit' AND from_addr = validator_id THEN -amount
                     WHEN event_type = 'slash' AND from_addr = validator_id THEN -amount
                     ELSE 0
                END
            ), 0) AS self_stake
            FROM stake_events
            WHERE block_height <= ?
            GROUP BY validator_id""",
            (block_height,),
        ).fetchall()

    # Build stake_states: { validator_id: { "total": N, "self": N } }
    stake_states: Dict[str, Dict[str, int]] = {}
    for r in total_rows:
        vid = r["validator_id"]
        total = max(0, r["total"])
        if total > 0:
            stake_states.setdefault(vid, {})["total"] = total
    for r in self_rows:
        vid = r["validator_id"]
        self_s = max(0, r["self_stake"])
        if self_s > 0:
            stake_states.setdefault(vid, {})["self"] = self_s

    # 3. Persist
    validator_blob = json.dumps(validator_states).encode("utf-8")
    stake_blob = json.dumps(stake_states).encode("utf-8")
    now = int(time.time())

    try:
        with state._lock, state._conn:
            state._conn.execute(
                "INSERT INTO state_snapshots "
                "(block_height, validator_states, stake_states, created_at) "
                "VALUES (?, ?, ?, ?)",
                (block_height, validator_blob, stake_blob, now),
            )
        return True
    except sqlite3.IntegrityError:
        # Snapshot at this height already exists — idempotent.
        return False


def load_latest_snapshot(
    state: ConsensusState,
    before_height: Optional[int] = None,
) -> Optional[Tuple[int, Dict[str, Dict[str, Any]], Dict[str, Dict[str, int]]]]:
    """Load the most recent snapshot, optionally before a given height.

    Returns (block_height, validator_states, stake_states) or None.
    """
    if before_height is not None:
        query = (
            "SELECT block_height, validator_states, stake_states "
            "FROM state_snapshots WHERE block_height <= ? "
            "ORDER BY block_height DESC LIMIT 1"
        )
        params: tuple = (before_height,)
    else:
        query = (
            "SELECT block_height, validator_states, stake_states "
            "FROM state_snapshots "
            "ORDER BY block_height DESC LIMIT 1"
        )
        params = ()

    with state._lock:
        row = state._conn.execute(query, params).fetchone()
    if row is None:
        return None

    height = row["block_height"]
    validator_states = json.loads(row["validator_states"])
    stake_states = json.loads(row["stake_states"])
    return height, validator_states, stake_states


def load_snapshot_at(
    state: ConsensusState,
    block_height: int,
) -> Optional[Tuple[int, Dict[str, Dict[str, Any]], Dict[str, Dict[str, int]]]]:
    """Load the snapshot at or just before *block_height*.

    Alias for load_latest_snapshot(state, before_height=block_height).
    """
    return load_latest_snapshot(state, before_height=block_height)


def get_validator_stake_fast(
    state: ConsensusState,
    validator_id: str,
    at_height: Optional[int] = None,
) -> int:
    """Snapshot-accelerated version of get_validator_stake.

    1. Find the latest snapshot at or before at_height.
    2. Read cached stake from the snapshot.
    3. Replay only incremental events after the snapshot.
    """
    snap = load_latest_snapshot(state, before_height=at_height)
    if snap is None:
        # No snapshot — fall back to full scan.
        return _full_scan_stake(state, validator_id, at_height)

    snap_height, _vs, stake_states = snap
    base_stake = stake_states.get(validator_id, {}).get("total", 0)

    # Incremental: events after snap_height up to at_height.
    incremental = _incremental_stake(state, validator_id, snap_height, at_height)
    return max(0, base_stake + incremental)


def get_self_stake_fast(
    state: ConsensusState,
    validator_id: str,
    at_height: Optional[int] = None,
) -> int:
    """Snapshot-accelerated self-stake query."""
    snap = load_latest_snapshot(state, before_height=at_height)
    if snap is None:
        return _full_scan_self_stake(state, validator_id, at_height)

    snap_height, _vs, stake_states = snap
    base_self = stake_states.get(validator_id, {}).get("self", 0)

    # Incremental self-stake events after snapshot
    incremental = _incremental_self_stake(state, validator_id, snap_height, at_height)
    return max(0, base_self + incremental)


# ── Internal helpers ──────────────────────────────────────────────────


def _reverted_clause(state: ConsensusState) -> str:
    """Return SQL clause to exclude reverted events, if column exists."""
    try:
        with state._lock:
            cols = [
                row[1] for row in
                state._conn.execute("PRAGMA table_info(stake_events)").fetchall()
            ]
        if "reverted_at" in cols:
            return " AND reverted_at IS NULL"
    except Exception:
        pass
    return ""


def _full_scan_stake(
    state: ConsensusState, validator_id: str, at_height: Optional[int]
) -> int:
    """Full scan — the original get_validator_stake logic."""
    height_clause = ""
    reverted_clause = _reverted_clause(state)
    params: list = [validator_id]
    if at_height is not None:
        height_clause = " AND block_height <= ?"
        params.append(at_height)
    with state._lock:
        row = state._conn.execute(
            f"""SELECT COALESCE(SUM(
                CASE WHEN event_type IN ('register_self', 'delegate', 'reward')
                     THEN amount
                     WHEN event_type IN ('undelegate', 'slash', 'exit')
                     THEN -amount
                     ELSE 0
                END
            ), 0) AS total
            FROM stake_events
            WHERE validator_id = ?{height_clause}{reverted_clause}""",
            params,
        ).fetchone()
    return max(0, row[0]) if row else 0


def _full_scan_self_stake(
    state: ConsensusState, validator_id: str, at_height: Optional[int]
) -> int:
    """Full scan — the original get_self_stake logic."""
    height_clause = ""
    reverted_clause = _reverted_clause(state)
    params: list = [validator_id, validator_id, validator_id]
    if at_height is not None:
        height_clause = " AND block_height <= ?"
        params.append(at_height)
    with state._lock:
        row = state._conn.execute(
            f"""SELECT COALESCE(SUM(
                CASE WHEN event_type = 'register_self' THEN amount
                     WHEN event_type = 'exit' AND from_addr = ? THEN -amount
                     WHEN event_type = 'slash' AND from_addr = ? THEN -amount
                     ELSE 0
                END
            ), 0) AS total
            FROM stake_events
            WHERE validator_id = ?{height_clause}{reverted_clause}""",
            params,
        ).fetchone()
    return max(0, row[0]) if row else 0


def _incremental_stake(
    state: ConsensusState,
    validator_id: str,
    after_height: int,
    up_to_height: Optional[int],
) -> int:
    """Sum stake changes for validator_id in (after_height, up_to_height]."""
    reverted_clause = _reverted_clause(state)
    params: list = [validator_id, after_height]
    up_to_clause = ""
    if up_to_height is not None:
        up_to_clause = " AND block_height <= ?"
        params.append(up_to_height)
    with state._lock:
        row = state._conn.execute(
            f"""SELECT COALESCE(SUM(
                CASE WHEN event_type IN ('register_self', 'delegate', 'reward')
                     THEN amount
                     WHEN event_type IN ('undelegate', 'slash', 'exit')
                     THEN -amount
                     ELSE 0
                END
            ), 0) AS total
            FROM stake_events
            WHERE validator_id = ?
              AND block_height > ?{up_to_clause}{reverted_clause}""",
            params,
        ).fetchone()
    return row[0] if row else 0


def _incremental_self_stake(
    state: ConsensusState,
    validator_id: str,
    after_height: int,
    up_to_height: Optional[int],
) -> int:
    """Sum self-stake changes in (after_height, up_to_height]."""
    reverted_clause = _reverted_clause(state)
    params: list = [validator_id, validator_id, validator_id, after_height]
    up_to_clause = ""
    if up_to_height is not None:
        up_to_clause = " AND block_height <= ?"
        params.append(up_to_height)
    with state._lock:
        row = state._conn.execute(
            f"""SELECT COALESCE(SUM(
                CASE WHEN event_type = 'register_self' THEN amount
                     WHEN event_type = 'exit' AND from_addr = ? THEN -amount
                     WHEN event_type = 'slash' AND from_addr = ? THEN -amount
                     ELSE 0
                END
            ), 0) AS total
            FROM stake_events
            WHERE validator_id = ?
              AND block_height > ?{up_to_clause}{reverted_clause}""",
            params,
        ).fetchone()
    return row[0] if row else 0

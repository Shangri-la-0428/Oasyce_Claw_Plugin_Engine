"""
Consensus state persistence — SQLite database for PoS consensus data.

All monetary values are stored as INTEGER (units, 1 OAS = 10^8 units).
State is derived from the append-only stake_events table.
Validators table stores only registration metadata.

Tables:
  - validators: registration info (id, status, commission, registered_at, counters)
  - stake_events: append-only event log (the single source of truth for stake)
  - unbonding: time-locked stake release queue
  - epochs: epoch metadata
  - leader_schedule: per-slot proposer assignment
  - slash_events: penalty records
  - reward_events: reward records
  - consensus_meta: key-value store
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional


class ConsensusState:
    """SQLite-backed consensus state store.

    Stake is derived from stake_events (append-only).
    No UPDATE on monetary columns — only INSERT into stake_events.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self._default_path()
        if self.db_path != ":memory:":
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    @staticmethod
    def _default_path() -> str:
        return os.path.join(os.path.expanduser("~"), ".oasyce", "consensus.db")

    def _create_tables(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS validators (
                    validator_id     TEXT PRIMARY KEY,
                    status           TEXT DEFAULT 'active',
                    commission_rate  INTEGER DEFAULT 1000,
                    registered_at    INTEGER NOT NULL,
                    jailed_until     INTEGER DEFAULT 0,
                    missed_blocks    INTEGER DEFAULT 0,
                    blocks_proposed  INTEGER DEFAULT 0,
                    work_completed   INTEGER DEFAULT 0,
                    total_rewards    INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS stake_events (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    block_height  INTEGER NOT NULL,
                    validator_id  TEXT NOT NULL,
                    event_type    TEXT NOT NULL,
                    from_addr     TEXT DEFAULT '',
                    amount        INTEGER NOT NULL,
                    asset_type    TEXT DEFAULT 'OAS',
                    reason        TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_stake_events_validator
                    ON stake_events(validator_id);
                CREATE INDEX IF NOT EXISTS idx_stake_events_height
                    ON stake_events(block_height);
                CREATE INDEX IF NOT EXISTS idx_stake_events_from
                    ON stake_events(from_addr);
                CREATE TABLE IF NOT EXISTS unbonding (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    delegator   TEXT NOT NULL,
                    validator_id TEXT NOT NULL,
                    amount      INTEGER NOT NULL,
                    unbond_at   INTEGER NOT NULL,
                    release_at  INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS epochs (
                    epoch_number    INTEGER PRIMARY KEY,
                    start_time      INTEGER NOT NULL,
                    end_time        INTEGER,
                    start_block     INTEGER,
                    end_block       INTEGER,
                    total_rewards   INTEGER DEFAULT 0,
                    validator_count INTEGER DEFAULT 0,
                    status          TEXT DEFAULT 'active'
                );
                CREATE TABLE IF NOT EXISTS leader_schedule (
                    epoch_number INTEGER NOT NULL,
                    slot_index   INTEGER NOT NULL,
                    validator_id TEXT NOT NULL,
                    proposed     INTEGER DEFAULT 0,
                    PRIMARY KEY(epoch_number, slot_index)
                );
                CREATE TABLE IF NOT EXISTS slash_events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    validator_id TEXT NOT NULL,
                    reason       TEXT NOT NULL,
                    amount       INTEGER NOT NULL,
                    epoch_number INTEGER NOT NULL,
                    block_height INTEGER DEFAULT 0,
                    timestamp    INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reward_events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    epoch_number INTEGER NOT NULL,
                    validator_id TEXT NOT NULL,
                    recipient    TEXT NOT NULL,
                    reward_type  TEXT NOT NULL,
                    amount       INTEGER NOT NULL,
                    block_height INTEGER DEFAULT 0,
                    timestamp    INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS consensus_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
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

    # ── Stake Events (append-only, single source of truth) ─────────

    def append_stake_event(self, block_height: int, validator_id: str,
                           event_type: str, amount: int,
                           from_addr: str = "", reason: str = "") -> int:
        """Append a stake event. This is the ONLY way to change stake state.

        event_type: register_self | delegate | undelegate | slash | reward | exit
        amount: always positive (the event_type determines the direction)
        """
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO stake_events "
                "(block_height, validator_id, event_type, from_addr, amount, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (block_height, validator_id, event_type, from_addr, amount, reason),
            )
        return cur.lastrowid

    def get_validator_stake(self, validator_id: str,
                            at_height: Optional[int] = None) -> int:
        """Derive total stake for a validator from events.

        Uses snapshot acceleration when available: loads cached stake from the
        most recent snapshot, then replays only incremental events after it.
        Falls back to full scan when no snapshot exists.
        """
        from oasyce_plugin.consensus.storage.snapshots import get_validator_stake_fast
        return get_validator_stake_fast(self, validator_id, at_height)

    def get_self_stake(self, validator_id: str,
                       at_height: Optional[int] = None) -> int:
        """Derive self-stake from events (register_self minus exit/slash on self).

        Uses snapshot acceleration when available.
        """
        from oasyce_plugin.consensus.storage.snapshots import get_self_stake_fast
        return get_self_stake_fast(self, validator_id, at_height)

    def get_delegations(self, validator_id: str,
                        at_height: Optional[int] = None) -> List[Dict[str, Any]]:
        """Derive current delegations from events."""
        height_clause = ""
        params: list = [validator_id]
        if at_height is not None:
            height_clause = " AND block_height <= ?"
            params.append(at_height)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT from_addr AS delegator, SUM(
                    CASE WHEN event_type = 'delegate' THEN amount
                         WHEN event_type IN ('undelegate', 'slash') THEN -amount
                         ELSE 0
                    END
                ) AS amount
                FROM stake_events
                WHERE validator_id = ?
                  AND event_type IN ('delegate', 'undelegate', 'slash')
                  AND from_addr != ''
                  AND from_addr != validator_id
                  {height_clause}
                GROUP BY from_addr
                HAVING SUM(
                    CASE WHEN event_type = 'delegate' THEN amount
                         WHEN event_type IN ('undelegate', 'slash') THEN -amount
                         ELSE 0
                    END
                ) > 0""",
                params,
            ).fetchall()
        return [{"delegator": r["delegator"], "validator_id": validator_id,
                 "amount": r["amount"]} for r in rows]

    def get_delegator_delegations(self, delegator: str,
                                  at_height: Optional[int] = None) -> List[Dict[str, Any]]:
        """Derive all delegations for a delegator from events."""
        height_clause = ""
        params: list = [delegator]
        if at_height is not None:
            height_clause = " AND block_height <= ?"
            params.append(at_height)
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT validator_id, SUM(
                    CASE WHEN event_type = 'delegate' THEN amount
                         WHEN event_type IN ('undelegate', 'slash') THEN -amount
                         ELSE 0
                    END
                ) AS amount
                FROM stake_events
                WHERE from_addr = ?
                  AND event_type IN ('delegate', 'undelegate', 'slash')
                  {height_clause}
                GROUP BY validator_id
                HAVING amount > 0""",
                params,
            ).fetchall()
        return [{"delegator": delegator, "validator_id": r["validator_id"],
                 "amount": r["amount"]} for r in rows]

    def get_delegation_amount(self, delegator: str, validator_id: str,
                              at_height: Optional[int] = None) -> int:
        """Get a specific delegator's stake with a validator."""
        height_clause = ""
        params: list = [delegator, validator_id]
        if at_height is not None:
            height_clause = " AND block_height <= ?"
            params.append(at_height)
        with self._lock:
            row = self._conn.execute(
                f"""SELECT COALESCE(SUM(
                    CASE WHEN event_type = 'delegate' THEN amount
                         WHEN event_type IN ('undelegate', 'slash') THEN -amount
                         ELSE 0
                    END
                ), 0) AS total
                FROM stake_events
                WHERE from_addr = ? AND validator_id = ?
                  AND event_type IN ('delegate', 'undelegate', 'slash')
                  {height_clause}""",
                params,
            ).fetchone()
        return max(0, row[0]) if row else 0

    # ── Validators (registration metadata only) ───────────────────

    def register_validator(self, validator_id: str,
                           commission_rate: int = 1000,
                           block_height: int = 0,
                           now: Optional[int] = None) -> bool:
        """Register a new validator. Stake is recorded via append_stake_event."""
        now = now or int(time.time())
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO validators "
                    "(validator_id, commission_rate, registered_at) "
                    "VALUES (?, ?, ?)",
                    (validator_id, commission_rate, now),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_validator(self, validator_id: str) -> Optional[Dict[str, Any]]:
        """Get validator info with derived stake values."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM validators WHERE validator_id = ?", (validator_id,)
            ).fetchone()
        if row is None:
            return None
        val = dict(row)
        # Derive stake from events
        val["total_stake"] = self.get_validator_stake(validator_id)
        val["self_stake"] = self.get_self_stake(validator_id)
        return val

    def get_active_validators(self, min_stake: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM validators WHERE status = 'active'"
            ).fetchall()
        result = []
        for r in rows:
            val = dict(r)
            val["total_stake"] = self.get_validator_stake(val["validator_id"])
            val["self_stake"] = self.get_self_stake(val["validator_id"])
            if val["total_stake"] >= min_stake:
                result.append(val)
        result.sort(key=lambda v: v["total_stake"], reverse=True)
        return result

    def get_all_validators(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM validators"
            ).fetchall()
        result = []
        for r in rows:
            val = dict(r)
            val["total_stake"] = self.get_validator_stake(val["validator_id"])
            val["self_stake"] = self.get_self_stake(val["validator_id"])
            result.append(val)
        result.sort(key=lambda v: v["total_stake"], reverse=True)
        return result

    def update_validator_status(self, validator_id: str, status: str,
                                jailed_until: int = 0) -> bool:
        """Update validator status (active/jailed/exited). No stake mutation."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE validators SET status = ?, jailed_until = ? "
                "WHERE validator_id = ?",
                (status, jailed_until, validator_id),
            )
        return cur.rowcount > 0

    def update_validator_commission(self, validator_id: str,
                                    commission_rate: int) -> bool:
        """Update commission rate (basis points)."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE validators SET commission_rate = ? WHERE validator_id = ?",
                (commission_rate, validator_id),
            )
        return cur.rowcount > 0

    def increment_validator(self, validator_id: str, **fields) -> bool:
        """Atomically increment counter fields (blocks_proposed, missed_blocks, etc.).
        Only allowed for non-monetary counters."""
        _COUNTER_COLUMNS = frozenset({
            "missed_blocks", "blocks_proposed", "work_completed", "total_rewards",
        })
        if not fields:
            return False
        for k in fields:
            if k not in _COUNTER_COLUMNS:
                raise ValueError(f"invalid counter field: {k}")
        sets = ", ".join(f"{k} = {k} + ?" for k in fields)
        vals = list(fields.values()) + [validator_id]
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"UPDATE validators SET {sets} WHERE validator_id = ?", vals
            )
        return cur.rowcount > 0

    def jail_validator(self, validator_id: str, until: int) -> bool:
        return self.update_validator_status(validator_id, "jailed", until)

    def unjail_validator(self, validator_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE validators SET status = 'active', jailed_until = 0, "
                "missed_blocks = 0 WHERE validator_id = ?",
                (validator_id,),
            )
        return cur.rowcount > 0

    def exit_validator(self, validator_id: str) -> bool:
        return self.update_validator_status(validator_id, "exited")

    def reactivate_validator(self, validator_id: str,
                             commission_rate: int) -> bool:
        """Re-activate an exited validator (preserving historical counters)."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE validators SET status = 'active', commission_rate = ?, "
                "jailed_until = 0 WHERE validator_id = ?",
                (commission_rate, validator_id),
            )
        return cur.rowcount > 0

    # ── Unbonding ─────────────────────────────────────────────────

    def add_unbonding(self, delegator: str, validator_id: str,
                      amount: int, unbonding_period: int,
                      now: Optional[int] = None) -> bool:
        now = now or int(time.time())
        release_at = now + unbonding_period
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO unbonding (delegator, validator_id, amount, unbond_at, release_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (delegator, validator_id, amount, now, release_at),
                )
            return True
        except Exception:
            return False

    def get_matured_unbondings(self, now: Optional[int] = None) -> List[Dict[str, Any]]:
        now = now or int(time.time())
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM unbonding WHERE release_at <= ?", (now,)
            ).fetchall()
        return [dict(r) for r in rows]

    def remove_unbonding(self, unbonding_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM unbonding WHERE id = ?", (unbonding_id,)
            )
        return cur.rowcount > 0

    def release_matured_unbondings(self, now: Optional[int] = None) -> int:
        now = now or int(time.time())
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM unbonding WHERE release_at <= ?", (now,)
            )
        return cur.rowcount

    def get_pending_unbondings(self, delegator: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM unbonding WHERE delegator = ? ORDER BY release_at",
                (delegator,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Epochs ────────────────────────────────────────────────────

    def create_epoch(self, epoch_number: int, start_time: int,
                     start_block: int = 0, validator_count: int = 0) -> bool:
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO epochs "
                    "(epoch_number, start_time, start_block, validator_count) "
                    "VALUES (?, ?, ?, ?)",
                    (epoch_number, start_time, start_block, validator_count),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_epoch(self, epoch_number: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM epochs WHERE epoch_number = ?", (epoch_number,)
            ).fetchone()
        return dict(row) if row else None

    def finalize_epoch(self, epoch_number: int, end_time: int,
                       end_block: int, total_rewards: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE epochs SET end_time = ?, end_block = ?, "
                "total_rewards = ?, status = 'finalized' "
                "WHERE epoch_number = ?",
                (end_time, end_block, total_rewards, epoch_number),
            )
        return cur.rowcount > 0

    def get_latest_epoch(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM epochs ORDER BY epoch_number DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    # ── Leader Schedule ───────────────────────────────────────────

    def set_leader_schedule(self, epoch_number: int,
                            schedule: List[Dict[str, Any]]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM leader_schedule WHERE epoch_number = ?",
                (epoch_number,),
            )
            for entry in schedule:
                self._conn.execute(
                    "INSERT INTO leader_schedule "
                    "(epoch_number, slot_index, validator_id) VALUES (?, ?, ?)",
                    (epoch_number, entry["slot_index"], entry["validator_id"]),
                )

    def get_leader_schedule(self, epoch_number: int) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM leader_schedule WHERE epoch_number = ? "
                "ORDER BY slot_index",
                (epoch_number,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_slot_leader(self, epoch_number: int,
                        slot_index: int) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT validator_id FROM leader_schedule "
                "WHERE epoch_number = ? AND slot_index = ?",
                (epoch_number, slot_index),
            ).fetchone()
        return row[0] if row else None

    def mark_slot_proposed(self, epoch_number: int, slot_index: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE leader_schedule SET proposed = 1 "
                "WHERE epoch_number = ? AND slot_index = ?",
                (epoch_number, slot_index),
            )
        return cur.rowcount > 0

    def count_proposed_slots(self, epoch_number: int,
                             validator_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM leader_schedule "
                "WHERE epoch_number = ? AND validator_id = ? AND proposed = 1",
                (epoch_number, validator_id),
            ).fetchone()
        return row[0] if row else 0

    def count_assigned_slots(self, epoch_number: int,
                             validator_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM leader_schedule "
                "WHERE epoch_number = ? AND validator_id = ?",
                (epoch_number, validator_id),
            ).fetchone()
        return row[0] if row else 0

    # ── Slash Events ──────────────────────────────────────────────

    def record_slash(self, validator_id: str, reason: str,
                     amount: int, epoch_number: int,
                     block_height: int = 0,
                     now: Optional[int] = None) -> int:
        now = now or int(time.time())
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO slash_events "
                "(validator_id, reason, amount, epoch_number, block_height, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (validator_id, reason, amount, epoch_number, block_height, now),
            )
        return cur.lastrowid

    def get_slash_events(self, validator_id: Optional[str] = None,
                         epoch_number: Optional[int] = None) -> List[Dict[str, Any]]:
        clauses = []
        params: list = []
        if validator_id:
            clauses.append("validator_id = ?")
            params.append(validator_id)
        if epoch_number is not None:
            clauses.append("epoch_number = ?")
            params.append(epoch_number)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM slash_events{where} ORDER BY timestamp DESC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Reward Events ─────────────────────────────────────────────

    def record_reward(self, epoch_number: int, validator_id: str,
                      recipient: str, reward_type: str, amount: int,
                      block_height: int = 0,
                      now: Optional[int] = None) -> int:
        now = now or int(time.time())
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO reward_events "
                "(epoch_number, validator_id, recipient, reward_type, amount, "
                "block_height, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (epoch_number, validator_id, recipient, reward_type, amount,
                 block_height, now),
            )
        return cur.lastrowid

    def get_reward_events(self, epoch_number: Optional[int] = None,
                          validator_id: Optional[str] = None,
                          recipient: Optional[str] = None) -> List[Dict[str, Any]]:
        clauses = []
        params: list = []
        if epoch_number is not None:
            clauses.append("epoch_number = ?")
            params.append(epoch_number)
        if validator_id:
            clauses.append("validator_id = ?")
            params.append(validator_id)
        if recipient:
            clauses.append("recipient = ?")
            params.append(recipient)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM reward_events{where} ORDER BY timestamp DESC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_epoch_total_rewards(self, epoch_number: int) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM reward_events "
                "WHERE epoch_number = ?",
                (epoch_number,),
            ).fetchone()
        return row[0] if row else 0

    # ── Meta KV store ───────────────────────────────────────────

    def get_meta(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM consensus_meta WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO consensus_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = ?",
                (key, value, value),
            )

    # ── Reorg support (event-sourced rollback) ─────────────────────

    def revert_to_height(self, height: int) -> int:
        """Mark all stake_events above *height* as reverted.

        Events are not deleted — a ``reverted_at`` column tracks which
        events have been logically removed.  Returns the number of events
        reverted.
        """
        self._ensure_reverted_column()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE stake_events SET reverted_at = ? "
                "WHERE block_height > ? AND reverted_at IS NULL",
                (height, height),
            )
            reverted = cur.rowcount

            self._conn.execute(
                "DELETE FROM slash_events WHERE block_height > ?", (height,)
            )
            self._conn.execute(
                "DELETE FROM reward_events WHERE block_height > ?", (height,)
            )
            self._conn.execute(
                "DELETE FROM leader_schedule WHERE epoch_number IN "
                "(SELECT epoch_number FROM epochs WHERE start_block > ?)",
                (height,),
            )
            self._conn.execute(
                "DELETE FROM epochs WHERE start_block > ?", (height,)
            )
        return reverted

    def delete_snapshots_above(self, height: int) -> int:
        """Delete all state snapshots above *height*."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM state_snapshots WHERE block_height > ?", (height,)
            )
        return cur.rowcount

    def _ensure_reverted_column(self) -> None:
        """Add ``reverted_at`` column to stake_events if it doesn't exist."""
        with self._lock:
            cols = [
                row[1] for row in
                self._conn.execute("PRAGMA table_info(stake_events)").fetchall()
            ]
        if "reverted_at" not in cols:
            with self._lock, self._conn:
                self._conn.execute(
                    "ALTER TABLE stake_events ADD COLUMN reverted_at INTEGER"
                )

    def get_stake_events(self, from_height: int = 0,
                         to_height: Optional[int] = None,
                         include_reverted: bool = False) -> List[Dict[str, Any]]:
        """Read stake events in a height range.

        By default, excludes reverted events.
        """
        self._ensure_reverted_column()
        clauses = ["block_height >= ?"]
        params: list = [from_height]
        if to_height is not None:
            clauses.append("block_height <= ?")
            params.append(to_height)
        if not include_reverted:
            clauses.append("reverted_at IS NULL")
        where = " AND ".join(clauses)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM stake_events WHERE {where} ORDER BY id",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Utility ───────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()

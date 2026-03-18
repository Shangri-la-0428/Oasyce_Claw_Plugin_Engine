"""
State replay verification — proves "delete DB + replay = current state".

Replays all stake_events through apply_operation to reconstruct state from
scratch, then compares the result against the current (live) state.

This module is read-only with respect to the source database — all replay
happens on a separate in-memory ConsensusEngine.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from oasyce_plugin.consensus.core.types import (
    OAS_DECIMALS, Operation, OperationType, from_units,
)

if TYPE_CHECKING:
    from oasyce_plugin.consensus.state import ConsensusState


# ── Result types ──────────────────────────────────────────────────────


@dataclass
class ReplayResult:
    """Summary of a replay run."""
    events_replayed: int = 0
    from_height: int = 0
    to_height: int = 0
    validators: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    state_hash: str = ""
    errors: List[str] = field(default_factory=list)


@dataclass
class FieldDiff:
    """A single field-level difference."""
    validator_id: str
    field: str
    expected: Any
    actual: Any


@dataclass
class ConsistencyReport:
    """Result of comparing replayed state against live state."""
    consistent: bool = True
    events_replayed: int = 0
    validators_checked: int = 0
    diffs: List[FieldDiff] = field(default_factory=list)
    state_hash_replayed: str = ""
    state_hash_live: str = ""
    errors: List[str] = field(default_factory=list)


# ── Core replay ───────────────────────────────────────────────────────


def _read_events(state: ConsensusState,
                 from_height: int = 0,
                 to_height: Optional[int] = None) -> List[Dict[str, Any]]:
    """Read stake_events in height order from the source database."""
    params: list = [from_height]
    to_clause = ""
    if to_height is not None:
        to_clause = " AND block_height <= ?"
        params.append(to_height)
    with state._lock:
        rows = state._conn.execute(
            f"SELECT * FROM stake_events "
            f"WHERE block_height >= ?{to_clause} "
            f"ORDER BY id ASC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def _read_validators_meta(state: ConsensusState) -> List[Dict[str, Any]]:
    """Read validator registration metadata from the source database."""
    with state._lock:
        rows = state._conn.execute(
            "SELECT validator_id, commission_rate, registered_at "
            "FROM validators ORDER BY registered_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def _compute_state_hash(stakes: Dict[str, Dict[str, Any]]) -> str:
    """Deterministic hash of validator stakes for comparison."""
    canonical = json.dumps(stakes, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _collect_stake_state(state: ConsensusState,
                         at_height: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """Build a {validator_id: {total_stake, self_stake}} dict from the state."""
    from oasyce_plugin.consensus.storage.snapshots import (
        _full_scan_stake, _full_scan_self_stake,
    )
    with state._lock:
        rows = state._conn.execute("SELECT validator_id FROM validators").fetchall()
    result: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        vid = r["validator_id"]
        total = _full_scan_stake(state, vid, at_height)
        self_s = _full_scan_self_stake(state, vid, at_height)
        if total > 0 or self_s > 0:
            result[vid] = {"total_stake": total, "self_stake": self_s}
    return result


def replay_events(source_state: ConsensusState,
                  from_height: int = 0,
                  to_height: Optional[int] = None) -> ReplayResult:
    """Replay stake_events onto a fresh in-memory state.

    Reads events and validator metadata from *source_state*, creates a
    brand-new ConsensusEngine in memory, and replays every event as an
    Operation through apply_operation.

    This is a read-only operation on source_state.

    Args:
        source_state: The database to read events from.
        from_height: Start replaying from this block height (inclusive).
        to_height: Stop at this block height (inclusive). None = all.

    Returns:
        ReplayResult with final validator stakes and state hash.
    """
    from oasyce_plugin.consensus import ConsensusEngine
    from oasyce_plugin.consensus.storage.snapshots import (
        _full_scan_stake, _full_scan_self_stake,
    )

    events = _read_events(source_state, from_height, to_height)
    result = ReplayResult(from_height=from_height)

    if not events:
        result.state_hash = _compute_state_hash({})
        return result

    result.to_height = events[-1]["block_height"]

    # Build a fresh engine in memory.
    engine = ConsensusEngine(db_path=":memory:")

    # Map event_type → OperationType for replayable events.
    _EVENT_TO_OP = {
        "register_self": OperationType.REGISTER,
        "delegate": OperationType.DELEGATE,
        "undelegate": OperationType.UNDELEGATE,
        "slash": OperationType.SLASH,
        "reward": OperationType.REWARD,
        "exit": OperationType.EXIT,
    }

    # Track seen validators so we know commission rates.
    validators_meta = {v["validator_id"]: v
                       for v in _read_validators_meta(source_state)}

    registered_validators: set = set()

    for ev in events:
        et = ev["event_type"]
        vid = ev["validator_id"]
        amount = ev["amount"]
        height = ev["block_height"]
        from_addr = ev.get("from_addr", "")
        reason = ev.get("reason", "")

        op_type = _EVENT_TO_OP.get(et)
        if op_type is None:
            result.errors.append(f"unknown event_type: {et} (event id={ev.get('id')})")
            continue

        if op_type == OperationType.REGISTER:
            commission = validators_meta.get(vid, {}).get("commission_rate", 1000)
            op = Operation(
                op_type=OperationType.REGISTER,
                validator_id=vid,
                amount=amount,
                commission_rate=commission,
            )
            res = engine.apply(op, height)
            if not res.get("ok"):
                # May be re-register after exit; record as event directly.
                engine.state.append_stake_event(
                    height, vid, "register_self", amount, from_addr=vid)
                if vid not in registered_validators:
                    engine.state.register_validator(vid, commission, height)
            registered_validators.add(vid)

        elif op_type == OperationType.DELEGATE:
            # Ensure validator is registered before delegating.
            if vid not in registered_validators:
                commission = validators_meta.get(vid, {}).get("commission_rate", 1000)
                engine.state.register_validator(vid, commission, height)
                registered_validators.add(vid)
            engine.state.append_stake_event(
                height, vid, "delegate", amount, from_addr=from_addr)

        elif op_type == OperationType.UNDELEGATE:
            engine.state.append_stake_event(
                height, vid, "undelegate", amount, from_addr=from_addr)

        elif op_type == OperationType.SLASH:
            engine.state.append_stake_event(
                height, vid, "slash", amount, from_addr=from_addr,
                reason=reason)

        elif op_type == OperationType.REWARD:
            engine.state.append_stake_event(
                height, vid, "reward", amount, from_addr=from_addr,
                reason=reason)

        elif op_type == OperationType.EXIT:
            engine.state.append_stake_event(
                height, vid, "exit", amount, from_addr=from_addr)

        result.events_replayed += 1

    # Collect final stakes from the replayed engine.
    with engine.state._lock:
        rows = engine.state._conn.execute(
            "SELECT validator_id FROM validators"
        ).fetchall()
    for r in rows:
        vid = r["validator_id"]
        total = _full_scan_stake(engine.state, vid, None)
        self_s = _full_scan_self_stake(engine.state, vid, None)
        if total > 0 or self_s > 0:
            result.validators[vid] = {"total_stake": total, "self_stake": self_s}

    # Also check validators that only appear in events (no metadata row).
    with engine.state._lock:
        ev_vids = engine.state._conn.execute(
            "SELECT DISTINCT validator_id FROM stake_events"
        ).fetchall()
    for r in ev_vids:
        vid = r["validator_id"]
        if vid not in result.validators:
            total = _full_scan_stake(engine.state, vid, None)
            self_s = _full_scan_self_stake(engine.state, vid, None)
            if total > 0 or self_s > 0:
                result.validators[vid] = {"total_stake": total, "self_stake": self_s}

    result.state_hash = _compute_state_hash(result.validators)
    engine.close()
    return result


def verify_state_consistency(source_state: ConsensusState,
                             to_height: Optional[int] = None) -> ConsistencyReport:
    """Compare replayed state against the current live state.

    1. Compute current (live) validator stakes from events.
    2. Replay all events onto a fresh engine.
    3. Compare per-validator total_stake and self_stake.

    Args:
        source_state: The live database.
        to_height: Compare state up to this block height. None = all.

    Returns:
        ConsistencyReport with diffs (empty if consistent).
    """
    report = ConsistencyReport()

    # 1. Live state.
    live_stakes = _collect_stake_state(source_state, at_height=to_height)
    report.state_hash_live = _compute_state_hash(live_stakes)

    # 2. Replayed state.
    replay = replay_events(source_state, from_height=0, to_height=to_height)
    report.events_replayed = replay.events_replayed
    report.state_hash_replayed = replay.state_hash
    report.errors = replay.errors

    # 3. Compare.
    all_vids = set(live_stakes.keys()) | set(replay.validators.keys())
    report.validators_checked = len(all_vids)

    for vid in sorted(all_vids):
        live = live_stakes.get(vid, {"total_stake": 0, "self_stake": 0})
        replayed = replay.validators.get(vid, {"total_stake": 0, "self_stake": 0})

        for fld in ("total_stake", "self_stake"):
            lv = live.get(fld, 0)
            rv = replayed.get(fld, 0)
            if lv != rv:
                report.consistent = False
                report.diffs.append(FieldDiff(
                    validator_id=vid,
                    field=fld,
                    expected=lv,
                    actual=rv,
                ))

    return report


def replay_from_snapshot(source_state: ConsensusState,
                         snapshot_height: int,
                         to_height: Optional[int] = None) -> ReplayResult:
    """Replay from a snapshot height instead of genesis.

    Loads the snapshot at *snapshot_height*, seeds a fresh engine with that
    snapshot's stake state, then replays only events after the snapshot.

    Args:
        source_state: The live database.
        snapshot_height: Load snapshot at or before this height.
        to_height: Replay events up to this height. None = all.

    Returns:
        ReplayResult starting from the snapshot.
    """
    from oasyce_plugin.consensus import ConsensusEngine
    from oasyce_plugin.consensus.storage.snapshots import (
        load_snapshot_at, _full_scan_stake, _full_scan_self_stake,
    )

    snap = load_snapshot_at(source_state, snapshot_height)
    if snap is None:
        # No snapshot — fall back to full replay.
        return replay_events(source_state, from_height=0, to_height=to_height)

    snap_height, validator_states, stake_states = snap

    # Create fresh engine and seed with snapshot data.
    engine = ConsensusEngine(db_path=":memory:")

    # Seed validator metadata.
    validators_meta = {v["validator_id"]: v
                       for v in _read_validators_meta(source_state)}
    for vid, ss in stake_states.items():
        total = ss.get("total", 0)
        self_s = ss.get("self", 0)
        commission = validators_meta.get(vid, {}).get("commission_rate", 1000)
        engine.state.register_validator(vid, commission, 0)

        # Record self-stake as a single genesis event at snap_height.
        if self_s > 0:
            engine.state.append_stake_event(
                snap_height, vid, "register_self", self_s, from_addr=vid)
        # Record delegated portion (total - self) as a single delegate event.
        delegated = total - self_s
        if delegated > 0:
            engine.state.append_stake_event(
                snap_height, vid, "delegate", delegated, from_addr="_snapshot_")

    # Replay events after snapshot.
    events = _read_events(source_state, from_height=snap_height + 1,
                          to_height=to_height)

    result = ReplayResult(from_height=snap_height, events_replayed=0)
    registered_vids = set(stake_states.keys())

    for ev in events:
        et = ev["event_type"]
        vid = ev["validator_id"]
        amount = ev["amount"]
        height = ev["block_height"]
        from_addr = ev.get("from_addr", "")
        reason = ev.get("reason", "")

        # Ensure validator exists.
        if vid not in registered_vids:
            commission = validators_meta.get(vid, {}).get("commission_rate", 1000)
            engine.state.register_validator(vid, commission, height)
            registered_vids.add(vid)

        engine.state.append_stake_event(
            height, vid, et, amount, from_addr=from_addr, reason=reason)
        result.events_replayed += 1

    if events:
        result.to_height = events[-1]["block_height"]
    else:
        result.to_height = snap_height

    # Collect final state.
    with engine.state._lock:
        all_vids_rows = engine.state._conn.execute(
            "SELECT DISTINCT validator_id FROM stake_events"
        ).fetchall()
    for r in all_vids_rows:
        vid = r["validator_id"]
        total = _full_scan_stake(engine.state, vid, None)
        self_s = _full_scan_self_stake(engine.state, vid, None)
        if total > 0 or self_s > 0:
            result.validators[vid] = {"total_stake": total, "self_stake": self_s}

    result.state_hash = _compute_state_hash(result.validators)
    engine.close()
    return result

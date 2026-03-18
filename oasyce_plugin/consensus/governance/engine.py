"""Governance engine — proposal lifecycle, voting, tallying, and execution.

All monetary values in integer units (1 OAS = 10^8 units).
Follows the same result-dict pattern as the rest of consensus: {"ok": True/False, ...}.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import replace
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from oasyce_plugin.consensus.governance.types import (
    DEFAULT_MIN_DEPOSIT,
    DEFAULT_VOTING_PERIOD,
    QUORUM_BPS,
    PASS_THRESHOLD_BPS,
    UNGOVERNABLE_KEYS,
    ParameterChange,
    Proposal,
    ProposalStatus,
    Vote,
    VoteOption,
    VoteResult,
    compute_proposal_id,
)
from oasyce_plugin.consensus.governance.registry import ParameterRegistry

if TYPE_CHECKING:
    from oasyce_plugin.consensus.state import ConsensusState
    from oasyce_plugin.consensus.assets.balances import MultiAssetBalance


class GovernanceEngine:
    """On-chain governance — proposals, votes, tallying, and execution.

    State is persisted in the consensus SQLite database (proposals + votes tables).
    """

    def __init__(self, state: ConsensusState,
                 param_registry: ParameterRegistry,
                 min_deposit: int = DEFAULT_MIN_DEPOSIT,
                 voting_period: int = DEFAULT_VOTING_PERIOD,
                 balances: Optional['MultiAssetBalance'] = None) -> None:
        self._state = state
        self._registry = param_registry
        self._min_deposit = min_deposit
        self._voting_period = voting_period
        self._balances = balances
        self._lock = state._lock
        self._conn = state._conn
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Create governance tables if they don't exist."""
        with self._lock, self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS governance_proposals (
                    id             TEXT PRIMARY KEY,
                    proposer       TEXT NOT NULL,
                    title          TEXT NOT NULL,
                    description    TEXT NOT NULL,
                    changes_json   TEXT NOT NULL,
                    deposit        INTEGER NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'active',
                    voting_start   INTEGER NOT NULL,
                    voting_end     INTEGER NOT NULL,
                    created_at     INTEGER NOT NULL,
                    snapshot_height INTEGER NOT NULL DEFAULT 0,
                    stake_snapshot_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_gov_proposals_status
                    ON governance_proposals(status);

                CREATE TABLE IF NOT EXISTS governance_votes (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id  TEXT NOT NULL,
                    voter        TEXT NOT NULL,
                    option       TEXT NOT NULL,
                    weight       INTEGER NOT NULL,
                    timestamp    INTEGER NOT NULL,
                    UNIQUE(proposal_id, voter)
                );
                CREATE INDEX IF NOT EXISTS idx_gov_votes_proposal
                    ON governance_votes(proposal_id);
            """)
            # Migration: add columns if they don't exist (for existing databases)
            try:
                self._conn.execute(
                    "ALTER TABLE governance_proposals ADD COLUMN snapshot_height INTEGER NOT NULL DEFAULT 0"
                )
            except Exception:
                pass  # column already exists
            try:
                self._conn.execute(
                    "ALTER TABLE governance_proposals ADD COLUMN stake_snapshot_json TEXT NOT NULL DEFAULT '{}'"
                )
            except Exception:
                pass  # column already exists

    # ── Submit proposal ────────────────────────────────────────────

    def submit_proposal(self, proposer: str, title: str,
                        description: str,
                        changes: List[ParameterChange],
                        deposit: int,
                        block_height: int = 0) -> Dict[str, Any]:
        """Submit a new governance proposal.

        Args:
            proposer: Address of the proposer.
            title: Short title.
            description: Detailed description.
            changes: List of ParameterChange to apply if passed.
            deposit: Deposit in units (must >= min_deposit).
            block_height: Current block height.

        Returns:
            {"ok": True, "proposal": {...}} or {"ok": False, "error": "..."}
        """
        if not title or not title.strip():
            return {"ok": False, "error": "title is required"}
        if not changes:
            return {"ok": False, "error": "at least one parameter change is required"}
        if deposit < self._min_deposit:
            return {"ok": False, "error": (
                f"deposit {deposit} below minimum {self._min_deposit}"
            )}

        # Validate each change against the registry
        for change in changes:
            if change.key in UNGOVERNABLE_KEYS:
                return {"ok": False, "error": (
                    f"parameter '{change.key}' is not governable"
                )}
            valid, err = self._registry.validate_change(
                change.module, change.key, change.new_value,
            )
            if not valid:
                return {"ok": False, "error": err}

            # Verify old_value matches current
            current = self._registry.get_current_value(change.module, change.key)
            if current is not None and current != change.old_value:
                return {"ok": False, "error": (
                    f"old_value mismatch for '{change.module}.{change.key}': "
                    f"expected {current}, got {change.old_value}"
                )}

        proposal_id = compute_proposal_id(proposer, title, changes, block_height)
        voting_start = block_height
        voting_end = block_height + self._voting_period

        changes_json = json.dumps([c.to_dict() for c in changes])

        # Debit deposit from proposer's balance if balance system is available
        if self._balances is not None:
            try:
                self._balances.debit(proposer, "OAS", deposit)
            except ValueError as e:
                return {"ok": False, "error": str(e)}

        # Build stake snapshot at current block height for voting power
        stake_snapshot = self._build_stake_snapshot()
        stake_snapshot_json = json.dumps(stake_snapshot)

        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO governance_proposals "
                    "(id, proposer, title, description, changes_json, deposit, "
                    "status, voting_start, voting_end, created_at, "
                    "snapshot_height, stake_snapshot_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (proposal_id, proposer, title, description, changes_json,
                     deposit, ProposalStatus.ACTIVE.value,
                     voting_start, voting_end, block_height,
                     block_height, stake_snapshot_json),
                )
        except sqlite3.IntegrityError:
            # Refund deposit on duplicate proposal
            if self._balances is not None:
                self._balances.credit(proposer, "OAS", deposit)
            return {"ok": False, "error": "duplicate proposal"}

        proposal = Proposal(
            id=proposal_id, proposer=proposer, title=title,
            description=description, changes=list(changes),
            deposit=deposit, status=ProposalStatus.ACTIVE,
            voting_start=voting_start, voting_end=voting_end,
            created_at=block_height,
            snapshot_height=block_height,
            stake_snapshot=stake_snapshot,
        )
        return {"ok": True, "proposal": proposal.to_dict()}

    # ── Cast vote ──────────────────────────────────────────────────

    def cast_vote(self, proposal_id: str, voter: str,
                  option: VoteOption,
                  block_height: int = 0) -> Dict[str, Any]:
        """Cast a stake-weighted vote on a proposal.

        Voter weight is derived from their total stake (self + delegated).
        """
        proposal = self._get_proposal(proposal_id)
        if proposal is None:
            return {"ok": False, "error": f"proposal '{proposal_id}' not found"}
        if proposal.status != ProposalStatus.ACTIVE:
            return {"ok": False, "error": (
                f"proposal is '{proposal.status.value}', not active"
            )}
        if block_height > proposal.voting_end:
            return {"ok": False, "error": "voting period has ended"}

        # Compute voting weight from stake snapshot (prevents flash-stake attacks)
        if proposal.stake_snapshot:
            weight = proposal.stake_snapshot.get(voter, 0)
        else:
            # Fallback for proposals created before snapshot support
            weight = self._get_voter_weight(voter)
        if weight <= 0:
            return {"ok": False, "error": "voter has no stake"}

        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO governance_votes "
                    "(proposal_id, voter, option, weight, timestamp) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(proposal_id, voter) DO UPDATE SET "
                    "option = excluded.option, weight = excluded.weight, "
                    "timestamp = excluded.timestamp",
                    (proposal_id, voter, option.value, weight, block_height),
                )
        except Exception as e:
            return {"ok": False, "error": str(e)}

        vote = Vote(
            proposal_id=proposal_id, voter=voter,
            option=option, weight=weight, timestamp=block_height,
        )
        return {"ok": True, "vote": vote.to_dict()}

    # ── Tally votes ────────────────────────────────────────────────

    def tally_votes(self, proposal_id: str) -> Dict[str, Any]:
        """Tally votes for a proposal. Does NOT change proposal status.

        Returns the VoteResult dict.
        """
        proposal = self._get_proposal(proposal_id)
        if proposal is None:
            return {"ok": False, "error": f"proposal '{proposal_id}' not found"}

        votes = self._get_votes(proposal_id)
        yes_w = sum(v["weight"] for v in votes if v["option"] == VoteOption.YES.value)
        no_w = sum(v["weight"] for v in votes if v["option"] == VoteOption.NO.value)
        abstain_w = sum(v["weight"] for v in votes if v["option"] == VoteOption.ABSTAIN.value)

        total_voting_power = self._get_total_stake()
        participated = yes_w + no_w + abstain_w

        quorum_reached = (
            total_voting_power > 0
            and (participated * 10000) >= (total_voting_power * QUORUM_BPS)
        )

        # 2/3 majority of yes/(yes+no), abstain doesn't count toward threshold
        yes_plus_no = yes_w + no_w
        passed = (
            quorum_reached
            and yes_plus_no > 0
            and (yes_w * 10000) >= (yes_plus_no * PASS_THRESHOLD_BPS)
        )

        result = VoteResult(
            proposal_id=proposal_id,
            yes_votes=yes_w,
            no_votes=no_w,
            abstain_votes=abstain_w,
            total_voting_power=total_voting_power,
            quorum_reached=quorum_reached,
            passed=passed,
        )
        return {"ok": True, "result": result.to_dict()}

    # ── Execute proposal ───────────────────────────────────────────

    def execute_proposal(self, proposal_id: str) -> Dict[str, Any]:
        """Execute a passed proposal — apply parameter changes.

        Only proposals with status PASSED can be executed.
        """
        proposal = self._get_proposal(proposal_id)
        if proposal is None:
            return {"ok": False, "error": f"proposal '{proposal_id}' not found"}
        if proposal.status != ProposalStatus.PASSED:
            return {"ok": False, "error": (
                f"proposal status is '{proposal.status.value}', must be 'passed'"
            )}

        applied = []
        for change in proposal.changes:
            ok = self._registry.apply_change(
                change.module, change.key, change.new_value,
            )
            if ok:
                applied.append(change.to_dict())

        self._update_status(proposal_id, ProposalStatus.EXECUTED)
        return {
            "ok": True,
            "proposal_id": proposal_id,
            "applied": applied,
            "count": len(applied),
        }

    # ── End-of-block processing ────────────────────────────────────

    def end_block(self, height: int) -> List[Dict[str, Any]]:
        """Called at the end of each block. Finalizes expired voting periods.

        Returns list of proposals whose status changed.
        """
        changed: List[Dict[str, Any]] = []

        # Find active proposals whose voting period has ended
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM governance_proposals "
                "WHERE status = ? AND voting_end <= ?",
                (ProposalStatus.ACTIVE.value, height),
            ).fetchall()

        for row in rows:
            pid = row[0]
            proposal = self._get_proposal(pid)
            tally = self.tally_votes(pid)
            if not tally.get("ok"):
                continue
            result = tally["result"]
            if result["passed"]:
                self._update_status(pid, ProposalStatus.PASSED)
                # Auto-execute
                exec_result = self.execute_proposal(pid)
                # Refund deposit on quorum reached (passed)
                if self._balances is not None and proposal is not None:
                    self._balances.credit(proposal.proposer, "OAS", proposal.deposit)
                changed.append({
                    "proposal_id": pid,
                    "new_status": ProposalStatus.EXECUTED.value,
                    "applied": exec_result.get("applied", []),
                })
            elif not result["quorum_reached"]:
                # Burn deposit — no refund when quorum not reached
                self._update_status(pid, ProposalStatus.EXPIRED)
                changed.append({
                    "proposal_id": pid,
                    "new_status": ProposalStatus.EXPIRED.value,
                })
            else:
                # Refund deposit on quorum reached (rejected)
                if self._balances is not None and proposal is not None:
                    self._balances.credit(proposal.proposer, "OAS", proposal.deposit)
                self._update_status(pid, ProposalStatus.REJECTED)
                changed.append({
                    "proposal_id": pid,
                    "new_status": ProposalStatus.REJECTED.value,
                })

        return changed

    # ── Query helpers ──────────────────────────────────────────────

    def get_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Get a proposal by ID."""
        p = self._get_proposal(proposal_id)
        if p is None:
            return None
        d = p.to_dict()
        # Attach vote summary
        votes = self._get_votes(proposal_id)
        d["vote_count"] = len(votes)
        return d

    def list_proposals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List proposals, optionally filtered by status."""
        if status:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT * FROM governance_proposals WHERE status = ? "
                    "ORDER BY created_at DESC",
                    (status,),
                ).fetchall()
        else:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT * FROM governance_proposals ORDER BY created_at DESC"
                ).fetchall()
        return [self._row_to_proposal(r).to_dict() for r in rows]

    def get_votes(self, proposal_id: str) -> List[Dict[str, Any]]:
        """Get all votes for a proposal."""
        return self._get_votes(proposal_id)

    # ── Internal helpers ───────────────────────────────────────────

    def _get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM governance_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_proposal(row)

    @staticmethod
    def _row_to_proposal(row) -> Proposal:
        changes_raw = json.loads(row["changes_json"])
        changes = [ParameterChange.from_dict(c) for c in changes_raw]
        # Parse stake snapshot (may be absent in old databases)
        snapshot_height = 0
        stake_snapshot = None
        try:
            snapshot_height = row["snapshot_height"]
        except (IndexError, KeyError):
            pass
        try:
            raw = row["stake_snapshot_json"]
            if raw:
                parsed = json.loads(raw)
                if parsed:
                    stake_snapshot = {k: int(v) for k, v in parsed.items()}
        except (IndexError, KeyError, json.JSONDecodeError):
            pass
        return Proposal(
            id=row["id"],
            proposer=row["proposer"],
            title=row["title"],
            description=row["description"],
            changes=changes,
            deposit=row["deposit"],
            status=ProposalStatus(row["status"]),
            voting_start=row["voting_start"],
            voting_end=row["voting_end"],
            created_at=row["created_at"],
            snapshot_height=snapshot_height,
            stake_snapshot=stake_snapshot,
        )

    def _get_votes(self, proposal_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM governance_votes WHERE proposal_id = ? "
                "ORDER BY timestamp",
                (proposal_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _build_stake_snapshot(self) -> Dict[str, int]:
        """Build a snapshot of all current stake weights for voting power.

        Captures both validator self-stake and delegator stakes so that
        voting power is frozen at proposal creation time, preventing
        flash-stake attacks (VULN-17).
        """
        snapshot: Dict[str, int] = {}
        # Capture all active validators' total stake
        active = self._state.get_active_validators(0)
        for v in active:
            vid = v["validator_id"]
            total = v["total_stake"]
            if total > 0:
                snapshot[vid] = total
        # Capture delegator stakes (delegators can also vote)
        # We need to walk through all delegations to find delegators
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT from_addr FROM stake_events "
                "WHERE event_type = 'delegate'"
            ).fetchall()
        for row in rows:
            delegator = row[0]
            if delegator in snapshot:
                continue  # already captured as validator
            delegations = self._state.get_delegator_delegations(delegator)
            total = sum(d["amount"] for d in delegations)
            if total > 0:
                snapshot[delegator] = total
        return snapshot

    def _get_voter_weight(self, voter: str) -> int:
        """Get voting weight for a voter — total stake (self + delegated to them)."""
        # Check if voter is a validator (has self-stake)
        validator_stake = self._state.get_validator_stake(voter)
        if validator_stake > 0:
            return validator_stake

        # Check delegator stakes across all validators
        delegations = self._state.get_delegator_delegations(voter)
        return sum(d["amount"] for d in delegations)

    def _get_total_stake(self) -> int:
        """Get total staked across all active validators."""
        active = self._state.get_active_validators(0)
        return sum(v["total_stake"] for v in active)

    def _update_status(self, proposal_id: str, status: ProposalStatus) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE governance_proposals SET status = ? WHERE id = ?",
                (status.value, proposal_id),
            )

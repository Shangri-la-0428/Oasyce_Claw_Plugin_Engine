"""Dispute Manager + Jury System for capability invocations.

Handles dispute lifecycle:
    1. open_dispute()   — consumer disputes a result within the dispute window
    2. select_jury()    — pick jurors weighted by reputation
    3. submit_vote()    — jurors vote consumer|provider
    4. resolve()        — tally votes, slash or release, compensate jury
"""

from __future__ import annotations

import enum
import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ── Constants ────────────────────────────────────────────────────────
DISPUTE_FEE = 5.0  # OAS — anti-spam, refunded if consumer wins
DEFAULT_DISPUTE_WINDOW = 3600  # seconds (1 hour — overridden per access level)
DEFAULT_JURY_SIZE = 5  # raised from 3 for collusion resistance
MAJORITY_THRESHOLD = 2 / 3  # 2/3 majority required
MIN_JUROR_REPUTATION = 50.0
JUROR_REWARD_FIXED = 2.0  # OAS per juror — fixed regardless of outcome
JUROR_STAKE_REQUIRED = 10.0  # minimum stake to serve as juror
VOTING_DEADLINE = 604800  # 7 days — disputes cannot hang forever

# ── Liability-aligned dispute windows (seconds) ─────────────────────
DISPUTE_WINDOWS_BY_LEVEL = {
    "L0": 86400,  # 1 day
    "L1": 259200,  # 3 days
    "L2": 604800,  # 7 days
    "L3": 2592000,  # 30 days
}


class DisputeState(str, enum.Enum):
    """Dispute lifecycle states."""

    OPEN = "open"  # jury selection pending or voting
    VOTING = "voting"  # jury selected, votes in progress
    RESOLVED = "resolved"  # verdict rendered
    CANCELLED = "cancelled"  # cancelled (edge case)


class Verdict(str, enum.Enum):
    """Individual juror verdict."""

    CONSUMER = "consumer"
    PROVIDER = "provider"


class ResolutionOutcome(str, enum.Enum):
    """Final dispute resolution outcome."""

    CONSUMER_WINS = "consumer_wins"
    PROVIDER_WINS = "provider_wins"
    NO_MAJORITY = "no_majority"


@dataclass
class JurorVote:
    """A single juror's vote."""

    juror_id: str
    verdict: Verdict
    reason: str
    voted_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class DisputeRecord:
    """Full state of a dispute."""

    dispute_id: str
    invocation_id: str
    consumer_id: str
    provider_id: str
    reason: str
    dispute_fee: float = DISPUTE_FEE
    state: DisputeState = DisputeState.OPEN
    juror_ids: List[str] = field(default_factory=list)
    votes: List[JurorVote] = field(default_factory=list)
    juror_stakes: Dict[str, float] = field(default_factory=dict)
    evidence: List[Dict[str, str]] = field(default_factory=list)
    outcome: Optional[ResolutionOutcome] = None
    slash_amount: float = 0.0
    created_at: int = field(default_factory=lambda: int(time.time()))
    resolved_at: Optional[int] = None


@dataclass
class DisputeResolution:
    """Result of resolving a dispute."""

    dispute_id: str
    outcome: ResolutionOutcome
    consumer_refunded: bool
    provider_paid: bool
    slash_amount: float
    jury_reward: float
    jury_reward_per_juror: float
    majority_jurors: List[str] = field(default_factory=list)
    minority_jurors: List[str] = field(default_factory=list)


class DisputeError(Exception):
    """Raised on invalid dispute operations."""


class DisputeManager:
    """Manages disputes, jury selection, voting, and resolution.

    Parameters
    ----------
    get_invocation : callable
        (invocation_id) → record with .consumer_id, .provider_id,
        .capability_id, .state, .settled_at, .escrow_id, .price
    get_reputation : callable
        (agent_id) → float reputation score
    get_stake : callable
        (agent_id) → float staked amount
    escrow_refund : callable
        (escrow_id) → refund consumer escrow
    escrow_release : callable
        (escrow_id) → release escrow to provider
    slash_fn : callable or None
        (provider_id, amount, reason) → slash provider bond
    deposit_fn : callable or None
        (consumer_id, amount) → deposit funds to consumer balance
    get_manifest : callable or None
        (capability_id) → manifest with .staking.slash_dispute_lost
    """

    def __init__(
        self,
        get_invocation: Callable[[str], Any],
        get_reputation: Callable[[str], float],
        get_stake: Callable[[str], float],
        escrow_refund: Callable[[str], Any],
        escrow_release: Callable[[str], Any],
        slash_fn: Optional[Callable] = None,
        deposit_fn: Optional[Callable] = None,
        get_manifest: Optional[Callable] = None,
        reputation_update_fn: Optional[Callable[[str, float, str], None]] = None,
    ) -> None:
        self._get_invocation = get_invocation
        self._get_reputation = get_reputation
        self._get_stake = get_stake
        self._escrow_refund = escrow_refund
        self._escrow_release = escrow_release
        self._slash_fn = slash_fn
        self._deposit_fn = deposit_fn
        self._get_manifest = get_manifest
        self._reputation_update_fn: Callable[[str, float, str], None] = (
            reputation_update_fn if reputation_update_fn is not None
            else lambda agent_id, delta, reason: None
        )
        self._disputes: Dict[str, DisputeRecord] = {}
        self._by_invocation: Dict[str, str] = {}  # invocation_id → dispute_id
        self._counter = 0

    def open_dispute(
        self,
        invocation_id: str,
        consumer_id: str,
        reason: str,
        dispute_window: int = DEFAULT_DISPUTE_WINDOW,
        access_level: Optional[str] = None,
        now: Optional[int] = None,
    ) -> DisputeRecord:
        """Open a dispute for an invocation.

        Validates:
            - Consumer is the caller of the invocation
            - Within dispute_window after result submission
            - Invocation is completed (settled) or disputed
            - Not already disputed

        Consumer pays dispute_fee (anti-spam, refunded if they win).
        """
        if invocation_id in self._by_invocation:
            raise DisputeError(f"invocation {invocation_id} already has a dispute")

        inv = self._get_invocation(invocation_id)
        if inv is None:
            raise DisputeError(f"invocation not found: {invocation_id}")

        # Cannot dispute own invocation
        if inv.consumer_id == inv.provider_id:
            raise DisputeError("Cannot dispute own invocation")

        # Consumer must match
        if inv.consumer_id != consumer_id:
            raise DisputeError("only the consumer can open a dispute")

        # Must be completed (settled) to dispute the result
        state_val = inv.state.value if hasattr(inv.state, "value") else str(inv.state)
        if state_val not in ("completed", "disputed"):
            raise DisputeError(f"can only dispute completed invocations, got {state_val}")

        # Override dispute window to match access level liability window
        if access_level and access_level in DISPUTE_WINDOWS_BY_LEVEL:
            dispute_window = DISPUTE_WINDOWS_BY_LEVEL[access_level]

        # Check dispute window
        current_time = now if now is not None else int(time.time())
        settled_at = getattr(inv, "settled_at", None) or 0
        if settled_at > 0 and (current_time - settled_at) > dispute_window:
            raise DisputeError(
                f"dispute window expired: {current_time - settled_at}s " f"> {dispute_window}s"
            )

        # Generate dispute ID
        self._counter += 1
        dispute_id = hashlib.sha256(
            f"dispute:{invocation_id}:{self._counter}".encode()
        ).hexdigest()[:16]

        record = DisputeRecord(
            dispute_id=dispute_id,
            invocation_id=invocation_id,
            consumer_id=consumer_id,
            provider_id=inv.provider_id,
            reason=reason,
        )

        self._disputes[dispute_id] = record
        self._by_invocation[invocation_id] = dispute_id

        return record

    def select_jury(
        self,
        dispute_id: str,
        eligible_nodes: List[str],
        jury_size: int = DEFAULT_JURY_SIZE,
    ) -> List[str]:
        """Select jurors from eligible nodes, weighted by reputation.

        Filters:
            - reputation >= 50
            - not consumer, not provider

        Uses deterministic seed: sha256(dispute_id + juror_id) for ordering.
        """
        dispute = self._require_dispute(dispute_id, DisputeState.OPEN)

        # Filter eligible candidates (reputation + stake)
        candidates: List[str] = []
        for node_id in eligible_nodes:
            if node_id in (dispute.consumer_id, dispute.provider_id):
                continue
            rep = self._get_reputation(node_id)
            stake = self._get_stake(node_id)
            if rep >= MIN_JUROR_REPUTATION and stake >= JUROR_STAKE_REQUIRED:
                candidates.append(node_id)

        if len(candidates) < jury_size:
            raise DisputeError(f"not enough eligible jurors: {len(candidates)} < {jury_size}")

        # Deterministic weighted selection using hash-based scoring
        # Score = sha256(dispute_id + node_id) interpreted as int, weighted by reputation
        scored: List[tuple] = []
        for node_id in candidates:
            seed = hashlib.sha256((dispute_id + node_id).encode()).hexdigest()
            hash_val = int(seed[:16], 16)  # first 64 bits
            rep = self._get_reputation(node_id)
            # Normalize: use hash to create a [0,1) random value, then weight by rep
            random_val = hash_val / (2**64)  # normalize to [0, 1)
            # Use rep as a weight with diminishing returns to reduce bias
            weight = math.log1p(rep)  # log(1+rep) smooths the advantage
            score = random_val * weight
            scored.append((score, node_id))

        scored.sort(reverse=True)
        selected = [node_id for _, node_id in scored[:jury_size]]

        dispute.juror_ids = selected
        dispute.state = DisputeState.VOTING

        return selected

    def submit_vote(
        self,
        dispute_id: str,
        juror_id: str,
        verdict: str,
        reason: str = "",
    ) -> JurorVote:
        """Submit a juror's vote.

        Each juror votes once. Verdict must be 'consumer' or 'provider'.
        """
        dispute = self._require_dispute(dispute_id, DisputeState.VOTING)

        if juror_id not in dispute.juror_ids:
            raise DisputeError(f"{juror_id} is not a juror for this dispute")

        # Check for duplicate vote
        existing = [v for v in dispute.votes if v.juror_id == juror_id]
        if existing:
            raise DisputeError(f"juror {juror_id} has already voted")

        # Validate verdict
        try:
            verdict_enum = Verdict(verdict)
        except ValueError:
            raise DisputeError(f"invalid verdict '{verdict}', must be 'consumer' or 'provider'")

        vote = JurorVote(
            juror_id=juror_id,
            verdict=verdict_enum,
            reason=reason,
        )
        dispute.votes.append(vote)
        return vote

    def resolve(self, dispute_id: str) -> DisputeResolution:
        """Resolve a dispute based on jury votes.

        Requires 2/3 majority:
            - Consumer wins: slash provider, refund consumer escrow + dispute_fee,
              jury rewarded from slashed amount
            - Provider wins: release escrow to provider, consumer loses dispute_fee
              (goes to jury as compensation)
            - No majority: refund all, no slash
        """
        dispute = self._require_dispute(dispute_id, DisputeState.VOTING)

        jury_size = len(dispute.juror_ids)
        if len(dispute.votes) < jury_size:
            raise DisputeError(f"not all jurors have voted: {len(dispute.votes)}/{jury_size}")

        # Tally votes
        consumer_votes = sum(1 for v in dispute.votes if v.verdict == Verdict.CONSUMER)
        provider_votes = sum(1 for v in dispute.votes if v.verdict == Verdict.PROVIDER)

        threshold = jury_size * MAJORITY_THRESHOLD

        inv = self._get_invocation(dispute.invocation_id)

        if consumer_votes >= threshold:
            outcome = ResolutionOutcome.CONSUMER_WINS
            resolution = self._resolve_consumer_wins(dispute, inv)
        elif provider_votes >= threshold:
            outcome = ResolutionOutcome.PROVIDER_WINS
            resolution = self._resolve_provider_wins(dispute, inv)
        else:
            outcome = ResolutionOutcome.NO_MAJORITY
            resolution = self._resolve_no_majority(dispute, inv)

        # Populate majority/minority juror lists for reputation accountability
        winning_verdict = (
            Verdict.CONSUMER
            if outcome == ResolutionOutcome.CONSUMER_WINS
            else Verdict.PROVIDER
            if outcome == ResolutionOutcome.PROVIDER_WINS
            else None
        )
        if winning_verdict is not None:
            resolution.majority_jurors = [
                v.juror_id for v in dispute.votes if v.verdict == winning_verdict
            ]
            resolution.minority_jurors = [
                v.juror_id for v in dispute.votes if v.verdict != winning_verdict
            ]

        # Reputation updates based on outcome
        if outcome == ResolutionOutcome.CONSUMER_WINS:
            self._reputation_update_fn(dispute.provider_id, -10.0, "lost dispute")
        elif outcome == ResolutionOutcome.PROVIDER_WINS:
            self._reputation_update_fn(dispute.consumer_id, -5.0, "lost dispute")
        for juror_id in resolution.majority_jurors:
            self._reputation_update_fn(juror_id, +1.0, "correct jury vote")
        for juror_id in resolution.minority_jurors:
            self._reputation_update_fn(juror_id, -2.0, "incorrect jury vote")

        dispute.outcome = outcome
        dispute.state = DisputeState.RESOLVED
        dispute.resolved_at = int(time.time())

        return resolution

    def get_dispute(self, dispute_id: str) -> Optional[DisputeRecord]:
        """Return dispute record by ID."""
        return self._disputes.get(dispute_id)

    def get_dispute_by_invocation(self, invocation_id: str) -> Optional[DisputeRecord]:
        """Return dispute record by invocation ID."""
        dispute_id = self._by_invocation.get(invocation_id)
        if dispute_id is None:
            return None
        return self._disputes.get(dispute_id)

    def submit_evidence(
        self,
        dispute_id: str,
        party_id: str,
        evidence_hash: str,
        description: str = "",
    ) -> None:
        """Submit evidence for a dispute. Both consumer and provider can submit."""
        dispute = self._disputes.get(dispute_id)
        if dispute is None:
            raise DisputeError(f"dispute not found: {dispute_id}")

        if dispute.state not in (DisputeState.OPEN, DisputeState.VOTING):
            raise DisputeError(
                f"cannot submit evidence in state {dispute.state.value}, "
                "must be open or voting"
            )

        if party_id not in (dispute.consumer_id, dispute.provider_id):
            raise DisputeError(
                f"{party_id} is not a party to this dispute "
                "(must be consumer or provider)"
            )

        dispute.evidence.append(
            {
                "party_id": party_id,
                "evidence_hash": evidence_hash,
                "description": description,
                "submitted_at": str(int(time.time())),
            }
        )

    def resolve_timeout(
        self, dispute_id: str, now: Optional[int] = None
    ) -> DisputeResolution:
        """Auto-resolve if voting deadline has passed without all votes.

        If current_time > dispute.created_at + VOTING_DEADLINE and not all
        votes submitted:
          - Count existing votes
          - If majority exists among submitted votes, use that outcome
          - If no majority (or no votes), outcome = NO_MAJORITY -> refund
            consumer fee
          - Mark dispute as RESOLVED
        """
        dispute = self._disputes.get(dispute_id)
        if dispute is None:
            raise DisputeError(f"dispute not found: {dispute_id}")
        if dispute.state == DisputeState.RESOLVED:
            raise DisputeError(f"dispute {dispute_id} is already resolved")
        if dispute.state == DisputeState.CANCELLED:
            raise DisputeError(f"dispute {dispute_id} is cancelled")

        current_time = now if now is not None else int(time.time())
        deadline = dispute.created_at + VOTING_DEADLINE

        if current_time <= deadline:
            raise DisputeError(
                f"voting deadline has not passed yet "
                f"({deadline - current_time}s remaining)"
            )

        jury_size = len(dispute.juror_ids)
        # If all votes are in, use normal resolve()
        if jury_size > 0 and len(dispute.votes) >= jury_size:
            return self.resolve(dispute_id)

        # Count existing votes
        consumer_votes = sum(
            1 for v in dispute.votes if v.verdict == Verdict.CONSUMER
        )
        provider_votes = sum(
            1 for v in dispute.votes if v.verdict == Verdict.PROVIDER
        )

        inv = self._get_invocation(dispute.invocation_id)

        # Determine outcome from submitted votes
        total_votes = consumer_votes + provider_votes
        if total_votes > 0 and consumer_votes > provider_votes:
            outcome = ResolutionOutcome.CONSUMER_WINS
            resolution = self._resolve_consumer_wins(dispute, inv)
        elif total_votes > 0 and provider_votes > consumer_votes:
            outcome = ResolutionOutcome.PROVIDER_WINS
            resolution = self._resolve_provider_wins(dispute, inv)
        else:
            # No votes, tied, or no majority
            outcome = ResolutionOutcome.NO_MAJORITY
            resolution = self._resolve_no_majority(dispute, inv)

        # Populate majority/minority juror lists
        winning_verdict = (
            Verdict.CONSUMER
            if outcome == ResolutionOutcome.CONSUMER_WINS
            else Verdict.PROVIDER
            if outcome == ResolutionOutcome.PROVIDER_WINS
            else None
        )
        if winning_verdict is not None:
            resolution.majority_jurors = [
                v.juror_id
                for v in dispute.votes
                if v.verdict == winning_verdict
            ]
            resolution.minority_jurors = [
                v.juror_id
                for v in dispute.votes
                if v.verdict != winning_verdict
            ]

        # Reputation updates based on outcome
        if outcome == ResolutionOutcome.CONSUMER_WINS:
            self._reputation_update_fn(dispute.provider_id, -10.0, "lost dispute")
        elif outcome == ResolutionOutcome.PROVIDER_WINS:
            self._reputation_update_fn(dispute.consumer_id, -5.0, "lost dispute")
        for juror_id in resolution.majority_jurors:
            self._reputation_update_fn(juror_id, +1.0, "correct jury vote")
        for juror_id in resolution.minority_jurors:
            self._reputation_update_fn(juror_id, -2.0, "incorrect jury vote")

        dispute.outcome = outcome
        dispute.state = DisputeState.RESOLVED
        dispute.resolved_at = current_time

        return resolution

    # ── Resolution helpers ───────────────────────────────────────────

    def _resolve_consumer_wins(
        self,
        dispute: DisputeRecord,
        inv: Any,
    ) -> DisputeResolution:
        """Consumer wins: slash provider, refund consumer, reward jury."""
        # Determine slash ratio from capability staking config
        slash_ratio = 0.20  # default from spec
        if self._get_manifest is not None:
            manifest = self._get_manifest(getattr(inv, "capability_id", ""))
            if manifest is not None and hasattr(manifest, "staking"):
                slash_ratio = getattr(manifest.staking, "slash_dispute_lost", slash_ratio)

        # Slash provider bond
        slash_amount = 0.0
        if self._slash_fn is not None:
            provider_stake = self._get_stake(dispute.provider_id)
            slash_amount = provider_stake * slash_ratio
            if slash_amount > 0:
                self._slash_fn(
                    dispute.provider_id,
                    slash_amount,
                    f"dispute {dispute.dispute_id}: consumer wins",
                )

        # Refund consumer: escrow amount + dispute fee
        if self._deposit_fn is not None:
            escrow_amount = getattr(inv, "price", 0.0)
            self._deposit_fn(dispute.consumer_id, escrow_amount + dispute.dispute_fee)

        # Fixed jury reward — independent of outcome to eliminate bias
        jury_size = len(dispute.juror_ids)
        jury_reward = JUROR_REWARD_FIXED * jury_size
        jury_reward_per_juror = JUROR_REWARD_FIXED

        dispute.slash_amount = slash_amount

        return DisputeResolution(
            dispute_id=dispute.dispute_id,
            outcome=ResolutionOutcome.CONSUMER_WINS,
            consumer_refunded=True,
            provider_paid=False,
            slash_amount=slash_amount,
            jury_reward=jury_reward,
            jury_reward_per_juror=jury_reward_per_juror,
        )

    def _resolve_provider_wins(
        self,
        dispute: DisputeRecord,
        inv: Any,
    ) -> DisputeResolution:
        """Provider wins: release escrow, consumer loses dispute fee.

        Jury reward is fixed — same as consumer_wins to eliminate incentive bias.
        """
        jury_size = len(dispute.juror_ids)
        jury_reward = JUROR_REWARD_FIXED * jury_size
        jury_reward_per_juror = JUROR_REWARD_FIXED

        return DisputeResolution(
            dispute_id=dispute.dispute_id,
            outcome=ResolutionOutcome.PROVIDER_WINS,
            consumer_refunded=False,
            provider_paid=True,
            slash_amount=0.0,
            jury_reward=jury_reward,
            jury_reward_per_juror=jury_reward_per_juror,
        )

    def _resolve_no_majority(
        self,
        dispute: DisputeRecord,
        inv: Any,
    ) -> DisputeResolution:
        """No majority: refund all, no slash. Jurors still get fixed reward."""
        # Refund dispute fee to consumer
        if self._deposit_fn is not None:
            self._deposit_fn(dispute.consumer_id, dispute.dispute_fee)

        jury_size = len(dispute.juror_ids)
        jury_reward = JUROR_REWARD_FIXED * jury_size
        jury_reward_per_juror = JUROR_REWARD_FIXED

        return DisputeResolution(
            dispute_id=dispute.dispute_id,
            outcome=ResolutionOutcome.NO_MAJORITY,
            consumer_refunded=True,
            provider_paid=False,
            slash_amount=0.0,
            jury_reward=jury_reward,
            jury_reward_per_juror=jury_reward_per_juror,
        )

    # ── Internal helpers ─────────────────────────────────────────────

    def _require_dispute(
        self,
        dispute_id: str,
        expected: DisputeState,
    ) -> DisputeRecord:
        dispute = self._disputes.get(dispute_id)
        if dispute is None:
            raise DisputeError(f"dispute not found: {dispute_id}")
        if dispute.state != expected:
            raise DisputeError(
                f"dispute {dispute_id} is {dispute.state.value}, " f"expected {expected.value}"
            )
        return dispute

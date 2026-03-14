"""
Reputation Engine — Agent Trust Scoring for Access Control

Tracks per-agent reputation scores that influence bond discounts and
sandbox restrictions.

Update formula:
  R(t+1) = R(t) + α·S − β·D − γ·L − δ·T

  α = +5   successful access
  β = −10  data damage / wrong result
  γ = −50  watermark leak detected
  δ = −5   time decay (every 90 days)

  Initial score = 10  (sandbox mode)
  Floor          = 50 (after decay only — penalties can go lower)
  Sandbox mode   = R < 20 → agent restricted to L0
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from oasyce_plugin.services.access.config import AccessControlConfig


# ─── Agent record ─────────────────────────────────────────────────

@dataclass
class AgentReputation:
    """Mutable reputation state for a single agent."""
    score: float
    last_decay_check: float  # epoch seconds
    access_count: int = 0


# ─── ReputationEngine ─────────────────────────────────────────────

class ReputationEngine:
    """Manages per-agent reputation scores.

    Scores start at `rep_initial` (default 10, sandbox mode).
    Updated via `update()` after each access event.
    Decay is applied lazily on every read/update.
    """

    def __init__(self, config: Optional[AccessControlConfig] = None) -> None:
        self.config = config or AccessControlConfig()
        self._agents: Dict[str, AgentReputation] = {}

    # ─── Public API ───────────────────────────────────────────────

    def get_reputation(self, agent_id: str) -> float:
        """Return current reputation score, applying any pending decay."""
        agent = self._ensure_agent(agent_id)
        self._decay(agent)
        return round(agent.score, 6)

    def update(
        self,
        agent_id: str,
        success: bool = False,
        data_delivered: bool = False,
        leak_detected: bool = False,
        time_since_last: float = 0.0,
    ) -> float:
        """Apply reputation deltas and return updated score.

        Args:
            success: +α if True (successful access completed)
            data_delivered: no direct effect (reserved for future use)
            leak_detected: −γ if True (watermark leak)
            time_since_last: days since last interaction (manual decay trigger)

        Returns:
            Updated reputation score.
        """
        agent = self._ensure_agent(agent_id)
        self._decay(agent)

        if success:
            agent.score += self.config.rep_success
            agent.access_count += 1

        if not success and not leak_detected:
            # data damage / error
            agent.score += self.config.rep_damage

        if leak_detected:
            agent.score += self.config.rep_leak

        # Manual time-based penalty (days → decay periods)
        if time_since_last > 0:
            periods = int(time_since_last / self.config.rep_decay_days)
            if periods > 0:
                agent.score += self.config.rep_decay_amount * periods
                agent.score = max(agent.score, self.config.rep_floor)

        # Score cannot go below 0
        agent.score = max(agent.score, 0.0)
        return round(agent.score, 6)

    def get_bond_discount(self, agent_id: str) -> float:
        """Return bond discount factor: (1 - R/100).

        Higher reputation → lower bond.  R=100 → factor=0, R=0 → factor=1.
        """
        rep = self.get_reputation(agent_id)
        return round(1.0 - rep / 100.0, 6)

    # ─── Internals ────────────────────────────────────────────────

    def _ensure_agent(self, agent_id: str) -> AgentReputation:
        """Lazily create agent record with initial score."""
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentReputation(
                score=self.config.rep_initial,
                last_decay_check=time.time(),
            )
        return self._agents[agent_id]

    def _decay(self, agent: AgentReputation) -> None:
        """Apply time-based decay: −δ per decay_days elapsed."""
        now = time.time()
        elapsed = now - agent.last_decay_check
        period_seconds = self.config.rep_decay_days * 86400
        periods = int(elapsed / period_seconds)

        if periods > 0:
            agent.score += self.config.rep_decay_amount * periods
            agent.score = max(agent.score, self.config.rep_floor)
            agent.last_decay_check += periods * period_seconds


__all__ = ["ReputationEngine", "AgentReputation"]

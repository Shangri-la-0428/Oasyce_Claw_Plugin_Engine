"""Access control configuration — all tunable parameters in one frozen dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccessControlConfig:
    """Immutable configuration for the access-control subsystem.

    Groups: access multipliers, reputation parameters, liability windows,
    risk factors, and sandbox limits.
    """

    # ─── Access level bond multipliers ────────────────────────────
    L0_multiplier: float = 1.0
    L1_multiplier: float = 2.0
    L2_multiplier: float = 3.0
    L3_multiplier: float = 15.0  # raised from 5.0 — reflects full data exposure risk

    # ─── Reputation parameters ────────────────────────────────────
    rep_initial: float = 0.0  # start at 0, not sandbox — agents must earn trust
    rep_success: float = 2.0  # α — successful access (lowered from 5.0 for Sybil resistance)
    rep_damage: float = -10.0  # β — data damage / error
    rep_leak: float = -50.0  # γ — watermark leak detected
    rep_decay_days: int = 90  # decay period
    rep_decay_amount: float = -5.0  # δ — per decay period
    rep_floor: float = 0.0  # absolute minimum — punished agents can decay to 0
    rep_cap: float = 95.0  # absolute maximum — prevents zero/negative bonds
    rep_max_gain_per_day: float = 5.0  # max reputation gain in 24h (lowered from 20)
    rep_nonlinear_half: float = 50.0  # score at which gain rate halves (diminishing returns)
    bond_discount_floor: float = 0.20  # minimum bond = 20% of base (raised from 5%)

    # ─── Minimum stake for high-level access ────────────────────
    min_stake_l2: float = 100.0  # OAS staked to access L2 (independent of reputation)
    min_stake_l3: float = 500.0  # OAS staked to access L3

    # ─── Liability windows (seconds) ─────────────────────────────
    L0_window: int = 86400  # 1 day
    L1_window: int = 259200  # 3 days
    L2_window: int = 604800  # 7 days
    L3_window: int = 2592000  # 30 days

    # ─── Risk factor by risk_level ────────────────────────────────
    risk_public: float = 1.0
    risk_low: float = 1.2
    risk_medium: float = 1.5
    risk_high: float = 2.0
    risk_critical: float = 3.0

    # ─── Sandbox mode ─────────────────────────────────────────────
    sandbox_threshold: float = 20.0
    sandbox_daily_limit: int = 10
    limited_threshold: float = 50.0  # R >= 50 for full access (L2/L3)

    # ─── Fragmentation detection ──────────────────────────────────
    fragmentation_penalty: float = 2.0  # bond multiplier when fragmentation detected

    # ─── Helpers ──────────────────────────────────────────────────

    def multiplier_for(self, level_value: str) -> float:
        """Return bond multiplier for a given access level value string."""
        return {
            "L0": self.L0_multiplier,
            "L1": self.L1_multiplier,
            "L2": self.L2_multiplier,
            "L3": self.L3_multiplier,
        }[level_value]

    def window_for(self, level_value: str) -> int:
        """Return liability window (seconds) for a given access level."""
        return {
            "L0": self.L0_window,
            "L1": self.L1_window,
            "L2": self.L2_window,
            "L3": self.L3_window,
        }[level_value]

    def risk_factor_for(self, risk_level: str) -> float:
        """Return risk factor for a given risk_level string."""
        return {
            "public": self.risk_public,
            "low": self.risk_low,
            "medium": self.risk_medium,
            "high": self.risk_high,
            "critical": self.risk_critical,
        }.get(risk_level, self.risk_public)

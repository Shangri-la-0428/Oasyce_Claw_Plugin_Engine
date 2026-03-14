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
    L3_multiplier: float = 5.0

    # ─── Reputation parameters ────────────────────────────────────
    rep_initial: float = 10.0
    rep_success: float = 5.0       # α — successful access
    rep_damage: float = -10.0      # β — data damage / error
    rep_leak: float = -50.0        # γ — watermark leak detected
    rep_decay_days: int = 90       # decay period
    rep_decay_amount: float = -5.0 # δ — per decay period
    rep_floor: float = 50.0        # absolute minimum (after decay)
    rep_cap: float = 95.0          # absolute maximum — prevents zero/negative bonds
    rep_max_gain_per_day: float = 20.0  # max reputation gain in a 24h rolling window
    bond_discount_floor: float = 0.05   # minimum bond discount factor (1 - R/100 ≥ this)

    # ─── Liability windows (seconds) ─────────────────────────────
    L0_window: int = 86400         # 1 day
    L1_window: int = 259200        # 3 days
    L2_window: int = 604800        # 7 days
    L3_window: int = 2592000       # 30 days

    # ─── Risk factor by risk_level ────────────────────────────────
    risk_public: float = 1.0
    risk_low: float = 1.2
    risk_medium: float = 1.5
    risk_high: float = 2.0
    risk_critical: float = 3.0

    # ─── Sandbox mode ─────────────────────────────────────────────
    sandbox_threshold: float = 20.0
    sandbox_daily_limit: int = 10

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

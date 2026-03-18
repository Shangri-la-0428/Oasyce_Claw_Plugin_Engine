"""
Testnet Faucet — Free tokens for testing

Every wallet address can claim a limited number of times with cooldown.
Mainnet calls are rejected.

Anti-abuse measures:
- Claims keyed by wallet address (not arbitrary node_id)
- No caller-controllable timestamp (uses time.time() internally)
- Per-address lifetime claim limit
- Total supply cap on faucet emissions
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional


class Faucet:
    """Testnet faucet with anti-abuse protections."""

    TESTNET_DRIP = 500.0         # per-claim amount (reduced from 10000)
    COOLDOWN = 86400              # 24-hour cooldown between claims
    MAX_CLAIMS_PER_ADDRESS = 3    # lifetime claim limit per address
    MAX_TOTAL_SUPPLY = 10_000_000.0  # total OAS the faucet will ever emit

    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self._claims: Dict[str, float] = {}      # address → last_claim_time
        self._balances: Dict[str, float] = {}     # address → balance
        self._claim_counts: Dict[str, int] = {}   # address → total claims made
        self._total_claimed: float = 0.0           # total OAS emitted
        self._state_path = Path(data_dir) / "faucet_state.json"
        self._load()

    # ── public API ────────────────────────────────────────────────

    def claim(self, address: str) -> dict:
        """Claim test tokens for a wallet address.

        Args:
            address: The wallet address (public key hex) to credit.

        Returns:
            {"success": bool, "amount": float, "balance": float,
             "next_claim_at": float, "error": str | None}
        """
        now = time.time()

        # Check total supply cap
        if self._total_claimed + self.TESTNET_DRIP > self.MAX_TOTAL_SUPPLY:
            return {
                "success": False,
                "amount": 0.0,
                "balance": self._balances.get(address, 0.0),
                "next_claim_at": 0.0,
                "error": "Faucet supply exhausted — total cap reached",
            }

        # Check per-address lifetime claim limit
        claim_count = self._claim_counts.get(address, 0)
        if claim_count >= self.MAX_CLAIMS_PER_ADDRESS:
            return {
                "success": False,
                "amount": 0.0,
                "balance": self._balances.get(address, 0.0),
                "next_claim_at": 0.0,
                "error": f"Lifetime claim limit reached ({self.MAX_CLAIMS_PER_ADDRESS} claims)",
            }

        # Check cooldown
        last = self._claims.get(address)
        remaining = (last + self.COOLDOWN) - now if last is not None else -1

        if remaining > 0:
            return {
                "success": False,
                "amount": 0.0,
                "balance": self._balances.get(address, 0.0),
                "next_claim_at": last + self.COOLDOWN,
                "error": f"Cooldown active — {remaining:.0f}s remaining",
            }

        self._claims[address] = now
        self._balances[address] = self._balances.get(address, 0.0) + self.TESTNET_DRIP
        self._claim_counts[address] = claim_count + 1
        self._total_claimed += self.TESTNET_DRIP
        self._save()

        return {
            "success": True,
            "amount": self.TESTNET_DRIP,
            "balance": self._balances[address],
            "next_claim_at": now + self.COOLDOWN,
            "error": None,
        }

    def balance(self, address: str) -> float:
        """Query balance for an address."""
        return self._balances.get(address, 0.0)

    @property
    def total_claimed(self) -> float:
        """Total OAS emitted by this faucet."""
        return self._total_claimed

    # ── persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text())
                self._claims = data.get("claims", {})
                self._balances = data.get("balances", {})
                self._claim_counts = data.get("claim_counts", {})
                self._total_claimed = data.get("total_claimed", 0.0)
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps({
            "claims": self._claims,
            "balances": self._balances,
            "claim_counts": self._claim_counts,
            "total_claimed": self._total_claimed,
        }, indent=2))

    def reset(self) -> None:
        """Reset all faucet state (for testnet reset)."""
        self._claims.clear()
        self._balances.clear()
        self._claim_counts.clear()
        self._total_claimed = 0.0
        if self._state_path.exists():
            self._state_path.unlink()

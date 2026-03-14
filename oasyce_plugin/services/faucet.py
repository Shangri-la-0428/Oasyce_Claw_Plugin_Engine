"""
Testnet Faucet — Free tokens for testing

Every node can claim once per 24 hours.  Mainnet calls are rejected.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, Optional


class Faucet:
    """Testnet 水龙头 — 每个节点每天可领一次"""

    TESTNET_DRIP = 10000.0   # 每次领取量（足够质押成 validator）
    COOLDOWN = 86400          # 24 小时冷却

    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self._claims: Dict[str, float] = {}  # node_id → last_claim_time
        self._balances: Dict[str, float] = {}  # node_id → balance
        self._state_path = Path(data_dir) / "faucet_state.json"
        self._load()

    # ── public API ────────────────────────────────────────────────

    def claim(self, node_id: str, now: Optional[float] = None) -> dict:
        """领取测试代币。

        Returns:
            {"success": bool, "amount": float, "balance": float,
             "next_claim_at": float, "error": str | None}
        """
        now = now if now is not None else time.time()
        last = self._claims.get(node_id)
        remaining = (last + self.COOLDOWN) - now if last is not None else -1

        if remaining > 0:
            return {
                "success": False,
                "amount": 0.0,
                "balance": self._balances.get(node_id, 0.0),
                "next_claim_at": last + self.COOLDOWN,
                "error": f"Cooldown active — {remaining:.0f}s remaining",
            }

        self._claims[node_id] = now
        self._balances[node_id] = self._balances.get(node_id, 0.0) + self.TESTNET_DRIP
        self._save()

        return {
            "success": True,
            "amount": self.TESTNET_DRIP,
            "balance": self._balances[node_id],
            "next_claim_at": now + self.COOLDOWN,
            "error": None,
        }

    def balance(self, node_id: str) -> float:
        """查询余额"""
        return self._balances.get(node_id, 0.0)

    # ── persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text())
                self._claims = data.get("claims", {})
                self._balances = data.get("balances", {})
            except (json.JSONDecodeError, OSError):
                pass

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps({
            "claims": self._claims,
            "balances": self._balances,
        }, indent=2))

    def reset(self) -> None:
        """Reset all faucet state (for testnet reset)."""
        self._claims.clear()
        self._balances.clear()
        if self._state_path.exists():
            self._state_path.unlink()

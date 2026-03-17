"""
Testnet Onboarding — guide new nodes from zero to validator in one call.

Flow: claim faucet → register sample asset → stake as validator
"""

from __future__ import annotations

import hashlib
import time
from typing import Optional

from oasyce_plugin.config import (
    TESTNET_ECONOMICS,
    NetworkMode,
    get_data_dir,
)
from oasyce_plugin.services.faucet import Faucet


class TestnetOnboarding:
    """Testnet 新用户引导"""

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir or get_data_dir(NetworkMode.TESTNET)
        self._faucet = Faucet(self._data_dir)

    @property
    def faucet(self) -> Faucet:
        return self._faucet

    def onboard(self, node_id: str, now: Optional[float] = None) -> dict:
        """一键引导：领币 → 注册示例资产 → 质押

        Returns dict with keys:
            faucet_result, sample_asset, stake_result, summary
        """
        now = now if now is not None else time.time()
        result: dict = {
            "mode": "LOCAL_SIMULATION",
            "faucet_result": None,
            "sample_asset": None,
            "stake_result": None,
            "summary": ["[LOCAL SIMULATION] All testnet operations run locally — no real network or tokens."],
        }

        # 1. 领取水龙头代币
        faucet_result = self._faucet.claim(node_id, now=now)
        result["faucet_result"] = faucet_result
        if faucet_result["success"]:
            result["summary"].append(
                f"Claimed {faucet_result['amount']:.0f} OAS from faucet"
            )
        else:
            result["summary"].append(
                f"Faucet skipped — {faucet_result['error']}"
            )

        # 2. 注册示例数据资产
        sample_asset = self._register_sample_asset(node_id)
        result["sample_asset"] = sample_asset
        result["summary"].append(
            f"Sample asset registered: {sample_asset['asset_id']}"
        )

        # 3. 尝试质押成为 validator
        balance = self._faucet.balance(node_id)
        min_stake = TESTNET_ECONOMICS["min_stake"]
        if balance >= min_stake:
            stake_result = {
                "staked": True,
                "amount": min_stake,
                "remaining": balance - min_stake,
            }
            result["stake_result"] = stake_result
            result["summary"].append(
                f"Staked {min_stake:.0f} OAS — validator active"
            )
        else:
            result["stake_result"] = {
                "staked": False,
                "amount": 0.0,
                "remaining": balance,
                "reason": f"Balance {balance:.0f} < min_stake {min_stake:.0f}",
            }
            result["summary"].append(
                f"Stake skipped — need {min_stake:.0f} OAS, have {balance:.0f}"
            )

        return result

    @staticmethod
    def _register_sample_asset(node_id: str) -> dict:
        """Create a synthetic sample asset for onboarding demo."""
        content = f"testnet-sample-{node_id}-{time.time()}"
        media_hash = hashlib.sha256(content.encode()).hexdigest()
        asset_id = f"OAS_TEST_{media_hash[:8].upper()}"
        return {
            "asset_id": asset_id,
            "media_hash": media_hash,
            "creator": node_id,
            "type": "sample",
        }

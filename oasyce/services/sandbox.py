"""
Local sandbox onboarding — guide a local sandbox node from zero to validator.

Flow: claim local faucet → register sample asset → stake as validator
"""

from __future__ import annotations

import hashlib
import time
from typing import Optional

from oasyce.config import SANDBOX_ECONOMICS, get_sandbox_data_dir
from oasyce.services.faucet import Faucet
from oasyce.utils import from_units


class SandboxOnboardingService:
    """Local sandbox onboarding flow."""

    def __init__(self, data_dir: Optional[str] = None):
        self._data_dir = data_dir or get_sandbox_data_dir()
        self._faucet = Faucet(self._data_dir)

    @property
    def faucet(self) -> Faucet:
        return self._faucet

    def onboard(self, address: str) -> dict:
        """Local sandbox onboarding: faucet -> sample asset -> stake."""
        result: dict = {
            "mode": "LOCAL_SIMULATION",
            "network": "sandbox",
            "faucet_result": None,
            "sample_asset": None,
            "stake_result": None,
            "summary": [
                "[LOCAL SIMULATION] All sandbox operations run locally — no real network or tokens."
            ],
        }

        faucet_result = self._faucet.claim(address)
        result["faucet_result"] = faucet_result
        if faucet_result["success"]:
            result["summary"].append(f"Claimed {faucet_result['amount']:.0f} OAS from faucet")
        else:
            result["summary"].append(f"Faucet skipped — {faucet_result['error']}")

        sample_asset = self._register_sample_asset(address)
        result["sample_asset"] = sample_asset
        result["summary"].append(f"Sample asset registered: {sample_asset['asset_id']}")

        balance = self._faucet.balance(address)
        min_stake = from_units(SANDBOX_ECONOMICS["min_stake"])
        if balance >= min_stake:
            stake_result = {
                "staked": True,
                "amount": min_stake,
                "remaining": balance - min_stake,
            }
            result["stake_result"] = stake_result
            result["summary"].append(f"Staked {min_stake:.0f} OAS — validator active")
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
        """Create a synthetic sample asset for sandbox onboarding."""
        content = f"sandbox-sample-{node_id}-{time.time()}"
        media_hash = hashlib.sha256(content.encode()).hexdigest()
        asset_id = f"OAS_TEST_{media_hash[:8].upper()}"
        return {
            "asset_id": asset_id,
            "media_hash": media_hash,
            "creator": node_id,
            "type": "sample",
        }

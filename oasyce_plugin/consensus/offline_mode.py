"""
Offline mode manager — graceful degradation strategy.

Classifies features into three tiers based on network dependency:
  CRITICAL   — always available (local-only operations)
  DEGRADED   — available with cached data when offline
  UNAVAILABLE — requires live network connectivity
"""

from __future__ import annotations

from typing import Optional

from oasyce_plugin.consensus.network.offline_detector import OfflineDetector
from oasyce_plugin.consensus.provider_cache import ProviderCache


# Feature classifications
CRITICAL = [
    "view_own_assets",
    "sign_operation",
    "local_query",
    "view_balance",
    "view_validators_local",
    "view_delegations",
    "view_unbondings",
    "replay_events",
    "key_management",
]

DEGRADED = [
    "browse_network",
    "search_providers",
    "view_consensus_status",
    "view_chain_info",
    "browse_capabilities",
]

UNAVAILABLE = [
    "register_asset",
    "transfer",
    "discover_live",
    "delegate_stake",
    "undelegate_stake",
    "register_validator",
    "submit_proposal",
    "cast_vote",
    "sync_blocks",
    "testnet_faucet",
]

# Human-readable descriptions
_FEATURE_LABELS = {
    "view_own_assets": "View your assets",
    "sign_operation": "Sign operations",
    "local_query": "Query local data",
    "view_balance": "View balance",
    "view_validators_local": "View local validator list",
    "view_delegations": "View delegations",
    "view_unbondings": "View unbondings",
    "replay_events": "Replay stake events",
    "key_management": "Key management",
    "browse_network": "Browse network (cached)",
    "search_providers": "Search providers (cached)",
    "view_consensus_status": "View consensus status (cached)",
    "view_chain_info": "View chain info (cached)",
    "browse_capabilities": "Browse capabilities (cached)",
    "register_asset": "Register asset",
    "transfer": "Transfer assets",
    "discover_live": "Live discovery",
    "delegate_stake": "Delegate stake",
    "undelegate_stake": "Undelegate stake",
    "register_validator": "Register validator",
    "submit_proposal": "Submit governance proposal",
    "cast_vote": "Vote on proposal",
    "sync_blocks": "Sync blocks from peers",
    "testnet_faucet": "Claim testnet tokens",
}

# Map CLI commands to features for automatic checking
COMMAND_FEATURE_MAP = {
    "register": "register_asset",
    "transfer": "transfer",
    "buy": "register_asset",
    "search": "search_providers",
    "quote": "browse_network",
    "consensus_register": "register_validator",
    "consensus_delegate": "delegate_stake",
    "consensus_undelegate": "undelegate_stake",
    "consensus_exit": "register_validator",
    "consensus_unjail": "register_validator",
    "consensus_status": "view_consensus_status",
    "consensus_validators": "view_validators_local",
    "consensus_delegations": "view_delegations",
    "consensus_unbondings": "view_unbondings",
    "sync": "sync_blocks",
    "governance_propose": "submit_proposal",
    "governance_vote": "cast_vote",
    "testnet_faucet": "testnet_faucet",
    "discover": "discover_live",
    "balance": "view_balance",
    "replay": "replay_events",
    "keys": "key_management",
}


class OfflineModeManager:
    """Manages feature availability based on network connectivity."""

    def __init__(
        self,
        detector: Optional[OfflineDetector] = None,
        cache: Optional[ProviderCache] = None,
    ):
        self.detector = detector or OfflineDetector()
        self.cache = cache

    def get_connectivity_status(self) -> str:
        """Return current connectivity: online/degraded/offline."""
        return self.detector.get_status()

    def get_available_features(self, connectivity_status: Optional[str] = None) -> list[str]:
        """Return list of available feature names for the given connectivity."""
        if connectivity_status is None:
            connectivity_status = self.detector.get_status()

        if connectivity_status == "online":
            return CRITICAL + DEGRADED + UNAVAILABLE

        if connectivity_status == "degraded":
            return CRITICAL + DEGRADED

        # offline
        return list(CRITICAL)

    def get_unavailable_features(self, connectivity_status: Optional[str] = None) -> list[str]:
        """Return list of unavailable feature names."""
        if connectivity_status is None:
            connectivity_status = self.detector.get_status()

        available = set(self.get_available_features(connectivity_status))
        all_features = set(CRITICAL + DEGRADED + UNAVAILABLE)
        return sorted(all_features - available)

    def is_feature_available(self, feature: str, connectivity_status: Optional[str] = None) -> bool:
        """Check if a specific feature is available."""
        return feature in self.get_available_features(connectivity_status)

    def get_feature_tier(self, feature: str) -> str:
        """Return the tier of a feature: critical/degraded/unavailable."""
        if feature in CRITICAL:
            return "critical"
        if feature in DEGRADED:
            return "degraded"
        if feature in UNAVAILABLE:
            return "unavailable"
        return "unknown"

    def get_unavailable_reason(self, feature: str) -> str:
        """Return a user-friendly explanation of why a feature is unavailable."""
        status = self.detector.get_status()
        tier = self.get_feature_tier(feature)
        label = _FEATURE_LABELS.get(feature, feature)

        if status == "online":
            return ""

        if tier == "critical":
            return ""  # always available

        if tier == "degraded":
            if status == "offline":
                has_cache = self.cache is not None
                if has_cache:
                    cached = self.cache.get_all_cached(include_expired=True)
                    if cached:
                        return (
                            f"Offline mode: '{label}' using cached data "
                            f"({len(cached)} entries, may be stale)"
                        )
                return f"Offline mode: '{label}' unavailable — no cached data"
            return ""  # degraded status, degraded features still work

        # unavailable tier
        if status == "offline":
            return f"Offline mode: '{label}' requires network connectivity. Please reconnect and retry."
        else:
            return (
                f"Degraded mode: '{label}' requires stable network. "
                f"Connection is unstable — please wait or retry."
            )

    def check_command(self, command_name: str) -> tuple[bool, str]:
        """Check if a CLI command can proceed. Returns (allowed, message).

        If allowed is False, message contains the reason.
        If allowed is True and message is non-empty, it's a warning (e.g., using cached data).
        """
        feature = COMMAND_FEATURE_MAP.get(command_name)
        if feature is None:
            return True, ""  # unknown command → allow

        status = self.detector.get_status()
        available = self.is_feature_available(feature, status)

        if available:
            tier = self.get_feature_tier(feature)
            if tier == "degraded" and status != "online":
                return True, f"⚠ Degraded mode: showing cached data (may be stale)"
            return True, ""

        reason = self.get_unavailable_reason(feature)
        return False, reason

    def summary(self) -> dict:
        """Return a summary of current offline mode state."""
        status = self.detector.get_status()
        available = self.get_available_features(status)
        unavailable = self.get_unavailable_features(status)
        cache_stats = self.cache.stats() if self.cache else None

        return {
            "connectivity": status,
            "available_count": len(available),
            "unavailable_count": len(unavailable),
            "available_features": available,
            "unavailable_features": unavailable,
            "cache": cache_stats,
        }

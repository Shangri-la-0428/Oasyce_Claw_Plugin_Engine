"""
OAS-Identity: Oasyce Identity Asset Standard

Defines the standard schema for identity assets — the "who" layer of
the Oasyce network. Every Agent, node, and human participant has an
identity that carries reputation, capabilities, and economic history.

Core insight: Identity has long-term cost (Law #3). A trustworthy
identity is expensive to build and easy to destroy. This creates
natural Sybil resistance — spinning up 1000 fake identities costs
1000 × Anti-Sybil deposit, and each starts in sandbox mode (R=10).

Identity types:
  - AGENT:  Autonomous AI agent (bot, model, pipeline)
  - NODE:   Network node (validator, relay, storage)
  - HUMAN:  Human operator (DID/Passkey binding)
  - ORG:    Organization (higher trust tier, higher bond)

Layer structure (extends OAS base):
  Layer 1 - Identity:    inherited from OAS (asset_id, creator, created_at)
  Layer 2 - Metadata:    inherited from OAS (title, tags, description)
  Layer 7 - IdentityExt: type, credentials, reputation binding, capabilities
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─── Identity Types ──────────────────────────────────────────────


class IdentityType(str, enum.Enum):
    """Classification of identity asset holders."""

    AGENT = "agent"  # AI agent / bot
    NODE = "node"  # Network infrastructure node
    HUMAN = "human"  # Human participant
    ORG = "org"  # Organization / company


_IDENTITY_TYPE_VALUES = {e.value for e in IdentityType}


# ─── Trust Tiers ─────────────────────────────────────────────────


class TrustTier(str, enum.Enum):
    """Trust tier derived from identity type + reputation + verification.

    Higher tiers get lower bond requirements and broader access.
    """

    SANDBOX = "sandbox"  # New identity, R < 20, L0 only
    BASIC = "basic"  # R >= 20, L0-L1
    VERIFIED = "verified"  # R >= 50, L0-L2, identity verified
    TRUSTED = "trusted"  # R >= 75, L0-L3, long history
    INSTITUTIONAL = "institutional"  # ORG type with formal verification


_TRUST_TIER_VALUES = {e.value for e in TrustTier}

# Trust tier → minimum reputation score
TRUST_TIER_THRESHOLDS: Dict[str, float] = {
    TrustTier.SANDBOX.value: 0.0,
    TrustTier.BASIC.value: 20.0,
    TrustTier.VERIFIED.value: 50.0,
    TrustTier.TRUSTED.value: 75.0,
    TrustTier.INSTITUTIONAL.value: 50.0,  # ORG needs lower R but formal verification
}

# Trust tier → max access level
TRUST_TIER_ACCESS: Dict[str, str] = {
    TrustTier.SANDBOX.value: "L0",
    TrustTier.BASIC.value: "L1",
    TrustTier.VERIFIED.value: "L2",
    TrustTier.TRUSTED.value: "L3",
    TrustTier.INSTITUTIONAL.value: "L3",
}


# ─── Credential Binding ─────────────────────────────────────────


@dataclass
class CredentialBinding:
    """Binds an identity to verifiable credentials.

    Supports multiple credential types for progressive trust building:
    an agent might start with just a pubkey, then add DID, then org verification.
    """

    pubkey: str = ""  # Ed25519 public key (mandatory)
    pubkey_algorithm: str = "ed25519"  # Key algorithm
    did: Optional[str] = None  # Decentralized Identifier (optional)
    passkey_id: Optional[str] = None  # WebAuthn Passkey ID (human only)
    org_verification: Optional[str] = None  # Organization verification certificate
    additional: Dict[str, str] = field(default_factory=dict)  # Extensible

    def validate(self) -> List[str]:
        """Validate credential binding."""
        errors: List[str] = []
        if not self.pubkey:
            errors.append("pubkey is required for identity binding")
        valid_algorithms = {"ed25519", "secp256k1", "ed448"}
        if self.pubkey_algorithm not in valid_algorithms:
            errors.append(
                f"pubkey_algorithm '{self.pubkey_algorithm}' "
                f"must be one of {sorted(valid_algorithms)}"
            )
        return errors


# ─── Reputation Binding ──────────────────────────────────────────


@dataclass
class ReputationBinding:
    """Links an identity to its cross-asset reputation state.

    Reputation is not stored here — it lives in ReputationEngine.
    This binding declares the identity's reputation context so that
    reputation can be carried across different asset types.

    Key design: reputation is portable but not transferable.
    You can't sell your reputation, but your reputation follows you
    across data access, capability invocations, and oracle queries.
    """

    reputation_score: float = 10.0  # Current snapshot (updated periodically)
    trust_tier: str = TrustTier.SANDBOX.value
    total_accesses: int = 0  # Lifetime access count
    total_violations: int = 0  # Lifetime violation count
    last_violation_at: Optional[int] = None
    registered_at: int = 0  # Identity creation timestamp
    anti_sybil_deposit: float = 100.0  # OAS deposit for anti-Sybil

    # Cross-asset reputation tracking
    data_access_score: float = 10.0  # Reputation in data domain
    capability_invoke_score: float = 10.0  # Reputation in capability domain
    oracle_provider_score: float = 10.0  # Reputation as oracle provider

    @property
    def composite_score(self) -> float:
        """Weighted composite of domain-specific scores.

        Weights: data 40%, capability 35%, oracle 25%
        This reflects that data access (the core use case) carries
        the most weight.
        """
        return round(
            self.data_access_score * 0.40
            + self.capability_invoke_score * 0.35
            + self.oracle_provider_score * 0.25,
            6,
        )

    def derive_trust_tier(self, identity_type: str) -> str:
        """Derive trust tier from composite score and identity type.

        ORG type can reach INSTITUTIONAL tier with lower score
        if org_verification is present.
        """
        score = self.composite_score
        if identity_type == IdentityType.ORG.value and score >= 50.0:
            return TrustTier.INSTITUTIONAL.value
        if score >= 75.0:
            return TrustTier.TRUSTED.value
        if score >= 50.0:
            return TrustTier.VERIFIED.value
        if score >= 20.0:
            return TrustTier.BASIC.value
        return TrustTier.SANDBOX.value


# ─── Capability Declaration ──────────────────────────────────────


@dataclass
class CapabilityDeclaration:
    """Declares what capabilities an identity provides.

    This is a forward-reference to registered capability assets,
    not the capabilities themselves. Think of it as a business card:
    "I can do X, Y, Z — here are the asset IDs to invoke."
    """

    provided_capability_ids: List[str] = field(default_factory=list)
    provided_oracle_feed_ids: List[str] = field(default_factory=list)
    registered_data_asset_ids: List[str] = field(default_factory=list)
    max_concurrent_invocations: int = 10
    available: bool = True  # Whether accepting new invocations


# ─── Identity Layer (composite) ──────────────────────────────────


@dataclass
class IdentityExtLayer:
    """Layer 7: Identity-specific properties for identity assets.

    Combines identity classification, credential binding, reputation
    context, and capability declarations into a single layer that
    extends the base OAS asset schema.

    Design principle: Identity is the anchor for all economic activity.
    Every access, invocation, and oracle query is attributed to an
    identity. Reputation accrues to the identity, not the asset.
    """

    identity_type: str = IdentityType.AGENT.value
    display_name: str = ""
    credentials: CredentialBinding = field(default_factory=CredentialBinding)
    reputation: ReputationBinding = field(default_factory=ReputationBinding)
    capabilities: CapabilityDeclaration = field(default_factory=CapabilityDeclaration)

    # Network metadata
    endpoint_url: Optional[str] = None  # How to reach this identity
    supported_protocols: List[str] = field(default_factory=lambda: ["ahrp/1.0"])
    max_connections: int = 100

    # Anti-Sybil
    anti_sybil_deposit_oas: float = 100.0  # Minimum 100 OAS per identity
    deposit_locked_until: Optional[int] = None  # Lock period timestamp

    def validate(self) -> List[str]:
        """Validate the identity layer. Returns list of error messages."""
        errors: List[str] = []

        if self.identity_type not in _IDENTITY_TYPE_VALUES:
            errors.append(
                f"identity_type '{self.identity_type}' must be one of "
                f"{sorted(_IDENTITY_TYPE_VALUES)}"
            )

        if not self.display_name:
            errors.append("display_name is required")

        # Credential validation
        errors.extend(self.credentials.validate())

        # Human-specific: should have DID or passkey
        if self.identity_type == IdentityType.HUMAN.value:
            if not self.credentials.did and not self.credentials.passkey_id:
                errors.append(
                    "human identities should have did or passkey_id "
                    "(warning: not enforced but recommended)"
                )

        # ORG-specific: should have org_verification
        if self.identity_type == IdentityType.ORG.value:
            if not self.credentials.org_verification:
                errors.append(
                    "org identities should have org_verification "
                    "(warning: required for INSTITUTIONAL trust tier)"
                )

        # Anti-Sybil deposit validation
        if self.anti_sybil_deposit_oas < 100.0:
            errors.append(
                f"anti_sybil_deposit_oas ({self.anti_sybil_deposit_oas}) " f"must be >= 100.0 OAS"
            )

        # Trust tier validation
        tier = self.reputation.trust_tier
        if tier not in _TRUST_TIER_VALUES:
            errors.append(
                f"reputation.trust_tier '{tier}' must be one of " f"{sorted(_TRUST_TIER_VALUES)}"
            )

        return errors

    @property
    def max_access_level(self) -> str:
        """Maximum access level allowed by current trust tier."""
        return TRUST_TIER_ACCESS.get(self.reputation.trust_tier, "L0")

    @property
    def is_sandbox(self) -> bool:
        """Whether this identity is in sandbox mode."""
        return self.reputation.trust_tier == TrustTier.SANDBOX.value

    def refresh_trust_tier(self) -> str:
        """Recalculate and update trust tier from current reputation.

        Returns the new trust tier.
        """
        new_tier = self.reputation.derive_trust_tier(self.identity_type)
        self.reputation.trust_tier = new_tier
        return new_tier


# ─── Helper: Anti-Sybil cost analysis ────────────────────────────


def sybil_attack_cost(num_identities: int, deposit_per_identity: float = 100.0) -> float:
    """Calculate the economic cost of a Sybil attack.

    Each fake identity costs at minimum 100 OAS deposit + starts in
    sandbox mode with R=10, meaning:
    - Only L0 access (read-only, most restricted)
    - 90 days × successful interactions to reach R=20 (basic)
    - Any violation resets progress

    Args:
        num_identities: Number of fake identities to spin up.
        deposit_per_identity: OAS deposit per identity.

    Returns:
        Total OAS cost (deposit only, not counting time/effort).
    """
    return num_identities * deposit_per_identity


def time_to_trust(
    target_tier: str,
    successes_per_day: float = 3.0,
    gain_per_success: float = 5.0,
    max_gain_per_day: float = 20.0,
) -> float:
    """Estimate days to reach a target trust tier from initial R=10.

    Assumes no violations or decay (optimistic scenario).

    Args:
        target_tier: Target TrustTier value.
        successes_per_day: Average successful interactions per day.
        gain_per_success: Reputation gain per success (α).
        max_gain_per_day: Daily reputation gain cap.

    Returns:
        Estimated days to reach target tier.
    """
    threshold = TRUST_TIER_THRESHOLDS.get(target_tier, 0.0)
    initial = 10.0
    if initial >= threshold:
        return 0.0

    gap = threshold - initial
    daily_gain = min(successes_per_day * gain_per_success, max_gain_per_day)
    if daily_gain <= 0:
        return float("inf")
    return round(gap / daily_gain, 1)


__all__ = [
    "IdentityType",
    "TrustTier",
    "TRUST_TIER_THRESHOLDS",
    "TRUST_TIER_ACCESS",
    "CredentialBinding",
    "ReputationBinding",
    "CapabilityDeclaration",
    "IdentityExtLayer",
    "sybil_attack_cost",
    "time_to_trust",
]

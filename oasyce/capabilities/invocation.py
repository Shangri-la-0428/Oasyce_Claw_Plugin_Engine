"""Capability Invocation Engine — orchestrates invoke → escrow → settle → mint.

Lifecycle:
    1. invoke()        — validate input, calculate price, lock escrow
    2. submit_result() — validate output, release escrow, mint shares, pay provider
    3. fail()          — refund escrow on execution failure
    4. dispute()       — mark escrow as disputed for resolution
"""

from __future__ import annotations

import enum
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from oasyce.capabilities._pricing_shim import BancorCurve, FeeSplitter, FeeSplitResult
from oasyce.capabilities.escrow import EscrowManager, EscrowError
from oasyce.capabilities.registry import CapabilityRegistry
from oasyce.capabilities.shares import ShareLedger, MintResult


# ── Protocol fee constants ────────────────────────────────────────────
_PROTOCOL_FEE_PCT = 0.03
_BURN_SHARE = 0.50
_VERIFIER_SHARE = 0.50


class InvocationState(str, enum.Enum):
    """Invocation lifecycle states."""

    PENDING = "pending"  # escrow locked, waiting for result
    COMPLETED = "completed"  # result accepted, settled
    FAILED = "failed"  # provider failed, refunded
    DISPUTED = "disputed"  # consumer disputed the result


@dataclass
class InvocationHandle:
    """Returned by invoke() — identifies the in-flight invocation."""

    invocation_id: str
    escrow_id: str
    capability_id: str
    consumer_id: str
    provider_id: str
    price: float
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class SettlementResult:
    """Returned by submit_result() — full settlement breakdown."""

    invocation_id: str
    escrow_released: bool
    protocol_fee: float
    burn_amount: float
    verifier_amount: float
    net_to_curve: float
    fee_split: Optional[FeeSplitResult] = None
    mint_result: Optional[MintResult] = None


@dataclass
class DisputeHandle:
    """Returned by dispute() — identifies the disputed invocation."""

    invocation_id: str
    escrow_id: str
    consumer_id: str
    reason: str
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class _InvocationRecord:
    """Internal tracking of an invocation."""

    invocation_id: str
    capability_id: str
    consumer_id: str
    provider_id: str
    escrow_id: str
    price: float
    input_payload: Dict[str, Any]
    state: InvocationState = InvocationState.PENDING
    output_payload: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time()))
    settled_at: Optional[int] = None


class InvocationError(Exception):
    """Raised on invalid invocation operations."""


class CapabilityInvocationEngine:
    """Orchestrates capability invocations with escrow and share minting.

    Parameters
    ----------
    registry : CapabilityRegistry
        For looking up capability manifests.
    escrow : EscrowManager
        For locking/releasing funds.
    shares : ShareLedger
        For minting/burning shares on settlement.
    fee_splitter : FeeSplitter | None
        For splitting provider revenue.  Uses default 60/20/15/5 if None.
    quality_gate : QualityGate | None
        For evaluating output quality.  If set, submit_result() runs
        the quality gate and auto-settles on PASS.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        escrow: EscrowManager,
        shares: ShareLedger,
        fee_splitter: Optional[FeeSplitter] = None,
        quality_gate: Optional[Any] = None,
    ) -> None:
        self._registry = registry
        self._escrow = escrow
        self._shares = shares
        self._fee_splitter = fee_splitter or FeeSplitter()
        self._curve = BancorCurve()
        self._quality_gate = quality_gate
        self._invocations: Dict[str, _InvocationRecord] = {}

    # ── Public API ────────────────────────────────────────────────────

    def invoke(
        self,
        consumer_id: str,
        capability_id: str,
        input_payload: Dict[str, Any],
        max_price: float,
    ) -> InvocationHandle:
        """Start a capability invocation.

        Steps:
            1. Look up capability manifest
            2. Validate input against input_schema (required keys)
            3. Calculate price from Bonding Curve
            4. Check price <= max_price
            5. Lock funds in escrow
            6. Return InvocationHandle

        Raises:
            InvocationError on validation failure, price exceeded, or insufficient funds.
        """
        # 1. Look up manifest
        manifest = self._registry.get(capability_id)
        if manifest is None:
            raise InvocationError(f"capability not found: {capability_id}")
        if manifest.status != "active":
            raise InvocationError(f"capability is {manifest.status}")

        # 2. Validate input against input_schema (basic required-key check)
        self._validate_schema(input_payload, manifest.input_schema, "input")

        # 3. Calculate price from Bonding Curve
        reserve = self._shares.pool_reserve(capability_id)
        supply = self._shares.total_supply(capability_id)
        price = self._curve.calculate_price(
            reserve,
            supply,
            manifest.pricing.reserve_ratio,
        )

        # 4. Check max_price
        if price > max_price:
            raise InvocationError(f"price {price:.4f} exceeds max_price {max_price:.4f}")

        # 5. Lock escrow
        invocation_id = uuid.uuid4().hex[:16]
        try:
            escrow_id = self._escrow.lock(consumer_id, price, invocation_id)
        except EscrowError as e:
            raise InvocationError(str(e)) from e

        # 6. Track and return
        record = _InvocationRecord(
            invocation_id=invocation_id,
            capability_id=capability_id,
            consumer_id=consumer_id,
            provider_id=manifest.provider,
            escrow_id=escrow_id,
            price=price,
            input_payload=input_payload,
        )
        self._invocations[invocation_id] = record

        return InvocationHandle(
            invocation_id=invocation_id,
            escrow_id=escrow_id,
            capability_id=capability_id,
            consumer_id=consumer_id,
            provider_id=manifest.provider,
            price=price,
        )

    def submit_result(
        self,
        invocation_id: str,
        output_payload: Dict[str, Any],
        provider_signature: str = "",
    ) -> SettlementResult:
        """Submit execution result and settle.

        Steps:
            1. Validate invocation exists and is PENDING
            2. Validate output against output_schema
            3. Run QualityGate if configured (FAIL → hold escrow, flag)
            4. Release escrow
            5. Deduct protocol fee (5%: 2.5% burn + 2.5% verifier)
            6. Remaining 95% enters curve pool via share minting
            7. Split provider portion via FeeSplitter

        Returns:
            SettlementResult with full breakdown.
        """
        record = self._require_invocation(invocation_id, InvocationState.PENDING)

        # Validate output
        manifest = self._registry.get(record.capability_id)
        if manifest is not None:
            self._validate_schema(output_payload, manifest.output_schema, "output")

        # Store output on record before quality gate
        record.output_payload = output_payload

        # Run quality gate if configured
        if self._quality_gate is not None and manifest is not None:
            qr = self._quality_gate.evaluate(invocation_id, output_payload, manifest)
            if qr.verdict.value == "fail":
                # Hold escrow, flag for review — do NOT settle
                self._quality_gate.flag(invocation_id, "; ".join(qr.reasons))
                record.state = InvocationState.FAILED
                record.error_code = "quality_fail"
                record.error_message = "; ".join(qr.reasons)
                self._escrow.refund(record.escrow_id)
                record.settled_at = int(time.time())
                return SettlementResult(
                    invocation_id=invocation_id,
                    escrow_released=False,
                    protocol_fee=0.0,
                    burn_amount=0.0,
                    verifier_amount=0.0,
                    net_to_curve=0.0,
                )

        # Release escrow
        self._escrow.release(record.escrow_id)

        gross = record.price

        # Protocol fee: 5%
        protocol_fee = gross * _PROTOCOL_FEE_PCT
        burn_amount = protocol_fee * _BURN_SHARE
        verifier_amount = protocol_fee * _VERIFIER_SHARE
        net_to_curve = gross - protocol_fee

        # Mint shares to consumer (net_to_curve enters the pool)
        mint_result = self._shares.mint(
            record.capability_id,
            record.consumer_id,
            net_to_curve,
        )

        # Split the provider portion via FeeSplitter
        fee_split = self._fee_splitter.split(net_to_curve, record.provider_id)

        # Finalize record
        record.state = InvocationState.COMPLETED
        record.settled_at = int(time.time())

        return SettlementResult(
            invocation_id=invocation_id,
            escrow_released=True,
            protocol_fee=protocol_fee,
            burn_amount=burn_amount,
            verifier_amount=verifier_amount,
            net_to_curve=net_to_curve,
            fee_split=fee_split,
            mint_result=mint_result,
        )

    def fail(
        self,
        invocation_id: str,
        error_code: str,
        error_message: str = "",
    ) -> bool:
        """Mark invocation as failed and refund escrow.

        Returns:
            True if refund succeeded.
        """
        record = self._require_invocation(invocation_id, InvocationState.PENDING)
        self._escrow.refund(record.escrow_id)
        record.state = InvocationState.FAILED
        record.error_code = error_code
        record.error_message = error_message
        record.settled_at = int(time.time())
        return True

    def dispute(
        self,
        invocation_id: str,
        consumer_id: str,
        reason: str,
    ) -> DisputeHandle:
        """Dispute an invocation result.  Escrow remains locked.

        Only the original consumer can dispute.
        """
        record = self._require_invocation(invocation_id, InvocationState.PENDING)
        if record.consumer_id != consumer_id:
            raise InvocationError("only the consumer can dispute")

        self._escrow.dispute(record.escrow_id)
        record.state = InvocationState.DISPUTED

        return DisputeHandle(
            invocation_id=invocation_id,
            escrow_id=record.escrow_id,
            consumer_id=consumer_id,
            reason=reason,
        )

    def get_invocation(self, invocation_id: str) -> Optional[_InvocationRecord]:
        """Return the internal invocation record, or None."""
        return self._invocations.get(invocation_id)

    # ── Internals ─────────────────────────────────────────────────────

    def _require_invocation(
        self,
        invocation_id: str,
        expected: InvocationState,
    ) -> _InvocationRecord:
        record = self._invocations.get(invocation_id)
        if record is None:
            raise InvocationError(f"invocation not found: {invocation_id}")
        if record.state != expected:
            raise InvocationError(
                f"invocation {invocation_id} is {record.state.value}, " f"expected {expected.value}"
            )
        return record

    @staticmethod
    def _validate_schema(
        payload: Dict[str, Any],
        schema: Dict[str, Any],
        label: str,
    ) -> None:
        """Basic dict validation: check required keys exist."""
        if not schema:
            return
        required = schema.get("required", [])
        missing = [k for k in required if k not in payload]
        if missing:
            raise InvocationError(f"{label} validation failed: missing required keys {missing}")

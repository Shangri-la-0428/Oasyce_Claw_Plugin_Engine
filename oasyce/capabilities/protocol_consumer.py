"""Protocol Consumer — manages consumer balance and service requests.

Provides a consumer-side interface for requesting protocol capabilities
(similarity check, tag generation, fingerprint operations, dispute
arbitration, storage proof) with balance management and request tracking.
"""

from __future__ import annotations

import enum
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Protocol identity ────────────────────────────────────────────────
PROTOCOL_CONSUMER_ID = "oasyce_protocol"


# ── Capability type constants ────────────────────────────────────────


class CapabilityType:
    """Protocol capability type constants."""

    SIMILARITY_CHECK = "similarity_check"
    TAG_GENERATE = "tag_generate"
    FINGERPRINT_EMBED = "fingerprint_embed"
    FINGERPRINT_SCAN = "fingerprint_scan"
    DISPUTE_ARBITRATE = "dispute_arbitrate"
    STORAGE_PROOF = "storage_proof"


# ── Status enum ──────────────────────────────────────────────────────


class RequestStatus(str, enum.Enum):
    """Service request lifecycle states."""

    PENDING = "pending"
    BIDDING = "bidding"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Data classes ─────────────────────────────────────────────────────


@dataclass
class ServiceRequest:
    """Represents a consumer's request for a protocol capability."""

    request_id: str
    capability_type: str
    input_data: Dict[str, Any]
    max_price: float
    status: RequestStatus = RequestStatus.PENDING
    created_at: int = field(default_factory=lambda: int(time.time()))


# ── Exceptions ───────────────────────────────────────────────────────


class ProtocolFundError(Exception):
    """Raised when consumer balance is insufficient for an operation."""


# ── Consumer ─────────────────────────────────────────────────────────


class ProtocolConsumer:
    """Consumer-side interface for requesting protocol capabilities.

    Parameters
    ----------
    initial_balance : float
        Starting balance for the consumer account.
    """

    def __init__(self, initial_balance: float = 0.0) -> None:
        self._balance: float = initial_balance
        self._requests: Dict[str, ServiceRequest] = {}

    # ── Balance management ───────────────────────────────────────────

    @property
    def balance(self) -> float:
        """Current consumer balance."""
        return self._balance

    def deposit(self, amount: float) -> None:
        """Add funds to the consumer balance.

        Raises
        ------
        ValueError
            If *amount* is not positive.
        """
        if amount <= 0:
            raise ValueError("deposit amount must be positive")
        self._balance += amount

    def withdraw(self, amount: float) -> None:
        """Withdraw funds from the consumer balance.

        Raises
        ------
        ValueError
            If *amount* is not positive.
        ProtocolFundError
            If the balance is insufficient.
        """
        if amount <= 0:
            raise ValueError("withdraw amount must be positive")
        if amount > self._balance:
            raise ProtocolFundError(
                f"insufficient balance: need {amount:.4f}, have {self._balance:.4f}"
            )
        self._balance -= amount

    # ── Service requests ─────────────────────────────────────────────

    def request_service(
        self,
        capability_type: str,
        input_data: Dict[str, Any],
        max_price: float,
    ) -> ServiceRequest:
        """Create a new service request for a protocol capability.

        Parameters
        ----------
        capability_type : str
            One of the :class:`CapabilityType` constants.
        input_data : dict
            Payload to send to the capability provider.
        max_price : float
            Maximum price the consumer is willing to pay.

        Returns
        -------
        ServiceRequest
            The newly created request with status PENDING.
        """
        request_id = uuid.uuid4().hex[:16]
        request = ServiceRequest(
            request_id=request_id,
            capability_type=capability_type,
            input_data=input_data,
            max_price=max_price,
        )
        self._requests[request_id] = request
        return request

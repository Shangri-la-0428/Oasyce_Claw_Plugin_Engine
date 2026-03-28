from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── Envelope ──────────────────────────────────────────────────────────


class Envelope(BaseModel):
    ok: bool
    data: Any = None
    error: Optional[str] = None


class CoreActionEnvelope(BaseModel):
    contract_version: str
    action: str
    ok: bool
    state: Literal["success", "failed", "retryable"]
    retryable: bool
    trace_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


# ── Request models ────────────────────────────────────────────────────


class CapturePackIn(BaseModel):
    timestamp: str
    gps_hash: str
    device_signature: str
    media_hash: str
    source: Literal["camera", "album"]


class SubmitRequest(BaseModel):
    pack: CapturePackIn
    creator: str


class BuyRequest(BaseModel):
    asset_id: str
    buyer: str


class CoreRegisterRequest(BaseModel):
    file_path: str
    owner: str
    tags: list[str] = Field(default_factory=list)
    rights_type: str = "original"
    price_model: Literal["auto", "fixed", "floor"] = "auto"
    price: Optional[float] = None
    trace_id: Optional[str] = None


class CoreQuoteRequest(BaseModel):
    asset_id: str
    amount_oas: float = 10.0
    trace_id: Optional[str] = None


class CoreBuyRequest(BaseModel):
    asset_id: str
    buyer: str
    amount_oas: float = 10.0
    trace_id: Optional[str] = None


class CorePortfolioRequest(BaseModel):
    buyer: str
    trace_id: Optional[str] = None


# ── Response data models ──────────────────────────────────────────────


class VerifyResultOut(BaseModel):
    valid: bool
    reason: Optional[str] = None


class SubmitResultOut(BaseModel):
    verify: VerifyResultOut
    asset_id: Optional[str] = None


class SettleSplitOut(BaseModel):
    creator: float
    protocol_burn: float
    protocol_validator: float
    router: float


class QuoteResultOut(BaseModel):
    asset_id: str
    price_oas: float
    supply: int


class SettleResultOut(BaseModel):
    success: bool
    tx_id: str
    split: Optional[SettleSplitOut] = None
    reason: Optional[str] = None


class BuyResultOut(BaseModel):
    quote: QuoteResultOut
    settlement: SettleResultOut


class HealthOut(BaseModel):
    status: str
    mode: str

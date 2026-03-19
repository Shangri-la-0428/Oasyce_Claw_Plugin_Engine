from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


# ── Envelope ──────────────────────────────────────────────────────────


class Envelope(BaseModel):
    ok: bool
    data: Any = None
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

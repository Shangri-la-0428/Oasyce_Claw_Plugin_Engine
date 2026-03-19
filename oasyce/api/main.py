from __future__ import annotations

from fastapi import Depends, FastAPI

from oasyce.api.deps import get_engine
from oasyce.api.schemas import (
    BuyRequest,
    BuyResultOut,
    CapturePackIn,
    Envelope,
    HealthOut,
    QuoteResultOut,
    SettleResultOut,
    SettleSplitOut,
    SubmitRequest,
    SubmitResultOut,
    VerifyResultOut,
)
from oasyce.engine import OasyceEngine
from oasyce.models.capture_pack import CapturePack

app = FastAPI(title="Oasyce PoPC API", version="0.1.0")


def _pack_from_schema(p: CapturePackIn) -> CapturePack:
    return CapturePack(
        timestamp=p.timestamp,
        gps_hash=p.gps_hash,
        device_signature=p.device_signature,
        media_hash=p.media_hash,
        source=p.source,
    )


@app.get("/v1/health", response_model=Envelope)
def health(engine: OasyceEngine = Depends(get_engine)) -> Envelope:
    return Envelope(ok=True, data=HealthOut(status="ok", mode=engine.cfg.mode))


@app.post("/v1/verify", response_model=Envelope)
def verify(body: CapturePackIn, engine: OasyceEngine = Depends(get_engine)) -> Envelope:
    pack = _pack_from_schema(body)
    result = engine.cfg.verifier.verify(pack)
    return Envelope(ok=result.valid, data=VerifyResultOut(valid=result.valid, reason=result.reason))


@app.post("/v1/submit", response_model=Envelope)
def submit(body: SubmitRequest, engine: OasyceEngine = Depends(get_engine)) -> Envelope:
    pack = _pack_from_schema(body.pack)
    result, asset_id = engine.submit(pack, creator=body.creator)
    data = SubmitResultOut(
        verify=VerifyResultOut(valid=result.valid, reason=result.reason),
        asset_id=asset_id,
    )
    return Envelope(ok=result.valid, data=data)


@app.post("/v1/buy", response_model=Envelope)
def buy(body: BuyRequest, engine: OasyceEngine = Depends(get_engine)) -> Envelope:
    quote, settle = engine.buy(body.asset_id, buyer=body.buyer)

    if quote is None or settle is None:
        return Envelope(ok=False, error=f"asset '{body.asset_id}' not found")

    split_out = None
    if settle.split is not None:
        split_out = SettleSplitOut(
            creator=settle.split.creator,
            protocol_burn=settle.split.protocol_burn,
            protocol_validator=settle.split.protocol_validator,
            router=settle.split.router,
        )

    data = BuyResultOut(
        quote=QuoteResultOut(
            asset_id=quote.asset_id, price_oas=quote.price_oas, supply=quote.supply
        ),
        settlement=SettleResultOut(
            success=settle.success, tx_id=settle.tx_id, split=split_out, reason=settle.reason
        ),
    )
    return Envelope(ok=settle.success, data=data)

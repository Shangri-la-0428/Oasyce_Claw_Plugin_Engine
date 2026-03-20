from __future__ import annotations

from fastapi import Depends, FastAPI

from oasyce.api.deps import get_engine, get_facade
from oasyce.api.schemas import (
    BuyRequest,
    BuyResultOut,
    CapturePackIn,
    Envelope,
    HealthOut,
    QuoteResultOut,
    SettleResultOut,
    SubmitRequest,
    SubmitResultOut,
    VerifyResultOut,
)
from oasyce.engine import OasyceEngine
from oasyce.models.capture_pack import CapturePack
from oasyce.services.facade import OasyceServiceFacade

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
def buy(body: BuyRequest, facade: OasyceServiceFacade = Depends(get_facade)) -> Envelope:
    result = facade.buy(body.asset_id, body.buyer)
    if not result.success:
        return Envelope(ok=False, error=result.error)

    data = result.data
    quote_data = data.get("quote") or {}

    buy_out = BuyResultOut(
        quote=QuoteResultOut(
            asset_id=data.get("asset_id", body.asset_id),
            price_oas=quote_data.get("spot_price_after", 0.0),
            supply=0,
        ),
        settlement=SettleResultOut(
            success=data.get("settled", False),
            tx_id=data.get("receipt_id", ""),
            split=None,
            reason=None,
        ),
    )
    return Envelope(ok=data.get("settled", False), data=buy_out)

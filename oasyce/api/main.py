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
    SettleSplitOut,
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
    quote_data = data.get("quote", {})
    settle_data = data.get("settlement", {})

    split_raw = settle_data.get("split")
    split_out = None
    if split_raw is not None:
        split_out = SettleSplitOut(
            creator=split_raw["creator"],
            protocol_burn=split_raw["protocol_burn"],
            protocol_validator=split_raw["protocol_validator"],
            router=split_raw["router"],
        )

    buy_out = BuyResultOut(
        quote=QuoteResultOut(
            asset_id=quote_data.get("asset_id", body.asset_id),
            price_oas=quote_data.get("price_oas", 0.0),
            supply=quote_data.get("supply", 0),
        ),
        settlement=SettleResultOut(
            success=settle_data.get("success", False),
            tx_id=settle_data.get("tx_id", ""),
            split=split_out,
            reason=settle_data.get("reason"),
        ),
    )
    return Envelope(ok=settle_data.get("success", False), data=buy_out)

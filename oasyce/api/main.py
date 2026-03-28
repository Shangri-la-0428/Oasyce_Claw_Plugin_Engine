from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from oasyce.api.deps import get_engine, get_facade
from oasyce.api.schemas import (
    BuyRequest,
    BuyResultOut,
    CapturePackIn,
    CoreActionEnvelope,
    CoreBuyRequest,
    CorePortfolioRequest,
    CoreQuoteRequest,
    CoreRegisterRequest,
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
_CORE_CONTRACT_VERSION = "beta-core-v1"
_RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _pack_from_schema(p: CapturePackIn) -> CapturePack:
    return CapturePack(
        timestamp=p.timestamp,
        gps_hash=p.gps_hash,
        device_signature=p.device_signature,
        media_hash=p.media_hash,
        source=p.source,
    )


def _resolve_trace_id(trace_id: str | None) -> str:
    value = str(trace_id or "").strip()
    if value:
        return value[:128]
    return f"v1-{uuid.uuid4().hex[:12]}"


def _core_state(ok: bool, status_code: int) -> str:
    if ok:
        return "success"
    if status_code in _RETRYABLE_HTTP_STATUSES:
        return "retryable"
    return "failed"


def _service_error_http_status(error: str | None, default: int = 400) -> int:
    text = str(error or "").strip().lower()
    if not text:
        return default
    if "not found" in text:
        return 404
    if "not authorized" in text or "identity verification failed" in text:
        return 403
    if "ledger not available" in text or "service unavailable" in text or "not initialized" in text:
        return 503
    if "duplicate" in text or "already" in text or "conflict" in text:
        return 409
    return default


def _core_response(
    *,
    action: str,
    trace_id: str,
    data: dict | None = None,
    status_code: int = 200,
    ok: bool | None = None,
    error: str | None = None,
) -> JSONResponse:
    resolved_ok = bool(ok if ok is not None else status_code < 400)
    state = _core_state(resolved_ok, status_code)
    payload = CoreActionEnvelope(
        contract_version=_CORE_CONTRACT_VERSION,
        action=action,
        ok=resolved_ok,
        state=state,  # type: ignore[arg-type]
        retryable=state == "retryable",
        trace_id=trace_id,
        data=data or {},
        error=error,
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def _core_buy_payload(data: dict, body: CoreBuyRequest) -> dict:
    quote_data = data.get("quote") or {}
    payload = {
        "asset_id": data.get("asset_id", body.asset_id),
        "buyer": data.get("buyer", body.buyer),
        "amount_oas": round(float(data.get("amount_oas", body.amount_oas) or 0), 6),
        "settled": bool(data.get("settled", False)),
        "receipt_id": data.get("receipt_id") or data.get("tx_id", ""),
        "equity_minted": round(float(quote_data.get("equity_minted", 0) or 0), 4),
        "spot_price_after": round(float(quote_data.get("spot_price_after", 0) or 0), 6),
        "equity_balance": round(float(data.get("equity_balance", 0) or 0), 4),
    }
    if "access_granted" in data:
        payload["access_granted"] = data.get("access_granted")
    return payload


def _core_register_payload(data: dict, body: CoreRegisterRequest) -> dict:
    payload = {
        "asset_id": data.get("asset_id", ""),
        "file_hash": data.get("file_hash", ""),
        "owner": data.get("owner", body.owner),
        "price_model": data.get("price_model", body.price_model),
        "rights_type": data.get("rights_type", body.rights_type),
    }
    if body.price is not None or data.get("manual_price") is not None:
        payload["manual_price"] = data.get("manual_price", body.price)
    return payload


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


@app.post("/v1/core/register", response_model=CoreActionEnvelope)
def core_register(
    body: CoreRegisterRequest,
    facade: OasyceServiceFacade = Depends(get_facade),
) -> JSONResponse:
    trace_id = _resolve_trace_id(body.trace_id)
    result = facade.register(
        file_path=body.file_path,
        owner=body.owner,
        tags=list(body.tags),
        rights_type=body.rights_type,
        price_model=body.price_model,
        manual_price=body.price,
        trace_id=trace_id,
        enforce_allowed_paths=True,
        allowed_price_models=["auto", "fixed", "floor"],
    )
    if not result.success:
        failure_data = {
            "file_path": body.file_path,
            "owner": body.owner,
        }
        if isinstance(result.data, dict):
            failure_data.update(result.data)
        return _core_response(
            action="register",
            trace_id=result.trace_id or trace_id,
            data=failure_data,
            status_code=_service_error_http_status(result.error, 400),
            ok=False,
            error=result.error,
        )
    payload = _core_register_payload(result.data or {}, body)
    return _core_response(
        action="register",
        trace_id=result.trace_id or trace_id,
        data=payload,
        status_code=200,
        ok=True,
    )


@app.post("/v1/core/quote", response_model=CoreActionEnvelope)
def core_quote(
    body: CoreQuoteRequest,
    facade: OasyceServiceFacade = Depends(get_facade),
) -> JSONResponse:
    trace_id = _resolve_trace_id(body.trace_id)
    result = facade.quote(body.asset_id, body.amount_oas, trace_id=trace_id)
    if not result.success:
        return _core_response(
            action="quote",
            trace_id=result.trace_id or trace_id,
            data={"asset_id": body.asset_id, "amount_oas": body.amount_oas},
            status_code=_service_error_http_status(result.error, 400),
            ok=False,
            error=result.error,
        )
    payload = dict(result.data)
    payload["amount_oas"] = round(float(body.amount_oas), 6)
    return _core_response(
        action="quote",
        trace_id=result.trace_id or trace_id,
        data=payload,
        status_code=200,
        ok=True,
    )


@app.post("/v1/core/buy", response_model=CoreActionEnvelope)
def core_buy(
    body: CoreBuyRequest,
    facade: OasyceServiceFacade = Depends(get_facade),
) -> JSONResponse:
    trace_id = _resolve_trace_id(body.trace_id)
    result = facade.buy(body.asset_id, body.buyer, body.amount_oas, trace_id=trace_id)
    if not result.success:
        return _core_response(
            action="buy",
            trace_id=result.trace_id or trace_id,
            data={
                "asset_id": body.asset_id,
                "buyer": body.buyer,
                "amount_oas": round(float(body.amount_oas), 6),
            },
            status_code=_service_error_http_status(result.error, 400),
            ok=False,
            error=result.error,
        )
    payload = _core_buy_payload(result.data, body)
    return _core_response(
        action="buy",
        trace_id=result.trace_id or trace_id,
        data=payload,
        status_code=200,
        ok=payload["settled"],
    )


@app.post("/v1/core/portfolio", response_model=CoreActionEnvelope)
def core_portfolio(
    body: CorePortfolioRequest,
    facade: OasyceServiceFacade = Depends(get_facade),
) -> JSONResponse:
    trace_id = _resolve_trace_id(body.trace_id)
    result = facade.get_portfolio(body.buyer)
    if not result.success:
        return _core_response(
            action="portfolio",
            trace_id=trace_id,
            data={"buyer": body.buyer},
            status_code=_service_error_http_status(result.error, 400),
            ok=False,
            error=result.error,
        )
    payload = {
        "buyer": body.buyer,
        "holdings": list((result.data or {}).get("holdings", [])),
    }
    return _core_response(
        action="portfolio",
        trace_id=trace_id,
        data=payload,
        status_code=200,
        ok=True,
    )

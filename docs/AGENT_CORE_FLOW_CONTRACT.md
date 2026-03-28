# Agent Core Flow Contract

> Updated: 2026-03-28
> Scope: first-user beta core flow for agent callers
> Status: beta-core-v1

## Purpose

This contract defines the machine-facing flow that an agent can execute without
dashboard-only behavior:

1. register asset
2. request quote
3. execute buy
4. verify resulting holdings

For beta, this contract is the source of truth for automation-facing behavior.

## Common Response Envelope

For agent callers, the normalized beta envelope is:

- `contract_version`: currently `beta-core-v1`
- `action`: one of `register`, `quote`, `buy`, `portfolio`
- `data`: action-specific result payload
- `trace_id`: flow correlation id
- `ok`: terminal success flag
- `state`: one of `success`, `failed`, `retryable`
- `retryable`: whether the caller may safely retry the same step
- `error`: present only on failures

Notes:

- `processing` is reserved for future async flows. The current beta core flow is synchronous.
- `retryable=true` means transport or temporary infra conditions. It does not mean "blindly submit again forever".
- `register`, `quote`, and `buy` must request this envelope explicitly with `format=agent`.
- `portfolio(machine=True)` already reads from the same envelope.
- FastAPI now also exposes machine-first mirrors for this contract under `/v1/core/register`, `/v1/core/quote`, `/v1/core/buy`, and `/v1/core/portfolio`.

## Step 1: Register Asset

Endpoint:

- `POST /api/register`

Agent mode:

- `POST /api/register` with body field `format=agent`

Required request fields:

- `file_path`
- `owner`

Supported request fields:

- `tags`
- `rights_type`
- `price_model`: `auto`, `fixed`, `floor`
- `price`

Recommended header:

- `X-Trace-Id: <workflow-trace-id>`
- `Idempotency-Key: <buy-attempt-id>`

`data` fields on success:

- `asset_id`
- `file_hash`
- `owner`
- `price_model`
- `rights_type`

Retry guidance:

- `failed`: caller must fix input or permissions before retrying
- `retryable`: caller may retry after transient dependency recovery

## Step 2: Quote

Endpoint:

- `GET /api/quote?asset_id=<id>&amount=<oas>`

Agent mode:

- `GET /api/quote?asset_id=<id>&amount=<oas>&format=agent`

Recommended header:

- `X-Trace-Id: <workflow-trace-id>`

`data` fields on success:

- `asset_id`
- `amount_oas`
- `payment_oas`
- `equity_minted`
- `spot_price_before`
- `spot_price_after`
- `price_impact_pct`
- `protocol_fee_oas`
- `burn_amount_oas`
- `price_model`

Retry guidance:

- Quote is read-only and always safe to retry
- `failed` means invalid input or missing asset
- `retryable` means transient backend failure

## Step 3: Buy

Endpoint:

- `POST /api/buy`

Agent mode:

- `POST /api/buy` with body field `format=agent`

Required request fields:

- `asset_id`
- `buyer`
- `amount`

Recommended header:

- `X-Trace-Id: <workflow-trace-id>`

`data` fields on success:

- `asset_id`
- `buyer`
- `amount_oas`
- `settled`
- `receipt_id`
- `equity_minted`
- `spot_price_after`
- `equity_balance`

Additional top-level metadata:

- `idempotency_key`
- `idempotent_replay` when the node replays a prior success
- `original_trace_id` on replay when available

Retry guidance:

- `failed`: treat as terminal for the current attempt unless a human or reconciliation check says otherwise
- `retryable`: check holdings first, then retry with the same `trace_id`
- repeated `buy` requests with the same `Idempotency-Key` and the same payload must replay the original success result instead of executing a second financial action
- reusing the same `Idempotency-Key` with a different payload must fail with a conflict response
- If the caller loses the response, run Step 4 before issuing another buy

## Step 4: Verify Resulting Holdings

Endpoint:

- `GET /api/portfolio?buyer=<id>&format=agent`

Recommended header:

- `X-Trace-Id: <workflow-trace-id>`

`data` fields on success:

- `buyer`
- `holdings`

Each holdings entry contains:

- `asset_id`
- `shares`
- `equity_pct`
- `access_level`
- `spot_price`
- `value_oas`

Retry guidance:

- This step is read-only and safe to retry
- `retryable` means the node could not resolve the current projection state

## Python Client Mapping

The Python client exposes the same contract primitives:

- `Oasyce.register(..., machine=True, trace_id=...)`
- `Oasyce.quote(..., machine=True, trace_id=...)`
- `Oasyce.buy(..., machine=True, trace_id=..., idempotency_key=...)`
- `Oasyce.portfolio(..., machine=True, trace_id=...)`

## Beta Constraints

- callers must not invent success from cached local state
- chain-authoritative outcomes still win over local projections when they disagree

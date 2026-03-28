# Beta Smoke Checklist

> Updated: 2026-03-28
> Scope: local pre-push and pre-beta verification for `oasyce-net`

Run this checklist before any push intended for beta users.

## 1. Local Test Gate

- [ ] `pytest -q /Users/wutongcheng/Desktop/Net/oasyce-net/tests`
- [ ] Confirm result is zero failures
- [ ] Confirm any skipped tests are expected Go chain gates, not missing dependencies
- [ ] `oas doctor --public-beta --json`
- [ ] Confirm doctor returns `status = ok`
- [ ] If `.github/workflows/*` changed, run the release workflow gate in `docs/RELEASE_GATE.md`

## 2. Agent Core Flow

- [ ] Register one test asset through the API or Python client
- [ ] Request a quote for that asset
- [ ] Execute one buy with an `Idempotency-Key`
- [ ] Re-submit the same buy and confirm replay, not duplicate execution
- [ ] Read holdings with `format=agent` and confirm the result is visible

## 3. Failure Semantics

- [ ] Try one malformed quote request and confirm `failed`, not ambiguous error text
- [ ] Try one cooldown-triggering buy and confirm `retryable`
- [ ] Try one conflicting `Idempotency-Key` payload and confirm conflict response
- [ ] Confirm each beta-critical response includes `trace_id`

## 4. GUI / Transport Boundaries

- [ ] Confirm `asset/update` still works
- [ ] Confirm `re-register` still works
- [ ] Confirm `stake` still works
- [ ] Confirm none of those paths required direct GUI ledger writes to pass

## 5. Logs And Recovery

- [ ] Confirm the trace log for one successful buy can be found locally
- [ ] Confirm one failed beta-core request can be traced by `trace_id`
- [ ] Confirm the team knows whether chain state or local projection wins for the tested action

## 6. Push Decision

Only push when all are true:

- [ ] The full suite is green
- [ ] The core agent flow is green
- [ ] Retry and idempotency behavior are green
- [ ] No new direct GUI write path was introduced
- [ ] The change is small enough that rollback scope is obvious
- [ ] Remote CI is green before any beta announcement

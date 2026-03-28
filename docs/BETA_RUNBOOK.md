# Public Beta Runbook

> Updated: 2026-03-28
> Scope: first external beta user, human-assisted while staying AI-first

## 1. What This Runbook Is For

Use this runbook when a beta user is blocked on the core flow:

`register -> quote -> buy -> verify holdings`

The goal is not to debug the whole system from first principles.
The goal is to answer four questions fast:

- Did the request really execute?
- Which state is authoritative?
- Is it safe to retry?
- Does the team need to intervene manually?

## 2. Source Of Truth

When two views disagree, use this order:

1. Chain outcome wins for purchase result, shares, settlement, and reputation.
2. Local ledger and cached dashboard state are projections for browsing, recovery, and operator visibility.
3. UI wording or stale cache never overrides chain truth.

## 3. Core Tools

Use these first:

- Trace logs from the local node
- `/api/support/beta`
- `oas support beta --json`
- `trace_id` returned by every beta-critical response

Recommended first command:

```bash
oas support beta --json
```

Before inviting a new public beta user, also run:

```bash
oas doctor --public-beta --json
```

What to look for:

- recent `register.*`, `quote.*`, `buy.*`, `portfolio.*` events
- matching `trace_id`
- recent failures and their error text
- recent transactions

## 4. Safe Retry Rules

Follow these rules strictly:

- `quote` can be retried safely.
- `register` can be retried only after checking whether the asset already exists or the file hash is already registered.
- `buy` must not be retried blindly.
- If `buy` used an `Idempotency-Key`, retry only with the same key.
- If `buy` timed out but may have reached the backend, inspect support data before any second attempt.

## 5. Core Flow Checks

### Register

Expected success:

- response includes `trace_id`
- response includes `asset_id`
- state is machine-readable

Common failures:

- `no wallet — create one first`
- `file path not allowed`
- `file not found`
- duplicate file hash / duplicate asset
- chain unavailable in strict mode

Operator action:

- confirm wallet exists
- confirm file is under the allowed path and still present
- if duplicate, do not tell the user to retry as if this were a transient error
- if strict chain is enabled and chain is unavailable, treat as infrastructure issue

### Quote

Expected success:

- response includes `trace_id`
- quote fields are complete
- state is `success`

Common failures:

- invalid amount
- missing asset
- backend unavailable

Operator action:

- validate request shape first
- if backend unavailable, retry after service recovery

### Buy

Expected success:

- response includes `trace_id`
- response includes `receipt_id`
- response includes machine-readable `ok/state/retryable`
- holdings or transactions reflect the result

Common failures:

- cooldown triggered
- conflicting `Idempotency-Key`
- asset file unavailable locally
- settlement or chain unavailable
- identity or authorization failure

Operator action:

- if `retryable=true`, check support data and retry safely
- if cooldown, wait instead of forcing a second buy
- if `Idempotency-Key` conflict, treat it as caller bug or duplicated automation input
- if the backend may already have executed the buy, inspect support data and holdings before any new submission

### Verify Holdings

Expected success:

- holdings are visible from `portfolio`
- user can confirm result without reading raw logs

Operator action:

- if holdings lag behind, check recent transactions and support events first
- if chain and local view disagree, trust chain outcome

## 6. Failure Triage

### P0

Immediate stop. Do not invite more users.

- buy result is ambiguous and cannot be resolved from support data
- chain and local state conflict on financial outcome
- duplicate financial side effects are suspected

### P1

Fix before more beta traffic.

- register or buy path broken for new users
- support data missing for core flow failures
- trace IDs missing from beta-critical responses

### P2

Can continue beta with operator awareness.

- stale cache or delayed holdings display
- non-critical dashboard inconsistency
- onboarding copy confusion with known workaround

## 7. Manual Intervention Rules

Manual intervention is allowed only when:

- the financial result is already clear
- the operator can point to the authoritative source
- the fix does not invent a second source of truth

Do not manually “patch the UI” and call it resolved.
If a manual fix is needed, fix the projection or presentation layer without changing the authoritative outcome.

## 8. First-User Session Checklist

Before the session:

- run `pytest -q /Users/wutongcheng/Desktop/Net/oasyce-net/tests`
- run the beta smoke checklist in `docs/BETA_SMOKE_CHECKLIST.md`
- make sure `oas support beta --json` returns usable data

During the session:

- capture `trace_id` for every core action
- do not let the user repeat `buy` blindly
- record every point of confusion, not just hard failures

After the session:

- classify issues into P0 / P1 / P2
- separate product confusion from backend failure
- update onboarding or recovery guidance before inviting the next user

## 9. Escalation Rule

Pause rollout immediately if any of these happen:

- financial outcome cannot be proven
- retries can create duplicate effects
- support tooling cannot explain a failed core action

When in doubt, stop rollout and recover clarity first.

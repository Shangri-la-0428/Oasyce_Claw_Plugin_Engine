# Public Beta Execution TODO

> Updated: 2026-03-28
> Scope: `oasyce-net` public beta launch readiness
> Goal: make sure the first real external user can complete one full flow safely and that the team can debug failures quickly.

## North Star

Before optimizing for elegance, optimize for trust:

- The first user can finish one full core flow without hand-holding.
- Money, shares, and transaction outcomes have one clear source of truth.
- Failures are visible, explainable, and recoverable.

Strategic posture:

- The product is AI-first. The final consumer is an agent, not a dashboard user.
- Dashboard is a temporary collaboration and observability surface.
- Beta work should favor machine-readable APIs, idempotent actions, and deterministic status semantics over UI-only convenience.

## Source Of Truth

- Chain is authoritative for: purchase outcome, share ownership, settlement result, reputation outcome.
- Local `Ledger` / cache / UI state are projections for UX, browsing, and recovery support.
- No new feature should introduce a second "official" state path in GUI or CLI.

## Milestones

### M1: First User Safe Path

Target date: 2026-04-05

- One core flow is stable end to end.
- Errors are user-readable.
- Team can trace a failed attempt in logs.
- The same core flow can be driven by API / CLI without hidden dashboard-only behavior.

### M2: Public Beta Controlled

Target date: 2026-04-12

- Critical writes go through one application path.
- UI state and backend state vocabulary are aligned.
- Retry / manual recovery path exists for core failures.
- Core actions have machine-safe semantics for retries and automation.

### M3: Ready For 5-10 Beta Users

Target date: 2026-04-26

- Core read paths are stable and fast.
- Support / ops has a beta runbook.
- Regression checks exist for the main path.
- Human-assisted beta flow can start giving way to agent-driven automation.

## Week 1: 2026-03-30 to 2026-04-05

### Core flow and observability

- [x] Issue: define the single public beta core flow
  - Delivered in: `docs/BETA_CORE_FLOW.md`
  - Selected flow: register asset -> quote -> buy -> view result / holdings
  - Acceptance: team agrees this is the only flow that must not break before first user access

- [x] Issue: write authority matrix for chain vs local state
  - Delivered in: `docs/BETA_CORE_FLOW.md` (`Source Of Truth` section)
  - Acceptance: one short doc section explains what is chain truth and what is local projection

- [x] Issue: add end-to-end trace logging for the beta core flow
  - Delivered in: `tests/test_beta_trace.py`, `oasyce/gui/app.py`, `oasyce/services/facade.py`
  - Acceptance: one failed attempt can be traced from UI action to service call to chain/local outcome

- [x] Issue: unify user-facing error states for the core flow
  - Delivered in: `oasyce/gui/app.py`, `tests/test_beta_trace.py`
  - Acceptance: UI and API both distinguish `processing`, `success`, `failed`, `retryable`

- [x] Issue: create executable beta smoke gate
  - Delivered in: `oas smoke public-beta --json`, `docs/BETA_SMOKE_CHECKLIST.md`
  - Acceptance: one repeatable command runs the beta release gate before each beta-facing release

- [x] Issue: define machine-facing core flow contract
  - Delivered in: `docs/AGENT_CORE_FLOW_CONTRACT.md`, `tests/test_agent_core_contract.py`, `oasyce/client.py`, `oasyce/gui/app.py`
  - Acceptance: register / quote / buy / verify each have explicit request, response, and retry semantics for agent callers

## Week 2: 2026-04-06 to 2026-04-12

### Close the architecture gaps

- [x] Issue: route all critical GUI writes through service/facade
  - Delivered in: `oasyce/gui/app.py`, `oasyce/services/facade.py`, `tests/test_architecture.py`, `tests/test_gui_write_routing.py`, `tests/test_facade_asset_mutations.py`
  - Scope delivered: `register`, `register-bundle`, `asset/update`, `re-register`, `stake` now route through facade; `buy` runtime state moved behind `oasyce/services/buy_runtime.py`
  - Acceptance: GUI does not directly create a second write path for core beta operations

- [x] Issue: normalize API result shape for core beta actions
  - Delivered in: `oasyce/gui/app.py`, `oasyce/client.py`, `docs/AGENT_CORE_FLOW_CONTRACT.md`, `tests/test_agent_core_contract.py`
  - Acceptance: core buy / quote / asset actions return consistent status and error semantics

- [x] Issue: define retry and no-double-submit behavior
  - Delivered in: `oasyce/gui/app.py`, `oasyce/services/buy_runtime.py`, `docs/AGENT_CORE_FLOW_CONTRACT.md`, `tests/test_buy_runtime.py`, `tests/test_agent_core_contract.py`, `tests/test_beta_trace.py`
  - Acceptance: timeout and partial-failure cases do not push users into duplicate payment / duplicate action confusion

- [x] Issue: add idempotency strategy for agent-triggered writes
  - Delivered in: `oasyce/gui/app.py`, `oasyce/client.py`, `docs/AGENT_CORE_FLOW_CONTRACT.md`, `tests/test_agent_core_contract.py`
  - Acceptance: repeated automated submits do not create duplicate financial side effects

- [x] Issue: create a minimal internal support panel or command set
  - Delivered in: `oasyce/services/beta_support.py`, `oasyce/gui/app.py`, `oasyce/client.py`, `oasyce/cli.py`, `tests/test_beta_support_store.py`, `tests/test_beta_support.py`, `tests/test_cli.py`
  - Acceptance: team can inspect recent actions, recent failures, and transaction status without digging through raw logs only

- [x] Issue: write first-user onboarding copy
  - Delivered in: `oasyce/info.py`, `oasyce/cli.py`, `tests/test_cli.py`
  - Acceptance: a new user can understand what to do first and what "success" looks like

## Week 3: 2026-04-13 to 2026-04-19

### Stabilize reads and beta operations

- [ ] Issue: separate projection/cache state from official transaction state
  - Acceptance: cached or inferred state is never shown as final authoritative success

- [ ] Issue: remove heavy synchronous work from main browse/query paths
  - Focus: asset list, holdings, network overview
  - Progress: `query_assets()` now uses cached projection + `stat` and no longer re-hashes file contents during list reads
  - Acceptance: user-facing read paths avoid unnecessary file-system or integrity work during page load

- [ ] Issue: define one canonical HTTP contract for beta-critical actions
  - Progress: machine-first `/v1/core/register`, `/v1/core/quote`, `/v1/core/buy`, and `/v1/core/portfolio` now expose the same `contract_version/action/ok/state/retryable/trace_id/data/error` envelope shape as the beta core flow
  - Acceptance: transport layers share one business meaning even if both `/api/*` and `/v1/*` still exist temporarily

- [ ] Issue: remove dashboard-only business behavior from beta-critical flows
  - Acceptance: no core beta action depends on hidden UI state or handler-local branching

## Current Push-Gate TODO

The codebase is not ready to push until these are closed locally:

- [x] Run `docs/BETA_SMOKE_CHECKLIST.md` before the first beta-facing push
  - Executed locally via targeted beta regression set on 2026-03-28:
    `tests/test_agent_core_contract.py`, `tests/test_beta_trace.py`, `tests/test_api.py`, `tests/test_gui_write_routing.py`, `tests/test_facade_asset_mutations.py`, `tests/test_buy_runtime.py`, `tests/test_asset_availability.py`, `tests/test_beta_support.py`
- [x] Add a minimal support panel or command set for recent core actions and failures
- [x] Write first-user onboarding copy with machine-first wording but human-assisted beta guidance
- [x] Decide whether buy notifications should remain in facade or move to a dedicated notification adapter
- Decision: buy notifications now route through `oasyce/services/buy_notifications.py`; broader lifecycle notifications stay in facade for this beta window
- [x] Final local full-suite run after the last push-gate item lands
  - Executed locally on 2026-03-28: `pytest -q /Users/wutongcheng/Desktop/Net/oasyce-net/tests`
  - Result: `1289 passed, 19 skipped`

- [x] Issue: write public beta runbook
  - Delivered in: `docs/BETA_RUNBOOK.md`
  - Acceptance: team has a short recovery guide for common failures and knows when manual intervention is required

- [ ] Issue: run first-user session and collect structured feedback
  - Acceptance: feedback is captured as concrete blockers, confusion points, and missing status cues

## Week 4: 2026-04-20 to 2026-04-26

### Prepare for small-scale rollout

- [ ] Issue: automate smoke tests for the beta core flow
  - Acceptance: at least register / quote / buy / view-result smoke coverage exists for both human-assisted and agent-driven entry paths before release

- [ ] Issue: add a beta metrics snapshot
  - Suggested metrics: quote success rate, buy success rate, median latency, failure reasons
  - Acceptance: weekly prioritization can use data instead of guesswork

- [ ] Issue: define incident severity levels
  - Acceptance: P0 / P1 / P2 language exists and the team knows what gets fixed same day

- [ ] Issue: stage rollout from 1 user to 3 users to 10 users
  - Acceptance: beta growth is gated by successful completion of the previous stage

- [ ] Issue: run milestone review against M1 / M2 / M3
  - Acceptance: each milestone is explicitly marked pass / partial / fail with next action

## Non-Goals During This Beta Window

- Do not start a microservice split.
- Do not remove all fallback logic at once.
- Do not add major new user-facing write features before the core path is stable.
- Do not let new UI code bypass the agreed write path.
- Do not ship beta-critical behavior that only works through manual dashboard interaction.

## Execution Notes

- Start with Week 1 issues before any large refactor.
- If a Week 1 issue reveals a core path bug, fix that before continuing.
- If the first external user is blocked, pause roadmap expansion and prioritize recovery and clarity.

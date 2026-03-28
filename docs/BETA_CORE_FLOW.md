# Beta Core Flow

> Updated: 2026-03-28
> Scope: first external public beta user

## Purpose

For the first real user, Oasyce should optimize for one thing:

- finish one full core flow safely

Do not optimize for breadth first. Do not assume the user will tolerate ambiguity.

At the same time, keep the strategic posture clear:

- Oasyce is AI-first. The long-term product is for agents, not for manual dashboard clicking.
- Dashboard is a transitional collaboration surface for the beta period.
- Any beta-critical flow must remain expressible as a deterministic machine workflow via API / CLI, not only through the dashboard.

## Single Core Flow

The public beta core flow is:

1. Open Dashboard, CLI, or agent entrypoint
2. Register one data asset
3. Request a quote for that asset
4. Complete one buy action
5. View the resulting status and holdings

This is the only flow that must be treated as release-blocking during the first-user beta window.

The human-visible version may start in Dashboard, but the machine-visible version is the one that matters strategically:

1. create/register asset
2. request quote
3. execute buy
4. verify resulting state

## User Story

As a first-time user, I should be able to:

- understand what to do first
- register an asset without guessing the next step
- see a clear quote before buying
- complete the buy without duplicate submission confusion
- see an unambiguous result after the buy

As a first beta agent integration, the system should also be able to:

- run the same flow without manual interpretation
- receive machine-readable states and errors
- avoid duplicate actions when retries happen
- determine final success from one authoritative source

## Required Product States

Every critical step in the core flow must use one of these states:

- `processing`
- `success`
- `failed`
- `retryable`

Avoid vague or mixed states such as "maybe done", "unknown", or silent fallback.

These states must be stable in both human UX and machine-facing responses.

## Step Expectations

### Step 1: Open Product

The user must see:

- what the product does in one sentence
- what the first action is
- where success will appear

### Step 2: Register Asset

The user must be able to:

- choose a file
- add minimum required metadata
- submit registration once

The product must show:

- registration is in progress
- registration succeeded or failed
- the new asset identifier if successful

### Step 3: Quote

The user must see:

- which asset is being quoted
- the quote amount
- any visible fees or expected outcome

The product must not imply that a quote is a completed trade.

### Step 4: Buy

The user must be protected from:

- double-click or duplicate submit confusion
- timeout ambiguity
- silent partial failure

The product must show:

- buy submitted
- buy confirmed or failed
- what to do next if the result is delayed

### Step 5: View Result

The user must be able to verify:

- whether the buy actually succeeded
- what they now hold
- where to see the resulting record again

## Source Of Truth

For the first-user beta, the rule is simple:

- Chain is authoritative for purchase outcome, settlement outcome, share ownership, and reputation outcome.
- Local `Ledger`, cache, and UI state are projections for speed, browsing, and recovery help.
- UI must not present projected or cached state as final authoritative success for a completed buy.

## Out Of Scope For This Beta Gate

These are important, but they do not block the first-user beta gate unless they break the core flow:

- advanced governance
- full automation breadth
- long-tail AHRP scenarios
- non-core network visualization polish
- large-scale performance tuning outside the core path

## Release Blocking Conditions

Do not expose the first external user if any of the following are true:

- the user can finish registration but cannot tell whether buy succeeded
- a buy can appear successful in UI while chain truth is unclear
- retrying a failed step can cause duplicate financial actions
- the team cannot trace a failed core-flow attempt end to end
- the flow works in Dashboard but not through stable API / CLI semantics

## Success Criteria

The first-user beta gate is passed when:

- one new external user completes the core flow without live developer intervention
- the team can inspect logs and explain each step afterward
- no step in the core flow depends on hidden local-only truth
- the same flow is machine-executable with clear, idempotent state transitions

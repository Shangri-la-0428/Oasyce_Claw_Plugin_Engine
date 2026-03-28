# Release Gate

> Updated: 2026-03-29
> Scope: push and beta release decisions across `oasyce-net`, `DataVault`, and `oasyce-chain`

## Why This Exists

The recent CI failures were not random.
They came from four repeated classes of drift:

- code changed, but workflow/test seams were not updated
- local tests were green, but release-critical CI behavior was never exercised locally
- workflow/tooling dependencies drifted out of date
- main-branch CI was doing more work than needed for every push

This gate exists to keep beta pushes boring.

## Non-Negotiable Rules

Only push when all are true:

1. local product tests are green
2. public beta smoke flow is green
3. workflow-related local checks are green
4. remote CI is green before announcing a release
5. rollback scope is obvious

## Required Local Gate

For `oasyce-net`:

- `pytest -q /Users/wutongcheng/Desktop/Net/oasyce-net/tests`
- `oas doctor --public-beta --json`
- run `docs/BETA_SMOKE_CHECKLIST.md`

For `DataVault` when touched:

- `pytest -q /Users/wutongcheng/Desktop/Net/DataVault/tests`

For `oasyce-chain` when touched:

- `go test ./...`

## Required Workflow Gate

Run this when `.github/workflows/*` changes or CI tooling changes:

- validate workflow YAML before push
- run the corresponding local toolchain before push
- do not rely on GitHub Actions to tell you basic version mismatches

Examples:

- Python workflow changes:
  - `black --check .`
  - packaging build
- Go workflow or lint changes:
  - `go test ./...`
  - `golangci-lint run ./...`

## Required Remote Gate

Do not announce beta readiness until:

- `oasyce-net` CI is green
- `oasyce-chain` `build / test / lint / docker` are green
- if a run is replaced by a newer push, cancel the stale run and judge only the newest one

## Design Rules Learned From This Incident

Keep these structural rules:

- local sandbox and public testnet must stay separate
- public beta must fail closed, never silently fall back to local state
- docs must point to one canonical onboarding flow
- main-branch docker CI should optimize for fast signal; release tags can do heavier multi-arch work
- style-only lint expansions must never be introduced as release blockers without an explicit cleanup project

## Push Decision

If any one of these is unclear, do not push:

- which state is authoritative
- whether retry is safe
- whether CI is red because of code, workflow, or infra
- how to roll back

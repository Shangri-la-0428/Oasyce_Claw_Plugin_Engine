# Account Unification Plan

## Goal

Make Oasyce treat one user's economic identity as a single canonical account across:

- multiple devices
- multiple AI runtimes (`Codex`, `Claude Code`, other agents)
- multiple local entrypoints (`CLI`, `GUI`, `DataVault`)

Target outcome:

- second device does not silently create a different economic account
- AI agents can act under the same account intentionally
- node identity, local wallet, and chain signer are no longer conflated

## Current Problems

The current implementation has three different identity layers:

1. App wallet
   - Stored locally in `~/.oasyce/wallet.json`
   - Used by many CLI / GUI defaults for `owner` / `buyer`

2. Chain signer
   - Chosen from `OASYCE_CHAIN_FROM` or local `managed_install.json`
   - Used by `oasyced` for strict-chain transactions

3. Node identity
   - Stored in `<data_dir>/node_id.json`
   - Used for P2P identity, not account ownership

This causes drift:

- device A and device B can bootstrap into different local wallets
- business actor (`owner`, `buyer`) can differ from chain signing actor
- multi-device usage is possible only by manual operator discipline

## Design Principles

1. Canonical economic account = chain account address
2. Node identity is not economic identity
3. Read-only attach and write-capable attach must be explicit
4. No silent fallback to a fresh account on a second device
5. All economic defaults must resolve through one account resolver

## Target Model

Introduce one canonical account model for Oasyce Net:

- `account_address`
- `account_mode`
  - `managed_local`
  - `attached_readonly`
  - `attached_signing`
- `signer_type`
  - `oasyced_local`
  - `native_signer`
  - `external`
  - `none`
- `signer_name`
- derived runtime fields
  - `wallet_address`
  - `wallet_matches_account`
  - `chain_signer_matches_account`

Proposed local intent file:

- `~/.oasyce/account.json`

This file should store only explicit attach intent:

- chosen `account_address`
- explicit `account_mode`
- optional signer hint (`signer_type`, `signer_name`)

Wallet address, signer address, and match/coherence fields must be derived live.
That avoids creating a second stale state snapshot that drifts from local signer or wallet state.

## Release Strategy

### Phase 1: Canonical account resolver

Add one shared resolver used by:

- `CLI`
- `GUI`
- `public beta doctor/smoke`
- `facade`

Deliverables:

- new account state module
- one function to resolve effective account address
- one function to resolve effective signer configuration
- removal of direct `Wallet.get_address() or "anonymous"` defaults from economic flows

Acceptance:

- register / buy / sell / stake no longer infer account identity from ad hoc local rules

### Phase 2: Attach or create account flow

Add explicit account lifecycle commands:

- `oas account status`
- `oas account adopt`
- `oas account verify`

Behavior:

- primary device can create a managed signing account
- secondary device can attach to the same account
- if signer material is absent, device becomes read-only unless user explicitly imports or configures signing

Acceptance:

- second device does not silently create a new economic identity during bootstrap

### Phase 3: Bootstrap refactor

Refactor `oas bootstrap`:

- stop treating wallet creation as the account truth
- bootstrap should first inspect existing account profile
- in `testnet + strict-chain`, bootstrap should require a coherent account state
- if account state is missing, bootstrap must either:
  - create a primary managed account
  - or attach to an existing account explicitly

Acceptance:

- bootstrap cannot end in "wallet address A, signer B" drift

### Phase 4: Multi-device safety gates

Extend doctor/smoke:

- detect wallet/signer/account mismatch
- detect readonly device trying to perform write operations
- fail if business actor and signer actor are inconsistent

Acceptance:

- `oas doctor --public-beta --json` reports account coherence
- `oas smoke public-beta --json` uses canonical account resolution only

### Phase 5: Signing model hardening

Support safer same-account multi-device patterns:

- local `oasyced` signer attach
- future `NativeSigner` attach
- future external signer / hardware wallet

Important rule:

- same-account multi-device write access must never depend on copying unrelated local state blindly

Acceptance:

- "same account on multiple devices" is an explicit supported workflow, not an accident

## Immediate TODO

1. Create `account_state.py` and define canonical account profile schema
2. Replace economic identity defaults in CLI and GUI with one shared account resolver
3. Add `oas account status`
4. Add `oas account adopt --address ... [--signer-name ...] [--readonly]`
5. Make `bootstrap` account-aware and fail-closed on mismatches
6. Extend `doctor --public-beta` to check account coherence
7. Extend smoke to use canonical account only
8. Update docs so multi-device usage has one canonical guide

## Non-Goals

These are not part of the first rollout:

- cross-device secret sync service
- cloud-hosted wallet custody
- background account replication between machines

Those can come later. First we need one coherent local account model.

## Product Rule

Until the above is implemented, public messaging should be:

- protocol supports one account being used from many clients
- product does not yet provide polished same-account multi-device onboarding by default
- second device must not be described as "automatic same account" unless attached intentionally

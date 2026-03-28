# Account Unification Plan

This document is now a delivery plan under the canonical architecture defined in:

- `/Users/wutongcheng/Desktop/Net/oasyce-net/docs/IDENTITY_WALLET_ARCHITECTURE.md`

## Goal

Make Oasyce treat one user's economic identity as a single canonical account across:

- multiple devices
- multiple AI runtimes (`Codex`, `Claude Code`, other agents)
- multiple local entrypoints (`CLI`, `GUI`, `DataVault`)

Target outcome:

- second device does not silently create a different economic account
- AI agents can act under the same account intentionally
- node identity, local wallet, and chain signer are no longer conflated

This plan follows the minimal shipping rule from:

- `/Users/wutongcheng/Desktop/Net/oasyce-net/docs/IDENTITY_WALLET_ARCHITECTURE.md`

Meaning:

- account + signer coherence is the hard gate
- device is the V1 authorization boundary
- agent begins as explicit audit metadata, not as a heavyweight subsystem
- session / trace stay mandatory for audit

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
2. Trusted device identity is the V1 authorization boundary
3. Agent identity starts as an audit label, not a signing principal
4. Read-only attach and write-capable attach must be explicit
5. No silent fallback to a fresh account on a second device
6. All economic defaults must resolve through one account resolver

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

For V1, add one trusted-device model on top:

- `device_id`
- `authorization_status`
  - `readonly`
  - `active`
  - `expired`
  - `revoked`
- `authorization_expires_at`

For V1, `agent_id` remains an audit field, not an authorization principal.

## Execution Sequence

### Phase 1: Canonical owner account

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

### Phase 2: Trusted device identity

Add a minimal trusted-device authorization model:

- one owner can bind multiple devices
- one device can be `readonly` or `active`
- device authorization can expire
- device authorization can be revoked

Acceptance:

- one owner may safely use multiple devices at once
- readonly and signing devices are explicit and auditable

### Phase 3: Attach or create account flow

Add explicit account / device lifecycle commands:

- `oas account status`
- `oas account adopt`
- `oas account verify`

Behavior:

- primary device can create a managed signing account
- secondary device can attach to the same account
- if signer material is absent, device becomes read-only unless user explicitly imports or configures signing

Acceptance:

- second device does not silently create a new economic identity during bootstrap

### Phase 4: Bootstrap refactor

Refactor `oas bootstrap`:

- stop treating wallet creation as the account truth
- bootstrap should first inspect existing account profile
- in `testnet + strict-chain`, bootstrap should require a coherent account state
- if account state is missing, bootstrap must either:
  - create a primary managed account
  - or attach to an existing account explicitly

Acceptance:

- bootstrap cannot end in "wallet address A, signer B" drift

### Phase 5: Multi-device safety gates

Extend doctor/smoke:

- detect device/account/signer mismatch
- detect readonly device trying to perform write operations
- fail if business actor and signer actor are inconsistent

Acceptance:

- `oas doctor --public-beta --json` reports account coherence
- `oas smoke public-beta --json` uses canonical account resolution only

### Phase 6: Off-chain first behavior

Treat high-frequency behavior as off-chain first:

- signals, traces, and local coordination stay off-chain
- only low-frequency settlements, anchors, or final writes go on-chain

Acceptance:

- identity design does not force every runtime event into a chain transaction

### Phase 7: Agent and session audit labels

Add:

- `agent_id`
- `session_id`
- `trace_id`

as stable audit labels across writes and important reads.

Acceptance:

- Oasyce can answer who acted, on which device, in which run
- without turning agents into first-class signing principals yet

### Phase 8: CLI adaptation

Make CLI reflect the V1 model by default:

- owner account first
- trusted device attach / verify second
- agent and session metadata attached automatically where relevant

Acceptance:

- multi-device same-owner flow is simple from CLI

### Phase 9: Dashboard adaptation

Make Dashboard reflect the same model:

- current owner account is visible
- current device mode is visible
- readonly vs active signing state is explicit
- agent label can be shown later without becoming the authorization boundary

Acceptance:

- a user can understand "who owns this", "can this device sign", and "what mode am I in" without opening the CLI docs

### Phase 10: Future hardening

Later, if needed:

Support safer same-account multi-device patterns:

- device subkeys
- future `NativeSigner` attach
- future external signer / hardware wallet
- future agent-level delegation
- future permission layering

Important rule:

- same-account multi-device write access must never depend on copying unrelated local state blindly

Acceptance:

- "same account on multiple devices" is an explicit supported workflow, not an accident

## Concrete TODO

### V1 foundation

1. Keep canonical owner account resolution as the only economic default
2. Introduce a minimal trusted-device authorization state
3. Define expiry and revocation semantics for trusted devices
4. Ensure multi-device online coexistence is explicit and tested
5. Emit `device_id` in trace / audit envelopes
6. Keep `session_id` / `trace_id` mandatory for operationally important writes
7. Preserve off-chain-first behavior for high-frequency signals

### V1 workflow adaptation

8. Make CLI treat device attach / verify as the default same-owner flow
9. Make Dashboard expose owner account, device mode, and signing capability clearly

### V2 follow-ups

10. Introduce explicit `agent_id` everywhere important as an audit label
11. Separate device identity from agent identity in downstream SDK envelopes
12. Add session key / subkey / delegation key only if V1 proves insufficient
13. Add permission layering only after same-owner multi-device flows are stable

## Non-Goals

These are not part of the first rollout:

- cross-device secret sync service
- cloud-hosted wallet custody
- background account replication between machines
- agent key infrastructure
- delegation token protocol
- standalone device registry
- full agent-level permissioning

Those can come later. First we need one coherent local account model.

## Product Rule

Until the above is implemented, public messaging should be:

- protocol supports one account being used from many clients
- product does not yet provide polished same-account multi-device onboarding by default
- second device must not be described as "automatic same account" unless attached intentionally

# Identity & Wallet Architecture

## Purpose

Define one coherent identity model for Oasyce across:

- CLI
- Dashboard
- DataVault
- SDK / MCP / LangChain integrations
- downstream AI systems such as Thronglets-like agent substrates

This document is the architectural source of truth for:

- who owns economic outcomes
- who is allowed to sign
- which AI or runtime actually acted
- which device or node executed the action
- how one account can safely span multiple devices and multiple AI runtimes

## Core Principle

**Economic identity and execution identity must not be conflated.**

Oasyce needs to answer five different questions, not one:

1. Who pays / owns / earns?
2. Who is allowed to sign on-chain?
3. Which AI runtime made the decision?
4. Which device / node executed the action?
5. Which concrete run / invocation produced this effect?

If these are collapsed into a single "identity", the system becomes ambiguous and unsafe.

## Minimal Shipping Model

To avoid overdesign, Oasyce should **not** try to fully materialize all five layers at once.

The minimum model we need to ship safely is:

1. **Owner account**
   - the economic principal
   - one canonical answer to "who owns / pays / earns?"

2. **Device identity**
   - the trusted device boundary
   - one canonical answer to "which device may act for this account?"

3. **Session**
   - one concrete execution boundary for audit and debugging
   - one canonical answer to "which run did this?"

4. **Agent**
   - present first as an audit label
   - not first as an authorization principal

That means:

- `account_address` must be first-class now
- trusted device authorization must be first-class now
- `session_id` / `trace_id` must be first-class now
- `agent_id` should start as an explicit metadata field

This gets the architecture right without prematurely building a complete multi-agent security framework.

## Oasyce Identity V1 / V2

### V1: must have

1. **One owner account can bind multiple device identities**
2. **Device identity can be authorized by the owner**
3. **Authorization can expire and be revoked**
4. **Device identity can sign off-chain, and signatures can be verified back to the owner**
5. **One owner can support multiple devices online at the same time**
6. **High-frequency behavior stays off-chain; low-frequency results settle or anchor on-chain**

### V2: better to have

7. **Separate device identity from agent identity**
8. **Support session keys / subkeys / delegation keys**
9. **Support permission layering**

### One-sentence product rule

**One owner account -> multiple authorized device identities; agent and session start as audit labels; high-frequency behavior signs off-chain, low-frequency results settle on-chain.**

## What We Explicitly Do Not Build Yet

To keep the system simple, the first rollout should **not** add:

1. a full agent PKI
2. cross-device secret sync
3. cloud wallet custody
4. a standalone device registry service
5. a full agent-level delegation / capability token protocol
6. agent-native reputation ledgers
7. separate persistence stores for agent, device, and session profiles

Those may become necessary later.

They are not necessary to correctly separate:

- economic ownership
- signing authority
- execution metadata

## The Five-Layer Model

### 1. Economic Account

The **economic account** is the top-level principal.

It answers:

- who owns assets
- who pays for invocations
- who receives earnings
- who holds stake
- who bears economic risk

This is the identity that should be treated as the user's canonical economic self.

In Oasyce today, this is best modeled as the **chain account address**.

Examples:

- `oasyce1alice...`
- `oasyce1researchlab...`

### 2. Device Identity and Signing Authority

The **device identity** is the V1 authorization boundary.

In V1, the signer is attached to the trusted device identity.
That means:

- the account owns value
- the device is what gets authorized
- the signer is how that device proves it may write

The signer is not the economic principal.
It is the authority used by an authorized device to write on behalf of the economic account.

It answers:

- can this device submit a signed buy / register / stake / invoke transaction?
- which local or external signer was used?

Possible signer forms:

- local `oasyced` signer
- native software signer
- external signer
- future hardware / remote signer

An account may have:

- zero signing authority on a device
- exactly one active local signer on a device
- multiple authorized devices online at once

### 3. Agent Identity

The **agent identity** is the execution principal.

It answers:

- which AI runtime decided to do this?
- which agent should receive execution reputation?
- which agent produced the signal or recommendation?

Examples:

- `codex-mbp`
- `claude-vps`
- `openclaw-worker-a`
- `thronglets-router-1`

An agent is **not** the account itself.

In V1, an agent is not the authorization boundary either.
It is an audit and provenance label.

Many agents may act under one economic account and one trusted device.

### 4. Device / Node Identity

The **device identity** is the runtime environment identity.

It answers:

- which machine or node executed the action?
- where should environment-specific trust / risk / health be attached?
- which local state and secrets are present here?

Examples:

- laptop A
- laptop B
- cloud worker
- local node

Two agents may run on one device.  
One agent may move across devices over time.

### 5. Session / Invocation Identity

The **session identity** is the concrete run boundary.

It answers:

- which specific run created this effect?
- which chain of prompts, tool calls, or invocation steps produced it?
- what should be replayed, disputed, or audited?

Examples:

- one `Codex` coding session
- one `Claude` task run
- one agent invocation request
- one `Thronglets` swarm execution

This is the right level for:

- traces
- audit records
- failure analysis
- challenge / dispute evidence

## Role of Wallet

Historically Oasyce used "wallet" as a general identity shortcut.  
That is too imprecise.

**Correct interpretation:**

- wallet = local key material / local account container
- account = economic owner

A wallet may resolve to the same economic account, but the wallet file itself is not the economic model.

So the architecture should speak in this order:

- economic account
- signer authority
- local wallet implementation

Not:

- wallet = user identity

## Current Oasyce Mapping

### Already Present

#### Economic account

- `/Users/wutongcheng/Desktop/Net/oasyce-net/oasyce/account_state.py`
- `/Users/wutongcheng/Desktop/Net/oasyce-net/oasyce/services/account_service.py`

Current role:

- canonical account resolution
- explicit attach intent
- readonly vs signing mode

#### Local wallet

- `/Users/wutongcheng/Desktop/Net/oasyce-net/oasyce/identity.py`

Current role:

- local Ed25519 wallet storage
- local address derivation

#### Signer authority

- `/Users/wutongcheng/Desktop/Net/oasyce-net/oasyce/services/public_beta_signer.py`
- `/Users/wutongcheng/Desktop/Net/oasyce-net/oasyce/chain_client.py`

Current role:

- prepare / inspect local testnet signer
- use signer for strict-chain writes

#### Device / node identity

- `/Users/wutongcheng/Desktop/Net/oasyce-net/oasyce/config.py`

Current role:

- `node_id.json`
- node role
- network presence

### Present but Inconsistent

Agent-like identity fields already exist across flows, but they are not yet unified:

- `agent_id`
- `requester_id`
- `consumer_id`
- `provider`
- `owner`
- `buyer`
- `seller`
- `submitter`

These fields currently mix:

- economic principal
- execution principal
- business actor

That is the main conceptual debt.

## Canonical Separation

### Economic actor fields

These should resolve to the **economic account**:

- `owner`
- `buyer`
- `seller`
- `provider`
- `consumer` when it means the paying party
- `staker`

### Execution actor fields

These should resolve to the **agent identity**:

- `agent_id`
- `executor_id`
- `requester_agent_id`
- `provider_agent_id`

### Environment fields

These should resolve to the **device / node identity**:

- `device_id`
- `node_id`
- `runtime_id`

### Run fields

These should resolve to the **session / invocation identity**:

- `session_id`
- `trace_id`
- `invocation_id`

## What Downstream Systems Like Thronglets Should Depend On

Even if Thronglets is outside this repository, the integration contract should be:

### What it may rely on

1. **Economic account**
   - who owns and pays

2. **Agent identity**
   - which Thronglets agent or role acted

3. **Session / invocation identity**
   - which concrete swarm run emitted the action

### What it must not rely on

1. Local wallet file layout
2. Local `managed_install.json` internals
3. Local signer naming conventions as semantic identity
4. Device-local storage as the sole source of economic truth

That means downstream systems should integrate against a stable envelope like:

- `account_address`
- `agent_id`
- `device_id`
- `session_id`
- `signer_type`
- `can_sign`

Not against:

- `~/.oasyce/wallet.json`
- ad hoc local defaults

## Product Rules

### Rule 1: One wallet can back many agents

Multiple AI runtimes may operate under one economic account:

- Codex on laptop A
- Codex on laptop B
- OpenClaw
- Thronglets router

That is valid.

In V1, the authorization boundary is still the trusted device, not the agent.

### Rule 2: Agents must still be distinguishable

Even if they share one economic account, they must not collapse into one execution identity.

Otherwise Oasyce cannot tell:

- who made which decision
- which agent learned what
- which environment caused a failure
- which agent deserves or loses reputation

### Rule 3: Device-local signing is a capability, not identity

Having a signer on a device means:

- this device may write

It does **not** mean:

- this device is the account

### Rule 4: Read-only attach is a first-class state

A second device may attach to the same account and still be:

- valid
- useful
- intentionally unable to sign

This is not a degraded hack.  
It is a correct mode.

### Rule 5: Audit must record agent + device + session

All write paths should be able to answer:

- economic account
- signer used
- agent identity
- device identity
- session / trace identity

### Rule 6: Start with metadata, not bureaucracy

For the first release, `agent_id` is primarily:

- explicit labels
- audit fields
- filtering keys

It does **not** need to begin as:

- cryptographic principals
- on-chain identities
- new account-like state machines

That is the main guardrail against overdesign.

For the first release, `device_id` is different:

- it is an explicit identity label
- and it is the V1 authorization boundary

That is the main reason device and agent must not be collapsed.

## Recommended Object Model

### AccountProfile

```json
{
  "account_address": "oasyce1...",
  "account_mode": "managed_local | attached_readonly | attached_signing"
}
```

### DeviceProfile

```json
{
  "device_id": "device-123",
  "account_address": "oasyce1...",
  "signer_type": "oasyced_local | native_signer | external | none",
  "signer_name": "optional",
  "can_sign": true,
  "authorization_expires_at": 0,
  "authorization_status": "active | expired | revoked | readonly"
}
```

### AgentProfile

```json
{
  "agent_id": "codex-mbp",
  "agent_type": "codex | claude | openclaw | thronglets | custom",
  "account_address": "oasyce1...",
  "device_id": "device-123",
  "status": "active"
}
```

### SessionProfile

```json
{
  "session_id": "sess-...",
  "agent_id": "codex-mbp",
  "device_id": "device-123",
  "account_address": "oasyce1...",
  "trace_id": "trace-...",
  "started_at": 0
}
```

## How Current Features Should Behave

### CLI

- `oas account status` = account layer
- `oas account verify` = signer + account coherence
- `oas device join` = device attachment workflow
- future `oas agent whoami` = agent audit label

### Dashboard

- should display current account mode
- should distinguish read-only vs signing
- should later expose agent/runtime label
- should not assume local wallet == economic account

### DataVault

- should register assets under account ownership
- may include optional `agent_id` / `device_id` metadata for provenance
- should not invent a second economic identity model

### SDK

The SDK should eventually model:

- account principal
- signer authority
- agent execution metadata

The current Python SDK already separates:

- stateless chain client
- signer bridge / native signer

That is good.  
It should not collapse signer and agent into the same concept.

## Migration Strategy

### Phase 1: Freeze terminology

Adopt these canonical terms:

- account
- signer
- agent
- device
- session

Stop using "wallet" as a synonym for all of them.

### Phase 2: Make account the only economic default

All economic defaults must come from canonical account resolution only.

### Phase 3: Introduce explicit agent identity

Add first-class `agent_id` to:

- automation
- capability invocation
- task scheduling
- audit events

In the first pass, treat `agent_id` as a stable explicit label.
Do not block this phase on agent key infrastructure.

### Phase 4: Introduce device identity into audit path

Attach `device_id` / `node_id` to write-side traces and operational events.

In the first pass, this can resolve from existing node/runtime state plus trusted-device authorization state.
Do not build a new distributed device registry first.

### Phase 5: Add delegation / authorization model

Longer term:

- account owns economic outcomes
- devices receive owner-scoped authority
- signers prove those devices may write
- agents may later receive scoped authority under an authorized device

That will allow multi-agent orchestration without private-key duplication becoming the whole story.

## Immediate Implementation TODO

1. Treat this document as the architectural truth for all identity work.
2. Stop calling the economic principal "wallet" in new code and new docs.
3. Make trusted device identity the V1 authorization boundary.
4. Keep `account_address` + device authorization + signer coherence as the only hard economic gate.
5. Add explicit `device_id` or `node_id` to beta trace / audit records.
6. Keep `session_id` / `trace_id` mandatory for operationally important writes.
7. Add explicit `agent_id` to write-side automation / invocation envelopes as an audit label.
8. Define expiry and revocation semantics for trusted device authorization.
9. Expose account mode, trusted-device mode, and signing capability consistently in Dashboard.
10. Adapt CLI to make device attach / verify the default multi-device flow.
11. Define a stable SDK-facing identity envelope for downstream systems like Thronglets.
12. Defer agent keys and fine-grained delegation until device-rooted V1 proves insufficient.

## Minimal Identity Envelope

The stable identity envelope we should aim to emit first is:

```json
{
  "account_address": "oasyce1...",
  "device_id": "device-123",
  "can_sign": true,
  "signer_type": "oasyced_local | native_signer | external | none",
  "agent_id": "codex-mbp",
  "session_id": "sess-...",
  "trace_id": "trace-..."
}
```

If Oasyce can emit this envelope consistently, downstream systems like Thronglets already get the separation they need without requiring a much heavier identity stack.

## One-Sentence Summary

**In Oasyce, the wallet/account owns value, the signer authorizes writes, the agent makes decisions, the device runs the agent, and the session records one concrete execution.**

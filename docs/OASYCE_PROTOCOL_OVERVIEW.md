# Oasyce Protocol Overview

## What is Oasyce?

Oasyce is a decentralized AI capability marketplace where data owners register assets with cryptographic proof-of-provenance (PoPc), AI developers list intelligent services, and autonomous agents discover, price, trade, and settle everything using bonding curves and escrow-protected OAS tokens. The protocol provides a unified framework for data rights, capability delivery, and consensus-driven trust.

---

## Architecture

The protocol is organized into four core layers:

### 1. Consensus Layer

A Proof-of-Stake (PoS) consensus engine that secures the network, produces blocks, and coordinates validators. Event-sourced design: all state is derived from an append-only log of stake events.

Key components:
- **State machine**: Single entry point `apply_operation()` for all state mutations
- **Validator registry**: Registration, delegation, exit, jail/unjail lifecycle
- **Rewards**: Block rewards with halving + work rewards for verified tasks
- **Slashing**: Three penalty conditions (offline, double-sign, low-quality)
- **Governance**: On-chain stake-weighted voting for parameter changes

### 2. Marketplace Layer

Discovery and trading of data assets and AI capabilities:
- **Schema Registry**: Unified validation for four asset types (see below)
- **Discovery Engine**: Recall (broad retrieval by intent/semantic/tag) then Rank (trust + economics) with feedback loop
- **Pricing**: Bonding curve with demand, scarcity, quality, freshness, and rights-type factors. Supports auto/fixed/floor pricing modes.

### 3. Settlement Layer

Handles all financial operations:
- **Bonding curve**: Automatic price discovery -- more buyers raise the price
- **Escrow**: Funds locked before capability execution, released after quality verification
- **Share minting**: Early buyers earn proportionally more (diminishing: 100% -> 80% -> 60% -> 40%)
- **Multi-asset balances**: Per-address per-asset tracking (OAS, USDC, DATA_CREDIT, CAPABILITY_TOKEN)

### 4. Identity Layer

Ed25519 cryptographic identities for all network participants:
- **Key generation**: `oasyce keys generate`
- **Signing**: All operations can be signed for replay protection
- **Chain ID**: Operations include `chain_id` to prevent cross-chain replay
- **Watermarking**: Content fingerprinting and distribution tracing

---

## Asset Types

The Schema Registry validates four asset types:

| Type | Description | Example |
|------|-------------|---------|
| `data` | Registered data assets with PoPc certificates | Medical imaging dataset |
| `capability` | AI services with callable endpoints | Translation API, image generation |
| `oracle` | External data feeds | Price feeds, weather data |
| `identity` | Network identity records | Validator registration, agent profiles |

Each asset includes metadata: owner, tags, timestamps, risk level, rights type, and optional co-creator shares.

---

## Key Flow: Register -> Price -> Trade -> Settle

### 1. Register

```bash
oasyce register photo.jpg --owner alice --tags "photography,landscape"
```

The engine pipeline runs: **Scan -> Classify -> Metadata -> PoPc Certificate -> Register**

- File is hashed and fingerprinted
- Risk engine auto-classifies as `public` / `internal` / `sensitive`
- A proof-of-provenance certificate (PoPc) is generated
- Asset is registered on the network with an ID

### 2. Price

```bash
oasyce quote ASSET_ID
```

The bonding curve computes the current price based on:
- How many times the asset has been queried (demand)
- How many similar assets exist (scarcity)
- The data quality score (quality)
- How old the data is (freshness)
- The declared rights type (rights multiplier)

### 3. Trade

```bash
oasyce buy ASSET_ID
```

- Buyer pays the quoted price in OAS
- Shares are minted to the buyer (diminishing returns for later buyers)
- The asset's spot price adjusts upward on the bonding curve

### 4. Settle

Settlement is automatic:
- Protocol fee (5% on capability invocations) is deducted
- Creator and protocol fees are distributed
- Share ownership is recorded on-chain

---

## Capability Delivery Flow

AI capability providers can list endpoints that other agents invoke via the protocol.

### 1. Register Endpoint

```bash
oasyce capability register \
  --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx \
  --price 0.5 \
  --tags nlp,translation
```

The provider's API key is encrypted at rest and never exposed to consumers.

### 2. Discover

```bash
oasyce discover --intents "translate" --tags nlp
```

The discovery engine uses a four-layer pipeline:
1. **Intent matching**: Parse natural language intents
2. **Semantic search**: Vector similarity on capability descriptions
3. **Tag filtering**: Exact tag match
4. **Ranking**: Trust score + economic signals + feedback loop

### 3. Escrow Lock

When a consumer invokes a capability, funds are locked in escrow before execution begins. This protects both parties.

### 4. Invoke

```bash
oasyce capability invoke CAP_ID --input '{"text": "hello", "target": "es"}'
```

The gateway routes the request to the provider's registered endpoint.

### 5. Settle

On success, the escrow releases:
- **95%** to the provider
- **5%** protocol fee

On failure (timeout, error), the escrow refunds the consumer in full.

---

## Consensus Overview

### Proof of Stake (PoS)

- **Minimum stake**: 10,000 OAS to become a validator
- **Commission**: Set by validator in basis points (max 5000 = 50%)
- **Delegation**: Any OAS holder can delegate to validators and earn proportional rewards
- **Unbonding**: 28-day cooldown period when undelegating

### Epochs and Slots

Block production is organized by epochs and slots, derived purely from block height:

```
epoch = block_height // blocks_per_epoch
slot  = block_height % blocks_per_epoch
```

- **Testnet**: 10 blocks per epoch
- Leader election: stake-weighted deterministic random selection per slot

### Validators

Validator lifecycle: **Register -> Active -> (Jailed) -> Exit**

- Register with minimum stake via `oasyce consensus register --stake 10000`
- Produce blocks when elected as slot leader
- Get jailed for misbehavior (offline, double-sign)
- Unjail after penalty expires
- Voluntary exit with unbonding period

### Fork Choice

Longest chain wins, with stake-weighted tiebreaker. Reorg support via event-sourced rollback with a max reorg depth limit.

---

## Agent Scheduler

The protocol includes an autonomous agent scheduler that can run unattended:

- **Scan**: Periodically scan configured directories for new data assets
- **Register**: Auto-register discovered assets (subject to trust level settings)
- **Trade**: Auto-buy capabilities matching configured tags (within spend limits)
- **Trust levels**:
  - Level 0: All actions require manual approval
  - Level 1: High-confidence actions auto-execute
  - Level 2: Full auto, only anomalies flagged

Configuration includes scan paths, execution interval, auto-register/trade toggles, trade tags, and max spend per cycle.

---

Source files:
- `oasyce_plugin/consensus/` -- Consensus engine (PoS, rewards, slashing, governance)
- `oasyce_plugin/schema_registry/` -- Asset type validation
- `oasyce_plugin/services/pricing/` -- Bonding curve pricing
- `oasyce_plugin/services/discovery/` -- Recall-Rank discovery
- `oasyce_plugin/services/capability_delivery/` -- Endpoint registry, escrow, gateway, settlement
- `oasyce_plugin/engines/` -- Scan/classify/metadata/PoPc pipeline
- `oasyce_plugin/cli.py` -- CLI commands
- `oasyce_plugin/gui/app.py` -- Dashboard SPA

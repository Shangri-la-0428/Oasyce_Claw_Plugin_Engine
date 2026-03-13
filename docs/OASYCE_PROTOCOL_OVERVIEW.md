# Oasyce Protocol Overview

*The rights-clearing network for machine-to-machine data economy.*

---

## The Problem

For twenty years, "data is the new oil" remained a slogan. The coordination cost of human-to-human data-rights clearing — contracts, lawyers, pricing negotiation, leak enforcement — exceeded the value of the data itself. No marketplace scaled.

## The Inflection Point

AI agents have become the primary consumers of data. This changes everything. Machines verify signatures in milliseconds, settle transactions atomically, price algorithmically, and trace leaks cryptographically. Every friction that killed human data-rights marketplaces is eliminated by machine-native infrastructure.

**There is no rights-clearing network for this new economy. Oasyce builds it.**

## What Oasyce Is

A decentralized protocol where AI agents autonomously register, license, settle, and enforce data rights. No central server. Every node is the network. Humans run nodes and collect revenue.

Think: **Bitcoin for data rights** — but the "miners" are AI agents, and the "transactions" are data-rights settlements.

### Bit Economy ≠ Atom Economy

In the physical world, selling means transferring ownership — if I have it, you don't. Digital data breaks this model: bits copy at zero cost, scarcity doesn't exist naturally.

**Oasyce does not sell data. It settles data rights:**

| Right | Description | Transferable? |
|-------|-------------|---------------|
| Attribution | Permanent proof of origin | ❌ Never |
| Access | Permission to decrypt and view | ✅ Yes |
| Usage | License terms (commercial, AI training, resale) | ✅ Yes |
| Revenue | Share of income when data generates value | ✅ Yes |

A single dataset can have free access (open source) but restricted commercial usage. Or free usage but revenue-sharing on derivatives. The protocol is agnostic — it enforces whatever rights the creator defines.

---

## Architecture

### Protocol Stack

```
┌─────────────────────────────────────────┐
│  Agent Layer (AI / Human)               │  ← Skills API, CLI, Web GUI
├─────────────────────────────────────────┤
│  Settlement Layer                       │  ← Bancor bonding curves, fee split
├─────────────────────────────────────────┤
│  Consensus Layer                        │  ← PoS, slashing, block rewards
├─────────────────────────────────────────┤
│  Network Layer                          │  ← P2P TCP mesh, block sync
├─────────────────────────────────────────┤
│  Storage Layer                          │  ← SQLite ledger, IPFS-compatible
├─────────────────────────────────────────┤
│  Crypto Layer                           │  ← Ed25519 signatures, Merkle trees
└─────────────────────────────────────────┘
```

### What's Been Built (9 Phases, 220 Tests Passing)

| Phase | Component | Purpose |
|-------|-----------|---------|
| 1 | Ed25519 Cryptography | Key generation, signatures, certificate signing |
| 2 | SQLite Persistent Ledger | Blockchain-structured storage, Merkle trees |
| 3 | Blockchain Structure | Block mining, hash chaining, chain verification |
| 4 | P2P Networking | TCP+JSON mesh, peer discovery (port 9527) |
| 5 | Block Synchronization | 3-way validation, chain download, fork detection |
| 6 | Consensus | Longest chain rule, reorganization, rate limiting |
| 7 | Multi-Node Demo | N-node local network with full consensus |
| 8 | Staking Economy | PoS validators, slashing, halving block rewards |
| 9 | Fingerprint Watermarking | Steganographic embedding, per-buyer tracing |

**Plus:** Web GUI dashboard (localhost:8420), settlement engine with Bancor curves, privacy filter, IPFS-compatible storage, PoPC verification service.

**All implemented in Python. 220 tests. Zero external infrastructure required — runs on a single laptop.**

---

## Core Mechanisms

### 1. Data Ownership — PoPC (Proof of Physical Capture)

Every data asset is registered with a cryptographic certificate:

```
File → SHA-256 hash → Ed25519 signature → PoPC Certificate → On-chain record
```

The certificate proves: *this specific file existed at this time, owned by this key*. Unforgeable, timestamped, verifiable by any node.

### 2. Algorithmic Pricing — Bancor Bonding Curve

No human sets the price. The protocol does.

**Formula:** `ΔTokens = S × ((1 + ΔR/R)^F − 1)`

- **S** = current supply, **R** = reserve balance, **F** = 0.20 (connector weight)
- More demand → price rises automatically
- Continuous liquidity — always tradeable, no order book

**Worked example:**
- Initial: 1,000 tokens, 100 OAS reserve → spot price **0.50 OAS/token**
- First buyer spends 100 OAS → receives 143.2 tokens → price rises to **0.85 OAS/token**
- Second buyer spends 100 OAS → receives 94.4 tokens → price rises to **1.17 OAS/token**
- Early participation is rewarded. Always.

### 3. Revenue Split — Two Layers

**Settlement Layer (per purchase):**

```
100 OAS payment
├── 5% protocol fee → 2.5 OAS burned + 2.5 OAS to verifier
└── 95% net deposit → enters bonding curve (pushes price up)
```

**Network Layer (data access fees):**

```
Creator:    70%   ← data owners earn the most
Validators: 20%   ← split by stake weight
Burn:       10%   ← permanent deflation
```

**Total burn per 100 OAS: ~12 OAS (12%).** Every transaction makes OAS scarcer.

### 4. Staking & Slashing

Run a node → stake OAS → earn block rewards + tx fees. Misbehave → lose your stake.

| | |
|---|---|
| Minimum stake | 1,000 OAS |
| Block reward | 50 OAS/block, halving yearly |
| Unbonding | 7 days (no hit-and-run) |
| Malicious block | **100% stake slashed** |
| Double block | 50% slashed |
| Prolonged offline | 5%/day bleed |

Slashed tokens are **burned, not redistributed**. Slashing is punitive, not a transfer.

### 5. Fingerprint Watermarking

Every buyer receives a uniquely watermarked copy of the data.

```
Data purchase → generate fingerprint (HMAC-SHA256) → embed via steganography → record on-chain
```

If leaked:

```
Leaked file → extract watermark → query ledger → identify buyer + timestamp → cryptographic proof
```

Two embedding strategies:
- **Text/code assets:** Whitespace steganography (spaces vs tabs at line endings)
- **Binary assets:** Trailer block with magic bytes + CRC32

The watermark survives partial modification. The leaker is always identifiable.

---

## Economics at a Glance

**Max supply:** 100,000,000 OAS

### Block Rewards (Halving Every 2 Years)

| Years | Block Reward | Annual Emission |
|-------|-------------|-----------------|
| 1-2 | 4.0 OAS | 2,102,400 |
| 3-4 | 2.0 OAS | 1,051,200 |
| 5-6 | 1.0 OAS | 525,600 |
| 7-8 | 0.5 OAS | 262,800 |

**Year 1 inflation:** ~5.25% (healthy range).

### Transaction Fee Split

Every data purchase:

```
Creator:    60%   ← data owners earn the most
Validators: 20%   ← split by stake weight
Burn:       15%   ← permanent deflation
Treasury:    5%   ← protocol development
```

### Deflation

At 50,000 OAS daily volume → 7,500 OAS burned daily → 2.74M annually.
**Year 1 emission: 2.1M.** Net result: supply already shrinking.

### Staking

- **Minimum stake:** 10,000 OAS
- **Slashing:** 100% for malicious blocks, 50% for double blocks, 5%/day offline
- **All slashed tokens burned**

### Bonding Curve (F = 0.35)

Provides OAS liquidity. **Decoupled from fee settlement** — reserve is never drained by fee distributions.

### Game Theory

| Attack | Cost | Reward | EV |
|--------|------|--------|----|
| Malicious block | 10,000+ OAS | ~12 OAS | **−9,499 OAS** |
| Double block | 50% of stake | ~4 OAS | **−4,996 OAS** |
| 51% stake | >50% of all staked OAS | Censorship only | Prohibitive |

**Every attack is economically irrational.** Honesty is the optimal strategy.

---

## Why This Couldn't Have Been Built Before

1. **No demand.** Before 2024, machines didn't autonomously buy data. No agents, no M2M economy, no need for a settlement network.
2. **No substrate.** Ed25519, Bancor curves, PoS consensus, steganography — each existed, but no one had a reason to compose them for machine data-rights settlement.
3. **No entry point.** Oasyce nodes run as plugins inside AI agent frameworks. The data entry point is the agent itself — it registers data as a side effect of working. No human upload required.

**The demand appeared. The building blocks existed. Someone had to wire them together.**

---

## Bootstrapping: The First 100 Agents

**Phase 1 — Self-generated data (zero friction):**
Every AI agent already produces outputs. The plugin registers them automatically. No behavior change.

**Phase 2 — Curated seed datasets:**
Core team seeds high-value, licensable datasets (API docs, financial feeds, sensor data, multilingual corpora).

**Phase 3 — Creator incentive program:**
Early providers get boosted OAS from the Ecosystem Incentives pool (25M OAS). First-mover data appreciates on the curve.

**Phase 4 — Framework integrations:**
One-line integration with OpenClaw, LangChain, AutoGPT — any agent can discover and purchase data via API.

---

## Competitive Landscape

| Project | Focus | Difference from Oasyce |
|---------|-------|----------------------|
| Ocean Protocol | Data marketplace | Human-operated, no agent-native pipeline |
| Filecoin | Storage | Stores data, doesn't price or settle access |
| Bittensor | AI compute | Compute incentives, not data ownership |
| Fetch.ai | Agent framework | Infrastructure, no settlement protocol |
| **Oasyce** | **M2M data settlement** | **End-to-end: autonomous ownership, pricing, trading, watermarking** |

---

## Alignment: Everyone Makes Money the Same Way

No SaaS fee. No subscription. No platform cut.

Every participant earns by holding OAS and contributing to the network. Growth → more transactions → more burns → less supply → higher value. Everyone's incentive is identical.

```
More agents → more data → more transactions → more burns
→ less supply → higher OAS value → more validators → more agents
```

---

## Current Status

| Metric | Value |
|--------|-------|
| Codebase | ~50 Python source files |
| Tests | 220 passing |
| Dependencies | cryptography, python-dotenv, aiohttp |
| Runs on | Single laptop (macOS/Linux, Python 3.9+) |
| Demo | `oasyce demo-network --nodes 3` |
| GUI | `oasyce gui` on localhost:8420 |

### What's Next

| Phase | Description |
|-------|-------------|
| Open source | MIT license, PyPI package, CI |
| On-chain governance | Token-weighted parameter voting |
| Token contract | OAS on ERC-20 or Solana SPL |
| Multi-machine P2P | NAT traversal, node discovery |
| Semantic watermarking | Robust against formatters and LLMs |
| Agent marketplace | Discovery + purchase in one API call |

### Implementation Note

Current codebase uses SQLite as the ledger backend — a reference implementation optimized for simplicity. Production nodes may use distributed storage (RocksDB) or integrate with existing L1 chains for settlement finality.

---

## Repository

```
Oasyce_Claw_Plugin_Engine/
├── oasyce_plugin/
│   ├── crypto/          Ed25519 keys, Merkle trees
│   ├── storage/         SQLite ledger, IPFS client
│   ├── network/         P2P TCP node
│   ├── engines/         Core engines, PoPC, privacy filter
│   ├── services/
│   │   ├── settlement/  Bancor bonding curves
│   │   ├── staking/     PoS, slashing, rewards
│   │   └── verification/ PoPC verification
│   ├── fingerprint/     Watermark engine + registry
│   ├── bridge/          oasyce_core protocol bridge
│   ├── skills/          Agent Skills API
│   ├── gui/             Web dashboard
│   └── cli.py           Command-line interface
├── tests/               220 test cases
├── docs/
│   ├── ECONOMICS.md     Full economic model + game theory
│   └── OASYCE_PROTOCOL_OVERVIEW.md  ← this document
└── README.md
```

---

*Built by Shangrila. Designed for machines. Owned by everyone.*

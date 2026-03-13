# Oasyce Protocol Overview

*The settlement network for machine-to-machine data commerce.*

---

## The Problem

For twenty years, "data is the new oil" remained a slogan. The coordination cost of human-to-human data trade — contracts, lawyers, pricing negotiation, leak enforcement — exceeded the value of the data itself. No marketplace scaled.

## The Inflection Point

AI agents have become the primary consumers of data. This changes everything. Machines verify signatures in milliseconds, settle transactions atomically, price algorithmically, and trace leaks cryptographically. Every friction that killed human data marketplaces is eliminated by machine-native infrastructure.

**There is no settlement network for this new economy. Oasyce builds it.**

## What Oasyce Is

A decentralized protocol where AI agents autonomously own, price, trade, and protect data. No central server. Every node is the network. Humans run nodes and collect revenue.

Think: **Bitcoin for data ownership** — but the "miners" are AI agents, and the "transactions" are data access purchases.

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

### Token Supply

| Year | Block Reward | Annual Emission | Cumulative |
|------|-------------|-----------------|------------|
| 1 | 50.0 OAS | 26,280,000 | 26.3M |
| 2 | 25.0 OAS | 13,140,000 | 39.4M |
| 3 | 12.5 OAS | 6,570,000 | 46.0M |
| 5 | 3.125 OAS | 1,642,500 | 50.9M |
| 10 | 0.098 OAS | 51,328 | 52.5M |

**Asymptotic max: ~52.56M OAS** (before burns).

### Deflation

At 10,000 OAS daily transaction volume → ~1,200 OAS burned daily → 438,000 annually.

**Crossover point:** When daily volume exceeds ~36,000 OAS (Year 1) or ~18,000 OAS (Year 2), daily burn exceeds daily emission. Total supply begins shrinking.

### Game Theory

| Attack | Cost | Reward | EV | Verdict |
|--------|------|--------|----|---------|
| Malicious block | 1,000+ OAS at risk | ~150 OAS | **−942 OAS** | Irrational |
| Double block | 50% of stake | ~50 OAS | **−450 OAS** | Irrational |
| 51% stake | >50% of all OAS | Censorship only | Scales with network | Prohibitive |
| Leak after purchase | Reputation + legal | Redistribute data | Traceable via watermark | Deterred |

**Every attack is economically irrational.** The protocol makes honesty the optimal strategy.

---

## Why This Couldn't Have Been Built Before

1. **No demand.** Before 2024, machines didn't autonomously buy data. No agents, no M2M economy, no need for a settlement network.
2. **No substrate.** Ed25519, Bancor curves, PoS consensus, steganography — each existed, but no one had a reason to compose them for machine data commerce.
3. **No entry point.** Oasyce nodes run as plugins inside AI agent frameworks (OpenClaw). The data entry point is the agent itself — it registers data as a side effect of working. No human upload required.

**The demand appeared. The building blocks existed. Someone had to wire them together. That's what Oasyce is.**

---

## Alignment: Everyone Makes Money the Same Way

There is no SaaS fee, no subscription, no platform cut.

Every participant — founder, validator, data creator, node operator — earns by holding OAS and contributing to the network. When the network grows, OAS becomes scarcer (burns) and more valuable (demand). Everyone's incentive is identical: **make the network better.**

```
More nodes → more data → more agents using it → more transactions
→ more burns → less supply → higher OAS value → more nodes want to join
```

This is the flywheel. Once it spins, it's self-reinforcing.

---

## Current Status

| Metric | Value |
|--------|-------|
| Codebase | ~50 Python source files |
| Tests | 220 passing (pytest) |
| Dependencies | cryptography, python-dotenv, aiohttp (minimal) |
| Runs on | Single laptop (macOS/Linux, Python 3.9+) |
| Demo | `oasyce demo-network --nodes 3` — full multi-node consensus |
| GUI | `oasyce gui` — web dashboard on localhost:8420 |

### What Works Today

- Register data assets with cryptographic certificates
- P2P network with block sync and consensus
- Bancor bonding curve pricing and settlement
- Staking with slashing and halving rewards
- Fingerprint watermarking with on-chain tracing
- Web dashboard for node monitoring
- Full CLI toolset

### What's Next

| Phase | Description |
|-------|-------------|
| Open source release | MIT/Apache 2.0, GitHub Actions CI, PyPI package |
| Token contract | On-chain OAS (ERC-20 or Solana SPL) |
| Multi-machine deployment | NAT traversal, node discovery, real-world P2P |
| Agent marketplace | Agents browse, purchase, and consume data autonomously |

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

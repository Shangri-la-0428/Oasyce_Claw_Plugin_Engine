# Oasyce

![CI](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/actions/workflows/ci.yml/badge.svg) ![PyPI](https://img.shields.io/pypi/v/oasyce) ![Python](https://img.shields.io/pypi/pyversions/oasyce) ![License](https://img.shields.io/github/license/Shangri-la-0428/Oasyce_Claw_Plugin_Engine)

> Chinese version: [README_CN.md](README_CN.md)

**Your data has sovereignty. Your capabilities have a price.**

Oasyce is a decentralized **rights settlement network** -- every data access and capability invocation between AI agents is priced, escrowed, and settled automatically.

Think of it this way: you take a photo, and an AI wants to use it for training. Today, your data gets used for free. With Oasyce, the AI must pay for access, and you receive earnings automatically. Just as Stripe gave the internet a payment layer, Oasyce gives the AI world a **rights settlement layer**.

```bash
pip install oasyce
oasyce start
```

Open `http://localhost:8420` and you're in.

---

## What Can Oasyce Do for Me?

### I have data (photos, documents, sensor data...)

Register your data as an on-chain asset. Any AI that accesses it must pay. The more people use it, the higher the price goes (automatic pricing via bonding curves). Register early, earn more.

```bash
oasyce register myfile.csv --owner alice --tags medical,imaging
```

### I'm an AI developer

Your agent can publish capabilities to the network -- things like "medical image analysis", "translation", or "code review". Every time another agent calls your service, you earn. Quality is backed by staked collateral, so there's real accountability.

### I want to build on the protocol

Oasyce is a protocol, not a platform. You can build anything on top -- data exchanges, agent labor markets, AI capability stores. The protocol handles pricing, settlement, reputation, and disputes for you.

---

## 30-Second Demo

```bash
pip install oasyce
oasyce demo
```

This runs the full pipeline end to end: **register -> price -> purchase -> settle -> distribute earnings**. You'll see how data rights are created and traded in real time.

---

## Quick Start

### 1. Install

```bash
pip install oasyce
```

> Requires Python 3.9+

### 2. Health check

```bash
oasyce doctor
```

Checks your keys, ports, dependencies, and network connectivity. If something is wrong, it tells you how to fix it.

### 3. Start the node

```bash
oasyce start
```

This launches:
- **Protocol node** (port 8000) -- matching, bidding, settlement
- **Dashboard** (port 8420) -- register data, browse assets, invoke capabilities

### 4. Register your first asset

Command line:
```bash
oasyce register myfile.csv --owner alice --tags medical,imaging
```

Or drag and drop in the Dashboard.

### 5. Browse and trade

Open `http://localhost:8420/explore` to see all data assets and AI capabilities on the network. Check prices, buy shares, and invoke services.

---

## Testnet

Don't want to use real OAS? Join the testnet:

```bash
oasyce testnet onboard    # Join the testnet
oasyce testnet faucet     # Get free test tokens
```

---

## CLI Reference

```
oasyce start              # Start everything (recommended)
oasyce demo               # Run the full demo pipeline
oasyce doctor             # Health check
oasyce info               # Project info, links, architecture, economics
oasyce info --section economics    # Token economics details
oasyce info --section architecture # Technical architecture
oasyce info --json        # Full info as JSON
```

### Data Assets

```
oasyce register <file>    # Register a data asset
  --rights-type original|co_creation|licensed|collection
  --co-creators '[{"address":"A","share":60},{"address":"B","share":40}]'
oasyce search <tag>       # Search by tag
oasyce quote <asset_id>   # Get bonding curve price
oasyce buy <asset_id>     # Buy shares
```

### Disputes

```
oasyce dispute <id> --reason "..."     # File a dispute against an asset
oasyce resolve <id> --remedy delist    # Resolve a dispute
  --remedy delist|transfer|rights_correction|share_adjustment
  --details '{"new_owner":"0x..."}'
```

### Capability Discovery

```
oasyce discover --intents "translation,text processing"  # Recall->Rank discovery
  --tags ai,nlp --limit 5
```

### Consensus (PoS)

```
oasyce consensus status                             # Current epoch/slot/validators
oasyce consensus register --stake 10000             # Register as validator
oasyce consensus delegate <validator_id> --amount 500    # Delegate stake
oasyce consensus undelegate <validator_id> --amount 200  # Undelegate
oasyce consensus rewards [--epoch N]                # Reward history
oasyce consensus exit                               # Voluntary exit
```

### Governance

```
oasyce governance propose --title "..." --description "..." --changes '[...]' --deposit 1000
oasyce governance vote <proposal_id> --option yes|no|abstain
oasyce governance list [--status voting|passed|rejected]
```

### Capability Marketplace

```
oasyce capability register --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx --price 0.5 --tags nlp,translation
oasyce capability list [--tag nlp]
oasyce capability invoke CAP_ID --input '{"text":"hello"}'
oasyce capability earnings --provider addr
```

### Node Management

```
oasyce node start         # Start P2P node only
oasyce node info          # Show node identity
oasyce node peers         # List known peers
oasyce node ping <host>   # Ping another node
```

### Other

```
oasyce testnet onboard    # Join the testnet
oasyce testnet faucet     # Get test tokens
oasyce gui                # Start Dashboard only (port 8420)
oasyce explorer           # Block explorer (port 8421)
oasyce keys generate      # Generate Ed25519 keypair
oasyce keys show          # Show public key
```

All commands support `--json` output for programmatic use.

---

## OpenClaw Users

If you're using [OpenClaw](https://github.com/openclaw/openclaw), just tell your agent:

```text
Install the oasyce skill
```

Your agent will install the Oasyce skill automatically, letting you register data, query assets, and invoke capabilities using natural language. No command line needed.

---

## Core Concepts

| Concept | What it means | Analogy |
|---------|--------------|---------|
| **OAS** | The protocol token; all transactions settle in OAS | Arcade tokens for a game center |
| **Bonding Curve** | Automatic pricing -- more buyers means a higher price | Concert tickets that get more expensive as they sell |
| **Diminishing Returns** | Earnings taper: 100% -> 80% -> 60% -> 40% | Prevents any single party from taking the whole pie |
| **Escrow** | Funds are locked first, released only after delivery | Like buyer protection on any e-commerce platform |
| **Reputation** | A long-term trust score; bad behavior lowers it | A credit score that follows you |
| **Capability** | A callable service published by an agent | A freelancer on a gig platform -- available for work, paid per job |
| **Rights Type** | Declares data origin (original / co-creation / licensed / collection) | Like songwriter credits vs. cover versions in music |
| **Dispute** | Challenge an asset for infringement; an arbitrator resolves it | A chargeback or formal complaint process |

### Five Rules

1. **Access requires collateral** -- Want to see the data? Put up a deposit first.
2. **Exposure is irreversible** -- Once you've accessed data, the network remembers.
3. **Identity has consequences** -- Bad behavior follows your identity permanently.
4. **Data is traceable** -- Fingerprint watermarks track every copy.
5. **Accountability never expires** -- Disputes can be raised at any time.

---

## Dashboard

After running `oasyce start`, open `http://localhost:8420` in your browser. The dashboard provides:

- **Overview** -- Network status, registered assets, transaction volume
- **Register** -- Register files as data assets (drag and drop supported)
- **Explore** -- Browse all assets and capabilities, view prices, buy shares
- **AHRP** -- Watch the full agent handshake and trade flow
- **Watermark** -- Embed data fingerprints and trace leaks
- **Stake** -- Stake OAS to become a validator

A block explorer is also available at `http://localhost:8421`.

---

<details>
<summary><h2>Architecture (click to expand)</h2></summary>

### System Overview

```
+-------------------------------------------------+
|                  oasyce (PE)                     |
|  CLI - Dashboard - P2P Node - Skills - Bridge   |
|  Schema Registry - Risk Engine - Feedback Loop  |
+-------------------------------------------------+
|               oasyce-core (Protocol)            |
|  AHRP - Settlement - Staking - Capabilities    |
|  Crypto - Reputation - Access Control - Standards|
+-------------------------------------------------+
```

- **oasyce-core**: Protocol engine (678 tests). Matching, escrow, bonding curve pricing, fee distribution, capability assets, dispute arbitration.
- **oasyce** (this repo): User-facing layer (590 tests). CLI, Dashboard, P2P networking, Schema Registry, Discovery (Recall -> Rank), Feedback Loop, automatic risk classification.

### Module Map

```
oasyce_plugin/
+-- schema_registry/  # Unified schema validation (data / capability / oracle / identity)
+-- engines/
|   +-- core_engines.py  # Scan -> Classify -> Metadata -> PoPc -> Register (+ auto risk)
|   +-- schema.py        # Backward-compat entry (delegates to schema_registry)
|   +-- risk.py          # Auto risk classification (public / internal / sensitive)
+-- consensus/           # PoS consensus engine (event-sourced)
|   +-- core/            # Operation types, state transitions, validation
|   +-- storage/         # Append-only event log
|   +-- execution/       # Block production, mempool
|   +-- governance/      # On-chain proposals, stake-weighted voting
|   +-- network/         # HTTP sync, block download
|   +-- enforcement/     # Content fingerprinting, infringement detection
+-- services/
|   +-- discovery/       # Recall -> Rank capability discovery + feedback loop
|   +-- capability_delivery/  # Endpoint registry, escrow, gateway, settlement
|   +-- settlement/      # Settlement engine
+-- info.py              # Project info hub (shared by GUI / CLI / API)
+-- gui/app.py           # Dashboard SPA

oasyce_core/
+-- ahrp/           # Agent Handshake Routing Protocol (match + bid + settle)
+-- capabilities/   # Capability assets (register -> invoke -> escrow -> settle -> dispute)
+-- oracle/         # Oracle framework (weather / price / internal / aggregator)
+-- settlement/     # Bonding curve + fee distribution + diminishing returns
+-- staking/        # Validator staking + slashing
+-- network/        # P2P gossip mesh + peer exchange + scoring
+-- services/       # Access control, reputation, exposure tracking, leak detection
+-- standards/      # OAS unified asset standard (data + capability + oracle + identity)
+-- crypto/         # Ed25519 signatures + Merkle proofs
+-- storage/        # Ledger + IPFS
+-- server.py       # FastAPI entry point
```

### Economic Parameters

| Parameter | Value |
|-----------|-------|
| Max supply | No hard cap (block rewards converge via halving; supply reduced by slashing burns) |
| Block reward | 4 OAS |
| Fee factor (F) | 0.35 |
| Fee split | Data owner 60% / Validator 20% / Protocol 15% / Burn 5% |
| Diminishing returns | 100% -> 80% -> 60% -> 40% |
| Minimum stake | 10,000 OAS |
| Year-1 inflation | ~5.25% |

### Security Tiers

| Tier | Min Stake | Max Data Size | Liability Window |
|------|-----------|---------------|-----------------|
| L0 | 10,000 OAS | 10 MB | 1 day |
| L1 | 50,000 OAS | 100 MB | 3 days |
| L2 | 200,000 OAS | 1 GB | 7 days |
| L3 | 1,000,000 OAS | Unlimited | 30 days |

### Four Asset Types

| Type | Description | Examples |
|------|------------|---------|
| **data** | Files and datasets | Medical images, CSVs, PDFs |
| **capability** | Callable AI services | Translation, code review, image analysis |
| **oracle** | Data feeds | Price feeds, weather data |
| **identity** | Identity credentials | DIDs, reputation proofs |

All types are validated by the Schema Registry, each with independent schema versioning.

### Tests

```bash
cd oasyce-core && pytest                    # 678 tests
cd oasyce-claw-plugin-engine && pytest      # 590 tests
```

</details>

---

## Documentation

- [Protocol Overview](docs/OASYCE_PROTOCOL_OVERVIEW.md)
- [Economics](docs/ECONOMICS.md)
- [Protocol Specification](docs/PROTOCOL.md)
- [Testnet Guide](docs/TESTNET.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute.

## Community

- [Discord](https://discord.gg/tfrCn54yZW) -- Questions, feedback, chat
- [GitHub Issues](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/issues) -- Bug reports and feature requests

## License

MIT

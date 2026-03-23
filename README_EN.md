# Oasyce

[![CI](https://github.com/Shangri-la-0428/oasyce-net/actions/workflows/ci.yml/badge.svg)](https://github.com/Shangri-la-0428/oasyce-net/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/oasyce)](https://pypi.org/project/oasyce/)
[![Python](https://img.shields.io/pypi/pyversions/oasyce)](https://pypi.org/project/oasyce/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 中文版: [README.md](README.md)

**Your data has sovereignty. Your capabilities have a price.**

Oasyce is a decentralized **rights settlement network** — every data access and capability invocation between AI agents is priced, escrowed, and settled automatically.

Think of it this way: you take a photo, and an AI wants to use it for training. Today, your data gets used for free. With Oasyce, the AI must pay for access, and you receive earnings automatically. Just as Stripe gave the internet a payment layer, Oasyce gives the AI world a **rights settlement layer**.

```bash
pip install oasyce
oas doctor            # Health check
oas start             # Dashboard at localhost:8420
```

Browser opens automatically. You're in.

---

## What Can Oasyce Do for Me?

### I have data (photos, documents, sensor data...)

Register your data as an on-chain asset. Any AI that accesses it must pay. The more people use it, the higher the price goes (automatic pricing via bonding curves). Register early, earn more.

```bash
oas register myfile.csv --owner alice --tags medical,imaging
```

### I'm an AI developer

Your agent can publish capabilities to the network — things like "medical image analysis", "translation", or "code review". Every time another agent calls your service, you earn. Quality is backed by staked collateral, so there's real accountability.

### I want to build on the protocol

Oasyce is a protocol, not a platform. You can build anything on top — data exchanges, agent labor markets, AI capability stores. The protocol handles pricing, settlement, reputation, and disputes for you.

---

## 30-Second Demo

```bash
pip install oasyce
oas demo
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
oas doctor
```

Checks your keys, ports, dependencies, and network connectivity. If something is wrong, it tells you how to fix it.

### 3. Start Dashboard

```bash
oas start
```

Browser auto-opens `http://localhost:8420` — register data, browse assets, invoke capabilities.

For API server (programmatic access), run `oas serve` separately.

Or use Docker:

```bash
docker compose up -d
```

### 4. Register your first asset

Command line:
```bash
oas register myfile.csv --owner alice --tags medical,imaging
```

Or drag and drop in the Dashboard.

### 5. Browse and trade

Open `http://localhost:8420/explore` to see all data assets and AI capabilities on the network. Check prices, buy shares, and invoke services.

---

## Testnet

Don't want to use real OAS? Join the testnet:

```bash
oas testnet onboard    # Join the testnet
oas testnet faucet     # Get free test tokens
```

---

## CLI Reference

```
oas start              # Start Dashboard (recommended)
oas serve              # Start API server (programmatic access)
oas demo               # Run the full demo pipeline
oas doctor             # Health check
oas update             # Auto-update to latest version
oas info               # Project info, links, architecture, economics
oas info --section economics    # Token economics details
oas info --section architecture # Technical architecture
oas info --json        # Full info as JSON
```

### Data Assets

```
oas register <file>    # Register a data asset
  --rights-type original|co_creation|licensed|collection
  --co-creators '[{"address":"A","share":60},{"address":"B","share":40}]'
oas search <tag>       # Search by tag
oas quote <asset_id>   # Get bonding curve price
oas buy <asset_id>     # Buy shares
oas sell <asset_id> --amount <n>  # Sell shares back to the curve
  --max-slippage 0.05               # Slippage protection (default 5%)
```

### Disputes

```
oas dispute <id> --reason "..."     # File a dispute against an asset
oas jury-vote <id> --verdict consumer|provider  # Jury vote
oas resolve <id> --remedy delist    # Resolve a dispute
  --remedy delist|transfer|rights_correction|share_adjustment
  --details '{"new_owner":"0x..."}'
```

### Capability Discovery

```
oas discover --intents "translation,text processing"  # Recall->Rank discovery
  --tags ai,nlp --limit 5
```

### Capability Marketplace

```
oas capability register --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx --price 0.5 --tags nlp,translation
oas capability list [--tag nlp]
oas capability invoke CAP_ID --input '{"text":"hello"}'
oas capability earnings --provider addr
```

### Task Bounties (AHRP)

```
oas task post "Translate this document" --budget 50 --deadline 3600
oas task list                                  # List all tasks
oas task bid TASK_ID --price 30 --seconds 1800 # Place a bid
oas task select TASK_ID --agent AGENT_ID       # Select winner
oas task complete TASK_ID                      # Mark complete
oas task cancel TASK_ID                        # Cancel task
```

### AI Feedback

```
oas feedback "Buy flow has a bug" --type bug --agent my-agent
oas feedback "Add batch import" --type suggestion --json
```

### Consensus & Governance (Chain-Only)

These commands are implemented on the **L1 chain** (`oasyced`):

```
oasyced tx staking create-validator ...              # Register as validator
oasyced tx staking delegate <validator> <amount>uoas # Delegate stake
oasyced tx gov submit-proposal ...                   # Submit governance proposal
oasyced tx gov vote <proposal_id> yes|no|abstain     # Vote on proposal
```

See [oasyce-chain](https://github.com/Shangri-la-0428/oasyce-chain) for full chain CLI reference.

### Node Management

```
oas node start         # Start P2P node only
oas node info          # Show node identity
oas node peers         # List known peers
oas node ping <host>   # Ping another node
```

### Tiered Access

```
oas access quote <asset_id>                     # Quote bond for all levels (L0-L3)
oas access buy <asset_id> --level L0|L1|L2|L3   # Buy tiered access
oas access query <asset_id>                     # L0: aggregated stats
oas access sample <asset_id>                    # L1: redacted fragments
oas access compute <asset_id>                   # L2: TEE execution
oas access deliver <asset_id>                   # L3: full data delivery
```

### Other

```
oas testnet onboard    # Join the testnet
oas testnet faucet     # Get test tokens
oas update             # Auto-update to latest version
oas start --no-browser # Start Dashboard without auto-open
oas explorer           # Block explorer (port 8421)
oas keys generate      # Generate Ed25519 keypair
oas keys show          # Show public key
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
| **Bonding Curve** | Automatic pricing — more buyers means a higher price | Concert tickets that get more expensive as they sell |
| **Escrow** | Funds are locked first, released only after delivery | Like buyer protection on any e-commerce platform |
| **Reputation** | A long-term trust score; bad behavior lowers it | A credit score that follows you |
| **Capability** | A callable service published by an agent | A freelancer on a gig platform — available for work, paid per job |
| **Rights Type** | Declares data origin (original / co-creation / licensed / collection) | Like songwriter credits vs. cover versions in music |
| **Dispute** | Challenge an asset for infringement; jury resolves it | A chargeback or formal complaint process |

### Five Rules

1. **Access requires collateral** — Want to see the data? Put up a deposit first.
2. **Exposure is irreversible** — Once you've accessed data, the network remembers.
3. **Identity has consequences** — Bad behavior follows your identity permanently.
4. **Data is traceable** — Fingerprint watermarks track every copy.
5. **Accountability never expires** — Disputes can be raised at any time.

---

## Dashboard

Run `oas start` — browser opens automatically at `http://localhost:8420`. The dashboard provides:

- **Home** — Register data assets (drag & drop), network status, earnings overview
- **My Data** — Manage your assets and published capabilities, edit tags, delist/terminate
- **Market** — Browse assets, view prices, buy shares, task bounties, staking
- **Automation** — Agent scheduler: auto-scan, register, and trade on a timer
- **Network** — Node identity, fingerprint watermarks, contribution proofs, AI feedback

---

<details>
<summary><h2>Architecture (click to expand)</h2></summary>

### System Overview

```
┌──────────────────────────────────────────┐
│           oasyce-chain (Go L1)           │
│  CometBFT + x/datarights + x/settlement │
│  x/capability + x/reputation             │
│  gRPC :9090 / REST :1317                 │
├──────────────────────────────────────────┤
│           oasyce (Python v2.3.0)         │
│  CLI + Dashboard + API + Skills Bridge   │
│  Facade -> Settlement -> Ledger          │
│  1083 tests                              │
├──────────────────────────────────────────┤
│           DataVault (AI Skill)           │
│  scan -> classify -> privacy -> report   │
│  pip install odv[oasyce]                 │
└──────────────────────────────────────────┘
```

### Module Map

```
oasyce/
├── core/
│   ├── formulas.py          # Layer 0: pure math (bonding curve, fees, jury score)
│   └── evidence.py          # Evidence submission interface
├── storage/ledger.py        # Layer 1: all state CRUD, thread-safe
├── services/
│   ├── facade.py            # Layer 3: thin orchestration (every method < 15 lines)
│   ├── settlement/engine.py # Layer 2: bonding curve (delegates to core/formulas.py)
│   ├── reputation/          # Layer 2: score + decay
│   ├── access/              # Layer 2: equity -> tiered access
│   ├── capability_delivery/ # Product: endpoint registry, escrow, gateway
│   ├── discovery/           # Product: recall -> rank + feedback
│   ├── fingerprint.py       # Evidence provider
│   ├── watermark.py         # Evidence provider
│   └── leakage/             # Evidence provider
├── engines/
│   ├── core_engines.py      # Scan -> Classify -> Metadata -> PoPc -> Register
│   └── risk.py              # Evidence provider: risk classification
├── gui/app.py               # Layer 4: Dashboard
└── cli.py                   # Layer 4: CLI
```

### Economic Parameters

| Parameter | Value |
|-----------|-------|
| Token | OAS |
| Bonding Curve | Bancor, CW = 0.5 |
| Bootstrap Price | 1 OAS/token |
| Protocol Fee | 5% |
| Burn Rate | 2% |
| Reserve Solvency Cap | 95% |
| Fee Split | Provider 93%, Protocol 5%, Burn 2% |

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
pytest      # 1083 tests, 19 skipped
```

</details>

---

## Current Progress

| Repository | Version | Tests | Status |
|-----------|---------|-------|--------|
| **oasyce-chain** (Go L1) | Cosmos SDK v0.50.10 | 30+ | Phase A complete |
| **oasyce** (this repo) | v2.3.0 | 1083 | Feature complete, architecture enforced |
| **DataVault** | v0.2.0 | 44 | AI Skill mode ready |

### Completed

- Layered architecture enforcement (zero violations)
- Facade API complete (quote, buy, sell, dispute, jury_vote, evidence...)
- GUI Dashboard fully functional
- Architecture invariant tests (prevent facade bypass, SQL injection, engine unauthorized instantiation)
- PyPI release automation

### Next

- Whitepaper v4 parameter alignment (F=0.35, fee 60/20/15/5, burn 15%) — requires chain ConsensusVersion upgrade
- AHRP Task Market wiring (Python facade + API + CLI for existing x/work bounty system)
- Ecosystem growth (cross-chain data rights, privacy compute, mobile wallet)

---

## Documentation

- [Protocol Overview](docs/OASYCE_PROTOCOL_OVERVIEW.md)
- [Economics](docs/ECONOMICS.md)
- [Protocol Specification](docs/PROTOCOL.md)
- [Testnet Guide](docs/TESTNET.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute.

## Community

- [Discord](https://discord.gg/tfrCn54yZW) — Questions, feedback, chat
- [GitHub Issues](https://github.com/Shangri-la-0428/oasyce-net/issues) — Bug reports and feature requests

## License

MIT

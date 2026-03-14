# Oasyce Claw Plugin Engine

<div align="center">

**Decentralized data-rights clearinghouse — settle access, usage, and revenue rights for the AI era.**
**Local-first, zero-server, every node is the network.**

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-445%20passed-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[Quick Start](#quick-start) · [CLI Reference](#cli-reference) · [Architecture](#architecture) · [Access Control](#data-access-control) · [OAS-DAS](#oas-das-standard) · [PDC](#proof-of-data-contribution) · [Pricing](#dataset-pricing-curve) · [Economics](docs/ECONOMICS.md) · [Testing](#testing)

</div>

---

## Why Oasyce? Why Now?

For twenty years, "data is the new oil" remained a slogan. Humans couldn't coordinate data-rights clearing at scale — the cost of contracts, lawyers, reconciliation, and enforcement exceeded the value of the data itself.

Then AI agents arrived. For the first time in history, the primary consumers of data are machines, not people. Machines can verify signatures in milliseconds, settle atomically, price algorithmically, and trace leaks cryptographically. Everything that made human-to-human data-rights settlement impractical is exactly what machine-to-machine commerce does natively.

**Oasyce is the rights-clearing network for this new economy.** A protocol where AI agents autonomously register, license, settle, and enforce data rights — and humans simply run nodes and collect revenue.

### What We Settle: Rights, Not Data

In the atomic economy, you sell ownership — if I have the chair, you don't. In the bit economy, data can be copied infinitely at zero cost. **You cannot sell bits the way you sell atoms.** What you *can* sell are the **rights** attached to those bits:

- **Access rights** — who can decrypt and view this data
- **Usage rights** — can you train AI on it? resell it? use it commercially?
- **Revenue rights** — when this data generates value, who gets paid?
- **Attribution rights** — who created this, permanently and irrevocably

Oasyce registers and settles these rights. The data itself can be free (open source, Creative Commons) or gated — the protocol doesn't care. It cares about **who has what rights, and enforcing them automatically.**

---

- **PoPC (Proof of Physical Capture)** — Cryptographic certificates proving data provenance at the physical layer
- **Bancor Bonding Curves** — Algorithmic pricing: no negotiation, no middlemen, price emerges from demand
- **Staking Economy** — Run a node, stake OAS, become a stakeholder — your interests are the network's interests
- **Fingerprint Watermarking** — Steganographic watermarks embedded per-buyer; leak a file and we trace it back to you
- **P2P Network** — TCP+JSON mesh networking on port 9527, no central server, every node validates

**Core principle:** Your data, your keys, your revenue. No intermediaries.

---

## Architecture

Built across 9 development phases:

| Phase | Component | What it does |
|-------|-----------|-------------|
| 1 | **Ed25519 Cryptography** | Key generation, digital signatures, certificate signing |
| 2 | **SQLite Persistent Ledger** | Blockchain-structured storage with Merkle trees and chained hashes |
| 3 | **Blockchain Structure** | Block mining, hash chaining, Merkle root computation |
| 4 | **P2P Networking** | TCP+JSON peer discovery and message relay (port 9527) |
| 5 | **Block Synchronization** | 3-way validation, chain download, fork detection |
| 6 | **Consensus** | Longest-chain rule, chain reorganization, rate limiting |
| 7 | **Multi-Node Demo** | `oasyce demo-network` spins up N local nodes with consensus |
| 8 | **Staking Economy** | Proof-of-Stake, validator lifecycle, slashing, halving rewards |
| 9 | **Fingerprint Watermarking** | Steganographic embedding, extraction, leak tracing |

**Plus:** Web GUI dashboard, settlement engine (Bancor curves), privacy filter, IPFS-compatible storage, PoPC verification service, oasyce_core bridge layer, **data access control (L0-L3)**, **reputation engine**, **exposure registry**, **OAS-DAS standard**.

---

## Economics Overview

Oasyce has two complementary economic layers. For full formulas, game theory analysis, and worked examples, see [docs/ECONOMICS.md](docs/ECONOMICS.md).

### Data Access Fee Split (Unified Single Layer)

Every data purchase triggers a single fee split:

```
Payment: 100 OAS
  ├── Creator:     60 OAS (60%)
  ├── Validators:  20 OAS (20%) — split by stake weight
  ├── Burn:        15 OAS (15%) — permanent deflation
  └── Treasury:     5 OAS (5%)  — governance-controlled
```

The bonding curve is **completely decoupled** from fee settlement — reserve is never drained by distributions.

**Bancor formula:** `ΔTokens = S × ((1 + ΔR/R)^F − 1)` where S=supply, R=reserve, F=0.35 (connector weight)

### Data Access Control (L0–L3)

Raw data exposure is minimized by default. Buyers purchase **rights to use**, not rights to possess:

| Level | Access | Data Exposure | Bond Multiplier |
|-------|--------|---------------|-----------------|
| **L0** Query | Statistics, Q&A | Zero | 1× |
| **L1** Sample | Redacted fragments | Minimal | 2× |
| **L2** Compute | Model runs in TEE | Zero | 3× |
| **L3** Deliver | Full + watermark | Full | 5× |

Bond is dynamic: `Bond = TWAP(Value) × Multiplier × RiskFactor × (1 - Reputation/100) × ExposureFactor`

### Security Stack

| Layer | Mechanisms |
|-------|-----------|
| Technical | TEE enclaves, per-buyer watermarking |
| Access | L0-L3 levels, creator-controlled caps |
| Economic | Dynamic bond, bonding curve, 15% burn |
| Behavioral | Three-tier reputation (sandbox R<20 / limited 20–50 / full R≥50), blacklist, exposure tracking |
| Anti-Scraping | Fragmentation detection (access-time + registration-time), thread-safe concurrent access |
| Information | Leakage Budget (per-agent, per-asset, L0–L3 gain estimation) |
| Temporal | Liability windows (1–30 days by level) |

### Transaction Fee Distribution (Network Layer)

For each data access fee collected at the network level:

| Recipient | Share | Purpose |
|-----------|-------|---------|
| Creator | 60% | Data creator gets the lion's share |
| Validators | 20% | Split by stake weight |
| Burn | 15% | Permanent deflation |
| Treasury | 5% | Protocol development |

### Block Rewards & Staking

- **Block reward:** 4 OAS/block, halving every 1,051,200 blocks (~2 years)
- **Minimum stake:** 10,000 OAS
- **Unbonding period:** 7 days
- **Slashing:** 100% for malicious blocks, 50% for double blocks, 5%/day for offline

### Fingerprint Economics

Each buyer receives a uniquely watermarked copy. Leak detection: extract watermark → identify leaker → on-chain proof (fingerprint ↔ caller_id ↔ timestamp).

---

## Data Access Control

Oasyce enforces **four levels of data access**, each with increasing exposure and correspondingly higher bond requirements. Buyers purchase **rights to use**, not rights to possess.

### Access Levels

| Level | Method | Data Exposure | Bond Multiplier | Use Case |
|-------|--------|---------------|-----------------|----------|
| **L0** Query | Aggregated statistics | Zero | 1× | "How many records match X?" |
| **L1** Sample | Redacted + watermarked fragments | Minimal | 2× | Preview before full purchase |
| **L2** Compute | Code executes in TEE, only outputs leave | Zero | 3× | Train a model without seeing raw data |
| **L3** Deliver | Full data + per-buyer watermark | Full | 5× | Traditional data delivery |

### Bond Calculation

Every access request requires a bond that is held for the liability window:

```
Bond = TWAP(Value) × Multiplier(Level) × RiskFactor × (1 - R/100) × ExposureFactor
```

- **Multipliers:** L0=1.0, L1=2.0, L2=3.0, L3=5.0
- **Risk Factors:** public=1.0, low=1.2, medium=1.5, high=2.0, critical=3.0
- **R** = agent reputation score (higher reputation → lower bond)
- **ExposureFactor** = `1 + (cumulative_exposure / asset_value)` — prevents fragmentation attacks

### Reputation Engine

Agents build trust through behavior. Reputation determines bond discounts and access privileges:

```
R(t+1) = R(t) + α·S − β·D − γ·L − δ·T

α = +5   successful access completion
β = −10  data damage or incorrect result
γ = −50  watermark leak detected
δ = −5   time decay (every 90 days)
```

- **Initial score:** 10 (sandbox mode — L0 only)
- **Sandbox threshold:** R < 20 restricts agent to L0 access
- **Floor after decay:** 50 (decay alone cannot push below 50)

### Liability Windows

Bonds are time-locked and released only after the liability period:

| Level | Window | Rationale |
|-------|--------|-----------|
| L0 Query | 1 day | No data exposed |
| L1 Sample | 3 days | Minimal exposure |
| L2 Compute | 7 days | TEE output verification |
| L3 Deliver | 30 days | Full exposure, maximum risk |

### Exposure Registry

Cumulative exposure tracking prevents fragmentation attacks — many small L1 requests cannot circumvent the bond requirement of a single L3 delivery:

```
E*(agent, dataset) = max(V_current, Σ V_i)
```

---

## OAS-DAS Standard

The **Oasyce Data Asset Standard (OAS-DAS)** defines a machine-readable, five-layer schema for every data asset on the network. It enables semantic deduplication, automated policy enforcement, and cross-platform interoperability.

### Five-Layer Schema

| Layer | Name | Contents |
|-------|------|----------|
| **L1** | Identity | Global unique ID, creator, timestamps, version, namespace |
| **L2** | Metadata | Title, tags, file info, checksum, language, category |
| **L3** | Access Policy | Risk level, max access level (L0-L3), pricing model, license type, geographic restrictions, expiry |
| **L4** | Compute Interface | TEE execution parameters: supported operations, input/output schemas, runtime, resource limits |
| **L5** | Provenance | PoPC signature, certificate issuer, parent assets, fingerprint ID, semantic vector |

### Validation

Every asset is validated against the OAS-DAS schema before registration:

- **Risk levels:** `public`, `low`, `medium`, `high`, `critical`
- **Access levels:** `L0`, `L1`, `L2`, `L3`
- **Pricing models:** `bonding_curve`, `free`
- **License types:** `proprietary`, `cc-by`, `cc-by-sa`, `mit`, `public-domain`

### Semantic Deduplication

Layer 5 includes a semantic vector that enables automatic detection of near-duplicate assets. The `similarity()` method computes cosine similarity between asset vectors, and `is_duplicate()` flags assets above the configurable threshold.

```python
from oasyce_plugin.standards import OasDas

# Build a standard descriptor from existing asset metadata
descriptor = OasDas.from_asset_metadata(asset_metadata)

# Validate
errors = descriptor.validate()
assert errors == []

# Check for duplicates
score = descriptor.similarity(other_descriptor)
```

---

## Proof of Data Contribution

**PDC (Proof of Data Contribution)** proves that a data asset was genuinely created by the registrant, complementing PoPC which proves data *existence* at capture time.

### Three-Layer Fingerprint

| Layer | What It Proves |
|-------|---------------|
| **Content Hash** | Exact binary identity (SHA-256) |
| **Semantic Fingerprint** | Meaning-level identity — survives reformatting, compression, minor edits |
| **Source Proof** | Provenance chain — git commit, camera EXIF, API trace, etc. |

### Contribution Score

Each asset receives a **ContributionScore** that influences pricing and reputation rewards:

```
ContributionScore = originality × rarity × freshness
```

- **Originality:** Semantic distance from all existing assets (0–1)
- **Rarity:** Inverse of supply in the same category (0–1)
- **Freshness:** Time decay — newer data scores higher

### ContributionCertificate

A `ContributionCertificate` bundles the three-layer fingerprint with the contribution score and is signed by the creator's Ed25519 key. It is stored on-chain alongside the PoPC certificate.

**Relationship to PoPC:** PoPC verifies *data existence* at capture time (physical layer). PDC verifies *data origin authenticity* (semantic layer). Together they form a complete provenance proof.

---

## Dataset Pricing Curve

The **Dataset Pricing Curve** determines the base price of a data asset using four market factors:

```
Price = BasePrice × D(demand) × S(scarcity) × Q(quality) × F(freshness)
```

| Factor | Formula | Range | What It Captures |
|--------|---------|-------|-----------------|
| **Demand** | `1 + ln(1 + purchases)` | 1.0–∞ | More buyers → higher price |
| **Scarcity** | `1 / (1 + competitors)` | 0–1.0 | Fewer alternatives → higher price |
| **Quality** | `ContributionScore` | 0–1.0 | Better data → higher price |
| **Freshness** | `exp(-λ × age_days)` | 0–1.0 | Newer data → higher price |

**Relationship to Bonding Curve:** The Bonding Curve manages **OAS token liquidity** (how much OAS you get for your deposit). The Pricing Curve manages **data asset valuation** (how much a dataset is worth). They are independent — the Pricing Curve feeds into settlement, the Bonding Curve feeds into token economics.

---

## Quick Start

```bash
# Install from PyPI (recommended)
pip install oasyce

# Or install as an OpenClaw skill
clawhub install oasyce-data-rights
```

### From source

```bash
# Clone and install
git clone https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine.git
cd Oasyce_Claw_Plugin_Engine
python3 -m venv venv
source venv/bin/activate
pip install -e .

# Configure
cp .env.example .env
# Edit .env with your settings (OASYCE_VAULT_DIR, OASYCE_OWNER, OASYCE_SIGNING_KEY)

# Verify installation
oasyce --help
```

### Register your first asset

```bash
oasyce register /path/to/file.pdf --owner "Alice" --tags "Research,Genesis"
```

### Run the full demo (register → quote → buy → shares)

```bash
oasyce demo
```

### Launch the web dashboard

```bash
oasyce gui
# Opens at http://localhost:8420
```

### Spin up a local P2P network

```bash
oasyce demo-network --nodes 3
```

---

## CLI Reference

### Asset Management

```bash
# Register a file as an Oasyce asset
oasyce register <file_path> --owner "Name" --tags "Tag1,Tag2"

# Search assets by tag
oasyce search <tag> [--json]

# Get Bancor pricing quote
oasyce quote <asset_id> [--use-core]

# Buy access to an asset
oasyce buy <asset_id> --buyer "BuyerName" --amount 10.0

# Verify a PoPC certificate
oasyce verify <asset_id>
```

### Staking

```bash
# Stake OAS tokens for a validator
oasyce stake <validator_id> <amount>

# View share holdings
oasyce shares <owner>
```

### P2P Node

```bash
# Start a P2P node
oasyce node start [--port 9527]

# Show node info
oasyce node info

# Ping a peer
oasyce node ping <host:port>
```

### Fingerprint Watermarking

```bash
# Embed a watermark
oasyce fingerprint embed <file_path> --caller "buyer_id" [--output watermarked.png]

# Extract watermark from a file
oasyce fingerprint extract <file_path>

# Trace a fingerprint to its distribution record
oasyce fingerprint trace <fingerprint_hash>

# List all distributions for an asset
oasyce fingerprint list <asset_id>
```

### Data Access Control

```bash
# Query aggregated statistics (L0 — zero exposure)
oasyce access query <asset_id> --agent <agent_id> [--query "count matching X"]

# Request redacted sample (L1 — minimal exposure)
oasyce access sample <asset_id> --agent <agent_id> [--size 10]

# Execute code in TEE (L2 — zero exposure)
oasyce access compute <asset_id> --agent <agent_id> --code "model.fit(data)"

# Full delivery with watermark (L3 — full exposure)
oasyce access deliver <asset_id> --agent <agent_id>

# Calculate bond requirement for a given access level
oasyce access bond <asset_id> --agent <agent_id> --level L0|L1|L2|L3
```

### Reputation

```bash
# Check an agent's reputation score
oasyce reputation check <agent_id>

# Update reputation (admin/testing)
oasyce reputation update <agent_id> [--success] [--leak] [--damage]
```

### Contribution (PDC)

```bash
# Generate a contribution certificate for an asset
oasyce contribution certify <asset_id>

# View contribution score breakdown
oasyce contribution score <asset_id> [--json]
```

### Leakage Budget

```bash
# Check remaining leakage budget for an agent on an asset
oasyce leakage budget <agent_id> <asset_id>

# View leakage gain estimation by access level
oasyce leakage estimate <agent_id> <asset_id> --level L0|L1|L2|L3
```

### Pricing

```bash
# Get dynamic price for a dataset (four-factor pricing)
oasyce price <asset_id> [--json]

# View pricing factor breakdown (demand, scarcity, quality, freshness)
oasyce price factors <asset_id> [--json]
```

### Asset Standard (OAS-DAS)

```bash
# View full 5-layer OAS-DAS descriptor for an asset
oasyce asset-info <asset_id> [--json]

# Validate an asset against the OAS-DAS schema
oasyce asset-validate <asset_id> [--json]
```

### Utilities

```bash
# Launch web GUI dashboard
oasyce gui [--port 8420]

# Run multi-node demo with consensus
oasyce demo-network [--nodes 3]

# Run end-to-end protocol demo
oasyce demo

# JSON output for any command
oasyce <command> --json
```

---

## Python SDK

```python
from oasyce_plugin.config import Config
from oasyce_plugin.skills.agent_skills import OasyceSkills

# Initialize
config = Config.from_env()
skills = OasyceSkills(config)

# Register a file
file_info = skills.scan_data_skill("/path/to/file.pdf")
metadata = skills.generate_metadata_skill(file_info, ["Core"], "Alice")
signed = skills.create_certificate_skill(metadata)
result = skills.register_data_asset_skill(signed)

print(f"Asset ID: {signed['asset_id']}")

# Get pricing quote
quote = skills.trade_data_skill(signed['asset_id'])
print(f"Price: {quote['current_price_oas']} OAS")
```

### Settlement Engine (direct)

```python
from oasyce_plugin.services.settlement.engine import SettlementEngine

engine = SettlementEngine()
pool = engine.register_asset("ASSET_001", owner="Alice")
receipt = engine.execute("ASSET_001", buyer="Bob", payment_oas=100.0)

print(f"Tokens received: {receipt.quote.equity_minted}")
print(f"Burned: {receipt.quote.burn_amount} OAS")
print(f"New spot price: {receipt.quote.spot_price_after} OAS")
```

### Staking Engine (direct)

```python
from oasyce_plugin.services.staking import StakingEngine

staking = StakingEngine()
staking.stake("validator_1", 5000.0)
reward = staking.produce_block("validator_1", block_height=1)
fees = staking.distribute_fees(100.0, creator="Alice")
```

---

## Project Structure

```
Oasyce_Claw_Plugin_Engine/
├── oasyce_plugin/                  # Core package
│   ├── cli.py                      # CLI entry point (argparse)
│   ├── config.py                   # Configuration management
│   ├── models.py                   # Data models
│   ├── bridge/
│   │   └── core_bridge.py          # Bridge to oasyce_core protocol
│   ├── crypto/
│   │   ├── keys.py                 # Ed25519 key generation & signing
│   │   └── merkle.py               # Merkle tree implementation
│   ├── engines/
│   │   ├── core_engines.py         # Local verification engines
│   │   ├── schema.py               # Data validation schemas
│   │   ├── result.py               # Unified result types
│   │   └── l3_tee/                 # TEE / ZK-PoE engine
│   ├── fingerprint/
│   │   ├── engine.py               # Steganographic watermarking
│   │   └── registry.py             # Distribution tracking
│   ├── gui/
│   │   └── app.py                  # Web dashboard
│   ├── network/
│   │   └── node.py                 # P2P TCP+JSON node
│   ├── security/
│   │   └── keymanager.py           # Key management
│   ├── services/
│   │   ├── access/
│   │   │   ├── __init__.py         # AccessLevel enum, helpers
│   │   │   ├── config.py           # Access control configuration
│   │   │   └── provider.py         # L0-L3 access methods + bond calc
│   │   ├── reputation/
│   │   │   └── __init__.py         # Agent reputation scoring engine
│   │   ├── exposure/
│   │   │   ├── registry.py         # Cumulative exposure tracking
│   │   │   └── window.py           # Liability window + bond release
│   │   ├── settlement/
│   │   │   └── engine.py           # Bancor bonding curve settlement
│   │   ├── staking/
│   │   │   └── __init__.py         # PoS staking, slashing, rewards
│   │   └── verification/
│   │       ├── api.py              # Verification API
│   │       └── engine.py           # PoPC verification engine
│   ├── skills/
│   │   └── agent_skills.py         # AI agent integration (OpenClaw)
│   ├── standards/
│   │   ├── __init__.py             # OAS-DAS exports
│   │   └── oas_das.py              # 5-layer data asset standard schema
│   ├── storage/
│   │   ├── __init__.py             # Storage backends
│   │   ├── ledger.py               # SQLite blockchain ledger
│   │   └── ipfs_client.py          # IPFS integration
│   └── scripts/
│       └── demo_network.py         # Multi-node demo orchestrator
├── tests/                          # 445 tests across 22 test files
├── examples/                       # Usage examples
├── scripts/                        # Setup & utility scripts
├── docs/                           # Documentation
│   └── ECONOMICS.md                # Detailed economic model
├── setup.py                        # Package config (v1.1.0)
└── README.md                       # This file
```

---

## Testing

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage
python3 -m pytest tests/ -v --cov=oasyce_plugin --cov-report=term-missing

# Run a specific test file
python3 -m pytest tests/test_settlement_engine.py -v
```

**Test suite:** 445 tests across 22 test files covering:

| Test File | Coverage Area |
|-----------|-------------|
| `test_blockchain.py` | Block mining, hash chains, Merkle trees |
| `test_consensus.py` | Longest chain, reorg, rate limiting |
| `test_core_bridge.py` | oasyce_core protocol integration |
| `test_core_flow.py` | End-to-end registration flow |
| `test_crypto.py` | Ed25519 signatures, key management |
| `test_engines.py` | Local verification engines |
| `test_fingerprint.py` | Watermark embed/extract/trace |
| `test_integration.py` | Cross-module integration |
| `test_l3_tee_engine.py` | TEE/ZK proof engine |
| `test_network.py` | P2P networking, peer discovery |
| `test_privacy_and_storage.py` | Privacy filter, storage backends |
| `test_settlement_engine.py` | Bancor curves, fee splits |
| `test_staking.py` | Staking, slashing, rewards |
| `test_sync.py` | Block synchronization |
| `test_verification_service.py` | PoPC verification service |
| `test_access_control.py` | L0-L3 access, bond calc, reputation |
| `test_exposure_registry.py` | Cumulative exposure, fragmentation |
| `test_liability_window.py` | Bond lock/release, time windows |
| `test_oas_das.py` | 5-layer schema validation, dedup |
| `test_reputation_tiers.py` | Three-tier reputation, fragmentation detection |
| `test_pdc.py` | Proof of Data Contribution, leakage budget |
| `test_pricing_curve.py` | Dataset pricing curve, four-factor pricing |

---

## Configuration

### .env file (recommended)

```env
OASYCE_VAULT_DIR=~/oasyce/genesis_vault
OASYCE_OWNER=YourName
OASYCE_SIGNING_KEY=your-secret-key-here
OASYCE_SIGNING_KEY_ID=my_key_001
```

### Environment variables

```bash
export OASYCE_VAULT_DIR=~/oasyce/genesis_vault
export OASYCE_OWNER=YourName
export OASYCE_SIGNING_KEY=your-secret-key
export OASYCE_SIGNING_KEY_ID=my_key_001
```

**Security:** Use a strong random key (32+ characters) in production. Development can use `DEFAULT_INSECURE_DEV_KEY_0x123`.

---

## Stats

| Metric | Value |
|--------|-------|
| Tests | 445 passing |
| Source files | ~50 |
| Development phases | 9 |
| Core dependencies | Zero (stdlib only for protocol) |

---

## License

Proprietary - All rights reserved.

---

<div align="center">

*Your AI works for you every day. Oasyce makes sure it gets paid.*

[GitHub](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine) · [Protocol Overview](docs/OASYCE_PROTOCOL_OVERVIEW.md) · [Economics](docs/ECONOMICS.md) · [Contributing](CONTRIBUTING.md)

</div>

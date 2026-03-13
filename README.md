# Oasyce Claw Plugin Engine

<div align="center">

**Decentralized data ownership and settlement protocol engine.**
**Local-first, zero-server, every node is the network.**

[![Version](https://img.shields.io/badge/version-0.9.0-blue.svg)](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-220%20passed-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/license-Proprietary-green.svg)](LICENSE)

[Quick Start](#quick-start) · [CLI Reference](#cli-reference) · [Architecture](#architecture) · [Economics](docs/ECONOMICS.md) · [Testing](#testing)

</div>

---

## Why Oasyce? Why Now?

For twenty years, "data is the new oil" remained a slogan. Humans couldn't coordinate data trade at scale — the cost of contracts, lawyers, reconciliation, and enforcement exceeded the value of the data itself.

Then AI agents arrived. For the first time in history, the primary consumers of data are machines, not people. Machines can verify signatures in milliseconds, settle atomically, price algorithmically, and trace leaks cryptographically. Everything that made human-to-human data commerce impractical is exactly what machine-to-machine commerce does natively.

**Oasyce is the settlement network for this new economy.** A protocol where AI agents autonomously own, price, trade, and protect data — and humans simply run nodes and collect revenue.

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

**Plus:** Web GUI dashboard, settlement engine (Bancor curves), privacy filter, IPFS-compatible storage, PoPC verification service, oasyce_core bridge layer.

---

## Economics Overview

Oasyce has two complementary economic layers. For full formulas, game theory analysis, and worked examples, see [docs/ECONOMICS.md](docs/ECONOMICS.md).

### Data Access Fee Split (Settlement Layer)

Each data purchase flows through the Bancor bonding curve:

```
Payment: 100 OAS
  ├── Protocol Fee: 5% → 5 OAS
  │     ├── Burn: 50% → 2.5 OAS (permanent deflation)
  │     └── Verifier: 50% → 2.5 OAS
  └── Net Deposit: 95% → 95 OAS → enters bonding curve → pushes price up
```

**Bancor formula:** `ΔTokens = S × ((1 + ΔR/R)^F − 1)` where S=supply, R=reserve, F=0.20 (connector weight)

### Transaction Fee Distribution (Network Layer)

For each data access fee collected at the network level:

| Recipient | Share | Purpose |
|-----------|-------|---------|
| Creator | 70% | Data creator gets the lion's share |
| Validators | 20% | Split by stake weight |
| Burn | 10% | Permanent deflation |

### Block Rewards & Staking

- **Block reward:** 50 OAS/block, halving every 525,600 blocks (~1 year)
- **Minimum stake:** 1,000 OAS
- **Unbonding period:** 7 days
- **Slashing:** 100% for malicious blocks, 50% for double blocks, 5%/day for offline

### Fingerprint Economics

Each buyer receives a uniquely watermarked copy. Leak detection: extract watermark → identify leaker → on-chain proof (fingerprint ↔ caller_id ↔ timestamp).

---

## Quick Start

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
│   │   ├── settlement/
│   │   │   └── engine.py           # Bancor bonding curve settlement
│   │   ├── staking/
│   │   │   └── __init__.py         # PoS staking, slashing, rewards
│   │   └── verification/
│   │       ├── api.py              # Verification API
│   │       └── engine.py           # PoPC verification engine
│   ├── skills/
│   │   └── agent_skills.py         # AI agent integration (OpenClaw)
│   ├── storage/
│   │   ├── __init__.py             # Storage backends
│   │   ├── ledger.py               # SQLite blockchain ledger
│   │   └── ipfs_client.py          # IPFS integration
│   └── scripts/
│       └── demo_network.py         # Multi-node demo orchestrator
├── tests/                          # 220 tests across 15 test files
├── examples/                       # Usage examples
├── scripts/                        # Setup & utility scripts
├── docs/                           # Documentation
│   └── ECONOMICS.md                # Detailed economic model
├── setup.py                        # Package config (v0.9.0)
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

**Test suite:** 220 tests across 15 test files covering:

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
| Tests | 220 passing |
| Source files | ~50 |
| Development phases | 9 |
| Core dependencies | Zero (stdlib only for protocol) |

---

## License

Proprietary - All rights reserved.

---

<div align="center">

**Your data, your keys, your revenue.**

[GitHub](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine) · [Economics](docs/ECONOMICS.md) · [Issues](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/issues)

</div>

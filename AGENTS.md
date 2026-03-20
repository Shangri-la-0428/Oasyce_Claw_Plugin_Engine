# Oasyce — AI Agent Integration Guide

> This file is the source of truth for AI tool integration. It is read automatically by Claude Code (CLAUDE.md), Cursor (.cursorrules), Windsurf (.windsurfrules), and any AI tool that supports project-level instructions.

You have access to the `oasyce` CLI — a unified client for the Oasyce decentralized AI data marketplace. One install gives you everything: data asset management, AI capability trading, local data scanning, and chain interaction.

## Install

```bash
pip install oasyce        # includes DataVault (odv) automatically
oasyce doctor             # verify installation
```

## What Is Oasyce?

A decentralized infrastructure where AI agents pay for data access and capability invocations. Data has sovereignty, capabilities have a price. Think **Stripe for the AI economy**.

Three components, one install:

| Component | What It Does | Command |
|-----------|-------------|---------|
| **oasyce** (this package) | Python client + Dashboard | `oasyce` |
| **odv** (DataVault) | Local data scanning, classification, PII detection | `datavault` |
| **oasyce-chain** | L1 Cosmos SDK appchain (Go) | `oasyced` |

---

## Quick Start Pipeline

The standard workflow for a new user:

```bash
# 1. Scan local data for registerable assets
datavault scan ~/Documents
datavault privacy              # check for PII
datavault report               # review results

# 2. Register safe assets to the network
oasyce register data.csv --owner alice --tags research,nlp

# 3. Check pricing and trade
oasyce quote ASSET_ID          # bonding curve spot price
oasyce buy ASSET_ID --buyer bob --amount 10.0
oasyce sell ASSET_ID --tokens 5 --seller bob

# 4. Start Dashboard
oasyce serve                   # http://localhost:8420
```

---

## Data Assets

```bash
oasyce register <file> --owner <name> --tags <tag1,tag2>
  --rights-type original|co_creation|licensed|collection
  --co-creators '[{"address":"A","share":60},...]'
  --price-model auto|fixed|floor --price <OAS>
  --free                                           # attribution only

oasyce search <keyword>
oasyce quote <asset_id>
oasyce buy <asset_id> --buyer <name> --amount <OAS>
oasyce sell <asset_id> --tokens <n> --seller <name>
oasyce shares <owner_id>
oasyce asset-info <asset_id>
```

## AI Capability Marketplace

```bash
oasyce capability register --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx --price 0.5 --tags nlp,translation

oasyce capability list [--tag nlp] [--provider addr]
oasyce capability invoke CAP_ID --input '{"text":"hello"}'
oasyce capability earnings --provider addr
oasyce discover --intents "translate" --tags nlp
```

## Dispute & Resolution

```bash
oasyce dispute <asset_id> --reason "..."
oasyce resolve <asset_id> --remedy delist|transfer|rights_correction|share_adjustment
```

## Agent Scheduler (Autonomous Mode)

```bash
oasyce agent start                          # enable scheduler
oasyce agent stop                           # disable
oasyce agent status                         # show status + stats
oasyce agent run                            # trigger one cycle
oasyce agent config --interval 12           # run every 12h
oasyce agent config --scan-paths ~/data     # directories to scan
oasyce agent config --auto-trade            # enable auto-buying
oasyce agent config --trade-max-spend 20.0  # max OAS per cycle
```

## Reputation & Access

```bash
oasyce reputation show <address>
oasyce reputation feedback <target> --score 5
oasyce access buy <asset_id> --level L0|L1|L2|L3 --agent <name>
```

## Local Data Scanning (DataVault)

```bash
datavault scan <path>            # scan directory, SHA-256 hashes
datavault classify               # auto-detect file types
datavault privacy                # regex PII detection
datavault report [--format json] # generate report
datavault register --confirm     # register safe assets to Oasyce
datavault inventory              # list tracked assets
datavault status                 # inventory stats
```

### Risk Levels

| Level | Meaning | Action |
|-------|---------|--------|
| safe | No PII | Can register |
| low | IP addresses only | Can register |
| medium | Email addresses | Needs confirmation |
| high | Phone, ID numbers | **Blocked** |
| critical | Credit cards, API keys | **Blocked** |

Pipeline order: **scan → privacy → report → register** (always this order).

## Consensus & Governance

```bash
oasyce consensus status
oasyce consensus register --stake 10000
oasyce consensus delegate <validator_id> --amount 500
oasyce governance propose --title "..." --description "..." --deposit 1000
oasyce governance vote <proposal_id> --option yes|no|abstain
```

## Node & Network

```bash
oasyce serve                    # Dashboard at http://localhost:8420
oasyce node info                # Ed25519 identity
oasyce node peers               # connected peers
oasyce testnet onboard          # one-click testnet setup
oasyce testnet faucet           # free test OAS
```

## Fingerprint & Watermark

```bash
oasyce fingerprint embed <file> --caller <id>
oasyce fingerprint extract <file>
oasyce fingerprint trace <fingerprint_hex>
```

## Diagnostics

```bash
oasyce doctor                   # health check
oasyce demo                     # full pipeline demo
oasyce info                     # project info and links
oasyce info --section economics # token economics
```

## All commands support `--json` for structured output.

---

## Key Concepts

- **OAS**: Protocol token (uoas = 10^-6 OAS). All transactions settle in OAS.
- **Bonding Curve**: `tokens = supply * (sqrt(1 + payment/reserve) - 1)`. More buyers = higher price.
- **Sell**: Inverse curve: `payout = reserve * (1 - (1 - tokens/supply)^2)`, 95% reserve cap.
- **2% Burn**: Every settlement burns 2% (93% provider, 5% protocol, 2% burn). Deflationary.
- **Access Levels**: Hold equity to unlock: >=0.1% L0, >=1% L1, >=5% L2, >=10% L3.
- **Jury Voting**: 5 jurors, `sha256(disputeID+nodeID) * log(1+reputation)`, 2/3 majority.
- **Escrow**: Lock funds before execution, release after verification. Auto-expiry refund.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   User / AI Agent                    │
├──────────┬──────────────────┬────────────────────────┤
│ DataVault│   Plugin Engine  │        CLI / GUI       │
│ (scan/   │  (Facade API)   │     (oasyced tx/query) │
│  classify│                  │                        │
│  privacy)│                  │                        │
├──────────┴──────────────────┴────────────────────────┤
│                  Oasyce L1 Chain                     │
│  ┌──────────┬──────────┬──────────┬───────────────┐  │
│  │settlement│capability│reputation│  datarights   │  │
│  ├──────────┴──────────┴──────────┴───────────────┤  │
│  │                   x/work                       │  │
│  │        (PoUW: AI compute + redundant verify)   │  │
│  ├────────────────────────────────────────────────┤  │
│  │              IBC (ibc-go v8.8.0)               │  │
│  └────────────────────────────────────────────────┘  │
│              Cosmos SDK v0.50.10                     │
└─────────────────────────────────────────────────────┘
```

## Facade API (Programmatic)

```python
from oasyce.services.facade import OasyceServiceFacade

facade = OasyceServiceFacade()
result = facade.quote("ASSET_ID", amount_oas=10.0)
result = facade.buy("ASSET_ID", buyer="alice", amount_oas=10.0)
result = facade.sell("ASSET_ID", seller="alice", tokens_to_sell=5.0)
result = facade.register(file_path, owner, tags)
result = facade.dispute("ASSET_ID", consumer_id="bob", reason="...")
result = facade.jury_vote("DIS_001", juror_id="charlie", verdict="consumer")
```

All methods return `ServiceResult(success: bool, data: dict, error: str | None)`.

## Links

- [oasyce-chain](https://github.com/Shangri-la-0428/oasyce-chain) — L1 appchain (Go)
- [Plugin Engine](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine) — Python client
- [DataVault](https://github.com/Shangri-la-0428/DataVault) — Data scanning skill
- Discord: https://discord.gg/tfrCn54yZW

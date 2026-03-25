# Oasyce — AI Agent Integration Guide

> This file is the source of truth for AI tool integration. It is read automatically by Claude Code (CLAUDE.md), Cursor (.cursorrules), Windsurf (.windsurfrules), and any AI tool that supports project-level instructions.

You have access to the `oas` CLI — a unified client for the Oasyce agent economy system. One install gives you everything: data asset management, AI capability trading, local data scanning, and chain interaction.

## Install

```bash
pip install oasyce        # includes DataVault (odv) automatically
oas doctor             # verify installation
```

## What Is Oasyce?

An on-chain economic system for autonomous agent commerce — **property rights** (data as financial assets with bonding curve pricing), **service contracts** (capabilities as on-chain agreements with escrow + challenge window), **transaction clearing** (90/5/2/3 fee split), and **dispute resolution** (on-chain jury voting).

Stripe / x402 solve "how to pay." Oasyce solves "why the payment is justified" — property, contracts, and arbitration for the agent economy.

Three components, one install:

| Component | What It Does | Command |
|-----------|-------------|---------|
| **oasyce** (this package) | Python client + Dashboard | `oas` |
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
oas register data.csv --owner alice --tags research,nlp

# 3. Check pricing and trade
oas quote ASSET_ID          # bonding curve spot price
oas buy ASSET_ID --buyer bob --amount 10.0
oas sell ASSET_ID --tokens 5 --seller bob

# 4. Start Dashboard
oas start                   # http://localhost:8420
```

## Running Modes

| Mode | Env Var | Backend | Use Case |
|------|---------|---------|----------|
| **Standalone** (default) | — | Local SQLite | Development, testing, single-node |
| **Chain-linked** | `OASYCE_STRICT_CHAIN=1` | oasyce-chain L1 | Production, multi-node network |

In standalone mode, all features work locally without a running chain. Chain-linked mode requires `oasyced start` and routes all state through the L1 appchain.

---

## Data Assets

```bash
oas register <file> --owner <name> --tags <tag1,tag2>
  --rights-type original|co_creation|licensed|collection
  --co-creators '[{"address":"A","share":60},...]'
  --price-model auto|fixed|floor --price <OAS>
  --free                                           # attribution only

oas search <keyword>
oas quote <asset_id>
oas buy <asset_id> --buyer <name> --amount <OAS>
oas sell <asset_id> --tokens <n> --seller <name>
oas shares <owner_id>
oas asset-info <asset_id>
```

## AI Capability Marketplace

```bash
oas capability register --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx --price 0.5 --tags nlp,translation

oas capability list [--tag nlp] [--provider addr]
oas capability invoke CAP_ID --input '{"text":"hello"}'
oas capability earnings --provider addr
oas discover --intents "translate" --tags nlp
```

## Dispute & Resolution

```bash
oas dispute <asset_id> --reason "..."
oas resolve <asset_id> --remedy delist|transfer|rights_correction|share_adjustment
```

## Task Bounties (AHRP)

```bash
oas task post "description" --budget 50 --deadline 3600
oas task list
oas task bid TASK_ID --price 30 --seconds 1800
oas task select TASK_ID --agent AGENT_ID
oas task complete TASK_ID
oas task cancel TASK_ID
```

## Feedback (AI Agent Reports)

```bash
oas feedback "message" --type bug|suggestion|other --agent <agent-id> --json
```

Feedback is stored locally (SQLite) and optionally forwarded to:
- **Discord/Slack webhook** via `OASYCE_FEEDBACK_WEBHOOK` env var
- **GitHub Issues** via `OASYCE_GITHUB_TOKEN` + `OASYCE_GITHUB_REPO` env vars

## Agent Scheduler (Autonomous Mode)

```bash
oas agent start                          # enable scheduler
oas agent stop                           # disable
oas agent status                         # show status + stats
oas agent run                            # trigger one cycle
oas agent config --interval 12           # run every 12h
oas agent config --scan-paths ~/data     # directories to scan
oas agent config --auto-trade            # enable auto-buying
oas agent config --trade-max-spend 20.0  # max OAS per cycle
```

## Reputation & Access

```bash
oas reputation check <address>
oas reputation update <target> --score 5
oas access buy <asset_id> --level L0|L1|L2|L3 --agent <name>
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

## Consensus & Governance (Chain-Only)

These commands are implemented on the **L1 chain** (`oasyced`), not the Python CLI:

```bash
# Requires oasyce-chain running (oasyced start)
oasyced tx staking create-validator ...
oasyced tx staking delegate <validator> <amount>uoas
oasyced tx gov submit-proposal ...
oasyced tx gov vote <proposal_id> yes|no|abstain
```

See [oasyce-chain CLAUDE.md](https://github.com/Shangri-la-0428/oasyce-chain) for full chain CLI reference.

## Node & Network

```bash
oas start                    # Dashboard at http://localhost:8420
oas node info                # Ed25519 identity
oas node peers               # connected peers
oas testnet onboard          # PoW self-registration (sha256 puzzle)
oas testnet faucet           # testnet-only supplemental OAS (requires registration)
```

## Fingerprint & Watermark

```bash
oas fingerprint embed <file> --caller <id>
oas fingerprint extract <file>
oas fingerprint trace <fingerprint_hex>
```

## Diagnostics

```bash
oas doctor                   # health check
oas demo                     # full pipeline demo
oas info                     # project info and links
oas info --section economics # token economics
```

## All commands support `--json` for structured output.

---

## Key Concepts

- **OAS**: Protocol token (uoas = 10^-6 OAS). All transactions settle in OAS.
- **Bonding Curve**: `tokens = supply * ((1 + payment/reserve)^0.50 - 1)`. CW=0.50 (sqrt curve), more buyers = higher price.
- **Sell**: Inverse curve: `payout = reserve * (1 - (1 - tokens/supply)^(1/0.50))`, 95% reserve cap.
- **Fee Split**: 93% creator/reserve, 3% validator, 2% burn, 2% treasury. Round-trip cost ~12%.
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
- [Plugin Engine](https://github.com/Shangri-la-0428/oasyce-net) — Python client
- [DataVault](https://github.com/Shangri-la-0428/DataVault) — Data scanning skill
- Discord: https://discord.gg/tfrCn54yZW

---

## Design Context

### Users
- **Primary:** Data providers/creators monetizing data assets — focused on earnings, security, rights
- **Secondary:** AI developers/researchers buying data and capabilities — focused on efficiency, precision
- **Context:** Professional users managing valuable digital assets. Expect financial-grade reliability.

### Brand Personality
**Precise. Restrained. Cutting-edge.** (精密 · 克制 · 前沿)
Feeling: 未来感 + 克制 — cutting-edge technology that doesn't shout. Calm futurism.

### Design Principles
1. **Earn every pixel** — No decoration. Every element serves a purpose.
2. **Monospace signals trust** — IDs, hashes, prices, addresses all use monospace (Geist Mono).
3. **Semantic color only** — Green/red/yellow/blue for status only. Everything else is grayscale.
4. **Data density** — Show useful information, maintain clear hierarchy.
5. **Whitespace is structural** — Generous breathing room between sections; tight grouping within related elements.

### Typography
- Dramatic scale contrast between hierarchy levels. Weight pairing with clear distinction (700/400, not 500/400).
- Rhythmic case and weight mixing within sections to create hierarchy before reaching for color or size.

### Motion
- Entrance choreography: staggered reveals (50–100ms offsets), fade + subtle translateY.
- Easing: `cubic-bezier(0.25, 1, 0.5, 1)` (ease-out-quart). Duration 0.12–0.3s micro, up to 0.5s page transitions.
- No bounce, no spring, no elastic. Always respect `prefers-reduced-motion`.

### References
Linear, Vercel, Stripe/Notion, Terminal/CLI, **Modus (fantik.studio)** for typographic rhythm and spatial composition.

### Anti-References
Colorful crypto dashboards, gradient Web3 UIs, gamified interfaces, gratuitous animation.

Full design tokens and component specs in `dashboard/.impeccable.md`.

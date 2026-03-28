---
name: oasyce
version: 2.3.3
description: >
  Oasyce Protocol — decentralized AI data marketplace. Register data assets,
  list AI capabilities, submit compute tasks (Proof of Useful Work), trade shares
  on bonding curves, and operate your node. One install: pip install oasyce.
  Use when user mentions Oasyce, data rights, data registration, bonding curve,
  AI capabilities, compute tasks, PoUW, capability marketplace, OAS tokens, staking,
  data scanning, or wants to monetize/protect their data.
read_when:
  - User mentions Oasyce, OAS, data rights, or data registration
  - User wants to register, protect, price, or monetize data
  - User asks about bonding curves, shares, manual pricing, or staking
  - User wants to invoke, list, or register AI capabilities/services
  - User asks about agent scheduler, autonomous trading, or periodic tasks
  - User asks about compute tasks, proof of useful work, PoUW, or AI execution
  - User asks about oracle feeds, real-time data, or price feeds
  - User asks about agent identity, trust tiers, or reputation
  - User mentions "确权", "上链", "数据资产", "能力市场", or agent services
  - User wants to run a protocol demo or start a node
  - User wants to scan, inventory, or classify local data assets
metadata: {"emoji":"⚡","requires":{"bins":["python3","oasyce"]}}
---

# Oasyce Protocol Skill

Decentralized AI data marketplace — data rights + AI capabilities + compute tasks + autonomous agent + P2P node.

## Prerequisites

```bash
pip install oasyce              # everything included (DataVault bundled)
oas bootstrap                   # self-update + wallet + DataVault readiness
oas doctor                      # optional diagnostics
```

---

## Install

```bash
pip install oasyce         # includes DataVault (odv)
oas bootstrap              # self-update + wallet + DataVault readiness
oas doctor                 # optional diagnostics
```

## Canonical Onboarding

Keep onboarding truth narrow, with owner account + trusted device:

- Product-facing public beta: [docs/public-testnet-guide.md](/Users/wutongcheng/Desktop/Net/oasyce-net/docs/public-testnet-guide.md)
- Chain-side onboarding and infra context: [chain.oasyce](https://chain.oasyce.com)
- This surface: concise AI command reference only, not a second parallel onboarding guide

Public beta release gate:

```bash
export OASYCE_NETWORK_MODE=testnet
export OASYCE_STRICT_CHAIN=1
oas account status --json
oas doctor --public-beta --json
oas smoke public-beta --json
```

Local simulation remains separate:

```bash
oas --json sandbox status
oas --json sandbox onboard
oas sandbox reset --force
```

## Data Assets

```bash
oas register <file> --owner <name> --tags <tag1,tag2>
  --rights-type original|co_creation|licensed|collection
  --co-creators '[{"address":"A","share":60},...]'
  --price-model auto|fixed|floor --price <OAS>
  --service-url <url>                              # data access endpoint
  --free                                           # attribution only

oas update-service-url <asset_id> <url> --owner <name>  # update data endpoint

oas search <keyword>
oas quote <asset_id> [--amount 10.0]
oas buy <asset_id> [--buyer <name>] --amount <OAS>
oas sell <asset_id> --tokens <n> [--seller <name>] [--max-slippage 0.05]
oas shares <owner_id>
oas asset-info <asset_id>
oas asset-validate <asset_id>                      # validate against OAS-DAS standard
oas stake <validator_id> <amount>                   # stake OAS for a validator
oas verify <asset_id_or_json_path> [--signing-key KEY]  # verify PoPC certificate
oas scan [<path>]                                  # scan directory for candidate assets (default: .)
```

## AI Capability Marketplace

```bash
oas capability register --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx --price 0.5 --tags nlp,translation \
  [--provider self] [--description "..."] [--rate-limit 60]

oas capability list [--tag nlp] [--provider addr] [--limit 50]
oas capability invoke CAP_ID [--input '{"text":"hello"}'] [--consumer self]
oas capability earnings [--provider addr] [--consumer addr]
oas discover --intents "translate" --tags nlp [--limit 10]
```

## Dispute & Resolution

```bash
oas dispute <asset_id> --reason "..." [--invocation-id ID] [--consumer ID]
oas jury-vote <dispute_id> --verdict uphold|reject --juror <name>
oas resolve <asset_id> --remedy delist|transfer|rights_correction|share_adjustment [--dispute-id ID] [--details '{"new_owner":"0x..."}']
oas delist <asset_id> --owner <name>                # owner voluntary delist
```

## Task Bounties (AHRP)

```bash
oas task post --requester ID --description "..." --budget 50 --deadline 3600 \
  [--capabilities cap1,cap2] [--strategy weighted_score|lowest_price|best_reputation|requester_choice] \
  [--min-reputation 0.5]
oas task list [--capability cap1,cap2]
oas task info TASK_ID
oas task bid TASK_ID --agent ID --price 30 [--seconds 1800] [--reputation 0.8]
oas task select TASK_ID [--agent AGENT_ID]
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
oas reputation check <agent_id>
oas reputation update <agent_id> --success|--leak|--damage

oas access quote <asset_id> --agent <name>         # bond quotes for all levels
oas access buy <asset_id> --level L0|L1|L2|L3 [--agent <name>]
oas access query <asset_id> --agent <name> [--query "..."]    # L0: aggregated stats
oas access sample <asset_id> --agent <name> [--size 10]       # L1: redacted fragments
oas access compute <asset_id> --agent <name> --code "..."     # L2: TEE execution
oas access deliver <asset_id> --agent <name>                  # L3: full data
oas access bond <asset_id> --agent <name> --level L0|L1|L2|L3 # calculate bond requirement
```

## Local Data Scanning (DataVault)

```bash
datavault scan <path>            # scan directory, SHA-256 hashes
datavault classify               # auto-detect file types
datavault privacy                # regex PII detection
datavault report <path> [--format json] # generate report
datavault register <path> --confirm --json  # register only safe assets to Oasyce
datavault inventory              # list tracked assets
datavault status                 # inventory stats
```

### Risk Levels

| Level | Meaning | Action |
|-------|---------|--------|
| safe | No PII | Can auto-register |
| low | IP addresses only | Review first |
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
oas start [--port 8420] [--no-browser]              # Dashboard at http://localhost:8420
oas serve [--port 8000] [--host 0.0.0.0]            # Start API server
oas status                                           # network connectivity status
oas explorer [--port 8421]                           # launch block explorer

oas node start [--port 9527]                         # start P2P node
oas node info                                        # Ed25519 identity
oas node peers                                       # connected peers
oas node ping <host:port>                            # ping another node
oas node role                                        # show current node role
oas node reset-identity                              # force-reset node identity
oas node become-validator [--amount OAS] [--api-key KEY] \
  [--api-provider claude|openai|ollama|local|custom] [--api-endpoint URL]
oas node become-arbitrator [--tags expertise1,expertise2] \
  [--description "..."] [--api-key KEY] [--api-provider claude|openai|ollama|local|custom]
oas node api-key <KEY> [--provider claude] [--endpoint URL]

oas sandbox start [--port 9528]                      # start local sandbox simulation node
oas --json sandbox onboard                           # local simulation: faucet + sample asset + stake
oas sandbox faucet                                   # local simulated OAS
oas --json sandbox status                            # show local simulation status
oas sandbox reset [--force]                          # reset all local simulation data
oas sandbox faucet-serve [--port 8421] [--data-dir DIR]  # start local faucet simulation HTTP server
oas smoke public-beta --json                         # executable public beta release smoke

# real public beta onboarding follows chain-side docs on chain.oasyce
```

## Fingerprint & Watermark

```bash
oas fingerprint embed <file> --caller <id> [--output path]
oas fingerprint extract <file>
oas fingerprint trace <fingerprint_hex>
oas fingerprint list <asset_id>                     # list distributions for an asset
```

## Pricing

```bash
oas price <asset_id> [--base-price 1.0] [--queries 0] [--similar 0] \
  [--contribution-score 1.0] [--days 0]             # calculate price with demand/scarcity factors
oas price-factors <asset_id> [--base-price 1.0] [--queries 0] [--similar 0] \
  [--contribution-score 1.0] [--days 0]             # show pricing factor breakdown
```

## Keys

```bash
oas keys generate [--force] [--passphrase "..."]    # generate Ed25519 keypair
oas keys show                                       # show current signing key
```

## Work

```bash
oas work list [--status STATUS] [--type TYPE] [--limit 20]
oas work stats                                      # show work system stats
oas work history [--limit 20]                       # show your work history
```

## Contribution

```bash
oas contribution prove <file> --creator <pubkey> \
  [--source-type tee_capture|api_log|sensor_sig|git_commit|manual] \
  [--source-evidence "hash/sig/URL"]                # generate contribution proof
oas contribution verify <certificate_json> <file>   # verify contribution certificate
oas contribution score <file> --creator <pubkey> [--source-type manual]  # calculate contribution score
```

## Leakage

```bash
oas leakage check <agent_id> <asset_id>            # check leakage budget
oas leakage reset <agent_id> <asset_id>            # reset leakage budget
```

## Cache

```bash
oas cache list [--all]                              # list cached providers (--all includes expired)
oas cache clear                                     # clear all cached providers
oas cache stats                                     # show cache statistics
oas cache purge                                     # remove expired cache entries
```

## Inbox & Trust

```bash
oas inbox list [--type register|purchase|all]       # list pending confirmation items
oas inbox approve <item_id>
oas inbox reject <item_id>
oas inbox edit <item_id> [--name "..."] [--tags "..."] [--description "..."]

oas trust [<level>]                                 # view or set trust level (0=manual, 1=low-auto, 2=full-auto)
```

## Diagnostics

```bash
oas doctor                   # health check
oas demo [--full]            # full pipeline demo (--full uses chain bridge)
oas info                     # project info and links
oas info --section economics # token economics
oas update [--check]         # check for updates and upgrade (--check = dry run)
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
│ DataVault│  Oasyce Client   │        CLI / GUI       │
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
- [Oasyce Client](https://github.com/Shangri-la-0428/oasyce-net) — Python client
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

---

## When to Use

- Data registration with pricing control (auto/fixed/floor)
- AI capability listing, discovery, invocation, settlement
- Compute task submission and executor registration (PoUW)
- Local data scanning, classification, PII detection
- Autonomous agent operation (scheduled scan/register/trade)
- Consensus participation, staking, governance voting
- Fingerprint watermarking and provenance verification
- Testnet onboarding and demos

## When NOT to Use

- General file management (mv/cp/rm — use standard tools)
- General crypto questions unrelated to data rights
- Browser-based web3 wallet interactions

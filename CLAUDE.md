# CLAUDE.md — Oasyce Protocol Integration (v2.0.0)

You have access to the `oasyce` CLI — a thin Python client for the Oasyce network. All consensus, settlement, and state are handled by the Go Cosmos SDK chain (`oasyce-chain`). This package communicates with the chain via gRPC/REST.

## Setup

```bash
pip install oasyce
oasyce doctor    # verify installation
```

## Core Commands

### Data Assets
```bash
oasyce register <file> --owner <name> --tags <tag1,tag2>   # Register data asset
  --rights-type original|co_creation|licensed|collection     # Rights declaration
  --co-creators '[{"address":"A","share":60},...]'           # Co-creator shares
oasyce search <keyword>                                      # Search assets
oasyce quote <asset_id>                                      # Get price (Bonding Curve)
oasyce buy <asset_id>                                        # Buy shares
oasyce sell <asset_id> --tokens <n> --seller <name>          # Sell tokens back to bonding curve
```

### AI Capabilities
```bash
oasyce search --type capability                # Find callable AI services
oasyce quote <capability_id>                   # Price per invocation
oasyce buy <capability_id>                     # Invoke and earn shares
oasyce discover --intents "翻译" --tags nlp    # Four-layer capability discovery
```

### Dispute & Resolution
```bash
oasyce dispute <asset_id> --reason "..."             # File a dispute
oasyce resolve <asset_id> --remedy delist            # Resolve with remedy
  # Remedies: delist, transfer, rights_correction, share_adjustment
  --details '{"new_owner":"0x..."}'                  # Details for remedy
```

### Node Management
```bash
oasyce serve                   # Start thin-client API server + Dashboard
oasyce node info               # Show node identity (Ed25519 pubkey)
oasyce node peers              # List connected peers
oasyce node ping <host:port>   # Ping another node
```

### Capability Marketplace
```bash
oasyce capability register --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx --price 0.5 --tags nlp,translation   # Register endpoint
oasyce capability list [--tag nlp] [--provider addr]     # Browse capabilities
oasyce capability invoke CAP_ID --input '{"text":"hello"}'  # Invoke via settlement
oasyce capability earnings --provider addr               # Provider earnings
oasyce capability earnings --consumer addr               # Consumer spending
```

### Reputation
```bash
oasyce reputation show <address>               # Show reputation score
oasyce reputation feedback <target> --score 5   # Submit feedback
```

### Access & Fingerprint
```bash
oasyce access grant <asset_id> --to <address>   # Grant access
oasyce access revoke <asset_id> --from <address> # Revoke access
oasyce access buy <asset_id> --level L0|L1|L2|L3 --agent <name>  # Buy tiered access
oasyce fingerprint <file>                        # Compute content fingerprint
```

### Discovery
```bash
oasyce discover --intents "翻译" --tags nlp     # Four-layer capability discovery
```

### Leakage & Contribution
```bash
oasyce leakage scan <asset_id>                  # Check for data leakage
oasyce contribution show <address>              # Show contribution history
```

### Keys
```bash
oasyce keys generate            # Generate Ed25519 keypair
oasyce keys show                # Show public key
```

### Testnet
```bash
oasyce testnet onboard          # Join testnet
oasyce testnet faucet           # Get free test OAS
```

### Diagnostics
```bash
oasyce doctor                   # Health check (keys, ports, deps)
oasyce demo                     # Run full pipeline demo
```

### Project Info
```bash
oasyce info                            # Show project info, links, asset types
oasyce info --section architecture     # Technical architecture details
oasyce info --section economics        # Token economics, bonding curves, staking
oasyce info --section quickstart       # Quick start guide
oasyce info --section update           # How to update and contribute
oasyce info --json                     # Full info as JSON
```

## All commands support `--json` for structured output.

## Key Concepts

- **OAS**: Protocol token. All transactions settle in OAS.
- **Bonding Curve**: Auto-pricing — more buyers = higher price. No order book.
- **Escrow**: Funds lock before execution, release after quality verification.
- **Reputation**: Long-term score. Bad behavior follows you.
- **Shares**: Buying data/capabilities earns shares. Early buyers get more (diminishing returns: 100%->80%->60%->40%).
- **Rights Type**: Declare data rights origin — `original` (1.0x), `co_creation` (0.9x), `licensed` (0.7x), `collection` (0.3x). Affects pricing.
- **Dispute**: File disputes against assets. Auto-matched arbitrators resolve with remedies: delist, transfer, rights correction, share adjustment.
- **Schema Registry**: Unified validation for 4 asset types: `data`, `capability`, `oracle`, `identity`.
- **Discovery Recall->Rank**: Broad recall (intent OR semantic OR tag) then ranked by trust + feedback-adjusted economics.
- **Risk Auto-Leveling**: Files auto-classified as `public`/`internal`/`sensitive` based on content, extension, and rights type.
- **Capability Delivery**: Provider registers endpoint + encrypted API key -> consumer invokes via gateway -> escrow lock -> call -> settle (release/refund). 5% protocol fee.
- **INITIAL_PRICE**: Fair bootstrap pricing — first buyer pays 1.0 OAS/token (no early-adopter exploit).
- **Equity → Access**: Holding equity in an asset grants tiered access: ≥0.1% → L0, ≥1% → L1, ≥5% → L2, ≥10% → L3.
- **Reputation Decay**: Scores decay over time (90-day cycle). Use `facade.decay_all_reputations()` for proactive bulk decay.
- **Architecture Enforcement**: CI tests prevent direct SQL writes outside storage layer, direct engine instantiation outside facade, and ensure facade has zero raw SQL.
- **Go Chain (oasyce-chain)**: Consensus (CometBFT), staking, delegation, slashing, governance, multi-asset balances, block production, and sync are all handled by the Cosmos SDK appchain. Use the `oasyced` CLI for direct chain interaction.

## Dashboard

After `oasyce serve`, the web Dashboard is at `http://localhost:8420`.
- `/explore` — Browse all data assets and capabilities
- `/register` — Register new assets (drag & drop)
- Supports both data assets and AI capabilities in unified view.

## Architecture (v2.0.0)

```
                    ┌──────────────────────────┐
                    │   oasyce-chain (Go)       │
                    │   Cosmos SDK Appchain     │
                    │   ─────────────────────   │
                    │   CometBFT Consensus      │
                    │   x/settlement             │
                    │   x/capability             │
                    │   x/reputation             │
                    │   x/datarights             │
                    │   gRPC :9090 / REST :1317  │
                    └────────────┬───────────────┘
                                 │ gRPC / REST
                    ┌────────────▼───────────────┐
                    │   oasyce (Python)           │
                    │   Thin Client v2.0.0        │
                    │   ─────────────────────     │
                    │   chain_client.py (RPC)     │
                    │   proto/ (type stubs)       │
                    │   engines/ (scan/classify)  │
                    │   services/discovery/       │
                    │   services/capability/      │
                    │   gui/app.py (Dashboard)    │
                    │   Dashboard :8420             │
                    └─────────────────────────────┘

oasyce/
├── chain_client.py          # gRPC/REST client to Go chain
├── proto/                   # Proto-generated Python type stubs
│   └── oasyce/
│       ├── settlement/v1/   # MsgCreateEscrow, MsgReleaseEscrow, Escrow
│       ├── capability/v1/   # MsgRegisterCapability, MsgInvokeCapability, Capability
│       ├── reputation/v1/   # MsgSubmitFeedback, Reputation
│       └── datarights/v1/   # MsgRegisterDataAsset, MsgBuyShares, DataAsset
├── schema_registry/         # Unified schema validation (data/capability/oracle/identity)
├── engines/
│   ├── core_engines.py      # Scan -> Classify -> Metadata -> PoPc -> Register (+ auto risk)
│   ├── risk.py              # Auto risk classification (public/internal/sensitive)
│   └── schema.py            # Backward-compat (delegates to schema_registry)
├── services/capability_delivery/  # Endpoint registry, escrow, gateway, settlement
├── services/discovery/      # Recall->Rank discovery + FeedbackStore
├── info.py                  # Project info hub (shared by GUI/CLI/API)
└── gui/app.py               # Dashboard SPA with tabbed about panel
```

## Architecture Constraints (enforced by CI)

- All business operations route through `OasyceServiceFacade` (single entry point).
- No direct `_ledger._conn` WRITE access outside `oasyce/storage/`.
- No `SettlementEngine()` instantiation outside facade.
- Settlement engine shared between CLI, GUI, and API (single pool state).
- Pool objects are read-only externally (safe accessors: `get_equity()`, `get_supply()`).

## Tips

- Always run `oasyce doctor` first to verify setup.
- Use `--json` flag when you need to parse output programmatically.
- Use `oasyce info` to see project links, architecture, economics, and update instructions.
- For batch operations, prefer CLI over Dashboard.
- The Dashboard starts on port 8420 with `oasyce serve`.
- For chain-level operations (staking, governance, transfers), use the `oasyced` CLI from `oasyce-chain`.

## Facade API (programmatic access)

```python
from oasyce.services.facade import OasyceServiceFacade, ServiceResult

facade = OasyceServiceFacade()

# Quote & Trade
result = facade.quote("ASSET_ID", amount_oas=10.0)
result = facade.buy("ASSET_ID", buyer="alice", amount_oas=10.0)
result = facade.sell("ASSET_ID", seller="alice", tokens_to_sell=5.0)
result = facade.sell_quote("ASSET_ID", tokens=5.0, seller="alice")

# Access Control
result = facade.access_quote("ASSET_ID", buyer="alice")
result = facade.access_buy("ASSET_ID", buyer="alice", level="L2")

# Portfolio & Pool Info
result = facade.get_pool_info("ASSET_ID")
result = facade.get_portfolio("alice")
result = facade.list_pools()
result = facade.protocol_stats()

# Asset Management
result = facade.register(file_path, owner, tags)
result = facade.get_asset("ASSET_ID")
result = facade.update_asset_metadata("ASSET_ID", {"tags": ["new"]})
result = facade.delete_asset("ASSET_ID")

# Disputes
result = facade.dispute("ASSET_ID", consumer_id="bob", reason="...")
result = facade.resolve_dispute(dispute_id="DIS_001")

# Maintenance
result = facade.decay_all_reputations()
```

All methods return `ServiceResult(success: bool, data: dict, error: str | None)`.

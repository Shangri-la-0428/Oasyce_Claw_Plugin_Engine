# CLAUDE.md — Oasyce Protocol Integration

You have access to the `oasyce` CLI for data rights and AI capability trading on the Oasyce network.

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
oasyce start                    # Start protocol node + Dashboard
oasyce node info                # Show node identity (Ed25519 pubkey)
oasyce node peers               # List connected peers
oasyce node ping <host:port>    # Ping another node
```

### Testnet
```bash
oasyce testnet onboard          # Join testnet
oasyce testnet faucet           # Get free test OAS
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

### Diagnostics
```bash
oasyce doctor                   # Health check (keys, ports, deps)
oasyce demo                     # Run full pipeline demo
```

## All commands support `--json` for structured output.

## Key Concepts

- **OAS**: Protocol token. All transactions settle in OAS.
- **Bonding Curve**: Auto-pricing — more buyers = higher price. No order book.
- **Escrow**: Funds lock before execution, release after quality verification.
- **Reputation**: Long-term score. Bad behavior follows you.
- **Shares**: Buying data/capabilities earns shares. Early buyers get more (diminishing returns: 100%→80%→60%→40%).
- **Rights Type**: Declare data rights origin — `original` (1.0x), `co_creation` (0.9x), `licensed` (0.7x), `collection` (0.3x). Affects pricing.
- **Dispute**: File disputes against assets. Auto-matched arbitrators resolve with remedies: delist, transfer, rights correction, share adjustment.
- **Schema Registry**: Unified validation for 4 asset types: `data`, `capability`, `oracle`, `identity`. Use `from oasyce_plugin.schema_registry import AssetType, validate`.
- **Discovery Recall→Rank**: Broad recall (intent OR semantic OR tag) then ranked by trust + feedback-adjusted economics.
- **Risk Auto-Leveling**: Files auto-classified as `public`/`internal`/`sensitive` based on content, extension, and rights type.

## Dashboard

After `oasyce start`, the web Dashboard is at `http://localhost:8420`.
- `/explore` — Browse all data assets and capabilities
- `/register` — Register new assets (drag & drop)
- Supports both data assets and AI capabilities in unified view.

## Architecture (v1.5.0)

```
oasyce_plugin/
├── schema_registry/  # Unified schema validation (data/capability/oracle/identity)
├── engines/
│   ├── core_engines.py  # Scan → Classify → Metadata → PoPc → Register (+ auto risk)
│   ├── risk.py          # Auto risk classification (public/internal/sensitive)
│   └── schema.py        # Backward-compat (delegates to schema_registry)
├── services/discovery/  # Recall→Rank discovery + FeedbackStore
├── info.py              # Project info hub (shared by GUI/CLI/API)
└── gui/app.py           # Dashboard SPA with tabbed about panel
```

## Tips

- Always run `oasyce doctor` first to verify setup.
- Use `--json` flag when you need to parse output programmatically.
- Use `oasyce info` to see project links, architecture, economics, and update instructions.
- For batch operations, prefer CLI over Dashboard.
- The protocol node (port 8000) and Dashboard (port 8420) start together with `oasyce start`.

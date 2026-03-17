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

### Consensus (PoS)
```bash
oasyce consensus status                             # Current epoch/slot/validators
oasyce consensus validators [--all]                 # List validators (--all includes jailed/exited)
oasyce consensus schedule [--epoch N]               # Leader schedule for an epoch
oasyce consensus register --stake 10000             # Register as validator
oasyce consensus exit                               # Voluntary exit
oasyce consensus unjail                             # Unjail after penalty expires
oasyce consensus delegate <validator_id> --amount 500    # Delegate stake
oasyce consensus undelegate <validator_id> --amount 200  # Undelegate (enters unbonding queue)
oasyce consensus rewards [--epoch N]                # Reward history
oasyce consensus slashing [--validator X]           # Slashing history
oasyce consensus delegations                        # Show your active delegations
oasyce consensus unbondings                         # Show your pending unbondings
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
- **PoS Consensus**: Event-sourced consensus. All monetary values in integer units (1 OAS = 10^8 units). State derived from append-only `stake_events`. Single entry point: `apply_operation()`.
- **Epoch/Slot**: Block-height based (`blocks_per_epoch=10` testnet). Wall-clock fallback for P2P timing. Leaders elected per slot via stake-weighted deterministic random.
- **Delegation**: Stake OAS to validators. Undelegation enters unbonding queue. Commission in basis points (1000 = 10%). All changes recorded as events.
- **Slashing**: Offline (100 bps + jail), double-sign (500 bps + 3x jail), low-quality (50 bps). Integer arithmetic, no float.
- **Operation**: Frozen dataclass with `op_type`, `validator_id`, `amount` (int units), `asset_type` (default "OAS"). Immutable once created.

## Dashboard

After `oasyce start`, the web Dashboard is at `http://localhost:8420`.
- `/explore` — Browse all data assets and capabilities
- `/register` — Register new assets (drag & drop)
- Supports both data assets and AI capabilities in unified view.

## Architecture (v2.0.0)

```
oasyce_plugin/
├── consensus/            # PoS consensus engine (event-sourced)
│   ├── core/
│   │   ├── types.py      # OAS_DECIMALS, Operation (frozen), OperationType
│   │   ├── transition.py # apply_operation — single state mutation entry point
│   │   └── validation.py # validate_operation — pure validation functions
│   ├── storage/
│   │   └── events.py     # append_event — single write function for stake
│   ├── execution/
│   │   └── engine.py     # Block-height scheduling, compute_block_hash
│   ├── state.py          # ConsensusState — event-derived views (no REAL, no UPDATE on stake)
│   ├── epoch.py          # EpochManager — wall-clock fallback for P2P
│   ├── proposer.py       # Stake-weighted leader election (integer arithmetic)
│   ├── validator_registry.py  # Registration/delegation/exit (event-sourced)
│   ├── slashing.py       # Three penalty conditions (basis points)
│   ├── rewards.py        # Reward distribution (integer units)
│   └── __init__.py       # ConsensusEngine facade + apply()
├── schema_registry/      # Unified schema validation (data/capability/oracle/identity)
├── engines/
│   ├── core_engines.py   # Scan → Classify → Metadata → PoPc → Register (+ auto risk)
│   ├── risk.py           # Auto risk classification (public/internal/sensitive)
│   └── schema.py         # Backward-compat (delegates to schema_registry)
├── services/discovery/   # Recall→Rank discovery + FeedbackStore
├── info.py               # Project info hub (shared by GUI/CLI/API)
└── gui/app.py            # Dashboard SPA with tabbed about panel
```

## Tips

- Always run `oasyce doctor` first to verify setup.
- Use `--json` flag when you need to parse output programmatically.
- Use `oasyce info` to see project links, architecture, economics, and update instructions.
- For batch operations, prefer CLI over Dashboard.
- The protocol node (port 8000) and Dashboard (port 8420) start together with `oasyce start`.

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
oasyce search <keyword>                                      # Search assets
oasyce quote <asset_id>                                      # Get price (Bonding Curve)
oasyce buy <asset_id>                                        # Buy shares
```

### AI Capabilities
```bash
oasyce search --type capability                # Find callable AI services
oasyce quote <capability_id>                   # Price per invocation
oasyce buy <capability_id>                     # Invoke and earn shares
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

## Dashboard

After `oasyce start`, the web Dashboard is at `http://localhost:8420`.
- `/explore` — Browse all data assets and capabilities
- `/register` — Register new assets (drag & drop)
- Supports both data assets and AI capabilities in unified view.

## Tips

- Always run `oasyce doctor` first to verify setup.
- Use `--json` flag when you need to parse output programmatically.
- For batch operations, prefer CLI over Dashboard.
- The protocol node (port 8000) and Dashboard (port 8420) start together with `oasyce start`.

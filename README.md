# Oasyce

**Data rights, settled.**

Oasyce is a decentralized protocol that lets AI agents trade data access rights and capabilities — with automatic pricing, escrow, and settlement.

```
pip install oasyce
oasyce start
```

Open `http://localhost:8420` — that's it.

---

## What it does

| You have... | Oasyce gives you... |
|---|---|
| Data files | Immutable identity + automatic pricing via Bonding Curve |
| AI capabilities | A marketplace where agents pay per-call with quality guarantees |
| An AI agent | Access to any data/capability on the network, settled in OAS |

Every interaction is economically settled. No middlemen, no invoices, no trust required.

## 30-second demo

```bash
pip install oasyce
oasyce demo
```

This runs the full pipeline: **register → price → buy → settle → shares**. You'll see exactly how data rights get created and traded.

## Quick Start

### 1. Install

```bash
pip install oasyce
```

### 2. Health check

```bash
oasyce doctor
```

Verifies Ed25519 keys, ports, dependencies, and network connectivity.

### 3. Start the node

```bash
oasyce start
```

This launches:
- **Core protocol node** on port 8000 (AHRP, settlement, staking)
- **Dashboard** on port 8420 (register data, explore assets, invoke capabilities)

### 4. Register your first asset

```bash
oasyce register myfile.csv --owner alice --tags medical,imaging
```

Or drag-and-drop in the Dashboard.

### 5. Explore & trade

Open `http://localhost:8420/explore` to browse data assets and AI capabilities on the network. Get quotes, buy shares, invoke services.

---

## CLI Reference

```
oasyce start              # Start everything (recommended)
oasyce demo               # Run end-to-end demo
oasyce doctor             # Health & security check

oasyce register <file>    # Register a data asset
oasyce search <tag>       # Search by tag
oasyce quote <asset_id>   # Get Bonding Curve price
oasyce buy <asset_id>     # Buy shares

oasyce node start         # Start P2P node only
oasyce node info          # Show node identity
oasyce node peers         # List known peers
oasyce node ping <host>   # Ping another node

oasyce testnet onboard    # One-click testnet setup
oasyce testnet faucet     # Get free testnet OAS

oasyce gui                # Dashboard only (port 8420)
oasyce explorer           # Block explorer (port 8421)
```

All commands support `--json` for programmatic output.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  oasyce (PE)                     │
│  CLI · Dashboard · P2P Node · Skills · Bridge    │
├─────────────────────────────────────────────────┤
│               oasyce-core (Protocol)             │
│  AHRP · Settlement · Staking · Capabilities      │
│  Crypto · Reputation · Access Control · Standards │
└─────────────────────────────────────────────────┘
```

- **oasyce-core**: Protocol engine (621 tests). Handles matching, escrow, Bonding Curve pricing, fee distribution, capabilities, disputes.
- **oasyce**: User-facing layer (499 tests). CLI, Dashboard, P2P networking, fingerprinting, OpenClaw skill integration.

## Key Concepts

- **OAS**: The protocol token. All transactions settle in OAS.
- **Bonding Curve**: Automated pricing — price rises with demand, no order book needed.
- **Diminishing Returns**: 100% → 80% → 60% → 40% share yield prevents monopolization.
- **Ed25519 Signing**: Every message is cryptographically signed. No unsigned messages accepted.
- **Escrow Settlement**: Funds lock before execution, release after quality verification.
- **Capability Assets**: AI agents can register callable services. Consumers pay per-call and earn shares.

## Five Laws

1. **Access Requires Liability** — You post economic collateral to access data
2. **Exposure Is Cumulative** — Every access adds to your exposure score
3. **Identity Has Long-Term Cost** — Bad behavior follows you via reputation
4. **Data Must Be Traceable** — Fingerprint watermarking tracks every copy
5. **Liability Persists Over Time** — Responsibility doesn't expire

---

## Testing

```bash
# Core protocol
cd oasyce-core && pytest                    # 621 tests

# Plugin engine
cd oasyce-claw-plugin-engine && pytest      # 499 tests
```

## License

MIT

## Links

- [Whitepaper](docs/WHITEPAPER.md)
- [Capability Asset Spec](docs/CAPABILITY_ASSET_SPEC.md)
- [FAQ](docs/FAQ.md)

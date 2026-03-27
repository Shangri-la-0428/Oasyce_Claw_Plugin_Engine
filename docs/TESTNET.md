# Oasyce Testnet Guide

> **Updated 2026-03-22**: Consensus/governance commands below marked with `(chain)` require the Go chain (`oasyced`). Commands without this marker work in standalone Python mode.

## Overview

The Oasyce testnet (`oasyce-testnet-1`) is a public test environment for validators, developers, and users to experiment with the Oasyce Protocol without risking real assets.

**Key differences from mainnet:**

| Parameter        | Testnet           | Mainnet           |
|------------------|-------------------|-------------------|
| Min stake        | 100 OAS           | 10,000 OAS        |
| Block reward     | 4 OAS/block       | 4 OAS/block       |
| Blocks per epoch | 10                | 60                |
| Unbonding        | 20 blocks (~3 min)| 10,080 blocks (~7d)|
| Voting period    | 100 blocks        | 60,480 blocks     |
| Min deposit      | 10 OAS            | 1,000 OAS         |
| Faucet           | Enabled (testnet utility) | Disabled  |

## Quick Start

### 1. Install

```bash
pip install oasyce
oas doctor
```

### 2. One-Click Onboarding

```bash
oas testnet onboard
```

This performs PoW registration (20 OAS debt airdrop), claims supplemental testnet OAS, registers a sample asset, and stakes as a validator — all in one command.

### 3. Check Status

```bash
oas testnet status
oasyce chain info
```

## Validator Guide

### Joining as a Validator

#### Option A: Quick Join (Solo)

```bash
# 1. Register identity (PoW → 20 OAS airdrop as debt)
oas testnet onboard

# 2. (Optional) Claim supplemental testnet OAS
oas testnet faucet

# 3. Register as validator (stake 100+ OAS)
oas node become-validator --stake 200

# 4. Check your status (Dashboard API)
# Open http://localhost:8420 → Network page → Validators section
```

#### Option B: Join Existing Testnet (with Genesis)

```bash
# 1. Obtain the genesis.json from the testnet coordinator
# 2. Join the network
oas testnet join --genesis genesis.json

# 3. Register identity + claim supplemental OAS
oas testnet onboard

# 4. Register as validator
oas node become-validator --stake 200
```

#### Option C: Deploy Your Own Testnet

```bash
# Initialize a 3-validator testnet
oas testnet init --validators 3 --output ./my-testnet

# Or use the deployment script
./scripts/deploy_testnet.sh --validators 3 --output ./my-testnet

# Start a validator node
oas testnet join --genesis ./my-testnet/genesis.json --data-dir ./my-testnet/node-0
```

### Validator Operations (via Dashboard API)

Validator operations are available through the Dashboard at `http://localhost:8420`:

- **Network page**: View validators, consensus status, rewards, slashing
- **API endpoints**: `/api/consensus/delegate`, `/api/consensus/undelegate`, `/api/consensus/validators`, `/api/consensus/rewards`

For full chain validator operations (delegation, unbonding, unjailing), use the Go chain CLI:

```bash
# (chain) Delegate stake to another validator
oasyced tx staking delegate <validator> <amount>uoas

# (chain) Undelegate
oasyced tx staking unbond <validator> <amount>uoas

# (chain) Unjail
oasyced tx slashing unjail
```

### Governance (Chain-Only)

Governance is implemented on the L1 chain. Use `oasyced` for proposals and voting:

```bash
# (chain) Submit a proposal
oasyced tx gov submit-proposal --title "..." --description "..." --deposit 10000000uoas

# (chain) Vote on a proposal
oasyced tx gov vote <proposal_id> yes|no|abstain
```

The Dashboard displays governance state via `/api/governance/proposals` and `/api/governance/vote` (local simulation in standalone mode).

## Faucet (Testnet Utility Only)

> **Note:** The faucet is a testnet development utility, not part of mainnet onboarding. On mainnet, new users receive 20 OAS via PoW debt-based airdrop. The faucet provides supplemental tokens for validator testing only.

### Prerequisites

- Must complete PoW registration first (`oas testnet onboard`)
- Unregistered addresses are rejected (403)

### CLI Usage

```bash
oas testnet faucet
```

### Limits

| Parameter | Value |
|-----------|-------|
| Amount per claim | 20 OAS |
| Cooldown | 1 hour |
| Max claims per address | unlimited (1/hr rate limit) |
| Global supply cap | 10,000,000 OAS |

### HTTP Faucet Server

For public testnet deployments:

```bash
python3 scripts/run_faucet.py --port 8421
```

```bash
# Claim (requires prior PoW registration)
curl -X POST http://localhost:8421/claim \
  -H "Content-Type: application/json" \
  -d '{"address": "your_node_id"}'

# Check status
curl http://localhost:8421/status
```

## Network Parameters

### Chain Identity

- **Chain ID:** `oasyce-testnet-1`
- **Genesis time:** Fixed at deployment
- **P2P port:** 9528 (testnet), 9527 (mainnet)

### Consensus

- **Epoch:** 10 blocks
- **Block time target:** 10 seconds
- **Slot duration:** 30 seconds (wall-clock fallback)
- **Leader election:** Stake-weighted deterministic random (SHA-256 seeded)

### Staking

- **Minimum validator stake:** 100 OAS (10^10 units)
- **Unbonding period:** 20 blocks
- **Max commission:** 50% (5000 bps)
- **Commission granularity:** basis points (100 bps = 1%)

### Slashing

| Condition       | Penalty  | Jail Duration |
|-----------------|----------|---------------|
| Offline         | 1% (100 bps) | 2 minutes |
| Double sign     | 5% (500 bps) | 6 minutes |
| Low quality     | 0.5% (50 bps)| No jail   |

### Economics

- All monetary values are in **integer units** (1 OAS = 10^8 units)
- No floating-point arithmetic for monetary calculations
- Block rewards halve every 10,000 blocks on testnet

## Testnet Deployment (for Operators)

### Using the Deployment Script

```bash
./scripts/deploy_testnet.sh --validators 3 --output ./testnet-data
```

This will:
1. Generate Ed25519 keypairs for each validator
2. Create a genesis.json with initial stakes
3. Distribute genesis to all node directories

### Using the CLI

```bash
# Generate genesis with 3 validators
oas testnet init --validators 3 --output ./testnet-data --json

# Create genesis from a config file
oas testnet genesis --config testnet-config.json --output genesis.json
```

### Validator Node Setup

```bash
./scripts/setup_validator.sh --genesis genesis.json --stake 1000 --port 9528
```

### Config File Format

```json
{
    "chain_id": "oasyce-testnet-1",
    "genesis_time": 1710720000,
    "blocks_per_epoch": 10,
    "block_time_seconds": 10,
    "min_stake": 10000000000,
    "block_reward": 400000000,
    "unbonding_blocks": 20,
    "voting_period": 100,
    "min_deposit": 1000000000,
    "faucet_enabled": true,
    "faucet_amount": 1000000000000,
    "initial_validators": [
        {
            "pubkey": "abc123...",
            "stake": 100000000000,
            "commission": 1000,
            "moniker": "validator-0"
        }
    ]
}
```

## FAQ

**Q: Are testnet tokens worth anything?**
A: No. Testnet tokens have no monetary value and exist only for testing.

**Q: How do I reset my testnet state?**
A: Run `oas testnet reset --force` to delete all testnet data.

**Q: Can I run testnet and mainnet simultaneously?**
A: Yes. They use separate data directories (`~/.oasyce-testnet` vs `~/.oasyce`) and ports (9528 vs 9527).

**Q: What happens if I get slashed on testnet?**
A: Claim supplemental OAS from the faucet (max 3 claims per address). Slashing on testnet is a learning experience, not a loss.

**Q: How do I connect to other testnet nodes?**
A: Use `oas testnet join --genesis genesis.json --bootstrap <host:port>` to connect to a bootstrap peer.

**Q: Where are my keys stored?**
A: Node identity keys are in `~/.oasyce-testnet/node_id.json`. Signing keys are in `~/.oasyce/keys/` (shared across networks).

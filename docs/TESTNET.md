# Oasyce Testnet Guide

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
| Faucet           | Enabled (10k OAS) | Disabled          |

## Quick Start

### 1. Install

```bash
pip install oasyce
oasyce doctor
```

### 2. One-Click Onboarding

```bash
oasyce testnet onboard
```

This claims faucet tokens, registers a sample asset, and stakes as a validator — all in one command.

### 3. Check Status

```bash
oasyce testnet status
oasyce chain info
```

## Validator Guide

### Joining as a Validator

#### Option A: Quick Join (Solo)

```bash
# 1. Claim faucet tokens
oasyce testnet faucet

# 2. Register as validator (stake 100+ OAS)
oasyce consensus register --stake 200

# 3. Check your status
oasyce consensus validators
```

#### Option B: Join Existing Testnet (with Genesis)

```bash
# 1. Obtain the genesis.json from the testnet coordinator
# 2. Join the network
oasyce testnet join --genesis genesis.json

# 3. Claim faucet tokens
oasyce testnet faucet

# 4. Register as validator
oasyce consensus register --stake 200
```

#### Option C: Deploy Your Own Testnet

```bash
# Initialize a 3-validator testnet
oasyce testnet init --validators 3 --output ./my-testnet

# Or use the deployment script
./scripts/deploy_testnet.sh --validators 3 --output ./my-testnet

# Start a validator node
oasyce testnet join --genesis ./my-testnet/genesis.json --data-dir ./my-testnet/node-0
```

### Validator Operations

```bash
# Delegate stake to another validator
oasyce consensus delegate <validator_pubkey> --amount 500

# Undelegate (enters unbonding queue)
oasyce consensus undelegate <validator_pubkey> --amount 200

# View your delegations
oasyce consensus delegations

# View pending unbondings
oasyce consensus unbondings

# Check rewards
oasyce consensus rewards

# View slashing history
oasyce consensus slashing

# Voluntary exit
oasyce consensus exit

# Unjail after penalty expires
oasyce consensus unjail
```

### Governance

```bash
# Submit a proposal (min deposit: 10 OAS on testnet)
oasyce governance propose \
    --title "Increase block reward" \
    --change economics.block_reward=500000000 \
    --deposit 10

# Vote on a proposal
oasyce governance vote --proposal <id> --vote yes

# List active proposals
oasyce governance list --status active

# View proposal details
oasyce governance show <proposal_id>
```

## Faucet

### CLI Usage

```bash
oasyce testnet faucet
```

Each address can claim **10,000 OAS** once per **24 hours**.

### HTTP Faucet Server

For public testnet deployments, run the faucet as an HTTP service:

```bash
python3 scripts/run_faucet.py --port 8421
```

**API:**

```bash
# Claim tokens
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
oasyce testnet init --validators 3 --output ./testnet-data --json

# Create genesis from a config file
oasyce testnet genesis --config testnet-config.json --output genesis.json
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
A: Run `oasyce testnet reset --force` to delete all testnet data.

**Q: Can I run testnet and mainnet simultaneously?**
A: Yes. They use separate data directories (`~/.oasyce-testnet` vs `~/.oasyce`) and ports (9528 vs 9527).

**Q: What happens if I get slashed on testnet?**
A: Just claim more tokens from the faucet. Slashing on testnet is a learning experience, not a loss.

**Q: How do I connect to other testnet nodes?**
A: Use `oasyce testnet join --genesis genesis.json --bootstrap <host:port>` to connect to a bootstrap peer.

**Q: Where are my keys stored?**
A: Node identity keys are in `~/.oasyce-testnet/node_id.json`. Signing keys are in `~/.oasyce/keys/` (shared across networks).

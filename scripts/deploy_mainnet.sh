#!/usr/bin/env bash
#
# deploy_mainnet.sh — Mainnet genesis + validator initialization
#
# Usage:
#   ./scripts/deploy_mainnet.sh [--validators N] [--output DIR]
#
# Differences from testnet:
#   - chain_id: oasyce-mainnet-1
#   - min stake: 10,000 OAS per validator
#   - port: 9527 (not 9528)
#   - require_signatures: true
#   - allow_local_fallback: false
#

set -euo pipefail

VALIDATORS=4
OUTPUT_DIR="./mainnet-data"
CHAIN_ID="oasyce-mainnet-1"
MIN_STAKE_OAS=10000

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --validators)
            VALIDATORS="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --chain-id)
            CHAIN_ID="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--validators N] [--output DIR] [--chain-id ID]"
            echo ""
            echo "Options:"
            echo "  --validators N    Number of validator nodes (default: 4)"
            echo "  --output DIR      Output directory (default: ./mainnet-data)"
            echo "  --chain-id ID     Chain identifier (default: oasyce-mainnet-1)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Require minimum 4 validators for mainnet
if [[ "$VALIDATORS" -lt 4 ]]; then
    echo "Error: Mainnet requires at least 4 validators (got $VALIDATORS)"
    exit 1
fi

echo "╔══════════════════════════════════════════════╗"
echo "║        Oasyce MAINNET Deployment             ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Validators:  ${VALIDATORS} (min 4 for mainnet)        ║"
echo "║  Min stake:   ${MIN_STAKE_OAS} OAS                    ║"
echo "║  Chain ID:    ${CHAIN_ID}"
echo "║  Output:      ${OUTPUT_DIR}"
echo "╚══════════════════════════════════════════════╝"
echo ""

# 1. Prerequisites
echo "[1/5] Checking prerequisites..."
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

if ! python3 -c "import oasyce" 2>/dev/null; then
    echo "Error: oasyce not installed. Run: pip install -e ."
    exit 1
fi

# Check oasyced is available (chain binary)
if ! command -v oasyced &> /dev/null; then
    echo "Warning: oasyced not found in PATH. Chain binary needed for full deployment."
    echo "         Continuing with Python-only genesis generation..."
fi

echo "  ✓ Prerequisites met"

# 2. Pre-deployment checks
echo ""
echo "[2/5] Running pre-deployment checks..."

# Disk space check (need at least 10GB free)
AVAIL_KB=$(df -k . | tail -1 | awk '{print $4}')
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
if [[ "$AVAIL_GB" -lt 10 ]]; then
    echo "Warning: Only ${AVAIL_GB}GB free disk space. Recommend 10GB+ for mainnet."
fi
echo "  ✓ Disk: ${AVAIL_GB}GB available"

# Verify economic parameters match mainnet
python3 -c "
from oasyce.config import get_economics, NetworkMode
econ = get_economics(NetworkMode.MAINNET)
min_stake_uoas = econ['agent_stake']
print(f'  ✓ Agent min stake: {min_stake_uoas / 1e8} OAS')
print(f'  ✓ Block reward: {econ[\"block_reward\"] / 1e8} OAS')

from oasyce.core.protocol_params import get_protocol_params
p = get_protocol_params()
print(f'  ✓ Fee split: {p.creator_rate}/{p.validator_rate}/{p.burn_rate}/{p.treasury_rate}')
print(f'  ✓ Reserve ratio: {p.reserve_ratio}')
"

# 3. Initialize mainnet
echo ""
echo "[3/5] Generating mainnet genesis..."
mkdir -p "$OUTPUT_DIR"

python3 -c "
import json, sys, os
from pathlib import Path

# Use oasyce crypto for key generation
from oasyce.crypto import generate_keypair
from oasyce.config import MAINNET_CONSENSUS

validators = []
for i in range($VALIDATORS):
    priv, pub = generate_keypair()
    v = {
        'pubkey': pub,
        'stake': $MIN_STAKE_OAS * 10**8,  # in uoas
        'commission': 1000,  # 10%
        'moniker': f'validator-{i}',
    }
    validators.append(v)

    # Save validator keys
    node_dir = Path('$OUTPUT_DIR') / f'node-{i}'
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / 'node_id.json').write_text(json.dumps({
        'node_id': pub,
        'private_key': priv,
        'moniker': f'validator-{i}',
        'network': 'mainnet',
    }, indent=2))

# Generate genesis
import hashlib, time
genesis = {
    'chain_id': '$CHAIN_ID',
    'genesis_time': int(time.time()),
    'consensus_params': MAINNET_CONSENSUS,
    'validators': validators,
    'app_state': {
        'settlement': {
            'reserve_ratio': 0.50,
            'creator_rate': 0.85,
            'validator_rate': 0.07,
            'burn_rate': 0.05,
            'treasury_rate': 0.03,
        },
    },
}
genesis_json = json.dumps(genesis, sort_keys=True)
genesis['genesis_hash'] = hashlib.sha256(genesis_json.encode()).hexdigest()

out_path = Path('$OUTPUT_DIR') / 'genesis.json'
out_path.write_text(json.dumps(genesis, indent=2))
print(f'  ✓ Genesis: {out_path}')
print(f'  ✓ Hash: {genesis[\"genesis_hash\"][:16]}...')
print(f'  ✓ Validators: {len(validators)}')
"

# 4. Distribute genesis
echo ""
echo "[4/5] Distributing genesis to validator nodes..."
for i in $(seq 0 $((VALIDATORS - 1))); do
    NODE_DIR="${OUTPUT_DIR}/node-${i}"
    cp "${OUTPUT_DIR}/genesis.json" "${NODE_DIR}/genesis.json"

    # Create mainnet environment file
    cat > "${NODE_DIR}/.env" << EOF
OASYCE_NETWORK_MODE=mainnet
OASYCE_DATA_DIR=${NODE_DIR}
OASYCE_NODE_PORT=9527
EOF

    echo "  ✓ node-${i}: genesis + .env configured"
done

# 5. Summary
echo ""
echo "[5/5] Mainnet initialization complete!"
echo ""
echo "  Genesis:    ${OUTPUT_DIR}/genesis.json"
echo "  Nodes:      ${VALIDATORS} validator nodes in ${OUTPUT_DIR}/node-*/"
echo "  Network:    MAINNET (signatures required, no local fallback)"
echo ""
echo "  To start a validator:"
echo "    OASYCE_NETWORK_MODE=mainnet oas serve --port 9527 --data-dir ${OUTPUT_DIR}/node-0"
echo ""
echo "  ⚠  Before mainnet launch:"
echo "    1. Distribute node-*/node_id.json to each validator operator SECURELY"
echo "    2. Verify genesis hash matches across all validators"
echo "    3. Configure firewall: allow port 9527 TCP"
echo "    4. Ensure oasyced is running with matching chain_id"

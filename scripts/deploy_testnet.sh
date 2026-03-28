#!/usr/bin/env bash
#
# deploy_testnet.sh — Automated testnet deployment
#
# Usage:
#   ./scripts/deploy_testnet.sh [--validators N] [--output DIR]
#
# Creates genesis, configures N validators, and prepares testnet data.
#

set -euo pipefail

VALIDATORS=3
OUTPUT_DIR="./testnet-data"
CHAIN_ID="oasyce-testnet-1"

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
            echo "  --validators N    Number of validator nodes (default: 3)"
            echo "  --output DIR      Output directory (default: ./testnet-data)"
            echo "  --chain-id ID     Chain identifier (default: oasyce-testnet-1)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "╔══════════════════════════════════════════════╗"
echo "║        Oasyce Testnet Deployment             ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Validators:  ${VALIDATORS}                             ║"
echo "║  Output:      ${OUTPUT_DIR}"
echo "║  Chain ID:    ${CHAIN_ID}"
echo "╚══════════════════════════════════════════════╝"
echo ""

# 1. Check Python and oasyce installation
echo "[1/4] Checking prerequisites..."
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found. Please install Python 3.8+."
    exit 1
fi

if ! python3 -c "import oasyce" 2>/dev/null; then
    echo "Error: oasyce not installed. Run: pip install -e ."
    exit 1
fi

echo "  ✓ Python3 found"
echo "  ✓ oasyce installed"

# 2. Initialize testnet
echo ""
echo "[2/4] Initializing testnet..."
python3 -m oasyce.cli testnet init \
    --validators "$VALIDATORS" \
    --output "$OUTPUT_DIR" \
    --json 2>/dev/null || {
    # Fallback: use Python directly
    python3 -c "
import json, sys
sys.path.insert(0, '.')
from oasyce.consensus.testnet_config import TestnetConfig, ValidatorInfo
from oasyce.consensus.genesis import create_genesis, export_genesis
from oasyce.crypto import generate_keypair
from oasyce.consensus.core.types import OAS_DECIMALS
from pathlib import Path

validators = []
for i in range($VALIDATORS):
    priv, pub = generate_keypair()
    v = ValidatorInfo(
        pubkey=pub,
        stake=1000 * OAS_DECIMALS,
        commission=1000,
        moniker=f'validator-{i}',
    )
    validators.append(v)

    # Save validator keys
    node_dir = Path('$OUTPUT_DIR') / f'node-{i}'
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / 'node_id.json').write_text(json.dumps({
        'node_id': pub,
        'private_key': priv,
        'moniker': f'validator-{i}',
    }, indent=2))

config = TestnetConfig(
    chain_id='$CHAIN_ID',
    initial_validators=validators,
)
genesis = create_genesis(config, validators)
export_genesis(genesis, '$OUTPUT_DIR/genesis.json')
print(json.dumps({
    'genesis_hash': genesis.genesis_hash,
    'validators': len(validators),
    'output': '$OUTPUT_DIR',
}, indent=2))
"
}
echo "  ✓ Genesis created"

# 3. Copy genesis to all validator nodes
echo ""
echo "[3/4] Distributing genesis to validator nodes..."
for i in $(seq 0 $((VALIDATORS - 1))); do
    NODE_DIR="${OUTPUT_DIR}/node-${i}"
    cp "${OUTPUT_DIR}/genesis.json" "${NODE_DIR}/genesis.json"
    echo "  ✓ node-${i}: genesis copied"
done

# 4. Summary
echo ""
echo "[4/4] Testnet ready!"
echo ""
echo "  Genesis:     ${OUTPUT_DIR}/genesis.json"
echo "  Nodes:       ${VALIDATORS} validator nodes in ${OUTPUT_DIR}/node-*/"
echo ""
echo "  To start a validator node:"
echo "    oasyced start --home ${OUTPUT_DIR}/node-0"
echo ""
echo "  To start all nodes:"
echo "    for i in \$(seq 0 $((VALIDATORS - 1))); do"
echo "      oasyced start --home ${OUTPUT_DIR}/node-\$i &"
echo "    done"

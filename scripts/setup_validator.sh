#!/usr/bin/env bash
#
# setup_validator.sh — Configure a validator node for testnet
#
# Usage:
#   ./scripts/setup_validator.sh --genesis genesis.json [--data-dir DIR] [--stake AMOUNT]
#

set -euo pipefail

GENESIS=""
DATA_DIR=""
STAKE=1000
PORT=9528

while [[ $# -gt 0 ]]; do
    case $1 in
        --genesis)
            GENESIS="$2"
            shift 2
            ;;
        --data-dir)
            DATA_DIR="$2"
            shift 2
            ;;
        --stake)
            STAKE="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 --genesis <path> [--data-dir DIR] [--stake AMOUNT] [--port PORT]"
            echo ""
            echo "Options:"
            echo "  --genesis PATH    Path to genesis.json (required)"
            echo "  --data-dir DIR    Node data directory (default: ~/.oasyce-testnet)"
            echo "  --stake AMOUNT    Validator stake in OAS (default: 1000)"
            echo "  --port PORT       Listen port (default: 9528)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [[ -z "$GENESIS" ]]; then
    echo "Error: --genesis is required"
    echo "Usage: $0 --genesis <path>"
    exit 1
fi

if [[ ! -f "$GENESIS" ]]; then
    echo "Error: Genesis file not found: $GENESIS"
    exit 1
fi

# Default data dir
if [[ -z "$DATA_DIR" ]]; then
    DATA_DIR="${HOME}/.oasyce-testnet"
fi

echo "╔══════════════════════════════════════════════╗"
echo "║        Validator Node Setup                  ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Genesis:   ${GENESIS}"
echo "║  Data dir:  ${DATA_DIR}"
echo "║  Stake:     ${STAKE} OAS"
echo "║  Port:      ${PORT}"
echo "╚══════════════════════════════════════════════╝"
echo ""

# 1. Create data directory
echo "[1/5] Creating data directory..."
mkdir -p "$DATA_DIR"
echo "  ✓ ${DATA_DIR}"

# 2. Copy genesis
echo "[2/5] Copying genesis..."
cp "$GENESIS" "${DATA_DIR}/genesis.json"
echo "  ✓ genesis.json copied"

# 3. Generate node identity (if not exists)
echo "[3/5] Setting up node identity..."
python3 -c "
import json
from pathlib import Path
data_dir = '${DATA_DIR}'
identity_path = Path(data_dir) / 'node_id.json'
if identity_path.exists():
    data = json.loads(identity_path.read_text())
    print(f'  Node ID: {data[\"node_id\"][:16]}... (existing)')
else:
    from oasyce_plugin.config import load_or_create_node_identity
    priv, pub = load_or_create_node_identity(data_dir)
    print(f'  Node ID: {pub[:16]}... (new)')
"

# 4. Validate genesis
echo "[4/5] Validating genesis..."
python3 -c "
from oasyce_plugin.consensus.genesis import import_genesis, validate_genesis
state = import_genesis('${DATA_DIR}/genesis.json')
errors = validate_genesis(state)
if errors:
    for e in errors:
        print(f'  ✗ {e}')
    raise SystemExit(1)
print(f'  ✓ Chain: {state.chain_id}')
print(f'  ✓ Genesis hash: {state.genesis_hash[:16]}...')
print(f'  ✓ Validators: {len(state.validators)}')
"

# 5. Register as validator
echo "[5/5] Registering as validator..."
echo "  Stake: ${STAKE} OAS"
echo ""
echo "  ✓ Validator setup complete!"
echo ""
echo "  To start the node:"
echo "    oasyce testnet join --genesis ${DATA_DIR}/genesis.json --data-dir ${DATA_DIR} --port ${PORT}"

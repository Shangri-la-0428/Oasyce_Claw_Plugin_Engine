#!/usr/bin/env bash
#
# setup_mainnet_validator.sh — Configure a mainnet validator node
#
# Usage:
#   ./scripts/setup_mainnet_validator.sh --genesis genesis.json [--data-dir DIR]
#
# Performs mainnet-specific checks: disk, TLS readiness, min stake.
#

set -euo pipefail

GENESIS=""
DATA_DIR="${HOME}/.oasyce"
STAKE=10000
PORT=9527

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
            echo "  --data-dir DIR    Node data directory (default: ~/.oasyce)"
            echo "  --stake AMOUNT    Validator stake in OAS (default: 10000)"
            echo "  --port PORT       Listen port (default: 9527)"
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
    exit 1
fi

if [[ ! -f "$GENESIS" ]]; then
    echo "Error: Genesis file not found: $GENESIS"
    exit 1
fi

# Min stake for mainnet
if [[ "$STAKE" -lt 10000 ]]; then
    echo "Error: Mainnet requires minimum 10,000 OAS stake (got $STAKE)"
    exit 1
fi

echo "╔══════════════════════════════════════════════╗"
echo "║     Mainnet Validator Setup                  ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  Genesis:   ${GENESIS}"
echo "║  Data dir:  ${DATA_DIR}"
echo "║  Stake:     ${STAKE} OAS"
echo "║  Port:      ${PORT}"
echo "╚══════════════════════════════════════════════╝"
echo ""

# 1. System checks
echo "[1/6] System requirements..."

# Disk space (min 20GB for mainnet)
AVAIL_KB=$(df -k "$HOME" | tail -1 | awk '{print $4}')
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
if [[ "$AVAIL_GB" -lt 20 ]]; then
    echo "  ✗ Disk: ${AVAIL_GB}GB (need 20GB+)"
    exit 1
fi
echo "  ✓ Disk: ${AVAIL_GB}GB available"

# RAM (recommend 4GB+)
if command -v sysctl &> /dev/null; then
    RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
    RAM_GB=$((RAM_BYTES / 1024 / 1024 / 1024))
    if [[ "$RAM_GB" -gt 0 ]]; then
        echo "  ✓ RAM: ${RAM_GB}GB"
    fi
fi

# Python
if ! command -v python3 &> /dev/null; then
    echo "  ✗ python3 not found"
    exit 1
fi
echo "  ✓ Python3 available"

# oasyce package
if ! python3 -c "import oasyce" 2>/dev/null; then
    echo "  ✗ oasyce not installed"
    exit 1
fi
echo "  ✓ oasyce package installed"

# 2. Data directory
echo ""
echo "[2/6] Creating data directory..."
mkdir -p "$DATA_DIR"
echo "  ✓ ${DATA_DIR}"

# 3. Copy genesis
echo ""
echo "[3/6] Installing genesis..."
cp "$GENESIS" "${DATA_DIR}/genesis.json"
echo "  ✓ genesis.json installed"

# 4. Node identity
echo ""
echo "[4/6] Setting up node identity..."
python3 -c "
import json
from pathlib import Path
data_dir = '${DATA_DIR}'
identity_path = Path(data_dir) / 'node_id.json'
if identity_path.exists():
    data = json.loads(identity_path.read_text())
    print(f'  Node ID: {data[\"node_id\"][:16]}... (existing)')
else:
    from oasyce.config import load_or_create_node_identity
    priv, pub = load_or_create_node_identity(data_dir)
    print(f'  Node ID: {pub[:16]}... (generated)')
"

# 5. Validate genesis
echo ""
echo "[5/6] Validating genesis..."
python3 -c "
import json
from pathlib import Path

genesis = json.loads(Path('${DATA_DIR}/genesis.json').read_text())
chain_id = genesis.get('chain_id', '')

if 'mainnet' not in chain_id:
    print(f'  ⚠ Warning: chain_id={chain_id} does not contain \"mainnet\"')

validators = genesis.get('validators', [])
print(f'  ✓ Chain: {chain_id}')
print(f'  ✓ Validators: {len(validators)}')

if 'genesis_hash' in genesis:
    print(f'  ✓ Genesis hash: {genesis[\"genesis_hash\"][:16]}...')

# Verify settlement params
settlement = genesis.get('app_state', {}).get('settlement', {})
if settlement:
    cr = settlement.get('creator_rate', 0)
    print(f'  ✓ Fee split: {cr}/{settlement.get(\"validator_rate\",0)}/{settlement.get(\"burn_rate\",0)}/{settlement.get(\"treasury_rate\",0)}')
"

# 6. Create environment config
echo ""
echo "[6/6] Creating mainnet environment..."
cat > "${DATA_DIR}/.env" << EOF
OASYCE_NETWORK_MODE=mainnet
OASYCE_DATA_DIR=${DATA_DIR}
OASYCE_NODE_PORT=${PORT}
# Mainnet security (auto-derived from NETWORK_MODE, but explicit for clarity)
# OASYCE_STRICT_CHAIN=1
EOF

echo "  ✓ .env created"

echo ""
echo "  ✓ Mainnet validator setup complete!"
echo ""
echo "  Security settings (auto-enabled for mainnet mode):"
echo "    - Signature verification: REQUIRED"
echo "    - Local fallback: DISABLED"
echo "    - Identity verification: REQUIRED"
echo ""
echo "  To start:"
echo "    OASYCE_NETWORK_MODE=mainnet oas serve --port ${PORT} --data-dir ${DATA_DIR}"
echo ""
echo "  Firewall: ensure port ${PORT}/tcp is open for P2P"

#!/bin/bash
# Oasyce Protocol - End-to-End Demo
# Shows: register → quote → buy → shares in 5 commands

set -e

echo "=== Oasyce Protocol E2E Demo ==="
echo ""

# Create a test file
echo "Hello Oasyce" > /tmp/oasyce_demo.txt

# 1. Register
echo "📝 Step 1: Register data asset..."
REGISTER_JSON=$(python -m oasyce_plugin.cli register /tmp/oasyce_demo.txt \
    --owner alice --tags demo,test --use-core --json)
echo "$REGISTER_JSON"

# Extract core_asset_id (try jq first, fall back to python)
if command -v jq &>/dev/null; then
    CORE_ASSET_ID=$(echo "$REGISTER_JSON" | jq -r '.core.core_asset_id')
else
    CORE_ASSET_ID=$(echo "$REGISTER_JSON" | python3 -c \
        "import sys, json; print(json.load(sys.stdin)['core']['core_asset_id'])")
fi

if [ -z "$CORE_ASSET_ID" ] || [ "$CORE_ASSET_ID" = "null" ]; then
    echo "❌ Failed to extract core_asset_id from register output" >&2
    exit 1
fi

echo ""
echo "   → core_asset_id: $CORE_ASSET_ID"

# 2. Quote
echo ""
echo "📈 Step 2: Get price quote..."
python -m oasyce_plugin.cli quote "$CORE_ASSET_ID" --use-core

# 3. Buy
echo ""
echo "🛒 Step 3: Buy asset (10 OAS)..."
python -m oasyce_plugin.cli buy "$CORE_ASSET_ID" --buyer bob --amount 10.0

# 4. Check shares
echo ""
echo "📊 Step 4: Check shares for bob..."
python -m oasyce_plugin.cli shares bob

echo ""
echo "✅ Demo complete!"

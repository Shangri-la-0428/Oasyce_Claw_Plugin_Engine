#!/usr/bin/env python3
"""
Oasyce Claw Plugin Engine - CLI

Command-line interface for data asset registration, search, and pricing.
"""

import argparse
import json
import sys
from pathlib import Path

from oasyce_plugin.config import Config
from oasyce_plugin.skills.agent_skills import OasyceSkills


def cmd_register(args):
    """Register a file as an Oasyce asset."""
    config = Config.from_env(
        owner=args.owner,
        tags=args.tags,
        signing_key=args.signing_key,
        signing_key_id=args.signing_key_id,
    )
    skills = OasyceSkills(config)

    try:
        file_info = skills.scan_data_skill(args.file)
        metadata = skills.generate_metadata_skill(file_info, config.tags, config.owner)
        signed = skills.create_certificate_skill(metadata)
        result = skills.register_data_asset_skill(signed)

        # If --use-core, also submit to oasyce_core
        core_result = None
        if getattr(args, "use_core", False):
            from oasyce_plugin.bridge.core_bridge import bridge_register
            core_result = bridge_register(signed, creator=config.owner)

        if args.json:
            out = dict(signed)
            if core_result:
                out["core"] = core_result
            print(json.dumps(out, indent=2))
        else:
            print(f"✅ Asset registered: {signed['asset_id']}")
            print(f"   Owner: {signed['owner']}")
            print(f"   File: {signed['filename']}")
            print(f"   Tags: {', '.join(signed['tags'])}")
            print(f"   Vault: {result['vault_path']}")
            if core_result:
                print(f"   Core Valid: {core_result['valid']}")
                print(f"   Core Asset ID: {core_result['core_asset_id']}")
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_search(args):
    """Search assets by tag."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    
    try:
        assets = skills.search_data_skill(args.tag)
        if args.json:
            print(json.dumps(assets, indent=2))
        else:
            if not assets:
                print(f"No assets found with tag: {args.tag}")
                return
            print(f"Found {len(assets)} asset(s) with tag '{args.tag}':")
            for asset in assets:
                print(f"  - {asset['asset_id']}: {asset['filename']} ({asset['owner']})")
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_quote(args):
    """Get L2 pricing quote for an asset."""
    if getattr(args, "use_core", False):
        from oasyce_plugin.bridge.core_bridge import bridge_quote
        result = bridge_quote(args.asset_id)
        if "error" in result:
            print(f"❌ {result['error']}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"📈 Bancor Quote for {args.asset_id}:")
            print(f"   Price:   {result['price_oas']:.6f} OAS/share")
            print(f"   Supply:  {result['supply']}")
            print(f"   Reserve: {result.get('reserve', 'N/A'):.2f} OAS")
            print(f"   CW:      {result.get('cw', 'N/A'):.2f} (connector weight)")
        return

    config = Config.from_env()
    skills = OasyceSkills(config)

    try:
        quote = skills.trade_data_skill(args.asset_id)
        if args.json:
            print(json.dumps(quote, indent=2))
        else:
            print(f"📈 Quote for {args.asset_id}:")
            print(f"   Current Price: {quote.get('current_price_oas', 'N/A')} OAS")
            print(f"   Price Impact: {quote.get('price_impact', 0):.2%}")
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_buy(args):
    """Buy an asset via oasyce_core (requires --use-core)."""
    from oasyce_plugin.bridge.core_bridge import bridge_buy

    result = bridge_buy(args.asset_id, buyer=args.buyer, amount=args.amount)
    if "error" in result:
        print(f"❌ {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        tokens = result.get("tokens_received", 0)
        print(f"🛒 Buy {args.asset_id}:")
        print(f"   Buyer:         {result['buyer']}")
        print(f"   Spent:         {args.amount} OAS")
        print(f"   Price:         {result['price_oas']:.6f} OAS/share")
        print(f"   Shares recv'd: {tokens:.6f}")
        print(f"   New supply:    {result.get('supply', 'N/A')}")
        print(f"   TX:            {result['tx_id']}")
        if "split" in result:
            s = result["split"]
            print(f"   Tax burned:    {s['protocol_burn']:.4f} OAS")
            print(f"   Tax validator: {s['protocol_validator']:.4f} OAS")
            print(f"   Creator cut:   {s['creator']:.4f} OAS")
            print(f"   Router cut:    {s['router']:.4f} OAS")


def cmd_stake(args):
    """Stake OAS for a validator via oasyce_core."""
    from oasyce_plugin.bridge.core_bridge import bridge_stake

    total = bridge_stake(args.validator_id, args.amount)
    if args.json:
        print(json.dumps({"validator_id": args.validator_id, "amount": args.amount, "total_staked": total}, indent=2))
    else:
        print(f"🔒 Staked {args.amount} OAS for validator '{args.validator_id}'")
        print(f"   Total staked: {total} OAS")


def cmd_shares(args):
    """Show share holdings for an owner via oasyce_core."""
    from oasyce_plugin.bridge.core_bridge import bridge_get_shares

    holdings = bridge_get_shares(args.owner)
    if args.json:
        serialized = [
            {"asset_id": h.asset_id, "shares": h.shares, "acquired_price": h.acquired_price}
            for h in holdings
        ]
        print(json.dumps(serialized, indent=2))
    else:
        if not holdings:
            print(f"No shares found for '{args.owner}'")
            return
        print(f"📊 Shares for '{args.owner}':")
        for h in holdings:
            print(f"   Asset: {h.asset_id}")
            print(f"     Shares: {h.shares:.6f}  |  Avg price: {h.acquired_price:.6f} OAS/share")


def cmd_demo(args):
    """Run a full end-to-end demo of the Oasyce protocol pipeline."""
    import hashlib
    import os
    import tempfile
    import time

    from oasyce_plugin.bridge.core_bridge import (
        bridge_buy,
        bridge_get_shares,
        bridge_quote,
        bridge_register,
    )

    steps = {}

    def _banner(n, total, text):
        if not args.json:
            print(f"\nStep {n}/{total} — {text}")

    # ── Step 1: create temp file ──────────────────────────────────────
    _banner(1, 5, "Creating temporary asset file...")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Oasyce demo data payload — genesis capture\n")
        temp_path = f.name

    try:
        file_hash = hashlib.sha256(open(temp_path, "rb").read()).hexdigest()
        steps["file"] = {"path": temp_path, "hash": file_hash}
        if not args.json:
            print(f"   📄 File:  {temp_path}")
            print(f"   🔑 Hash:  {file_hash[:16]}...")

        # ── Step 2: register ──────────────────────────────────────────
        _banner(2, 5, "Registering asset in oasyce_core...")
        signed_metadata = {
            "asset_id": f"OAS_DEMO_{file_hash[:8].upper()}",
            "filename": os.path.basename(temp_path),
            "owner": "demo_user",
            "tags": ["Demo", "Genesis"],
            "timestamp": int(time.time()),
            "file_hash": file_hash,
            "popc_signature": file_hash[:16],  # must be pure hex for MockVerifier
        }
        reg = bridge_register(signed_metadata, creator="demo_user")
        steps["register"] = reg
        if not args.json:
            status = "✅" if reg["valid"] else "❌"
            print(f"   {status} Valid: {reg['valid']}")
            print(f"   🆔 Core Asset ID: {reg['core_asset_id']}")
        if not reg["valid"]:
            if not args.json:
                print("❌ Registration failed — aborting demo.")
            else:
                print(json.dumps(steps, indent=2))
            return

        asset_id = reg["core_asset_id"]

        # ── Step 3: initial quote ─────────────────────────────────────
        _banner(3, 5, "Getting initial Bancor price quote...")
        quote_before = bridge_quote(asset_id)
        steps["quote_initial"] = quote_before
        if not args.json:
            print(f"   💰 Price:   {quote_before['price_oas']:.6f} OAS/share")
            print(f"   📊 Supply:  {quote_before['supply']}")
            print(f"   🏦 Reserve: {quote_before.get('reserve', 0):.2f} OAS")
            print(f"   🔗 CW:      {quote_before.get('cw', 0.5):.2f}")

        # ── Step 4: buy ───────────────────────────────────────────────
        _banner(4, 5, "Buying shares (10.0 OAS)...")
        buy = bridge_buy(asset_id, buyer="demo_user", amount=10.0)
        steps["buy"] = buy
        if not args.json:
            if "error" in buy:
                print(f"   ❌ {buy['error']}")
            else:
                tokens = buy.get("tokens_received", 0)
                print(f"   🛒 Spent:          10.0 OAS")
                print(f"   🪙 Shares recv'd:  {tokens:.6f}")
                print(f"   📈 Price paid:     {buy['price_oas']:.6f} OAS/share")
                if "split" in buy:
                    s = buy["split"]
                    print(f"   🔥 Burned:         {s['protocol_burn']:.4f} OAS")
                    print(f"   🏛️  Validator fee:  {s['protocol_validator']:.4f} OAS")
                    print(f"   👤 Creator cut:    {s['creator']:.4f} OAS")
                    print(f"   🔀 Router cut:     {s['router']:.4f} OAS")

        # ── Step 5: final state ───────────────────────────────────────
        _banner(5, 5, "Checking final state...")
        quote_after = bridge_quote(asset_id)
        steps["quote_final"] = quote_after

        holdings = bridge_get_shares("demo_user")
        steps["shares"] = [
            {"asset_id": h.asset_id, "shares": h.shares, "acquired_price": h.acquired_price}
            for h in holdings
        ]

        if not args.json:
            p_before = quote_before["price_oas"]
            p_after = quote_after["price_oas"]
            print(f"   📊 New supply:  {quote_after['supply']}")
            print(f"   💹 Price delta: {p_before:.6f} → {p_after:.6f} OAS (+{p_after - p_before:.6f})")
            if holdings:
                for h in holdings:
                    print(f"   🏦 Holdings:    {h.shares:.6f} shares of {h.asset_id}")
                    print(f"                   avg price {h.acquired_price:.6f} OAS/share")
            print()
            print("=" * 40)
            print("✅ Demo complete! Pipeline: register → quote → buy → shares")

        if args.json:
            print(json.dumps(steps, indent=2))

    finally:
        os.unlink(temp_path)


def cmd_demo_network(args):
    """Run multi-node network demo."""
    from oasyce_plugin.scripts.demo_network import main as demo_main
    demo_main(num_nodes=args.nodes)


def cmd_node_start(args):
    """Start the Oasyce P2P node."""
    import asyncio
    from oasyce_plugin.network.node import OasyceNode
    from oasyce_plugin.storage.ledger import Ledger

    config = Config.from_env()
    port = args.port or config.node_port
    host = config.node_host
    ledger = Ledger(config.db_path)
    node_id = (config.public_key or "unknown")[:16]

    node = OasyceNode(host=host, port=port, node_id=node_id, ledger=ledger)

    async def _run():
        await node.start()
        print(f"Oasyce node {node_id} listening on {host}:{port}")
        print("Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await node.stop()
            print("\nNode stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


def cmd_node_info(args):
    """Show node information."""
    config = Config.from_env()
    from oasyce_plugin.storage.ledger import Ledger

    ledger = Ledger(config.db_path)
    node_id = (config.public_key or "unknown")[:16]
    height = ledger.get_chain_height()

    info = {
        "node_id": node_id,
        "host": config.node_host,
        "port": config.node_port,
        "chain_height": height,
    }
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"Node ID:      {node_id}")
        print(f"Listen:       {config.node_host}:{config.node_port}")
        print(f"Chain height: {height}")


def cmd_node_ping(args):
    """Ping another Oasyce node."""
    import asyncio
    from oasyce_plugin.network.node import OasyceNode

    parts = args.target.split(":")
    host = parts[0]
    port = int(parts[1]) if len(parts) > 1 else 9527

    config = Config.from_env()
    node_id = (config.public_key or "unknown")[:16]
    node = OasyceNode(node_id=node_id)

    async def _ping():
        return await node.connect_to_peer(host, port)

    try:
        resp = asyncio.run(_ping())
        if args.json:
            print(json.dumps(resp, indent=2))
        else:
            print(f"Pong from {resp.get('node_id', '?')}")
            print(f"  Chain height: {resp.get('height', '?')}")
    except (ConnectionRefusedError, OSError) as e:
        print(f"Failed to connect to {host}:{port}: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_fingerprint_embed(args):
    """Embed a distribution fingerprint into a file."""
    import time

    from oasyce_plugin.crypto.keys import load_or_create_keypair
    from oasyce_plugin.fingerprint.engine import FingerprintEngine
    from oasyce_plugin.fingerprint.registry import FingerprintRegistry
    from oasyce_plugin.storage.ledger import Ledger

    config = Config.from_env()
    priv_hex, _ = load_or_create_keypair()
    engine = FingerprintEngine(priv_hex)
    ledger = Ledger(config.db_path)
    registry = FingerprintRegistry(ledger)

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    ts = int(time.time())
    asset_id = file_path.stem
    fp = engine.generate_fingerprint(asset_id, args.caller, ts)

    # Detect binary vs text
    raw = file_path.read_bytes()
    try:
        text = raw.decode("utf-8")
        is_text = True
    except UnicodeDecodeError:
        is_text = False

    if is_text:
        watermarked = engine.embed_text(text, fp).encode("utf-8")
    else:
        watermarked = engine.embed_binary(raw, fp)

    out_path = Path(args.output) if args.output else file_path
    out_path.write_bytes(watermarked)

    registry.record_distribution(asset_id, args.caller, fp, ts)
    ledger.close()

    if args.json:
        print(json.dumps({"fingerprint": fp, "asset_id": asset_id,
                          "caller_id": args.caller, "output": str(out_path)}))
    else:
        print(f"Fingerprint embedded: {fp[:16]}...")
        print(f"  Caller:  {args.caller}")
        print(f"  Output:  {out_path}")


def cmd_fingerprint_extract(args):
    """Extract a fingerprint from a watermarked file."""
    from oasyce_plugin.fingerprint.engine import FingerprintEngine

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    raw = file_path.read_bytes()
    # Try binary first (faster check), then text
    fp = FingerprintEngine.extract_binary(raw)
    if fp is None:
        try:
            text = raw.decode("utf-8")
            fp = FingerprintEngine.extract_text(text)
        except UnicodeDecodeError:
            pass

    if fp is None:
        if args.json:
            print(json.dumps({"fingerprint": None}))
        else:
            print("No fingerprint found.")
        sys.exit(1)

    if args.json:
        print(json.dumps({"fingerprint": fp}))
    else:
        print(f"Fingerprint: {fp}")


def cmd_fingerprint_trace(args):
    """Trace a fingerprint to its distribution record."""
    from oasyce_plugin.fingerprint.registry import FingerprintRegistry
    from oasyce_plugin.storage.ledger import Ledger

    config = Config.from_env()
    ledger = Ledger(config.db_path)
    registry = FingerprintRegistry(ledger)

    record = registry.trace_fingerprint(args.fingerprint)
    ledger.close()

    if record is None:
        if args.json:
            print(json.dumps({"found": False}))
        else:
            print("Fingerprint not found in registry.")
        sys.exit(1)

    if args.json:
        print(json.dumps(record, default=str))
    else:
        print(f"Fingerprint: {record['fingerprint']}")
        print(f"  Caller:   {record['caller_id']}")
        print(f"  Asset:    {record['asset_id']}")
        print(f"  Time:     {record['timestamp']}")


def cmd_fingerprint_list(args):
    """List all fingerprint distributions for an asset."""
    from oasyce_plugin.fingerprint.registry import FingerprintRegistry
    from oasyce_plugin.storage.ledger import Ledger

    config = Config.from_env()
    ledger = Ledger(config.db_path)
    registry = FingerprintRegistry(ledger)

    records = registry.get_distributions(args.asset_id)
    ledger.close()

    if args.json:
        print(json.dumps(records, default=str))
    else:
        if not records:
            print(f"No distributions for asset: {args.asset_id}")
            return
        print(f"Distributions for {args.asset_id} ({len(records)}):")
        for r in records:
            print(f"  {r['fingerprint'][:16]}... -> {r['caller_id']} @ {r['timestamp']}")


def cmd_verify(args):
    """Verify a PoPC certificate."""
    from oasyce_plugin.engines.core_engines import CertificateEngine
    import json
    
    config = Config.from_env(signing_key=args.signing_key)
    if not config.signing_key:
        print("❌ Error: Signing key required for verification", file=sys.stderr)
        sys.exit(1)
    
    try:
        # Load metadata from file or vault
        if Path(args.asset).exists():
            with open(args.asset, 'r') as f:
                metadata = json.load(f)
        else:
            # Try to load from vault
            vault_path = Path(config.vault_dir) / f"{args.asset}.json"
            if vault_path.exists():
                with open(vault_path, 'r') as f:
                    metadata = json.load(f)
            else:
                print(f"❌ Error: Asset not found: {args.asset}", file=sys.stderr)
                sys.exit(1)
        
        result = CertificateEngine.verify_popc_certificate(metadata, config.public_key)
        if result.ok:
            print(f"✅ Certificate valid: {metadata.get('asset_id', 'UNKNOWN')}")
        else:
            print(f"❌ Certificate invalid: {result.error}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="oasyce",
        description="Oasyce Claw Plugin Engine - Data Asset Management CLI"
    )
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument("--use-core", action="store_true",
                        help="Route through oasyce_core engine")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Register command
    reg_parser = subparsers.add_parser("register", help="Register a file as an asset")
    reg_parser.add_argument("file", help="Path to the file to register")
    reg_parser.add_argument("--owner", default="Shangrila", help="Asset owner")
    reg_parser.add_argument("--tags", default="Core,Genesis", help="Comma-separated tags")
    reg_parser.add_argument("--signing-key", help="Signing key (or OASYCE_SIGNING_KEY env)")
    reg_parser.add_argument("--signing-key-id", help="Signing key ID")
    reg_parser.set_defaults(func=cmd_register)
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search assets by tag")
    search_parser.add_argument("tag", help="Tag to search for")
    search_parser.set_defaults(func=cmd_search)
    
    # Quote command
    quote_parser = subparsers.add_parser("quote", help="Get L2 pricing quote")
    quote_parser.add_argument("asset_id", help="Asset ID (e.g., OAS_6596A36F)")
    quote_parser.set_defaults(func=cmd_quote)
    
    # Buy command (requires oasyce_core)
    buy_parser = subparsers.add_parser("buy", help="Buy asset via oasyce_core")
    buy_parser.add_argument("asset_id", help="Core asset ID")
    buy_parser.add_argument("--buyer", default="anonymous", help="Buyer identity")
    buy_parser.add_argument("--amount", type=float, default=10.0, help="OAS to spend (default 10.0)")
    buy_parser.set_defaults(func=cmd_buy)

    # Stake command
    stake_parser = subparsers.add_parser("stake", help="Stake OAS for a validator")
    stake_parser.add_argument("validator_id", help="Validator identity")
    stake_parser.add_argument("amount", type=float, help="OAS amount to stake")
    stake_parser.set_defaults(func=cmd_stake)

    # Shares command
    shares_parser = subparsers.add_parser("shares", help="Show share holdings for an owner")
    shares_parser.add_argument("owner", help="Owner identity")
    shares_parser.set_defaults(func=cmd_shares)

    # Demo command
    demo_parser = subparsers.add_parser(
        "demo", help="Run full end-to-end protocol demo (register→quote→buy→shares)"
    )
    demo_parser.set_defaults(func=cmd_demo)

    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify PoPC certificate")
    verify_parser.add_argument("asset", help="Asset ID or path to JSON file")
    verify_parser.add_argument("--signing-key", help="Signing key for verification")
    verify_parser.set_defaults(func=cmd_verify)

    # Node command group
    node_parser = subparsers.add_parser("node", help="P2P node management")
    node_sub = node_parser.add_subparsers(dest="node_command", help="Node sub-commands")

    node_start_parser = node_sub.add_parser("start", help="Start the P2P node")
    node_start_parser.add_argument("--port", type=int, default=None, help="Listen port (default 9527)")
    node_start_parser.set_defaults(func=cmd_node_start)

    node_info_parser = node_sub.add_parser("info", help="Show node information")
    node_info_parser.set_defaults(func=cmd_node_info)

    node_ping_parser = node_sub.add_parser("ping", help="Ping another node")
    node_ping_parser.add_argument("target", help="Target node (host:port)")
    node_ping_parser.set_defaults(func=cmd_node_ping)

    # Fingerprint command group
    fp_parser = subparsers.add_parser("fingerprint", help="Fingerprint watermarking")
    fp_sub = fp_parser.add_subparsers(dest="fp_command", help="Fingerprint sub-commands")

    fp_embed_parser = fp_sub.add_parser("embed", help="Embed watermark into a file")
    fp_embed_parser.add_argument("file", help="Path to file to watermark")
    fp_embed_parser.add_argument("--caller", required=True, help="Caller / recipient ID")
    fp_embed_parser.add_argument("--output", default=None, help="Output path (default: overwrite)")
    fp_embed_parser.set_defaults(func=cmd_fingerprint_embed)

    fp_extract_parser = fp_sub.add_parser("extract", help="Extract watermark from file")
    fp_extract_parser.add_argument("file", help="Path to watermarked file")
    fp_extract_parser.set_defaults(func=cmd_fingerprint_extract)

    fp_trace_parser = fp_sub.add_parser("trace", help="Trace a fingerprint")
    fp_trace_parser.add_argument("fingerprint", help="Fingerprint hex string")
    fp_trace_parser.set_defaults(func=cmd_fingerprint_trace)

    fp_list_parser = fp_sub.add_parser("list", help="List distributions for an asset")
    fp_list_parser.add_argument("asset_id", help="Asset ID")
    fp_list_parser.set_defaults(func=cmd_fingerprint_list)

    # GUI command
    gui_parser = subparsers.add_parser("gui", help="Launch web dashboard (port 8420)")
    gui_parser.add_argument("--port", type=int, default=8420, help="Port (default: 8420)")
    gui_parser.set_defaults(func=lambda args: __import__('oasyce_plugin.gui.app', fromlist=['OasyceGUI']).OasyceGUI(port=args.port).run())

    # ── demo-network ─────────────────────────────────────────────────
    demo_net_parser = subparsers.add_parser(
        "demo-network",
        help="Spin up N local nodes, register assets, mine, sync, verify consensus",
    )
    demo_net_parser.add_argument("--nodes", type=int, default=3, help="Number of nodes (default: 3)")
    demo_net_parser.set_defaults(func=cmd_demo_network)

    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "node" and getattr(args, "node_command", None) is None:
        node_parser.print_help()
        sys.exit(0)

    if args.command == "fingerprint" and getattr(args, "fp_command", None) is None:
        fp_parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()

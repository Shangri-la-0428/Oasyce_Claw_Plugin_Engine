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
            print(f"📈 Quote for {args.asset_id} (core):")
            print(f"   Price: {result['price_oas']} OAS")
            print(f"   Supply: {result['supply']}")
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

    result = bridge_buy(args.asset_id, buyer=args.buyer)
    if "error" in result:
        print(f"❌ {result['error']}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"🛒 Buy {args.asset_id}:")
        print(f"   Buyer: {result['buyer']}")
        print(f"   Price: {result['price_oas']} OAS")
        print(f"   Settled: {result['settled']}")
        print(f"   TX: {result['tx_id']}")
        if "split" in result:
            s = result["split"]
            print(f"   Split → creator={s['creator']:.4f} router={s['router']:.4f}")


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
        
        result = CertificateEngine.verify_popc_certificate(metadata, config.signing_key)
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
    buy_parser.set_defaults(func=cmd_buy)

    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify PoPC certificate")
    verify_parser.add_argument("asset", help="Asset ID or path to JSON file")
    verify_parser.add_argument("--signing-key", help="Signing key for verification")
    verify_parser.set_defaults(func=cmd_verify)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        sys.exit(0)
    
    args.func(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Oasyce Claw Plugin Engine - CLI

Command-line interface for data asset registration, search, and pricing.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from oasyce_plugin.config import Config
from oasyce_plugin.skills.agent_skills import OasyceSkills


def cmd_info(args):
    """Show comprehensive project information."""
    from oasyce_plugin.info import get_info, LINKS

    use_json = getattr(args, "json", False)

    if use_json:
        print(json.dumps(get_info("en"), indent=2, ensure_ascii=False))
        return

    info = get_info("en")
    print(f"\n  {info['project']} v{info['version']}")
    print(f"  {info['tagline']}")
    print(f"  License: {info['license']}\n")

    section = getattr(args, "section", None)

    if section is None or section == "links":
        print("  Links:")
        print(f"    Homepage         {LINKS['homepage']}")
        print(f"    GitHub (Project) {LINKS['github_project']}")
        print(f"    GitHub (Engine)  {LINKS['github_engine']}")
        print(f"    Whitepaper       {LINKS['whitepaper']}")
        print(f"    Discord          {LINKS['discord']}")
        print(f"    Email            {LINKS['email']}")
        print()

    if section == "quickstart":
        print("  Quick Start:")
        for line in info["quick_start"].split("\n"):
            print(f"    {line}")
        print()

    if section == "architecture":
        print("  Architecture:")
        for line in info["architecture"].split("\n"):
            print(f"    {line}")
        print()

    if section == "economics":
        print("  Economics:")
        for line in info["economics"].split("\n"):
            print(f"    {line}")
        print()

    if section == "update":
        print("  Maintenance & Update:")
        for line in info["update_guide"].split("\n"):
            print(f"    {line}")
        print()

    if section is None:
        print("  Asset types: data, capability, oracle, identity")
        print(f"  Schema version: {info['schema_version']}")
        print()
        print("  For details: oasyce info --section <quickstart|architecture|economics|update|links>")
        print()


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
        # Parse co-creators if provided
        co_creators = None
        if getattr(args, "co_creators", None):
            co_creators = json.loads(args.co_creators)

        file_info = skills.scan_data_skill(args.file)
        metadata = skills.generate_metadata_skill(
            file_info, config.tags, config.owner,
            rights_type=getattr(args, "rights_type", "original"),
            co_creators=co_creators,
        )
        signed = skills.create_certificate_skill(metadata)
        result = skills.register_data_asset_skill(signed)

        # If --free, mark as free asset (attribution only)
        price_model = "free" if getattr(args, "free", False) else "bonding_curve"

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
            print(f"   Rights: {signed.get('rights_type', 'original')}")
            if signed.get('co_creators'):
                for c in signed['co_creators']:
                    print(f"   Co-creator: {c['address']} ({c['share']}%)")
            print(f"   Price: {'Free (attribution only)' if price_model == 'free' else 'Bonding Curve'}")
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
            quote["pricing_mode"] = "local_estimate"
            print(json.dumps(quote, indent=2))
        else:
            print(f"📈 Quote for {args.asset_id} [LOCAL ESTIMATE]:")
            print(f"   Current Price: {quote.get('current_price_oas', 'N/A')} OAS")
            print(f"   Price Impact: {quote.get('price_impact', 0):.2%}")
            print(f"   Note: Use --use-core for Bancor curve pricing.")
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_price(args):
    """Calculate dataset price with demand/scarcity/quality/freshness factors."""
    from oasyce_plugin.services.pricing import DatasetPricingCurve

    curve = DatasetPricingCurve()
    result = curve.calculate_price(
        asset_id=args.asset_id,
        base_price=args.base_price,
        query_count=args.queries,
        similar_count=args.similar,
        contribution_score=args.contribution_score,
        days_since_creation=args.days,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"💰 Price for {args.asset_id}: {result['final_price']:.6f} OAS")
        print(f"   Base price:  {result['base_price']:.6f} OAS")
        print(f"   Final price: {result['final_price']:.6f} OAS")


def cmd_price_factors(args):
    """Show detailed pricing factor breakdown."""
    from oasyce_plugin.services.pricing import DatasetPricingCurve

    curve = DatasetPricingCurve()
    result = curve.calculate_price(
        asset_id=args.asset_id,
        base_price=args.base_price,
        query_count=args.queries,
        similar_count=args.similar,
        contribution_score=args.contribution_score,
        days_since_creation=args.days,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"📊 Pricing Factors for {args.asset_id}:")
        print(f"   Base price:        {result['base_price']:.6f} OAS")
        print(f"   Demand factor:     {result['demand_factor']:.6f}  (queries={args.queries})")
        print(f"   Scarcity factor:   {result['scarcity_factor']:.6f}  (similar={args.similar})")
        print(f"   Quality factor:    {result['quality_factor']:.6f}  (score={args.contribution_score})")
        print(f"   Freshness factor:  {result['freshness_factor']:.6f}  (days={args.days})")
        print(f"   ─────────────────────────────")
        print(f"   Final price:       {result['final_price']:.6f} OAS")


def cmd_dispute(args):
    """File a dispute against an asset."""
    config = Config.from_env()
    from oasyce_plugin.storage.ledger import Ledger
    ledger = Ledger(config.db_path) if config.db_path else None
    if not ledger:
        print("❌ Ledger not available", file=sys.stderr)
        sys.exit(1)

    try:
        row = ledger._conn.execute(
            "SELECT metadata FROM assets WHERE asset_id = ?", (args.asset_id,)
        ).fetchone()
        if not row:
            print(f"❌ Asset not found: {args.asset_id}", file=sys.stderr)
            sys.exit(1)

        import time as _time
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        meta["disputed"] = True
        meta["dispute_reason"] = args.reason
        meta["dispute_time"] = int(_time.time())

        # Attempt arbitrator discovery
        arbitrators = []
        try:
            from oasyce_plugin.services.discovery import SkillDiscoveryEngine
            discovery = SkillDiscoveryEngine(get_capabilities=lambda: [])
            candidates = discovery.discover_arbitrators(
                dispute_tags=meta.get("tags", []), limit=3,
            )
            arbitrators = [
                {"capability_id": c.capability_id, "name": c.name, "score": c.final_score}
                for c in candidates
            ]
            meta["arbitrator_candidates"] = arbitrators
        except Exception:
            pass

        ledger._conn.execute(
            "UPDATE assets SET metadata = ? WHERE asset_id = ?",
            (json.dumps(meta), args.asset_id),
        )
        ledger._conn.commit()

        if args.json:
            print(json.dumps({"ok": True, "asset_id": args.asset_id,
                              "disputed": True, "arbitrators": arbitrators}, indent=2))
        else:
            print(f"⚠️  Dispute filed for {args.asset_id}")
            print(f"   Reason: {args.reason}")
            if arbitrators:
                print(f"   Arbitrator candidates: {len(arbitrators)}")
                for a in arbitrators:
                    print(f"     - {a['name'] or a['capability_id'][:12]} (score: {a['score']:.2f})")
            else:
                print(f"   No arbitrators found (will be assigned later)")
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_resolve(args):
    """Resolve a dispute with a remedy."""
    from oasyce_plugin.models import VALID_REMEDY_TYPES
    config = Config.from_env()
    from oasyce_plugin.storage.ledger import Ledger
    ledger = Ledger(config.db_path) if config.db_path else None
    if not ledger:
        print("❌ Ledger not available", file=sys.stderr)
        sys.exit(1)

    if args.remedy not in VALID_REMEDY_TYPES:
        print(f"❌ Invalid remedy. Must be one of: {', '.join(VALID_REMEDY_TYPES)}", file=sys.stderr)
        sys.exit(1)

    try:
        row = ledger._conn.execute(
            "SELECT metadata FROM assets WHERE asset_id = ?", (args.asset_id,)
        ).fetchone()
        if not row:
            print(f"❌ Asset not found: {args.asset_id}", file=sys.stderr)
            sys.exit(1)

        import time as _time
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        if not meta.get("disputed"):
            print(f"❌ Asset is not disputed", file=sys.stderr)
            sys.exit(1)

        details = json.loads(args.details) if args.details else {}
        resolution = {"remedy": args.remedy, "details": details, "resolved_at": int(_time.time())}
        meta["dispute_status"] = "resolved"
        meta["dispute_resolution"] = resolution

        if args.remedy == "delist":
            meta["delisted"] = True
        elif args.remedy == "transfer":
            new_owner = details.get("new_owner", "")
            if new_owner:
                meta["owner"] = new_owner
                ledger._conn.execute(
                    "UPDATE assets SET owner = ? WHERE asset_id = ?",
                    (new_owner, args.asset_id),
                )
        elif args.remedy == "rights_correction":
            from oasyce_plugin.models import VALID_RIGHTS_TYPES
            new_rights = details.get("new_rights_type", "collection")
            if new_rights in VALID_RIGHTS_TYPES:
                meta["rights_type"] = new_rights
        elif args.remedy == "share_adjustment":
            new_co_creators = details.get("co_creators")
            if new_co_creators:
                meta["co_creators"] = new_co_creators

        ledger._conn.execute(
            "UPDATE assets SET metadata = ? WHERE asset_id = ?",
            (json.dumps(meta), args.asset_id),
        )
        ledger._conn.commit()

        if args.json:
            print(json.dumps({"ok": True, "asset_id": args.asset_id, "remedy": args.remedy, "resolution": resolution}, indent=2))
        else:
            print(f"✅ Dispute resolved: {args.asset_id}")
            print(f"   Remedy: {args.remedy}")
            if details:
                print(f"   Details: {json.dumps(details)}")
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_discover(args):
    """Discover capabilities/skills using four-layer search."""
    from oasyce_plugin.services.discovery import SkillDiscoveryEngine

    def _list_capabilities():
        try:
            from oasyce_core.capabilities.registry import CapabilityRegistry
            reg = CapabilityRegistry()
            return [
                {
                    "capability_id": m.capability_id,
                    "name": m.name,
                    "provider": m.provider,
                    "tags": m.tags,
                    "intents": m.tags,
                    "semantic_vector": m.semantic_vector,
                    "base_price": m.pricing.base_price if m.pricing else 1.0,
                }
                for m in reg.list_all()
            ]
        except Exception:
            return []

    discovery = SkillDiscoveryEngine(get_capabilities=_list_capabilities)

    intents = args.intents.split(",") if args.intents else None
    tags = args.tags.split(",") if args.tags else None

    candidates = discovery.discover(intents=intents, query_tags=tags, limit=args.limit)

    if args.json:
        print(json.dumps([
            {
                "capability_id": c.capability_id, "name": c.name,
                "provider": c.provider, "tags": c.tags,
                "final_score": c.final_score,
                "intent_score": c.intent_score,
                "trust_score": c.trust_score,
                "economic_score": c.economic_score,
                "base_price": c.base_price,
            }
            for c in candidates
        ], indent=2))
    else:
        if not candidates:
            print("No capabilities found.")
            return
        print(f"Found {len(candidates)} capability(ies):")
        for c in candidates:
            print(f"  {c.name or c.capability_id[:16]}")
            print(f"    Score: {c.final_score:.4f}  (intent={c.intent_score:.2f} trust={c.trust_score:.2f} econ={c.economic_score:.2f})")
            print(f"    Price: {c.base_price:.4f} OAS  Tags: {', '.join(c.tags)}")


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
    """Start the Oasyce P2P node with persistent identity."""
    import asyncio
    from oasyce_plugin.config import load_or_create_node_identity
    from oasyce_plugin.network.node import OasyceNode
    from oasyce_plugin.storage.ledger import Ledger

    config = Config.from_env()
    port = args.port or config.node_port
    host = config.node_host
    ledger = Ledger(config.db_path)

    # Use persistent node identity
    _priv, node_id = load_or_create_node_identity(config.data_dir)
    node_id_short = node_id[:16]

    node = OasyceNode(
        host=host, port=port, node_id=node_id_short,
        ledger=ledger, data_dir=config.data_dir,
    )

    async def _run():
        await node.start(bootstrap=True)
        print(f"Oasyce node {node_id_short} listening on {host}:{port}")
        if node.peers:
            print(f"  Known peers: {len(node.peers)}")
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
    from oasyce_plugin.config import load_or_create_node_identity
    from oasyce_plugin.storage.ledger import Ledger

    config = Config.from_env()
    ledger = Ledger(config.db_path)
    _priv, node_id = load_or_create_node_identity(config.data_dir)
    node_id_short = node_id[:16]
    height = ledger.get_chain_height()

    # Load saved peers count
    from pathlib import Path
    peers_path = Path(config.data_dir) / "peers.json"
    peers_count = 0
    if peers_path.exists():
        try:
            peers_count = len(json.loads(peers_path.read_text()))
        except Exception:
            pass

    info = {
        "node_id": node_id_short,
        "node_id_full": node_id,
        "host": config.node_host,
        "port": config.node_port,
        "chain_height": height,
        "known_peers": peers_count,
    }
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"Node ID:      {node_id_short}")
        print(f"Full ID:      {node_id}")
        print(f"Listen:       {config.node_host}:{config.node_port}")
        print(f"Chain height: {height}")
        print(f"Known peers:  {peers_count}")


def cmd_node_reset_identity(args):
    """Force-reset node identity."""
    from oasyce_plugin.config import reset_node_identity

    config = Config.from_env()
    _priv, new_id = reset_node_identity(config.data_dir)
    print(f"Node identity reset.")
    print(f"  New Node ID: {new_id[:16]}")
    print(f"  Full ID:     {new_id}")


def cmd_node_peers(args):
    """Show known peer list."""
    from pathlib import Path

    config = Config.from_env()
    peers_path = Path(config.data_dir) / "peers.json"

    if not peers_path.exists():
        print("No known peers.")
        return

    try:
        peers = json.loads(peers_path.read_text())
    except (json.JSONDecodeError, OSError):
        print("No known peers.")
        return

    if not peers:
        print("No known peers.")
        return

    if args.json:
        print(json.dumps(peers, indent=2))
    else:
        print(f"Known peers ({len(peers)}):")
        for p in peers:
            print(f"  {p.get('node_id', '?')[:16]}  {p['host']}:{p['port']}")


def cmd_node_become_validator(args):
    """Register this node as a validator by staking OAS."""
    from oasyce_plugin.config import load_or_create_node_identity, load_node_role, save_node_role, get_economics

    config = Config.from_env()
    priv_key, node_id = load_or_create_node_identity(config.data_dir)
    node_id_short = node_id[:16]

    from oasyce_plugin.consensus.core.types import from_units
    economics = get_economics()
    min_stake = economics["min_stake"]
    amount_oas = args.amount or from_units(min_stake)

    if amount_oas < from_units(min_stake):
        print(f"Minimum stake is {from_units(min_stake):.0f} OAS")
        return
    amount = amount_oas  # bridge_stake uses OAS float

    try:
        from oasyce_plugin.bridge.core_bridge import bridge_stake
        total = bridge_stake(node_id_short, amount)
    except Exception as e:
        print(f"Staking failed: {e}")
        return

    # Save role
    role = load_node_role(config.data_dir)
    if "validator" not in role.get("roles", []):
        role.setdefault("roles", []).append("validator")
    role["validator_stake"] = total

    # Save API key if provided
    api_key = getattr(args, "api_key", None)
    api_provider = getattr(args, "api_provider", None)
    api_endpoint = getattr(args, "api_endpoint", None)
    if api_key:
        from pathlib import Path as _P
        key_file = _P(config.data_dir) / "ai_api_key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(api_key)
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        role["api_key_set"] = True
    if api_provider:
        role["api_provider"] = api_provider
    if api_endpoint:
        role["api_endpoint"] = api_endpoint
    save_node_role(config.data_dir, role)

    if args.json:
        print(json.dumps({"ok": True, "node_id": node_id_short, "role": "validator", "staked": total}, indent=2))
    else:
        print(f"Node {node_id_short} is now a validator")
        print(f"  Staked: {total} OAS")
        print(f"  Min stake: {from_units(min_stake):.0f} OAS")
        if api_key:
            print(f"  AI API key: configured ({api_provider or 'claude'})")


def cmd_node_become_arbitrator(args):
    """Register this node as an arbitrator by publishing arbitration capability."""
    from oasyce_plugin.config import load_or_create_node_identity, load_node_role, save_node_role

    config = Config.from_env()
    _priv, node_id = load_or_create_node_identity(config.data_dir)
    node_id_short = node_id[:16]

    tags = ["arbitration", "dispute"]
    if args.tags:
        tags.extend(t.strip() for t in args.tags.split(",") if t.strip())

    # Register arbitration capability
    try:
        from oasyce_core.capabilities.registry import CapabilityRegistry
        registry = CapabilityRegistry()
        from oasyce_core.capabilities.models import CapabilityMetadata, PricingConfig
        cap = CapabilityMetadata(
            capability_id=f"arb_{node_id_short}",
            name=f"Arbitrator {node_id_short}",
            provider=node_id_short,
            description=args.description or "Dispute arbitration service",
            tags=tags,
            intents=["dispute_arbitrate"],
            pricing=PricingConfig(base_price=0.0),
        )
        registry.register(cap)
    except ImportError:
        # Fallback: just save role locally without oasyce_core
        pass

    # Save role
    role = load_node_role(config.data_dir)
    if "arbitrator" not in role.get("roles", []):
        role.setdefault("roles", []).append("arbitrator")
    role["arbitrator_tags"] = tags

    # Save API key if provided
    api_key = getattr(args, "api_key", None)
    api_provider = getattr(args, "api_provider", None)
    api_endpoint = getattr(args, "api_endpoint", None)
    if api_key:
        from pathlib import Path as _P
        key_file = _P(config.data_dir) / "ai_api_key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(api_key)
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        role["api_key_set"] = True
    if api_provider:
        role["api_provider"] = api_provider
    if api_endpoint:
        role["api_endpoint"] = api_endpoint
    save_node_role(config.data_dir, role)

    if args.json:
        print(json.dumps({"ok": True, "node_id": node_id_short, "role": "arbitrator", "tags": tags}, indent=2))
    else:
        print(f"Node {node_id_short} is now an arbitrator")
        print(f"  Tags: {', '.join(tags)}")
        print(f"  Discoverable via: oasyce discover --intents dispute_arbitrate")
        if api_key:
            print(f"  AI API key: configured ({api_provider or 'claude'})")


def cmd_node_role(args):
    """Show current node role."""
    from oasyce_plugin.config import load_or_create_node_identity, load_node_role

    config = Config.from_env()
    _priv, node_id = load_or_create_node_identity(config.data_dir)
    node_id_short = node_id[:16]
    role = load_node_role(config.data_dir)

    roles = role.get("roles", [])
    if args.json:
        print(json.dumps({"node_id": node_id_short, **role}, indent=2))
    else:
        if not roles:
            print(f"Node {node_id_short}: no special role (standard peer)")
            print(f"  Use 'oasyce node become-validator' or 'oasyce node become-arbitrator'")
        else:
            print(f"Node {node_id_short}")
            for r in roles:
                if r == "validator":
                    print(f"  Validator — staked: {role.get('validator_stake', 0)} OAS")
                elif r == "arbitrator":
                    print(f"  Arbitrator — tags: {', '.join(role.get('arbitrator_tags', []))}")


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


def cmd_access_query(args):
    """L0 query an asset."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    result = skills.query_data_skill(args.agent, args.asset_id, args.query)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            print(f"✅ L0 Query OK — bond: {result['bond_required']:.2f} OAS")
            if result["data"]:
                print(f"   Data: {result['data']}")
        else:
            print(f"❌ Denied: {result['error']}")


def cmd_access_sample(args):
    """L1 sample an asset."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    result = skills.sample_data_skill(args.agent, args.asset_id, args.size)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            print(f"✅ L1 Sample OK — bond: {result['bond_required']:.2f} OAS")
            if result["data"]:
                print(f"   Data: {result['data']}")
        else:
            print(f"❌ Denied: {result['error']}")


def cmd_access_compute(args):
    """L2 compute on an asset."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    result = skills.compute_data_skill(args.agent, args.asset_id, args.code)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            print(f"✅ L2 Compute OK — bond: {result['bond_required']:.2f} OAS")
            if result["data"]:
                print(f"   Data: {result['data']}")
        else:
            print(f"❌ Denied: {result['error']}")


def cmd_access_deliver(args):
    """L3 deliver an asset."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    result = skills.deliver_data_skill(args.agent, args.asset_id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["success"]:
            print(f"✅ L3 Deliver OK — bond: {result['bond_required']:.2f} OAS")
            if result["data"]:
                print(f"   Data: {result['data']}")
        else:
            print(f"❌ Denied: {result['error']}")


def cmd_access_bond(args):
    """Calculate bond for an access level."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    try:
        result = skills.calculate_bond_skill(args.agent, args.asset_id, args.level)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"💰 Bond for {args.asset_id} at {args.level}:")
            print(f"   Agent: {args.agent}")
            print(f"   Bond:  {result['bond_required']:.2f} OAS")
    except (ValueError, KeyError) as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_reputation_check(args):
    """Check agent reputation."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    result = skills.check_reputation_skill(args.agent_id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"📊 Reputation for '{args.agent_id}':")
        print(f"   Score:    {result['reputation']:.1f}")
        print(f"   Discount: {result['bond_discount']:.2f} (bond multiplier)")


def cmd_reputation_update(args):
    """Update agent reputation."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    rep = skills.access_provider.reputation
    score = rep.update(
        args.agent_id,
        success=args.success,
        leak_detected=args.leak,
    )
    if args.json:
        print(json.dumps({"agent_id": args.agent_id, "reputation": score}, indent=2))
    else:
        event = "success" if args.success else ("leak" if args.leak else "damage")
        print(f"📊 Updated '{args.agent_id}' ({event}) → reputation: {score:.1f}")


def cmd_contribution_prove(args):
    """Generate a contribution proof for a file."""
    from oasyce_plugin.services.contribution import ContributionEngine

    engine = ContributionEngine()
    try:
        cert = engine.generate_proof(
            args.file, args.creator,
            source_type=args.source_type,
            source_evidence=args.source_evidence or "",
        )
        if args.json:
            print(json.dumps(cert.to_dict(), indent=2))
        else:
            print(f"✅ Contribution proof generated")
            print(f"   Hash:    {cert.content_hash[:16]}...")
            print(f"   Source:  {cert.source_type}")
            print(f"   Creator: {cert.creator_key}")
            print(f"   Time:    {cert.timestamp}")
            if cert.semantic_fingerprint:
                print(f"   Vector:  [{len(cert.semantic_fingerprint)} dims]")
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_contribution_verify(args):
    """Verify a contribution certificate."""
    from oasyce_plugin.services.contribution import ContributionEngine, ContributionCertificate

    engine = ContributionEngine()
    try:
        cert_data = json.loads(args.certificate_json)
        cert = ContributionCertificate.from_dict(cert_data)
        result = engine.verify_proof(cert, args.file)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            status = "✅ Valid" if result["valid"] else "❌ Invalid"
            print(f"{status}")
            for check, ok in result["checks"].items():
                mark = "✅" if ok else "❌"
                print(f"   {mark} {check}")
    except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_contribution_score(args):
    """Calculate contribution score for a file."""
    from oasyce_plugin.services.contribution import ContributionEngine

    config = Config.from_env()
    engine = ContributionEngine()
    try:
        cert = engine.generate_proof(args.file, args.creator, source_type=args.source_type)

        # Gather existing assets for comparison
        skills = OasyceSkills(config)
        existing = skills._get_existing_asset_vectors()

        score = engine.calculate_contribution_score(cert, existing)
        if args.json:
            print(json.dumps({"score": score, "content_hash": cert.content_hash}, indent=2))
        else:
            print(f"📊 Contribution Score: {score:.4f}")
            print(f"   File: {args.file}")
            print(f"   Hash: {cert.content_hash[:16]}...")
            print(f"   Compared against {len(existing)} existing asset(s)")
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_leakage_check(args):
    """Check leakage budget for an agent-asset pair."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    result = skills.check_leakage_budget_skill(args.agent_id, args.asset_id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"📊 Leakage Budget: {args.agent_id} → {args.asset_id}")
        print(f"   Budget:    {result['budget']:.2f}")
        print(f"   Used:      {result['used']:.2f}")
        print(f"   Remaining: {result['remaining']:.2f}")
        print(f"   Queries:   {result['queries']}")
        print(f"   Exhausted: {result['exhausted']}")


def cmd_leakage_reset(args):
    """Reset leakage budget for an agent-asset pair."""
    config = Config.from_env()
    skills = OasyceSkills(config)
    result = skills.access_provider.leakage.reset_budget(args.agent_id, args.asset_id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            print(f"✅ Leakage budget reset for {args.agent_id} → {args.asset_id}")


def cmd_asset_info(args):
    """Display full OAS-DAS 5-layer information for an asset."""
    config = Config.from_env()
    skills = OasyceSkills(config)

    try:
        result = skills.get_asset_standard_skill(args.asset_id)
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        das = result
        ident = das["identity"]
        meta = das["metadata"]
        access = das["access_policy"]
        compute = das["compute_interface"]
        prov = das["provenance"]

        print(f"📋 OAS-DAS Asset: {ident['asset_id']}")
        print()
        print("── Layer 1: Identity ──")
        print(f"   Creator:    {ident['creator']}")
        print(f"   Created:    {ident['created_at']}")
        print(f"   Version:    {ident['version']}")
        print(f"   Namespace:  {ident['namespace']}")
        print()
        print("── Layer 2: Metadata ──")
        print(f"   Title:      {meta['title']}")
        print(f"   Tags:       {', '.join(meta['tags']) if meta['tags'] else '(none)'}")
        print(f"   File size:  {meta['file_size_bytes']} bytes")
        if meta.get("description"):
            print(f"   Desc:       {meta['description']}")
        if meta.get("category"):
            print(f"   Category:   {meta['category']}")
        print()
        print("── Layer 3: Access Policy ──")
        print(f"   Risk level: {access['risk_level']}")
        print(f"   Max access: {access['max_access_level']}")
        print(f"   Pricing:    {access['price_model']}")
        print(f"   License:    {access['license_type']}")
        if access.get("geographic_restrictions"):
            print(f"   Geo restrict: {', '.join(access['geographic_restrictions'])}")
        if access.get("expiry_timestamp"):
            print(f"   Expires:    {access['expiry_timestamp']}")
        print()
        print("── Layer 4: Compute Interface ──")
        ops = compute.get("supported_operations", [])
        print(f"   Operations: {', '.join(ops) if ops else '(none)'}")
        print(f"   Runtime:    {compute['runtime']}")
        print(f"   Max time:   {compute['max_compute_seconds']}s")
        print(f"   Memory:     {compute['memory_limit_mb']} MB")
        print()
        print("── Layer 5: Provenance ──")
        print(f"   PoPC sig:   {prov.get('popc_signature') or '(none)'}")
        print(f"   Issuer:     {prov.get('certificate_issuer') or '(none)'}")
        parents = prov.get("parent_assets", [])
        print(f"   Parents:    {', '.join(parents) if parents else '(none)'}")
        print(f"   Fingerprint:{prov.get('fingerprint_id') or '(none)'}")
        vec = prov.get("semantic_vector")
        print(f"   Vector:     {'[' + str(len(vec)) + ' dims]' if vec else '(none)'}")


def cmd_asset_validate(args):
    """Validate asset against OAS-DAS standard."""
    config = Config.from_env()
    skills = OasyceSkills(config)

    try:
        result = skills.validate_asset_standard_skill(args.asset_id)
    except RuntimeError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["valid"]:
            print(f"✅ Asset {args.asset_id} conforms to OAS-DAS standard")
        else:
            print(f"❌ Asset {args.asset_id} has {len(result['errors'])} validation error(s):")
            for err in result["errors"]:
                print(f"   - {err}")


def cmd_testnet_start(args):
    """Start a testnet node."""
    import asyncio
    from oasyce_plugin.config import (
        NetworkMode, get_data_dir, load_or_create_node_identity,
        TESTNET_NETWORK_CONFIG,
    )
    from oasyce_plugin.network.node import OasyceNode
    from oasyce_plugin.storage.ledger import Ledger

    data_dir = get_data_dir(NetworkMode.TESTNET)
    port = args.port or TESTNET_NETWORK_CONFIG.listen_port
    host = TESTNET_NETWORK_CONFIG.listen_host
    db_path = os.path.join(data_dir, "chain.db")
    ledger = Ledger(db_path)

    _priv, node_id = load_or_create_node_identity(data_dir)
    node_id_short = node_id[:16]

    node = OasyceNode(
        host=host, port=port, node_id=node_id_short,
        ledger=ledger, data_dir=data_dir,
    )

    async def _run():
        await node.start(bootstrap=True)
        print(f"[TESTNET · LOCAL SIMULATION] Oasyce node {node_id_short} listening on {host}:{port}")
        if node.peers:
            print(f"  Connected peers: {len(node.peers)}")
        else:
            print("  ⚠️  No peers connected — running as isolated local node.")
        print("  Note: Testnet runs locally for testing. No real tokens or network.")
        print("Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await node.stop()
            print("\nTestnet node stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


def cmd_testnet_faucet(args):
    """Claim testnet tokens from faucet."""
    from oasyce_plugin.config import NetworkMode, get_data_dir, load_or_create_node_identity
    from oasyce_plugin.services.faucet import Faucet

    data_dir = get_data_dir(NetworkMode.TESTNET)
    _priv, node_id = load_or_create_node_identity(data_dir)
    node_id_short = node_id[:16]

    faucet = Faucet(data_dir)
    result = faucet.claim(node_id_short)

    if args.json:
        result["mode"] = "LOCAL_SIMULATION"
        print(json.dumps(result, indent=2))
    elif result["success"]:
        print(f"[LOCAL SIMULATION] Claimed {result['amount']:.0f} test OAS")
        print(f"  Balance: {result['balance']:.0f} test OAS")
        print(f"  Next claim available in 24h")
        print(f"  Note: These are simulated tokens for local testing only.")
    else:
        print(f"Faucet: {result['error']}")
        print(f"  Balance: {result['balance']:.0f} test OAS")


def cmd_testnet_status(args):
    """Show testnet status."""
    from oasyce_plugin.config import (
        NetworkMode, get_data_dir, get_economics,
        load_or_create_node_identity, TESTNET_NETWORK_CONFIG,
    )
    from oasyce_plugin.services.faucet import Faucet

    data_dir = get_data_dir(NetworkMode.TESTNET)
    economics = get_economics(NetworkMode.TESTNET)

    # Node identity
    _priv, node_id = load_or_create_node_identity(data_dir)
    node_id_short = node_id[:16]

    # Faucet balance
    faucet = Faucet(data_dir)
    balance = faucet.balance(node_id_short)

    # Chain height
    db_path = os.path.join(data_dir, "chain.db")
    height = 0
    try:
        from oasyce_plugin.storage.ledger import Ledger
        ledger = Ledger(db_path)
        height = ledger.get_chain_height()
    except Exception:
        pass

    # Peers
    peers_path = Path(data_dir) / "peers.json"
    peers_count = 0
    if peers_path.exists():
        try:
            peers_count = len(json.loads(peers_path.read_text()))
        except Exception:
            pass

    info = {
        "mode": "testnet",
        "node_id": node_id_short,
        "port": TESTNET_NETWORK_CONFIG.listen_port,
        "data_dir": data_dir,
        "chain_height": height,
        "known_peers": peers_count,
        "faucet_balance": balance,
        "economics": economics,
    }

    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"── Testnet Status [LOCAL SIMULATION] ──")
        print(f"  Node ID:      {node_id_short}")
        print(f"  Port:         {TESTNET_NETWORK_CONFIG.listen_port}")
        print(f"  Data dir:     {data_dir}")
        print(f"  Chain height: {height}")
        print(f"  Known peers:  {peers_count}")
        print(f"  Balance:      {balance:.0f} test OAS")
        from oasyce_plugin.consensus.core.types import from_units
        print(f"  Min stake:    {from_units(economics['min_stake']):.0f} test OAS")
        print(f"  Block reward: {from_units(economics['block_reward']):.0f} test OAS")


def cmd_testnet_onboard(args):
    """One-click testnet onboarding."""
    from oasyce_plugin.config import NetworkMode, get_data_dir, load_or_create_node_identity
    from oasyce_plugin.services.testnet import TestnetOnboarding

    data_dir = get_data_dir(NetworkMode.TESTNET)
    _priv, node_id = load_or_create_node_identity(data_dir)
    node_id_short = node_id[:16]

    onboarding = TestnetOnboarding(data_dir)
    result = onboarding.onboard(node_id_short)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"── Testnet Onboarding [LOCAL SIMULATION] ──")
        for step in result["summary"]:
            print(f"  {step}")


def cmd_testnet_reset(args):
    """Reset testnet data."""
    import shutil
    from oasyce_plugin.config import NetworkMode, get_data_dir

    data_dir = get_data_dir(NetworkMode.TESTNET)
    data_path = Path(data_dir)

    if not data_path.exists():
        print("Testnet data directory does not exist — nothing to reset.")
        return

    if not args.force:
        print(f"This will delete all testnet data in {data_dir}")
        print("Use --force to confirm.")
        return

    shutil.rmtree(data_dir)
    print(f"Testnet data reset. Removed {data_dir}")


def cmd_start(args):
    """Start Core node + Dashboard in one command."""
    import threading
    import time

    core_port = args.core_port
    gui_port = args.port

    # Check if oasyce-core is available
    has_core = False
    try:
        import oasyce_core  # noqa: F401
        has_core = True
    except ImportError:
        pass

    core_line = f"http://localhost:{core_port}" if has_core else "(not installed — local mode)"
    print(f"""
╔══════════════════════════════════════════════╗
║            Oasyce — Starting Up              ║
╠══════════════════════════════════════════════╣
║  Dashboard:   http://localhost:{gui_port:<14}║
║  Core Node:   {core_line:<31}║
╠══════════════════════════════════════════════╣
║  Open Dashboard in your browser to begin.    ║
║  Press Ctrl+C to stop.                       ║
╚══════════════════════════════════════════════╝
""")

    if not has_core:
        print("ℹ️  oasyce-core not installed — running in local mode.")
        print("   Local features work: register, search, dashboard, scan.")
        print("   For AHRP/Bancor features: pip install oasyce-core\n")

    # Start Core node in background thread (only if available)
    if has_core:
        def run_core():
            try:
                from oasyce_core.server import create_app
                import uvicorn
                app = create_app(node_id="oasyce-node-0", testnet=True)
                uvicorn.run(app, host="0.0.0.0", port=core_port, log_level="warning")
            except Exception as e:
                print(f"⚠️  Core node failed: {e}")

        core_thread = threading.Thread(target=run_core, daemon=True)
        core_thread.start()
        time.sleep(1)  # let core start first

    # Start Dashboard in main thread
    from oasyce_plugin.gui.app import OasyceGUI
    gui = OasyceGUI(port=gui_port)
    gui.run()


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


def cmd_scan(args):
    """Scan a directory for candidate data assets."""
    from oasyce_plugin.services.scanner import AssetScanner

    scanner = AssetScanner()
    target = args.path or "."
    try:
        results = scanner.scan_directory(target)
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        from dataclasses import asdict
        print(json.dumps([asdict(r) for r in results], indent=2))
        return

    if not results:
        print("No candidate assets found.")
        return

    print(f"\n📂 Found {len(results)} candidate asset(s) in {target}\n")
    for r in results:
        sens_icon = {"public": "🟢", "internal": "🟡", "sensitive": "🔴"}.get(r.sensitivity, "⚪")
        print(f"  {sens_icon} {r.suggested_name}")
        print(f"     Path: {r.file_path}")
        print(f"     Type: {r.file_type}  Size: {r.size_bytes} bytes  Sensitivity: {r.sensitivity}")
        print(f"     Tags: {', '.join(r.suggested_tags)}  Confidence: {r.confidence}")
        print()


def cmd_inbox_list(args):
    """List pending inbox items."""
    from oasyce_plugin.services.scanner import ConfirmationInbox

    inbox = ConfirmationInbox()
    filter_type = getattr(args, "type", "all") or "all"
    items = inbox.list_pending(filter_type)

    if getattr(args, "json", False):
        print(json.dumps([i.to_dict() for i in items], indent=2))
        return

    if not items:
        print("No pending items in inbox.")
        return

    print(f"\n📥 {len(items)} pending item(s)\n")
    for item in items:
        if item.item_type == "register":
            print(f"  [{item.item_id}] REGISTER  {item.suggested_name}")
            print(f"     File: {item.file_path}  Sensitivity: {item.sensitivity}")
        else:
            print(f"  [{item.item_id}] PURCHASE  asset={item.asset_id}  price={item.price} OAS")
            if item.reason:
                print(f"     Reason: {item.reason}")
        print()


def cmd_inbox_approve(args):
    """Approve an inbox item."""
    from oasyce_plugin.services.scanner import ConfirmationInbox

    inbox = ConfirmationInbox()
    item = inbox.approve(args.item_id)
    if item is None:
        print(f"❌ Item not found: {args.item_id}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Approved: {args.item_id}")


def cmd_inbox_reject(args):
    """Reject an inbox item."""
    from oasyce_plugin.services.scanner import ConfirmationInbox

    inbox = ConfirmationInbox()
    item = inbox.reject(args.item_id)
    if item is None:
        print(f"❌ Item not found: {args.item_id}", file=sys.stderr)
        sys.exit(1)
    print(f"🚫 Rejected: {args.item_id}")


def cmd_inbox_edit(args):
    """Edit and approve an inbox item."""
    from oasyce_plugin.services.scanner import ConfirmationInbox

    inbox = ConfirmationInbox()
    changes = {}
    if args.name:
        changes["suggested_name"] = args.name
    if args.tags:
        changes["suggested_tags"] = [t.strip() for t in args.tags.split(",")]
    if args.description:
        changes["suggested_description"] = args.description

    item = inbox.edit(args.item_id, changes)
    if item is None:
        print(f"❌ Item not found: {args.item_id}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ Edited and approved: {args.item_id}")


def cmd_trust(args):
    """View or set the trust level."""
    from oasyce_plugin.services.scanner import ConfirmationInbox

    inbox = ConfirmationInbox()
    if args.level is not None:
        try:
            inbox.set_trust_level(args.level)
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(1)
        print(f"✅ Trust level set to {args.level}")
    else:
        level = inbox.get_trust_level()
        labels = {0: "manual", 1: "low-value auto", 2: "full auto"}
        print(f"Trust level: {level} ({labels.get(level, 'unknown')})")
        print(f"Auto-approve threshold: {inbox.get_auto_threshold()} OAS")


def cmd_doctor(args):
    """Run security and readiness checks for the Oasyce node."""
    import platform
    import socket
    import subprocess

    home = Path.home()
    oasyce_dir = home / ".oasyce"
    keys_dir = oasyce_dir / "keys"

    errors = 0
    warnings = 0

    print("\n\U0001f50d Oasyce Security Doctor")
    print("\u2550" * 39)

    # 1. Ed25519 Keys
    priv = keys_dir / "private.key"
    pub = keys_dir / "public.key"
    if priv.exists() and pub.exists():
        print("\u2705 Ed25519 keys          Found in ~/.oasyce/keys/")
    else:
        warnings += 1
        print("\u26a0\ufe0f  Ed25519 keys          Missing (will auto-generate on first run)")

    # 2. Protocol Port 9527
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 9527))
        s.close()
        print("\u2705 Protocol port 9527    Available")
    except OSError:
        errors += 1
        print("\u274c Protocol port 9527    Already in use")

    # 3. Core Node (optional — local features work without it)
    try:
        import oasyce_core  # noqa: F401
        ver = getattr(oasyce_core, "__version__", "unknown")
        print(f"\u2705 oasyce-core           Installed (v{ver})")
    except ImportError:
        warnings += 1
        print("\u26a0\ufe0f  oasyce-core           Not installed (optional — local features work without it)")
        print("                        Install for Bancor pricing: pip install oasyce-core")

    # 4. Dashboard port
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 8420))
        s.close()
        print("\u2705 Dashboard port 8420   Available")
    except OSError:
        warnings += 1
        print("\u26a0\ufe0f  Dashboard port 8420   In use (will auto-select alternative)")

    # 5. Required dependencies
    dep_ok = True
    for dep_name in ["cryptography", "dotenv", "aiohttp"]:
        mod = dep_name if dep_name != "dotenv" else "dotenv"
        try:
            __import__(mod)
        except ImportError:
            dep_ok = False
            errors += 1
            print(f"\u274c {dep_name:<22s} Not installed")
    if dep_ok:
        print("\u2705 Dependencies          All required packages installed")

    # 6. Seed Node Connectivity
    try:
        s = socket.create_connection(("seed1.oasyce.com", 9527), timeout=3)
        s.close()
        print("\u2705 Seed node             seed1.oasyce.com reachable")
    except (OSError, socket.timeout):
        warnings += 1
        print("\u26a0\ufe0f  Seed node             Unreachable (local mode — this is normal for now)")

    # 5. Local Firewall
    system = platform.system()
    firewall_detected = False
    if system == "Darwin":
        try:
            result = subprocess.run(
                ["pfctl", "-s", "info"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and "Status: Enabled" in result.stdout:
                firewall_detected = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    elif system == "Linux":
        for cmd in [["ufw", "status"], ["iptables", "-L", "-n"]]:
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    if cmd[0] == "ufw" and "active" in result.stdout.lower():
                        firewall_detected = True
                    elif cmd[0] == "iptables":
                        firewall_detected = True
                    break
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

    if firewall_detected:
        print("\u2705 Firewall              Detected")
    else:
        warnings += 1
        print("\u26a0\ufe0f  Firewall              Not detected \u2014 consider enabling")

    # 6. SSH Exposure
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("127.0.0.1", 22))
        s.close()
        warnings += 1
        print("\u26a0\ufe0f  SSH port 22           Listening (consider restricting to specific IPs)")
    except (OSError, socket.timeout):
        print("\u2705 SSH port 22           Not exposed")

    # 7. Data Directory
    if oasyce_dir.exists():
        if os.access(str(oasyce_dir), os.W_OK):
            print("\u2705 Data directory         ~/.oasyce/ writable")
        else:
            errors += 1
            print("\u274c Data directory         ~/.oasyce/ not writable")
    else:
        try:
            oasyce_dir.mkdir(parents=True, exist_ok=True)
            print("\u2705 Data directory         ~/.oasyce/ created")
        except OSError:
            errors += 1
            print("\u274c Data directory         Could not create ~/.oasyce/")

    # 8. Python Version
    ver = sys.version_info
    ver_str = f"{ver.major}.{ver.minor}.{ver.micro}"
    if ver >= (3, 9):
        print(f"\u2705 Python {ver_str:<14s} OK")
    else:
        errors += 1
        print(f"\u274c Python {ver_str:<14s} Too old (need >= 3.9)")

    print("\u2550" * 39)

    if errors > 0:
        print(f"\u274c {errors} error(s) must be fixed before running.")
    elif warnings > 0:
        print(f"\u26a0\ufe0f  {warnings} warning(s). Review above for recommendations.")
    else:
        print("\u2705 All checks passed. Your node is ready.")
    print()


def cmd_work_list(args):
    """List work tasks."""
    from oasyce_plugin.services.work_value import WorkValueEngine

    config = Config.from_env()
    db_path = os.path.join(config.data_dir, "work.db")
    engine = WorkValueEngine(db_path=db_path)

    status = getattr(args, "status", None)
    task_type = getattr(args, "type", None)
    tasks = engine.list_tasks(status=status, task_type=task_type, limit=args.limit)
    engine.close()

    if args.json:
        print(json.dumps([t.to_dict() for t in tasks], indent=2))
    else:
        if not tasks:
            print("No tasks found.")
            return
        print(f"Tasks ({len(tasks)}):")
        for t in tasks:
            worker = t.assigned_to or "-"
            val = f"{t.final_value:.2f}" if t.final_value else "-"
            print(f"  {t.task_id}  {t.task_type:<14s}  {t.status:<10s}  worker={worker}  value={val} OAS")


def cmd_work_stats(args):
    """Show work system stats."""
    from oasyce_plugin.services.work_value import WorkValueEngine
    from oasyce_plugin.config import load_or_create_node_identity

    config = Config.from_env()
    db_path = os.path.join(config.data_dir, "work.db")
    engine = WorkValueEngine(db_path=db_path)
    _priv, node_id = load_or_create_node_identity(config.data_dir)
    node_id_short = node_id[:16]

    global_s = engine.global_stats()
    worker_s = engine.worker_stats(node_id_short)
    engine.close()

    if args.json:
        print(json.dumps({"global": global_s, "worker": worker_s}, indent=2))
    else:
        print("Global:")
        print(f"  Total tasks:    {global_s['total_tasks']}")
        for st, cnt in global_s.get("by_status", {}).items():
            print(f"    {st}: {cnt}")
        print(f"  Total settled:  {global_s['total_value_settled']:.4f} OAS")
        print()
        print(f"Your node ({node_id_short}):")
        print(f"  Tasks done:     {worker_s['total_tasks']}")
        print(f"  Settled:        {worker_s['settled']}")
        print(f"  Failed:         {worker_s['failed']}")
        print(f"  Total earned:   {worker_s['total_earned']:.4f} OAS")
        print(f"  Avg quality:    {worker_s['avg_quality']:.4f}")


def cmd_work_history(args):
    """Show work history for this node."""
    from oasyce_plugin.services.work_value import WorkValueEngine
    from oasyce_plugin.config import load_or_create_node_identity

    config = Config.from_env()
    db_path = os.path.join(config.data_dir, "work.db")
    engine = WorkValueEngine(db_path=db_path)
    _priv, node_id = load_or_create_node_identity(config.data_dir)
    node_id_short = node_id[:16]

    tasks = engine.list_tasks(worker_id=node_id_short, limit=args.limit)
    engine.close()

    if args.json:
        print(json.dumps([t.to_dict() for t in tasks], indent=2))
    else:
        if not tasks:
            print("No work history.")
            return
        print(f"Work history ({len(tasks)}):")
        for t in tasks:
            val = f"{t.final_value:.2f}" if t.final_value else "-"
            print(f"  {t.task_id}  {t.task_type:<14s}  {t.status:<10s}  value={val} OAS  trigger={t.trigger_tx}")


def cmd_node_api_key(args):
    """Set AI API key for this node."""
    from oasyce_plugin.config import load_node_role, save_node_role

    config = Config.from_env()
    api_key = args.api_key
    provider = getattr(args, "provider", "claude") or "claude"
    endpoint = getattr(args, "endpoint", None)

    # Save key to secure file
    from pathlib import Path as _P
    key_file = _P(config.data_dir) / "ai_api_key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(api_key)
    try:
        key_file.chmod(0o600)
    except OSError:
        pass

    # Update role with provider info
    role = load_node_role(config.data_dir)
    role["api_provider"] = provider
    role["api_key_set"] = True
    if endpoint:
        role["api_endpoint"] = endpoint
    save_node_role(config.data_dir, role)

    if args.json:
        print(json.dumps({"ok": True, "provider": provider, "api_key_set": True}))
    else:
        print(f"AI API key saved ({provider})")
        if endpoint:
            print(f"  Endpoint: {endpoint}")


# ── Consensus commands ─────────────────────────────────────────────


def _get_consensus_engine(args):
    """Create a ConsensusEngine from config."""
    from oasyce_plugin.consensus import ConsensusEngine
    from oasyce_plugin.config import get_consensus_params, get_economics, NetworkMode

    config = Config.from_env()
    mode = NetworkMode.TESTNET  # default to testnet for now
    consensus_db = os.path.join(config.data_dir, "consensus.db")
    return ConsensusEngine(
        db_path=consensus_db,
        consensus_params=get_consensus_params(mode),
        economics=get_economics(mode),
    )


def cmd_consensus_status(args):
    """Show current consensus status."""
    engine = _get_consensus_engine(args)
    try:
        status = engine.status()
        if args.json:
            print(json.dumps(status, indent=2))
        else:
            print(f"Consensus Status:")
            print(f"  Epoch:             {status['current_epoch']}")
            print(f"  Slot:              {status['current_slot']} / {status['slots_per_epoch']}")
            print(f"  Active validators: {status['active_validators']}")
            from oasyce_plugin.consensus.core.types import from_units
            print(f"  Total staked:      {from_units(status['total_staked']):.2f} OAS")
            print(f"  Next epoch in:     {status['time_until_next_epoch']}s")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_validators(args):
    """List validators."""
    engine = _get_consensus_engine(args)
    try:
        include_inactive = getattr(args, "all", False)
        validators = engine.get_validators(include_inactive=include_inactive)
        if args.json:
            print(json.dumps(validators, indent=2))
        else:
            if not validators:
                print("No validators registered.")
                return
            print(f"Validators ({len(validators)}):")
            for v in validators:
                from oasyce_plugin.consensus.core.types import from_units
                print(f"  {v['validator_id'][:16]}  stake={from_units(v['total_stake']):.2f}  "
                      f"commission={v['commission_rate'] / 100:.0f}%  status={v['status']}  "
                      f"blocks={v['blocks_proposed']}  rewards={from_units(v['total_rewards']):.2f}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_schedule(args):
    """Show leader schedule for an epoch."""
    engine = _get_consensus_engine(args)
    try:
        epoch = getattr(args, "epoch", None)
        if epoch is None:
            epoch = engine.epoch_manager.current_epoch()
        schedule = engine.get_schedule(epoch)
        if args.json:
            print(json.dumps({"epoch": epoch, "schedule": schedule}, indent=2))
        else:
            if not schedule:
                print(f"No schedule for epoch {epoch}.")
                return
            print(f"Leader schedule for epoch {epoch} ({len(schedule)} slots):")
            for s in schedule:
                mark = "*" if s.get("proposed") else " "
                print(f"  [{mark}] slot {s['slot_index']:3d}  {s['validator_id'][:16]}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_register(args):
    """Register as a validator."""
    from oasyce_plugin.config import load_or_create_node_identity

    config = Config.from_env()
    _priv, pubkey = load_or_create_node_identity(config.data_dir)
    engine = _get_consensus_engine(args)
    try:
        from oasyce_plugin.consensus.core.types import to_units
        commission_pct = getattr(args, "commission", 0.10) or 0.10
        commission_bps = int(commission_pct * 10000)
        stake_units = to_units(args.stake)
        result = engine.register_validator(pubkey, stake_units, commission_bps)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("ok"):
                print(f"Registered as validator: {pubkey[:16]}")
                print(f"  Self-stake: {args.stake:.2f} OAS")
                print(f"  Commission: {commission_pct:.0%}")
            else:
                print(f"Registration failed: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_exit(args):
    """Voluntary exit as validator."""
    from oasyce_plugin.config import load_or_create_node_identity

    config = Config.from_env()
    _priv, pubkey = load_or_create_node_identity(config.data_dir)
    engine = _get_consensus_engine(args)
    try:
        result = engine.exit_validator(pubkey)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("ok"):
                print(f"Validator {pubkey[:16]} exited. Stake entering unbonding period.")
            else:
                print(f"Exit failed: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_unjail(args):
    """Unjail validator."""
    from oasyce_plugin.config import load_or_create_node_identity

    config = Config.from_env()
    _priv, pubkey = load_or_create_node_identity(config.data_dir)
    engine = _get_consensus_engine(args)
    try:
        result = engine.unjail_validator(pubkey)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("ok"):
                print(f"Validator {pubkey[:16]} unjailed.")
            else:
                print(f"Unjail failed: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_delegate(args):
    """Delegate stake to a validator."""
    from oasyce_plugin.config import load_or_create_node_identity

    config = Config.from_env()
    _priv, pubkey = load_or_create_node_identity(config.data_dir)
    engine = _get_consensus_engine(args)
    try:
        from oasyce_plugin.consensus.core.types import to_units
        amount_units = to_units(args.amount)
        result = engine.delegate(pubkey, args.validator_id, amount_units)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("ok"):
                print(f"Delegated {args.amount:.2f} OAS to {args.validator_id[:16]}")
            else:
                print(f"Delegation failed: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_undelegate(args):
    """Undelegate stake from a validator."""
    from oasyce_plugin.config import load_or_create_node_identity

    config = Config.from_env()
    _priv, pubkey = load_or_create_node_identity(config.data_dir)
    engine = _get_consensus_engine(args)
    try:
        from oasyce_plugin.consensus.core.types import to_units
        amount_units = to_units(args.amount)
        result = engine.undelegate(pubkey, args.validator_id, amount_units)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("ok"):
                print(f"Undelegated {args.amount:.2f} OAS from {args.validator_id[:16]}")
                print(f"  Unbonding period: {result.get('unbonding_period', 0)}s")
            else:
                print(f"Undelegation failed: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_rewards(args):
    """Show reward history."""
    engine = _get_consensus_engine(args)
    try:
        epoch = getattr(args, "epoch", None)
        rewards = engine.get_rewards(epoch_number=epoch)
        if args.json:
            print(json.dumps(rewards, indent=2))
        else:
            if not rewards:
                print("No rewards found.")
                return
            print(f"Reward events ({len(rewards)}):")
            for r in rewards:
                from oasyce_plugin.consensus.core.types import from_units
                print(f"  epoch={r['epoch_number']}  {r['recipient'][:16]}  "
                      f"type={r['reward_type']}  amount={from_units(r['amount']):.4f} OAS")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_slashing(args):
    """Show slashing history."""
    engine = _get_consensus_engine(args)
    try:
        validator = getattr(args, "validator", None)
        events = engine.get_slashing(validator_id=validator)
        if args.json:
            print(json.dumps(events, indent=2))
        else:
            if not events:
                print("No slashing events.")
                return
            print(f"Slash events ({len(events)}):")
            for e in events:
                from oasyce_plugin.consensus.core.types import from_units
                print(f"  epoch={e['epoch_number']}  {e['validator_id'][:16]}  "
                      f"reason={e['reason']}  amount={from_units(e['amount']):.4f} OAS")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_delegations(args):
    """Show your delegations."""
    from oasyce_plugin.config import load_or_create_node_identity
    config = Config.from_env()
    _priv, pubkey = load_or_create_node_identity(config.data_dir)
    engine = _get_consensus_engine(args)
    try:
        delegations = engine.get_delegations(pubkey)
        if args.json:
            print(json.dumps(delegations, indent=2))
        else:
            if not delegations:
                print("No active delegations.")
                return
            print(f"Your delegations ({len(delegations)}):")
            for d in delegations:
                from oasyce_plugin.consensus.core.types import from_units
                print(f"  → {d['validator_id'][:16]}  amount={from_units(d['amount']):.2f} OAS")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


def cmd_consensus_unbondings(args):
    """Show your pending unbondings."""
    from oasyce_plugin.config import load_or_create_node_identity
    config = Config.from_env()
    _priv, pubkey = load_or_create_node_identity(config.data_dir)
    engine = _get_consensus_engine(args)
    try:
        unbondings = engine.get_unbondings(pubkey)
        if args.json:
            print(json.dumps(unbondings, indent=2))
        else:
            if not unbondings:
                print("No pending unbondings.")
                return
            print(f"Pending unbondings ({len(unbondings)}):")
            for u in unbondings:
                import time as _time
                remaining = max(0, u['release_at'] - int(_time.time()))
                from oasyce_plugin.consensus.core.types import from_units
                print(f"  ← {u['validator_id'][:16]}  amount={from_units(u['amount']):.2f} OAS  releases in {remaining}s")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.close()


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
    reg_parser.add_argument("--free", action="store_true", help="Register as free asset (attribution only, no Bonding Curve)")
    reg_parser.add_argument("--rights-type", default="original",
                            choices=["original", "co_creation", "licensed", "collection"],
                            help="Rights type (default: original)")
    reg_parser.add_argument("--co-creators",
                            help='Co-creators JSON, e.g. \'[{"address":"A","share":60},{"address":"B","share":40}]\'')
    reg_parser.add_argument("--json", action="store_true", help="Output as JSON")
    reg_parser.set_defaults(func=cmd_register)
    
    # Dispute command
    dispute_parser = subparsers.add_parser("dispute", help="File a dispute against an asset")
    dispute_parser.add_argument("asset_id", help="Asset ID to dispute")
    dispute_parser.add_argument("--reason", required=True, help="Reason for dispute")
    dispute_parser.add_argument("--json", action="store_true", help="Output as JSON")
    dispute_parser.set_defaults(func=cmd_dispute)

    # Resolve command
    resolve_parser = subparsers.add_parser("resolve", help="Resolve a dispute with a remedy")
    resolve_parser.add_argument("asset_id", help="Asset ID to resolve")
    resolve_parser.add_argument("--remedy", required=True,
                                choices=["delist", "transfer", "rights_correction", "share_adjustment"],
                                help="Remedy type")
    resolve_parser.add_argument("--details",
                                help='Details JSON, e.g. \'{"new_owner":"0x..."}\'')
    resolve_parser.add_argument("--json", action="store_true", help="Output as JSON")
    resolve_parser.set_defaults(func=cmd_resolve)

    # Discover command
    discover_parser = subparsers.add_parser("discover", help="Discover capabilities via four-layer search")
    discover_parser.add_argument("--intents", help="Comma-separated intents (e.g. generate_quest,dispute_arbitrate)")
    discover_parser.add_argument("--tags", help="Comma-separated tags to filter")
    discover_parser.add_argument("--limit", type=int, default=10, help="Max results (default 10)")
    discover_parser.add_argument("--json", action="store_true", help="Output as JSON")
    discover_parser.set_defaults(func=cmd_discover)

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

    # Asset info command (OAS-DAS)
    asset_info_parser = subparsers.add_parser("asset-info", help="Show OAS-DAS 5-layer asset info")
    asset_info_parser.add_argument("asset_id", help="Asset ID")
    asset_info_parser.add_argument("--json", action="store_true", help="Output as JSON")
    asset_info_parser.set_defaults(func=cmd_asset_info)

    # Asset validate command (OAS-DAS)
    asset_validate_parser = subparsers.add_parser("asset-validate", help="Validate asset against OAS-DAS standard")
    asset_validate_parser.add_argument("asset_id", help="Asset ID")
    asset_validate_parser.add_argument("--json", action="store_true", help="Output as JSON")
    asset_validate_parser.set_defaults(func=cmd_asset_validate)

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
    node_info_parser.add_argument("--json", action="store_true", help="Output as JSON")
    node_info_parser.set_defaults(func=cmd_node_info)

    node_ping_parser = node_sub.add_parser("ping", help="Ping another node")
    node_ping_parser.add_argument("target", help="Target node (host:port)")
    node_ping_parser.set_defaults(func=cmd_node_ping)

    node_reset_parser = node_sub.add_parser("reset-identity", help="Force-reset node identity")
    node_reset_parser.set_defaults(func=cmd_node_reset_identity)

    node_peers_parser = node_sub.add_parser("peers", help="Show known peer list")
    node_peers_parser.add_argument("--json", action="store_true", help="Output as JSON")
    node_peers_parser.set_defaults(func=cmd_node_peers)

    node_role_parser = node_sub.add_parser("role", help="Show current node role")
    node_role_parser.add_argument("--json", action="store_true")
    node_role_parser.set_defaults(func=cmd_node_role)

    node_val_parser = node_sub.add_parser("become-validator", help="Register as a validator node")
    node_val_parser.add_argument("--amount", type=float, default=None, help="Stake amount (default: minimum)")
    node_val_parser.add_argument("--api-key", default=None, help="AI API key for compute tasks")
    node_val_parser.add_argument("--api-provider", default=None, help="AI provider (claude/openai/ollama/local/custom)")
    node_val_parser.add_argument("--api-endpoint", default=None, help="Custom AI endpoint URL")
    node_val_parser.add_argument("--json", action="store_true")
    node_val_parser.set_defaults(func=cmd_node_become_validator)

    node_arb_parser = node_sub.add_parser("become-arbitrator", help="Register as an arbitrator node")
    node_arb_parser.add_argument("--tags", default=None, help="Extra expertise tags (comma-separated)")
    node_arb_parser.add_argument("--description", default=None, help="Arbitrator description")
    node_arb_parser.add_argument("--api-key", default=None, help="AI API key for compute tasks")
    node_arb_parser.add_argument("--api-provider", default=None, help="AI provider (claude/openai/ollama/local/custom)")
    node_arb_parser.add_argument("--api-endpoint", default=None, help="Custom AI endpoint URL")
    node_arb_parser.add_argument("--json", action="store_true")
    node_arb_parser.set_defaults(func=cmd_node_become_arbitrator)

    node_apikey_parser = node_sub.add_parser("api-key", help="Set AI API key for this node")
    node_apikey_parser.add_argument("api_key", help="API key value")
    node_apikey_parser.add_argument("--provider", default="claude", help="AI provider (default: claude)")
    node_apikey_parser.add_argument("--endpoint", default=None, help="Custom endpoint URL")
    node_apikey_parser.add_argument("--json", action="store_true")
    node_apikey_parser.set_defaults(func=cmd_node_api_key)

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

    # Access command group
    access_parser = subparsers.add_parser("access", help="Data access control")
    access_sub = access_parser.add_subparsers(dest="access_command", help="Access sub-commands")

    access_query_parser = access_sub.add_parser("query", help="L0 query (aggregated stats)")
    access_query_parser.add_argument("asset_id", help="Asset ID")
    access_query_parser.add_argument("--agent", required=True, help="Agent ID")
    access_query_parser.add_argument("--query", default="", help="Query string")
    access_query_parser.set_defaults(func=cmd_access_query)

    access_sample_parser = access_sub.add_parser("sample", help="L1 sample (redacted fragments)")
    access_sample_parser.add_argument("asset_id", help="Asset ID")
    access_sample_parser.add_argument("--agent", required=True, help="Agent ID")
    access_sample_parser.add_argument("--size", type=int, default=10, help="Sample size (default 10)")
    access_sample_parser.set_defaults(func=cmd_access_sample)

    access_compute_parser = access_sub.add_parser("compute", help="L2 compute (TEE execution)")
    access_compute_parser.add_argument("asset_id", help="Asset ID")
    access_compute_parser.add_argument("--agent", required=True, help="Agent ID")
    access_compute_parser.add_argument("--code", required=True, help="Code to execute")
    access_compute_parser.set_defaults(func=cmd_access_compute)

    access_deliver_parser = access_sub.add_parser("deliver", help="L3 deliver (full data)")
    access_deliver_parser.add_argument("asset_id", help="Asset ID")
    access_deliver_parser.add_argument("--agent", required=True, help="Agent ID")
    access_deliver_parser.set_defaults(func=cmd_access_deliver)

    access_bond_parser = access_sub.add_parser("bond", help="Calculate bond requirement")
    access_bond_parser.add_argument("asset_id", help="Asset ID")
    access_bond_parser.add_argument("--agent", required=True, help="Agent ID")
    access_bond_parser.add_argument("--level", required=True, help="Access level (L0/L1/L2/L3)")
    access_bond_parser.set_defaults(func=cmd_access_bond)

    # Reputation command group
    rep_parser = subparsers.add_parser("reputation", help="Agent reputation management")
    rep_sub = rep_parser.add_subparsers(dest="rep_command", help="Reputation sub-commands")

    rep_check_parser = rep_sub.add_parser("check", help="Check agent reputation")
    rep_check_parser.add_argument("agent_id", help="Agent ID")
    rep_check_parser.set_defaults(func=cmd_reputation_check)

    rep_update_parser = rep_sub.add_parser("update", help="Update agent reputation")
    rep_update_parser.add_argument("agent_id", help="Agent ID")
    rep_update_parser.add_argument("--success", action="store_true", help="Record successful access")
    rep_update_parser.add_argument("--leak", action="store_true", help="Record data leak")
    rep_update_parser.add_argument("--damage", action="store_true", help="Record damage event")
    rep_update_parser.set_defaults(func=cmd_reputation_update)

    # Contribution command group
    contrib_parser = subparsers.add_parser("contribution", help="Contribution proof management")
    contrib_sub = contrib_parser.add_subparsers(dest="contrib_command", help="Contribution sub-commands")

    contrib_prove_parser = contrib_sub.add_parser("prove", help="Generate contribution proof")
    contrib_prove_parser.add_argument("file", help="Path to the data file")
    contrib_prove_parser.add_argument("--creator", required=True, help="Creator public key")
    contrib_prove_parser.add_argument("--source-type", default="manual",
                                      help="Source type (tee_capture/api_log/sensor_sig/git_commit/manual)")
    contrib_prove_parser.add_argument("--source-evidence", default="", help="Source evidence (hash/sig/URL)")
    contrib_prove_parser.set_defaults(func=cmd_contribution_prove)

    contrib_verify_parser = contrib_sub.add_parser("verify", help="Verify contribution certificate")
    contrib_verify_parser.add_argument("certificate_json", help="Certificate JSON string")
    contrib_verify_parser.add_argument("file", help="Path to original data file")
    contrib_verify_parser.set_defaults(func=cmd_contribution_verify)

    contrib_score_parser = contrib_sub.add_parser("score", help="Calculate contribution score")
    contrib_score_parser.add_argument("file", help="Path to the data file")
    contrib_score_parser.add_argument("--creator", required=True, help="Creator public key")
    contrib_score_parser.add_argument("--source-type", default="manual", help="Source type")
    contrib_score_parser.set_defaults(func=cmd_contribution_score)

    # Leakage command group
    leak_parser = subparsers.add_parser("leakage", help="Leakage budget management")
    leak_sub = leak_parser.add_subparsers(dest="leak_command", help="Leakage sub-commands")

    leak_check_parser = leak_sub.add_parser("check", help="Check leakage budget")
    leak_check_parser.add_argument("agent_id", help="Agent ID")
    leak_check_parser.add_argument("asset_id", help="Asset ID")
    leak_check_parser.set_defaults(func=cmd_leakage_check)

    leak_reset_parser = leak_sub.add_parser("reset", help="Reset leakage budget")
    leak_reset_parser.add_argument("agent_id", help="Agent ID")
    leak_reset_parser.add_argument("asset_id", help="Asset ID")
    leak_reset_parser.set_defaults(func=cmd_leakage_reset)

    # GUI command
    gui_parser = subparsers.add_parser("gui", help="Launch web dashboard (port 8420)")
    gui_parser.add_argument("--port", type=int, default=8420, help="Port (default: 8420)")
    def _run_gui(args):
        from oasyce_plugin.gui.app import OasyceGUI
        OasyceGUI(port=args.port).run()
    gui_parser.set_defaults(func=_run_gui)

    # Start command — one command to rule them all
    start_parser = subparsers.add_parser("start", help="Start everything: Core node + Dashboard (recommended)")
    start_parser.add_argument("--port", type=int, default=8420, help="Dashboard port (default: 8420)")
    start_parser.add_argument("--core-port", type=int, default=8000, help="Core node port (default: 8000)")
    start_parser.set_defaults(func=cmd_start)

    # Explorer command
    explorer_parser = subparsers.add_parser("explorer", help="Launch block explorer (port 8421)")
    explorer_parser.add_argument("--port", type=int, default=8421, help="Port (default: 8421)")
    explorer_parser.set_defaults(func=lambda args: __import__('oasyce_plugin.explorer.app', fromlist=['OasyceExplorer']).OasyceExplorer(port=args.port).run())

    # ── price ─────────────────────────────────────────────────────────
    price_parser = subparsers.add_parser("price", help="Calculate dataset price with demand/scarcity factors")
    price_parser.add_argument("asset_id", help="Asset ID")
    price_parser.add_argument("--base-price", type=float, default=1.0, help="Base price in OAS (default: 1.0)")
    price_parser.add_argument("--queries", type=int, default=0, help="Query count (default: 0)")
    price_parser.add_argument("--similar", type=int, default=0, help="Number of similar assets (default: 0)")
    price_parser.add_argument("--contribution-score", type=float, default=1.0, help="Contribution score (default: 1.0)")
    price_parser.add_argument("--days", type=float, default=0, help="Days since creation (default: 0)")
    price_parser.add_argument("--json", action="store_true", help="Output as JSON")
    price_parser.set_defaults(func=cmd_price)

    # ── price-factors ────────────────────────────────────────────────
    pf_parser = subparsers.add_parser("price-factors", help="Show pricing factor breakdown for an asset")
    pf_parser.add_argument("asset_id", help="Asset ID")
    pf_parser.add_argument("--base-price", type=float, default=1.0, help="Base price in OAS (default: 1.0)")
    pf_parser.add_argument("--queries", type=int, default=0, help="Query count (default: 0)")
    pf_parser.add_argument("--similar", type=int, default=0, help="Number of similar assets (default: 0)")
    pf_parser.add_argument("--contribution-score", type=float, default=1.0, help="Contribution score (default: 1.0)")
    pf_parser.add_argument("--days", type=float, default=0, help="Days since creation (default: 0)")
    pf_parser.add_argument("--json", action="store_true", help="Output as JSON")
    pf_parser.set_defaults(func=cmd_price_factors)

    # ── scan ─────────────────────────────────────────────────────────
    scan_parser = subparsers.add_parser("scan", help="Scan a directory for candidate assets")
    scan_parser.add_argument("path", nargs="?", default=".", help="Directory to scan (default: .)")
    scan_parser.add_argument("--json", action="store_true", help="Output as JSON")
    scan_parser.set_defaults(func=cmd_scan)

    # ── inbox ────────────────────────────────────────────────────────
    inbox_parser = subparsers.add_parser("inbox", help="Confirmation inbox")
    inbox_sub = inbox_parser.add_subparsers(dest="inbox_command", help="Inbox sub-commands")

    inbox_list_parser = inbox_sub.add_parser("list", help="List pending items")
    inbox_list_parser.add_argument("--type", choices=["register", "purchase", "all"],
                                   default="all", help="Filter by type")
    inbox_list_parser.add_argument("--json", action="store_true", help="Output as JSON")
    inbox_list_parser.set_defaults(func=cmd_inbox_list)

    inbox_approve_parser = inbox_sub.add_parser("approve", help="Approve an item")
    inbox_approve_parser.add_argument("item_id", help="Item ID to approve")
    inbox_approve_parser.set_defaults(func=cmd_inbox_approve)

    inbox_reject_parser = inbox_sub.add_parser("reject", help="Reject an item")
    inbox_reject_parser.add_argument("item_id", help="Item ID to reject")
    inbox_reject_parser.set_defaults(func=cmd_inbox_reject)

    inbox_edit_parser = inbox_sub.add_parser("edit", help="Edit and approve an item")
    inbox_edit_parser.add_argument("item_id", help="Item ID to edit")
    inbox_edit_parser.add_argument("--name", default=None, help="New name")
    inbox_edit_parser.add_argument("--tags", default=None, help="New tags (comma-separated)")
    inbox_edit_parser.add_argument("--description", default=None, help="New description")
    inbox_edit_parser.set_defaults(func=cmd_inbox_edit)

    # ── trust ────────────────────────────────────────────────────────
    trust_parser = subparsers.add_parser("trust", help="View or set trust level (0/1/2)")
    trust_parser.add_argument("level", nargs="?", type=int, default=None,
                              help="Trust level: 0=manual, 1=low-auto, 2=full-auto")
    trust_parser.set_defaults(func=cmd_trust)

    # ── testnet ──────────────────────────────────────────────────────
    testnet_parser = subparsers.add_parser("testnet", help="Testnet management")
    testnet_sub = testnet_parser.add_subparsers(dest="testnet_command", help="Testnet sub-commands")

    testnet_start_parser = testnet_sub.add_parser("start", help="Start a testnet node")
    testnet_start_parser.add_argument("--port", type=int, default=None, help="Listen port (default 9528)")
    testnet_start_parser.set_defaults(func=cmd_testnet_start)

    testnet_faucet_parser = testnet_sub.add_parser("faucet", help="Claim testnet tokens")
    testnet_faucet_parser.set_defaults(func=cmd_testnet_faucet)

    testnet_status_parser = testnet_sub.add_parser("status", help="Show testnet status")
    testnet_status_parser.set_defaults(func=cmd_testnet_status)

    testnet_onboard_parser = testnet_sub.add_parser("onboard", help="One-click onboarding (faucet + register + stake)")
    testnet_onboard_parser.set_defaults(func=cmd_testnet_onboard)

    testnet_reset_parser = testnet_sub.add_parser("reset", help="Reset all testnet data")
    testnet_reset_parser.add_argument("--force", action="store_true", help="Confirm reset")
    testnet_reset_parser.set_defaults(func=cmd_testnet_reset)

    # ── demo-network ─────────────────────────────────────────────────
    demo_net_parser = subparsers.add_parser(
        "demo-network",
        help="Spin up N local nodes, register assets, mine, sync, verify consensus",
    )
    demo_net_parser.add_argument("--nodes", type=int, default=3, help="Number of nodes (default: 3)")
    demo_net_parser.set_defaults(func=cmd_demo_network)

    # ── info ───────────────────────────────────────────────────────
    info_parser = subparsers.add_parser("info", help="Show project information, links, architecture, economics")
    info_parser.add_argument("--section",
                             choices=["quickstart", "architecture", "economics", "update", "links"],
                             help="Show a specific section")
    info_parser.add_argument("--json", action="store_true", help="Output as JSON")
    info_parser.set_defaults(func=cmd_info)

    # ── work ──────────────────────────────────────────────────────
    work_parser = subparsers.add_parser("work", help="Work task management")
    work_sub = work_parser.add_subparsers(dest="work_command", help="Work sub-commands")

    work_list_parser = work_sub.add_parser("list", help="List work tasks")
    work_list_parser.add_argument("--status", default=None, help="Filter by status")
    work_list_parser.add_argument("--type", default=None, help="Filter by task type")
    work_list_parser.add_argument("--limit", type=int, default=20, help="Max results")
    work_list_parser.add_argument("--json", action="store_true")
    work_list_parser.set_defaults(func=cmd_work_list)

    work_stats_parser = work_sub.add_parser("stats", help="Show work system stats")
    work_stats_parser.add_argument("--json", action="store_true")
    work_stats_parser.set_defaults(func=cmd_work_stats)

    work_history_parser = work_sub.add_parser("history", help="Show your work history")
    work_history_parser.add_argument("--limit", type=int, default=20, help="Max results")
    work_history_parser.add_argument("--json", action="store_true")
    work_history_parser.set_defaults(func=cmd_work_history)

    # ── consensus ─────────────────────────────────────────────────
    consensus_parser = subparsers.add_parser("consensus", help="PoS consensus management")
    consensus_sub = consensus_parser.add_subparsers(dest="consensus_command", help="Consensus sub-commands")

    cs_status_parser = consensus_sub.add_parser("status", help="Show current epoch/slot/validators")
    cs_status_parser.add_argument("--json", action="store_true")
    cs_status_parser.set_defaults(func=cmd_consensus_status)

    cs_val_parser = consensus_sub.add_parser("validators", help="List validators")
    cs_val_parser.add_argument("--all", action="store_true", help="Include jailed/exited")
    cs_val_parser.add_argument("--json", action="store_true")
    cs_val_parser.set_defaults(func=cmd_consensus_validators)

    cs_sched_parser = consensus_sub.add_parser("schedule", help="Show leader schedule")
    cs_sched_parser.add_argument("--epoch", type=int, default=None)
    cs_sched_parser.add_argument("--json", action="store_true")
    cs_sched_parser.set_defaults(func=cmd_consensus_schedule)

    cs_reg_parser = consensus_sub.add_parser("register", help="Register as a validator")
    cs_reg_parser.add_argument("--stake", type=float, required=True, help="Self-stake amount")
    cs_reg_parser.add_argument("--commission", type=float, default=0.10, help="Commission rate (0-0.50)")
    cs_reg_parser.add_argument("--json", action="store_true")
    cs_reg_parser.set_defaults(func=cmd_consensus_register)

    cs_exit_parser = consensus_sub.add_parser("exit", help="Voluntary exit")
    cs_exit_parser.add_argument("--json", action="store_true")
    cs_exit_parser.set_defaults(func=cmd_consensus_exit)

    cs_unjail_parser = consensus_sub.add_parser("unjail", help="Unjail validator")
    cs_unjail_parser.add_argument("--json", action="store_true")
    cs_unjail_parser.set_defaults(func=cmd_consensus_unjail)

    cs_del_parser = consensus_sub.add_parser("delegate", help="Delegate stake to a validator")
    cs_del_parser.add_argument("validator_id", help="Validator public key")
    cs_del_parser.add_argument("--amount", type=float, required=True, help="Amount to delegate")
    cs_del_parser.add_argument("--json", action="store_true")
    cs_del_parser.set_defaults(func=cmd_consensus_delegate)

    cs_undel_parser = consensus_sub.add_parser("undelegate", help="Undelegate stake")
    cs_undel_parser.add_argument("validator_id", help="Validator public key")
    cs_undel_parser.add_argument("--amount", type=float, required=True, help="Amount to undelegate")
    cs_undel_parser.add_argument("--json", action="store_true")
    cs_undel_parser.set_defaults(func=cmd_consensus_undelegate)

    cs_rewards_parser = consensus_sub.add_parser("rewards", help="Show reward history")
    cs_rewards_parser.add_argument("--epoch", type=int, default=None)
    cs_rewards_parser.add_argument("--json", action="store_true")
    cs_rewards_parser.set_defaults(func=cmd_consensus_rewards)

    cs_slash_parser = consensus_sub.add_parser("slashing", help="Show slashing history")
    cs_slash_parser.add_argument("--validator", default=None)
    cs_slash_parser.add_argument("--json", action="store_true")
    cs_slash_parser.set_defaults(func=cmd_consensus_slashing)

    p = consensus_sub.add_parser("delegations", help="Show your active delegations")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_consensus_delegations)

    p = consensus_sub.add_parser("unbondings", help="Show your pending unbondings")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_consensus_unbondings)

    # ── doctor ──────────────────────────────────────────────────────
    doctor_parser = subparsers.add_parser("doctor", help="Security and readiness check")
    doctor_parser.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    
    if args.command is None:
        # First-run welcome
        oasyce_dir = Path.home() / ".oasyce"
        if not oasyce_dir.exists():
            print()
            print("  Welcome to Oasyce! Looks like this is your first time.")
            print()
            print("  Quick start:")
            print("    oasyce doctor    — check your setup")
            print("    oasyce demo      — run a full demo (register → quote → buy)")
            print("    oasyce start     — launch Dashboard at http://localhost:8420")
            print()
            print("  For more: oasyce info")
            print()
            sys.exit(0)
        parser.print_help()
        sys.exit(0)

    if args.command == "node" and getattr(args, "node_command", None) is None:
        node_parser.print_help()
        sys.exit(0)

    if args.command == "fingerprint" and getattr(args, "fp_command", None) is None:
        fp_parser.print_help()
        sys.exit(0)

    if args.command == "access" and getattr(args, "access_command", None) is None:
        access_parser.print_help()
        sys.exit(0)

    if args.command == "reputation" and getattr(args, "rep_command", None) is None:
        rep_parser.print_help()
        sys.exit(0)

    if args.command == "contribution" and getattr(args, "contrib_command", None) is None:
        contrib_parser.print_help()
        sys.exit(0)

    if args.command == "leakage" and getattr(args, "leak_command", None) is None:
        leak_parser.print_help()
        sys.exit(0)

    if args.command == "testnet" and getattr(args, "testnet_command", None) is None:
        testnet_parser.print_help()
        sys.exit(0)

    if args.command == "consensus" and getattr(args, "consensus_command", None) is None:
        consensus_parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()

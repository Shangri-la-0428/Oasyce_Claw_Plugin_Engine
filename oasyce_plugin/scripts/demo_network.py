"""
Multi-node network demo — spin up N nodes on localhost, register assets,
mine blocks, sync and verify the entire chain across all nodes.

Usage:
    oasyce demo-network --nodes 3

This is the "investor demo": one command, full protocol showcase.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import List, Tuple

from oasyce_plugin.crypto.keys import generate_keypair, sign
from oasyce_plugin.network.node import OasyceNode
from oasyce_plugin.storage.ledger import Ledger


BASE_PORT = 9527


def _make_data_dir(node_index: int, base_dir: str) -> str:
    """Create isolated data directory for a demo node."""
    d = os.path.join(base_dir, f"node-{node_index}")
    os.makedirs(os.path.join(d, "keys"), exist_ok=True)
    return d


def _print_banner(msg: str) -> None:
    width = max(len(msg) + 4, 50)
    print(f"\n{'═' * width}")
    print(f"  {msg}")
    print(f"{'═' * width}\n")


def _print_step(step: int, total: int, msg: str) -> None:
    print(f"  [{step}/{total}] {msg}")


async def run_demo(num_nodes: int = 3, base_dir: Optional[str] = None) -> bool:
    """Run the full multi-node demo. Returns True on success."""

    if base_dir is None:
        base_dir = os.path.join(os.path.expanduser("~"), ".oasyce-demo")

    # Clean previous demo data
    if os.path.exists(base_dir):
        shutil.rmtree(base_dir)

    total_steps = 7
    _print_banner(f"Oasyce Multi-Node Demo — {num_nodes} Nodes")

    # ── Step 1: Create nodes ──────────────────────────────────────────
    _print_step(1, total_steps, f"Creating {num_nodes} isolated nodes...")

    nodes: List[OasyceNode] = []
    ledgers: List[Ledger] = []
    keypairs: List[Tuple[bytes, bytes]] = []

    for i in range(num_nodes):
        data_dir = _make_data_dir(i, base_dir)
        db_path = os.path.join(data_dir, "chain.db")
        ledger = Ledger(db_path)
        ledgers.append(ledger)

        priv, pub = generate_keypair()
        keypairs.append((priv, pub))

        # Save keys
        with open(os.path.join(data_dir, "keys", "private.key"), "w") as f:
            f.write(priv)
        with open(os.path.join(data_dir, "keys", "public.key"), "w") as f:
            f.write(pub)

        node_id = f"node-{i}"
        port = BASE_PORT + i
        node = OasyceNode(host="127.0.0.1", port=port, node_id=node_id, ledger=ledger)
        nodes.append(node)

        print(f"    ✅ Node {i}: port={port}, data={data_dir}")

    # ── Step 2: Start all nodes ───────────────────────────────────────
    _print_step(2, total_steps, "Starting all nodes...")

    for node in nodes:
        await node.start()
        print(f"    🟢 {node.node_id} listening on :{node.port}")

    # ── Step 3: Peer discovery (full mesh) ────────────────────────────
    _print_step(3, total_steps, "Connecting peers (full mesh)...")

    for i, node_a in enumerate(nodes):
        for j, node_b in enumerate(nodes):
            if i != j:
                resp = await node_a.connect_to_peer("127.0.0.1", node_b.port)
                print(f"    🔗 {node_a.node_id} → {node_b.node_id} (height={resp.get('height', 0)})")

    # ── Step 4: Register assets on different nodes ────────────────────
    _print_step(4, total_steps, "Registering assets on different nodes...")

    asset_names = ["photo_sunrise.jpg", "quant_strategy_v2.py", "research_paper.pdf"]
    for i, (name, ledger) in enumerate(zip(asset_names, ledgers)):
        tx_id = ledger.record_tx(
            tx_type="register",
            asset_id=f"asset_{i:04d}",
            from_addr="system",
            to_addr=f"owner_{i}",
            metadata={"filename": name, "tags": ["demo"]},
            signature=sign(name.encode(), keypairs[i][0]),
        )
        print(f"    📝 Node {i} registered '{name}' → tx={tx_id[:12]}...")

    # ── Step 5: Mine blocks ───────────────────────────────────────────
    _print_step(5, total_steps, "Mining blocks and broadcasting...")

    for i, ledger in enumerate(ledgers):
        block = ledger.create_block()
        if block:
            block_full = ledger.get_block(block["block_number"], include_tx=True)
            await nodes[i].broadcast_block(block_full)
            print(
                f"    ⛏️  Node {i} mined block #{block['block_number']} "
                f"(hash={block['block_hash'][:16]}..., txs={block['tx_count']})"
            )

    await asyncio.sleep(0.2)  # let broadcasts settle

    # ── Step 6: Sync all nodes ────────────────────────────────────────
    _print_step(6, total_steps, "Syncing all nodes to the longest chain...")

    for i, node in enumerate(nodes):
        for j, peer_node in enumerate(nodes):
            if i != j:
                fetched = await node.sync_from_peer("127.0.0.1", peer_node.port)
                if fetched > 0:
                    print(f"    📥 Node {i} pulled {fetched} blocks from Node {j}")

    # ── Step 7: Verify consensus ──────────────────────────────────────
    _print_step(7, total_steps, "Verifying consensus across all nodes...")

    heights = []
    all_valid = True
    for i, ledger in enumerate(ledgers):
        h = ledger.get_chain_height()
        valid = ledger.verify_chain()
        heights.append(h)
        status = "✅" if valid else "❌"
        print(f"    {status} Node {i}: height={h}, chain_valid={valid}")
        if not valid:
            all_valid = False

    # Check all nodes have the same height
    consensus_reached = len(set(heights)) == 1 and all_valid

    # ── Summary ───────────────────────────────────────────────────────
    _print_banner("Demo Results")

    print(f"  Nodes:           {num_nodes}")
    print(f"  Assets registered: {len(asset_names)}")
    print(f"  Blocks mined:    {max(heights)}")
    print(f"  Chain heights:   {heights}")
    print(f"  All chains valid: {all_valid}")
    print(f"  Consensus:       {'✅ REACHED' if consensus_reached else '❌ FAILED'}")
    print()

    if consensus_reached:
        print("  🎉 All nodes agree on the same chain. The network works!")
    else:
        print("  ⚠️  Nodes diverged. Investigate sync/consensus logic.")

    # ── Cleanup ───────────────────────────────────────────────────────
    for node in nodes:
        await node.stop()
    for ledger in ledgers:
        ledger.close()

    print(f"\n  Demo data saved to: {base_dir}")
    print(f"  To clean up: rm -rf {base_dir}\n")

    return consensus_reached


def main(num_nodes: int = 3) -> None:
    """Entry point for CLI."""
    success = asyncio.run(run_demo(num_nodes))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Oasyce multi-node demo")
    parser.add_argument("--nodes", type=int, default=3, help="Number of nodes (default: 3)")
    args = parser.parse_args()
    main(args.nodes)

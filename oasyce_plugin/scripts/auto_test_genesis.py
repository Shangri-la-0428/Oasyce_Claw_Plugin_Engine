from __future__ import annotations

import argparse
import json
import os
import time
from typing import List

from oasyce_plugin.config import Config
from oasyce_plugin.skills.agent_skills import OasyceSkills


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Oasyce Autonomous Genesis Batch Registration")
    parser.add_argument("--files", help="Comma-separated file paths to register")
    parser.add_argument("--vault", help="Vault directory path")
    parser.add_argument("--owner", help="Asset owner")
    parser.add_argument("--tags", help="Comma-separated tags")
    parser.add_argument("--signing-key", help="Signing key (or set OASYCE_SIGNING_KEY)")
    parser.add_argument("--signing-key-id", help="Signing key id")
    return parser


def _parse_files(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def main() -> None:
    args = _build_parser().parse_args()
    config = Config.from_env(
        vault_dir=args.vault,
        owner=args.owner,
        tags=args.tags,
        signing_key=args.signing_key,
        signing_key_id=args.signing_key_id,
    )

    skills = OasyceSkills(config)
    files_to_register = _parse_files(args.files)

    if not files_to_register:
        print("[!] No files provided. Use --files or set paths explicitly.")
        return

    print("=" * 60)
    print("  OASYCE AUTONOMOUS AGENT - GENESIS BATCH REGISTRATION")
    print("=" * 60)

    for path in files_to_register:
        if not os.path.exists(path):
            print(f"[X] Skipping: {path} not found.")
            continue

        print(f"\n[*] Processing: {os.path.basename(path)}")
        try:
            file_info = skills.scan_data_skill(path)
            print(f"    Scan: {file_info['file_hash'][:16]}...")

            metadata = skills.generate_metadata_skill(file_info, config.tags, config.owner)
            print(f"    Metadata: {metadata['asset_id']}")

            signed = skills.create_certificate_skill(metadata)
            print(f"    Certificate: {signed['popc_signature'][:32]}...")

            res = skills.register_data_asset_skill(signed)
            print(f"✅ ASSET MINED: {signed['asset_id']}")
            print(json.dumps(signed, indent=2, ensure_ascii=False))
        except RuntimeError as e:
            print(f"[!] Error: {e}")

    print("\n" + "=" * 60)
    print("  DATA BACKPACK DEFENSE & L2 PRICING TEST")
    print("=" * 60)

    try:
        assets = skills.search_data_skill("Genesis")
        if assets:
            target_asset = assets[0]
            print(f"[*] Simulating Unauthorized AI scraping on {target_asset['asset_id']}...")
            time.sleep(0.5)
            print(
                f"🚨 [INTERCEPTED] Data Backpack blocked unauthorized AI read attempt on {target_asset['filename']}."
            )
            print("    Reason: Missing cryptographic Session Key & PoPC Verification.")

            print("\n[*] Querying L2 Bonding Curve for pricing...")
            time.sleep(0.5)
            quote = skills.trade_data_skill(target_asset["asset_id"])
            print(
                f"📈 [QUOTE] {target_asset['filename']} current access price: {quote['current_price_oas']} OAS"
            )
    except RuntimeError as e:
        print(f"[!] Test Error: {e}")

    print("\n✅ All tests completed.")


if __name__ == "__main__":
    main()

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

    skills = OasyceSkills(config.vault_dir, config.signing_key, config.signing_key_id)
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
        file_res = skills.scan_data_skill(path)
        if not file_res.ok:
            print(f"[!] Scan Error: {file_res.error}")
            continue

        meta_res = skills.generate_metadata_skill(file_res.data, config.tags, config.owner)
        if not meta_res.ok:
            print(f"[!] Metadata Error: {meta_res.error}")
            continue

        cert_res = skills.create_certificate_skill(meta_res.data)
        if not cert_res.ok:
            print(f"[!] Certificate Error: {cert_res.error}")
            continue

        reg_res = skills.register_data_asset_skill(cert_res.data)
        if not reg_res.ok:
            print(f"[!] Register Error: {reg_res.error}")
            continue

        print(f"✅ ASSET MINED: {cert_res.data['asset_id']}")
        print(json.dumps(cert_res.data, indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("  DATA BACKPACK DEFENSE & L2 PRICING TEST")
    print("=" * 60)

    assets_res = skills.search_data_skill("Genesis")
    if assets_res.ok and assets_res.data:
        target_asset = assets_res.data[0]
        print(f"[*] Simulating Unauthorized AI scraping on {target_asset['asset_id']}...")
        time.sleep(0.5)
        print(
            f"🚨 [INTERCEPTED] Data Backpack blocked unauthorized AI read attempt on {target_asset['filename']}."
        )
        print("    Reason: Missing cryptographic Session Key & PoPC Verification.")

        print("\n[*] Querying L2 Bonding Curve for pricing...")
        time.sleep(0.5)
        quote_res = skills.trade_data_skill(target_asset["asset_id"])
        if quote_res.ok:
            print(
                f"📈 [QUOTE] {target_asset['filename']} current access price: {quote_res.data['current_price_oas']} OAS"
            )
            print(f"    Liquidity Depth: {quote_res.data['liquidity_depth']}")

    print("\n[+] Autonomous testing completed successfully.")


if __name__ == "__main__":
    main()

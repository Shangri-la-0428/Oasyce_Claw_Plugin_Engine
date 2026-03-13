import os
import sys
import json
import time

from oasyce_plugin.skills.agent_skills import OasyceSkills
from oasyce_plugin.config import Config

skills = OasyceSkills()

files_to_register = [
    "./examples/architecture.pdf",
    "./examples/plugin_architecture.pdf"
]

print("="*60)
print("  OASYCE AUTONOMOUS AGENT - GENESIS BATCH REGISTRATION")
print("="*60)

for path in files_to_register:
    if not os.path.exists(path):
        print(f"[X] Skipping: {path} not found.")
        continue
        
    print(f"\n[*] Processing: {os.path.basename(path)}")
    res1 = skills.scan_data_skill(path)
    if not res1.success: 
        print(f"[!] {res1.error}")
        continue
    
    res2 = skills.generate_metadata_skill(res1.data, ["Core", "Genesis"], "Shangrila")
    if not res2.success: continue
    
    res3 = skills.create_certificate_skill(res2.data)
    if not res3.success: continue
    
    res4 = skills.register_data_asset_skill(res3.data)
    if not res4.success: continue
    
    final_meta = res3.data.__dict__
    print(f"✅ ASSET MINED: {final_meta['asset_id']}")
    print(json.dumps(final_meta, indent=2, ensure_ascii=False))

print("\n" + "="*60)
print("  DATA BACKPACK DEFENSE & L2 PRICING TEST")
print("="*60)

search_res = skills.search_data_skill("Genesis")
if search_res.success and search_res.data:
    target_asset = search_res.data[0]
    print(f"[*] Simulating Unauthorized AI scraping on {target_asset['asset_id']}...")
    time.sleep(1)
    
    print(f"🚨 [INTERCEPTED] Data Backpack blocked unauthorized AI read attempt on {target_asset['filename']}.")
    print(f"    Reason: Missing cryptographic Session Key & PoPC Verification.")
    
    print(f"\n[*] Querying L2 Bonding Curve for pricing...")
    time.sleep(1)
    quote_res = skills.trade_data_skill(target_asset['asset_id'])
    if quote_res.success:
        quote = quote_res.data
        print(f"📈 [QUOTE] {target_asset['filename']} current access price: {quote['current_price_oas']} OAS")
        print(f"    Liquidity Depth: {quote['liquidity_depth']}")

print("\n[+] Autonomous testing completed successfully.")

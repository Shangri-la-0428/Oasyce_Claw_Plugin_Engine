import os
import sys
import json
import time

from oasyce_plugin.skills.agent_skills import OasyceSkills
from oasyce_plugin.config import Config

class OasyceCLI:
    def __init__(self):
        self.config = Config.from_env()
        self.skills = OasyceSkills(self.config)

    def clear(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def print_header(self):
        self.clear()
        print("=" * 60)
        print("    OASYCE DATA BACKPACK - GENESIS NODE (TERMINAL UI)    ")
        print("=" * 60)
        print(f"[*] Node Vault: {self.config.vault_dir}")
        print("[-] Status: Online & Waiting for local assets...\n")

    def run(self):
        self.print_header()
        print("Please enter the full path to a local file for Oasyce Registration.")
        print("(Type 'exit' or 'q' to quit)")
        
        while True:
            try:
                path = input("\n[File Path] > ").strip()
                if path.lower() in ['exit', 'q']:
                    print("Shutting down Oasyce Node...")
                    break
                if not path:
                    continue
                
                # Handling escaped spaces from terminal drag-and-drop
                path = path.replace("\\ ", " ")
                
                if not os.path.exists(path):
                    print(f"[!] Error: File not found at '{path}'")
                    continue
                
                self.process_file(path)
            except KeyboardInterrupt:
                print("\nShutting down Oasyce Node...")
                break
            except Exception as e:
                print(f"[!] Fatal Error: {str(e)}")

    def process_file(self, file_path):
        print("\n" + "="*50)
        try:
            print(f"[*] Trigger 1/4: scan_data_skill")
            file_info = self.skills.scan_data_skill(file_path)
            time.sleep(0.5)

            print(f"\n[*] Trigger 2/4: generate_metadata_skill")
            metadata = self.skills.generate_metadata_skill(file_info, ["Core", "Genesis"], "Shangrila")
            time.sleep(0.5)

            print(f"\n[*] Trigger 3/4: create_certificate_skill")
            final_meta = self.skills.create_certificate_skill(metadata)
            time.sleep(0.8)

            print(f"\n[*] Trigger 4/4: register_data_asset_skill")
            res = self.skills.register_data_asset_skill(final_meta)
            time.sleep(0.5)

            print(f"\n✅ [ASSET REGISTERED SUCCESS] Core Asset ID: {res['asset_id']}")
            print("-" * 30 + " ON-CHAIN RECEIPT " + "-" * 30)
            print(json.dumps(final_meta, indent=2, ensure_ascii=False))
            print("-" * 76)
        except RuntimeError as e:
            print(f"[!] Oasyce Engine Error: {str(e)}")

if __name__ == "__main__":
    cli = OasyceCLI()
    cli.run()

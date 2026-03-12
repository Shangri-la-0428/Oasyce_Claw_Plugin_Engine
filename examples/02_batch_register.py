#!/usr/bin/env python3
"""
示例 2: 批量注册 + L2 询价

演示批量注册文件并查询 L2 定价。
"""

from oasyce_plugin.config import Config
from oasyce_plugin.skills.agent_skills import OasyceSkills

def main():
    config = Config.from_env()
    skills = OasyceSkills(config)
    
    # 批量文件列表
    files_to_register = [
        "/path/to/file1.pdf",
        "/path/to/file2.md",
        "/path/to/file3.txt",
    ]
    
    print("=" * 60)
    print("  批量资产注册演示")
    print("=" * 60)
    
    # === 批量注册 ===
    registered_assets = []
    
    for file_path in files_to_register:
        try:
            print(f"\n📝 注册：{file_path}")
            
            file_info = skills.scan_data_skill(file_path)
            metadata = skills.generate_metadata_skill(
                file_info,
                tags=["Batch", "Demo"],
                owner="Shangrila"
            )
            signed = skills.create_certificate_skill(metadata)
            result = skills.register_data_asset_skill(signed)
            
            registered_assets.append(signed['asset_id'])
            print(f"   ✅ {signed['asset_id']}")
            
        except RuntimeError as e:
            print(f"   ❌ 失败：{e}")
    
    # === L2 询价 ===
    print("\n" + "=" * 60)
    print("  L2 定价查询")
    print("=" * 60)
    
    for asset_id in registered_assets:
        try:
            quote = skills.trade_data_skill(asset_id)
            print(f"\n📈 {asset_id}:")
            print(f"   当前价格：{quote.get('current_price_oas', 'N/A')} OAS")
            print(f"   滑点：{quote.get('price_impact', 0):.2%}")
        except RuntimeError as e:
            print(f"   ❌ 询价失败：{e}")
    
    # === 搜索已注册资产 ===
    print("\n" + "=" * 60)
    print("  搜索资产 (tag: Batch)")
    print("=" * 60)
    
    assets = skills.search_data_skill("Batch")
    print(f"找到 {len(assets)} 个资产:")
    for asset in assets:
        print(f"  - {asset['asset_id']}: {asset['filename']}")


if __name__ == "__main__":
    main()

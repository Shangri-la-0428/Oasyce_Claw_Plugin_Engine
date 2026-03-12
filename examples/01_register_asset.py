#!/usr/bin/env python3
"""
示例 1: 基础资产注册流程

演示如何使用 Oasyce SDK 注册单个文件。
"""

from oasyce_plugin.config import Config
from oasyce_plugin.skills.agent_skills import OasyceSkills

def main():
    # 方法 1: 使用环境变量或 .env 文件配置（推荐）
    config = Config.from_env()
    skills = OasyceSkills(config)
    
    # 方法 2: 或者显式指定配置
    # config = Config.from_env(
    #     vault_dir="~/my_vault",
    #     owner="Alice",
    #     tags="Personal,Important",
    #     signing_key="your-secret-key",
    #     signing_key_id="my_key_001"
    # )
    
    # 要注册的文件路径
    file_path = "/path/to/your/file.pdf"
    
    print(f"📝 注册文件：{file_path}")
    
    # Step 1: 扫描文件（计算哈希）
    print("  Step 1/4: 扫描文件...")
    file_info = skills.scan_data_skill(file_path)
    print(f"    ✓ 哈希：{file_info['file_hash'][:16]}...")
    
    # Step 2: 生成元数据
    print("  Step 2/4: 生成元数据...")
    metadata = skills.generate_metadata_skill(
        file_info,
        tags=["Example", "Demo"],
        owner="Shangrila"
    )
    print(f"    ✓ Asset ID: {metadata['asset_id']}")
    
    # Step 3: 创建物理证书 (PoPC)
    print("  Step 3/4: 签名证书...")
    signed = skills.create_certificate_skill(metadata)
    print(f"    ✓ 签名：{signed['popc_signature'][:32]}...")
    
    # Step 4: 注册到 Genesis Vault
    print("  Step 4/4: 注册到账本...")
    result = skills.register_data_asset_skill(signed)
    print(f"    ✓ 账本路径：{result['vault_path']}")
    
    print(f"\n✅ 注册成功！")
    print(f"   Asset ID: {signed['asset_id']}")
    print(f"   所有者：{signed['owner']}")
    print(f"   标签：{', '.join(signed['tags'])}")


if __name__ == "__main__":
    main()

"""
示例 04: 隐私过滤器和 IPFS 存储

演示：
1. PrivacyFilter 自动识别敏感文件
2. 批量过滤文件列表
3. 使用可插拔存储后端注册资产
"""

import os
import tempfile
from oasyce.config import Config
from oasyce.skills.agent_skills import OasyceSkills
from oasyce.engines.core_engines import PrivacyFilter
from oasyce.storage.ipfs_client import IPFSClient


def demo_privacy_filter():
    """演示隐私过滤器"""
    print("\n" + "=" * 60)
    print("🛡️  隐私过滤器演示")
    print("=" * 60)

    # 测试敏感文件
    test_files = [
        "/photos/vacation.jpg",  # 正常文件
        "/docs/身份证扫描.png",  # 敏感：身份证
        "/notes/meeting.md",  # 正常文件
        "/private/key.pem",  # 敏感：私钥
        "/backup/银行卡复印件.pdf",  # 敏感：银行卡
        "/projects/code.py",  # 正常文件
    ]

    print("\n📋 批量过滤测试：")
    for file_path in test_files:
        result = PrivacyFilter.is_sensitive_file(file_path)
        status = "🔒 阻止" if result.data["is_sensitive"] else "✅ 允许"
        print(f"  {status} {file_path}")
        if result.data["is_sensitive"]:
            print(f"       原因：{result.data['reason']}")

    # 批量过滤 API
    print("\n📦 批量过滤 API：")
    result = PrivacyFilter.filter_batch(test_files)
    print(f"  总计：{result.data['total_scanned']} 个文件")
    print(f"  允许：{result.data['total_allowed']} 个")
    print(f"  阻止：{result.data['total_blocked']} 个")
    print(f"  阻止列表：{result.data['blocked']}")


def demo_scan_with_privacy_check():
    """演示带隐私检查的扫描"""
    print("\n" + "=" * 60)
    print("🔍 带隐私检查的文件扫描演示")
    print("=" * 60)

    # 创建临时文件
    with tempfile.TemporaryDirectory() as tmpdir:
        # 正常文件
        normal_file = os.path.join(tmpdir, "normal_photo.jpg")
        with open(normal_file, "w") as f:
            f.write("test content")

        # 敏感文件
        sensitive_file = os.path.join(tmpdir, "身份证.jpg")
        with open(sensitive_file, "w") as f:
            f.write("sensitive content")

        # 扫描正常文件
        print(f"\n📄 扫描正常文件：{normal_file}")
        from oasyce.engines.core_engines import DataEngine

        result = DataEngine.scan_data_with_privacy_check(normal_file)
        if result.ok:
            print(f"  ✅ 扫描成功，哈希：{result.data['file_hash'][:16]}...")
        else:
            print(f"  ❌ 扫描失败：{result.error}")

        # 扫描敏感文件
        print(f"\n📄 扫描敏感文件：{sensitive_file}")
        result = DataEngine.scan_data_with_privacy_check(sensitive_file)
        if result.ok:
            print(f"  ✅ 扫描成功")
        else:
            print(f"  🔒 被隐私过滤器阻止：{result.error}")


def demo_ipfs_storage():
    """演示 IPFS 可插拔存储"""
    print("\n" + "=" * 60)
    print("🌐 IPFS 可插拔存储演示")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试文件
        test_file = os.path.join(tmpdir, "test_asset.md")
        with open(test_file, "w") as f:
            f.write("# Test Asset\n\nThis is a test document.")

        vault_path = os.path.join(tmpdir, "vault")
        storage_dir = os.path.join(tmpdir, "storage")

        # 使用本地存储
        print("\n📦 使用 LocalStorage 注册资产：")
        client = IPFSClient(storage_type="local", storage_dir=storage_dir)

        metadata = {
            "asset_id": "OAS_DEMO123",
            "filename": "test_asset.md",
            "owner": "Alice",
            "tags": ["demo", "test"],
            "timestamp": 1773320602,
        }

        result = client.register_asset_with_storage(
            file_path=test_file,
            metadata=metadata,
            vault_path=vault_path,
        )

        if result["success"]:
            print(f"  ✅ 注册成功")
            print(f"  Asset ID: {result['asset_id']}")
            print(f"  CID: {result['cid']}")
            print(f"  存储后端：{result['storage_backend']}")
            print(f"  Vault 路径：{result['vault_path']}")
        else:
            print(f"  ❌ 注册失败：{result.get('error')}")

        # 下载文件
        print("\n📥 从存储后端下载文件：")
        cid = result["cid"]
        download_path = os.path.join(tmpdir, "downloaded.md")
        download_result = client.download(cid, download_path)

        if download_result["success"]:
            print(f"  ✅ 下载成功")
            print(f"  保存路径：{download_result['dest_path']}")
            print(f"  文件大小：{download_result['size']} bytes")
        else:
            print(f"  ❌ 下载失败：{download_result.get('error')}")


def demo_agent_skills_integration():
    """演示 Agent Skills 集成"""
    print("\n" + "=" * 60)
    print("🧠 Agent Skills 集成演示")
    print("=" * 60)

    # 配置（使用临时目录）
    with tempfile.TemporaryDirectory() as tmpdir:
        config = Config.from_env(
            vault_dir=os.path.join(tmpdir, "vault"),
            owner="DemoUser",
            tags="demo,test",
            signing_key="demo_secret_key_12345",
            signing_key_id="demo_key_001",
        )

        skills = OasyceSkills(config)

        # 创建测试文件
        test_file = os.path.join(tmpdir, "demo_doc.pdf")
        with open(test_file, "w") as f:
            f.write("%PDF-1.4\nTest PDF content")

        print("\n📝 完整注册流程（带隐私检查）：")

        # 1. 扫描（自动隐私检查）
        print("  1️⃣  扫描文件...")
        file_info = skills.scan_data_skill(test_file)
        print(f"      ✅ 哈希：{file_info['file_hash'][:16]}...")

        # 2. 分类
        print("  2️⃣  AI 分类...")
        classification = skills.classify_data_skill(file_info)
        print(f"      类别：{classification['category']}, 敏感度：{classification['sensitivity']}")

        # 3. 生成元数据
        print("  3️⃣  生成元数据...")
        metadata = skills.generate_metadata_skill(
            file_info, tags=["demo", "test"], classification=classification
        )
        print(f"      Asset ID: {metadata['asset_id']}")

        # 4. 创建证书
        print("  4️⃣  创建 PoPC 证书...")
        signed = skills.create_certificate_skill(metadata)
        print(f"      ✅ 签名：{signed['popc_signature'][:16]}...")

        # 5. 注册资产（带存储）
        print("  5️⃣  注册资产并存储...")
        result = skills.register_data_asset_skill(
            signed, file_path=test_file, storage_backend="local"
        )
        print(f"      ✅ 注册成功")
        print(f"      存储 CID: {result.get('storage_cid', 'N/A')}")
        print(f"      存储后端：{result.get('storage_backend', 'N/A')}")


if __name__ == "__main__":
    print("\n" + "🦎 Oasyce Client - 新特性演示")
    print("=" * 60)

    demo_privacy_filter()
    demo_scan_with_privacy_check()
    demo_ipfs_storage()
    demo_agent_skills_integration()

    print("\n" + "=" * 60)
    print("✅ 所有演示完成！")
    print("=" * 60 + "\n")

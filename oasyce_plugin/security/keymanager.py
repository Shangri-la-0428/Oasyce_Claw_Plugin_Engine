"""
Oasyce 密钥管理模块 - 安全生产级密钥生成与存储

提供强随机密钥生成和系统集成密钥存储（macOS Keychain / 1Password）。
"""

import logging
import secrets
import hashlib
import subprocess
import sys

_logger = logging.getLogger(__name__)
from typing import Optional, Tuple


def generate_signing_key(length: int = 32) -> str:
    """
    生成强随机签名密钥。
    
    Args:
        length: 密钥字节长度（默认 32 字节 = 256 位）
    
    Returns:
        十六进制编码的密钥字符串（64 字符）
    """
    return secrets.token_hex(length)


def validate_key_strength(key: str) -> Tuple[bool, str]:
    """
    验证密钥强度。
    
    Returns:
        (是否合格, 建议信息)
    """
    if len(key) < 32:
        return False, "密钥长度不足 32 字符，建议使用 64 字符（256 位）"
    
    # 检查熵（简单启发式）
    unique_chars = len(set(key))
    if unique_chars < 10:
        return False, "密钥熵值过低，可能不够随机"
    
    if key in ["DEFAULT_INSECURE_DEV_KEY_0x123", "your-secret-key", ""]:
        return False, "使用了默认/示例密钥，生产环境请生成新密钥"
    
    return True, "密钥强度合格"


class KeychainStorage:
    """macOS Keychain 集成 - 安全存储密钥。"""
    
    def __init__(self, service_name: str = "Oasyce"):
        self.service_name = service_name
    
    def store_key(self, key_id: str, key_value: str) -> bool:
        """存储密钥到 Keychain。"""
        try:
            cmd = [
                "security", "add-generic-password",
                "-a", "Oasyce",
                "-s", f"{self.service_name}:{key_id}",
                "-w", key_value,
                "-U"  # 更新已有条目
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            _logger.error("Keychain 存储失败：%s", e)
            return False
    
    def get_key(self, key_id: str) -> Optional[str]:
        """从 Keychain 读取密钥。"""
        try:
            cmd = [
                "security", "find-generic-password",
                "-a", "Oasyce",
                "-s", f"{self.service_name}:{key_id}",
                "-w"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except Exception as e:
            _logger.error("Keychain 读取失败：%s", e)
            return None
    
    def delete_key(self, key_id: str) -> bool:
        """从 Keychain 删除密钥。"""
        try:
            cmd = [
                "security", "delete-generic-password",
                "-a", "Oasyce",
                "-s", f"{self.service_name}:{key_id}"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            return result.returncode == 0
        except Exception as e:
            _logger.error("Keychain 删除失败：%s", e)
            return False


def interactive_key_setup() -> str:
    """
    交互式密钥设置向导。
    
    Returns:
        设置好的密钥（存储到 Keychain 或环境变量）
    """
    print("=" * 60)
    print("  Oasyce 密钥设置向导")
    print("=" * 60)
    print()
    
    # 生成新密钥
    print("1️⃣  生成新密钥...")
    new_key = generate_signing_key()
    print(f"   已生成 256 位强随机密钥：")
    print(f"   {new_key}")
    print()
    
    # 验证强度
    is_valid, message = validate_key_strength(new_key)
    print(f"2️⃣  密钥验证：{message}")
    print()
    
    # 询问存储方式
    print("3️⃣  选择存储方式:")
    print("   [1] macOS Keychain（推荐，最安全）")
    print("   [2] 1Password（需手动复制）")
    print("   [3] 仅显示，自行处理")
    print()
    
    choice = input("请选择 (1/2/3): ").strip()
    
    if choice == "1":
        # 尝试存储到 Keychain
        keychain = KeychainStorage()
        key_id = "signing_key_001"
        if keychain.store_key(key_id, new_key):
            print(f"✅ 密钥已安全存储到 Keychain")
            print(f"   以后使用时自动读取，无需手动配置")
            print(f"   设置环境变量：OASYCE_SIGNING_KEY_ID={key_id}")
            return new_key
        else:
            print("⚠️  Keychain 存储失败，回退到选项 3")
    
    elif choice == "2":
        print("✅ 请将以下信息保存到 1Password:")
        print(f"   标题：Oasyce Signing Key")
        print(f"   密钥：{new_key}")
        print(f"   密钥 ID: signing_key_001")
    
    # 选项 3 或回退
    print()
    print("⚠️  请安全保存密钥（建议存入密码管理器）:")
    print(f"   {new_key}")
    print()
    print("然后在 .env 文件中配置:")
    print(f"   OASYCE_SIGNING_KEY={new_key}")
    print(f"   OASYCE_SIGNING_KEY_ID=signing_key_001")
    
    return new_key


if __name__ == "__main__":
    # 命令行运行此脚本时启动交互式设置
    interactive_key_setup()

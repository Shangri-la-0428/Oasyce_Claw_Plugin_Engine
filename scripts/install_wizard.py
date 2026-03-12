#!/usr/bin/env python3
"""
Oasyce 交互式安装向导
====================

给非技术用户的福利：跟着提示回答几个问题，自动完成配置！

使用方法:
    python scripts/install_wizard.py
"""

import os
import sys
import secrets
import shutil
from pathlib import Path


def print_header(text: str):
    """打印漂亮的标题。"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60 + "\n")


def print_step(step: int, text: str):
    """打印步骤提示。"""
    print(f"\n【步骤 {step}】{text}\n")


def ask_question(question: str, default: str = None) -> str:
    """问问题，支持默认值。"""
    if default:
        answer = input(f"{question} [{default}]: ").strip()
        return answer if answer else default
    else:
        return input(f"{question}: ").strip()


def generate_key() -> str:
    """生成强随机密钥。"""
    return secrets.token_hex(32)


def check_prerequisites() -> bool:
    """检查前置条件。"""
    print_step(0, "检查环境")
    
    # 检查 Python 版本
    if sys.version_info < (3, 9):
        print(f"❌ Python 版本过低 (当前 {sys.version_info.major}.{sys.version_info.minor})")
        print("   需要 Python 3.9 或更高版本")
        print("   下载地址：https://www.python.org/downloads/")
        return False
    
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")
    
    # 检查是否已安装依赖
    try:
        import dotenv
        print("✅ 依赖包已安装")
    except ImportError:
        print("⚠️  依赖包未安装，正在安装...")
        os.system("pip install python-dotenv")
    
    return True


def configure_vault() -> str:
    """配置数据账本目录。"""
    print("选择一个目录存放你的数字资产凭证。")
    print("建议：创建一个新目录，专门用于存储 Oasyce 资产。\n")
    
    default_vault = str(Path.home() / "oasyce" / "genesis_vault")
    vault_dir = ask_question("账本目录路径", default_vault)
    
    # 创建目录
    vault_path = Path(vault_dir).expanduser()
    vault_path.mkdir(parents=True, exist_ok=True)
    
    print(f"✅ 已创建：{vault_path}")
    
    return str(vault_path)


def configure_owner() -> str:
    """配置所有者名称。"""
    print("给你的资产设置一个所有者名称。")
    print("这将是你的名字/笔名/公司名，显示在资产证书上。\n")
    
    default_owner = "Creator"
    owner = ask_question("所有者名称", default_owner)
    
    print(f"✅ 所有者：{owner}")
    
    return owner


def configure_tags() -> str:
    """配置默认标签。"""
    print("给你的资产设置默认标签，方便后续搜索。")
    print("多个标签用逗号分隔，例如：Core,Genesis,Important\n")
    
    default_tags = "Core,Genesis"
    tags = ask_question("默认标签", default_tags)
    
    print(f"✅ 默认标签：{tags}")
    
    return tags


def configure_security() -> tuple:
    """配置安全选项。"""
    print("密钥管理方式选择：\n")
    print("  [1] macOS Keychain（最安全，推荐 Mac 用户）")
    print("  [2] 1Password / 密码管理器（推荐）")
    print("  [3] 仅显示密钥，我自己保存（手动复制）\n")
    
    choice = ask_question("选择密钥管理方式 [1/2/3]", "2")
    
    # 生成密钥
    print("\n正在生成强随机密钥...")
    signing_key = generate_key()
    signing_key_id = "key_" + secrets.token_hex(4)
    
    print(f"✅ 已生成 256 位密钥：{signing_key[:32]}...")
    
    if choice == "1":
        # 尝试存储到 Keychain
        try:
            import subprocess
            cmd = [
                "security", "add-generic-password",
                "-a", "Oasyce",
                "-s", f"Oasyce:{signing_key_id}",
                "-w", signing_key,
                "-U"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print("✅ 密钥已安全存储到 macOS Keychain")
            else:
                print("⚠️  Keychain 存储失败，回退到选项 3")
        except Exception as e:
            print(f"⚠️  Keychain 不可用：{e}")
    
    elif choice == "2":
        print("\n📋 请将以下信息保存到 1Password:")
        print(f"   标题：Oasyce Signing Key")
        print(f"   用户名：{signing_key_id}")
        print(f"   密码：{signing_key}")
        print(f"   分类：密码\")
        input("\n   保存好后按回车继续...")
    
    else:
        print("\n⚠️  请安全保存以下信息（建议截图或抄写）:")
        print(f"   密钥 ID: {signing_key_id}")
        print(f"   密钥：{signing_key}")
        print("\n   ⚠️  丢失后无法恢复！")
        input("\n   保存好后按回车继续...")
    
    return signing_key, signing_key_id


def write_config(vault_dir: str, owner: str, tags: str, signing_key: str, signing_key_id: str):
    """写入配置文件。"""
    print_step(6, "写入配置")
    
    env_content = f"""# Oasyce 配置文件
# 由 install_wizard.py 自动生成于 {Path.home()}

# === 基础配置 ===
OASYCE_VAULT_DIR={vault_dir}
OASYCE_OWNER={owner}
OASYCE_TAGS={tags}

# === 安全配置 ===
OASYCE_SIGNING_KEY={signing_key}
OASYCE_SIGNING_KEY_ID={signing_key_id}

# === 日志配置 ===
OASYCE_LOG_LEVEL=INFO
# OASYCE_LOG_FILE=~/.oasyce/oasyce.log
"""
    
    env_path = Path(".env")
    env_path.write_text(env_content)
    
    print(f"✅ 配置文件已写入：{env_path.absolute()}")
    print("   ⚠️  不要将此文件提交到 Git！")


def run_quickstart() -> bool:
    """运行快速验证。"""
    print_step(7, "验证安装")
    print("正在运行快速验证测试...\n")
    
    result = os.system("python scripts/quickstart.py")
    
    if result == 0:
        print("\n✅ 所有检查通过！Oasyce 已就绪\n")
        return True
    else:
        print("\n⚠️  验证未完全通过，但不影响基本使用\n")
        return False


def print_next_steps():
    """打印下一步指引。"""
    print_header("🎉 安装完成！")
    
    print("""
接下来你可以：

1️⃣  注册你的第一个文件
    oasyce register ~/Desktop/我的文件.pdf

2️⃣  查看帮助
    oasyce --help

3️⃣  阅读详细文档
    打开：https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine

4️⃣  遇到问题？
    提 issue: https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/issues

""")


def main():
    """主函数。"""
    print_header("🦎 Oasyce 插件安装向导")
    
    print("""
欢迎使用 Oasyce 插件！

这个向导会帮你完成所有配置，全程约 2 分钟。
跟着提示回答几个问题就行，不用担心技术细节。

    """)
    
    input("按回车开始...")
    
    # 检查前置条件
    if not check_prerequisites():
        print("\n❌ 环境检查失败，请先解决上述问题后重新运行。")
        sys.exit(1)
    
    # 配置步骤
    vault_dir = configure_vault()
    owner = configure_owner()
    tags = configure_tags()
    signing_key, signing_key_id = configure_security()
    
    # 写入配置
    write_config(vault_dir, owner, tags, signing_key, signing_key_id)
    
    # 验证安装
    run_quickstart()
    
    # 下一步指引
    print_next_steps()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 安装已取消。随时可以重新运行：python scripts/install_wizard.py")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 安装过程出错：{e}")
        print("\n请截图并发到 GitHub Issues 寻求帮助。")
        sys.exit(1)

#!/usr/bin/env python3
"""
快速验证脚本 - 验证 Oasyce 安装和配置是否正确

使用方法:
    python scripts/quickstart.py

如果一切正常，将输出:
    ✅ 所有检查通过！Oasyce 已就绪
"""

import sys
import os
from pathlib import Path

def check_python_version():
    """检查 Python 版本 >= 3.9"""
    print("1️⃣  检查 Python 版本...", end=" ")
    if sys.version_info < (3, 9):
        print(f"❌ 需要 Python 3.9+, 当前 {sys.version_info.major}.{sys.version_info.minor}")
        return False
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor}")
    return True

def check_dependencies():
    """检查依赖包"""
    print("2️⃣  检查依赖包...", end=" ")
    try:
        import dotenv
        import pytest
        print("✅ 所有依赖已安装")
        return True
    except ImportError as e:
        print(f"❌ 缺少依赖：{e.name}")
        print("   运行：pip install -e .")
        return False

def check_imports():
    """检查核心模块导入"""
    print("3️⃣  检查模块导入...", end=" ")
    try:
        from oasyce_plugin.config import Config
        from oasyce_plugin.skills.agent_skills import OasyceSkills
        from oasyce_plugin.cli import main
        print("✅ 核心模块正常")
        return True
    except ImportError as e:
        print(f"❌ 导入失败：{e}")
        return False

def check_env():
    """检查环境配置"""
    print("4️⃣  检查环境配置...", end=" ")
    
    env_file = Path(".env")
    env_example = Path(".env.example")
    
    if not env_file.exists():
        if env_example.exists():
            print(f"⚠️  未找到 .env 文件")
            print(f"   运行：cp .env.example .env")
            print(f"   然后编辑 .env 文件填入配置")
            return None  # 警告但不失败
        else:
            print(f"❌ 未找到 .env 或 .env.example")
            return False
    
    # 检查必填配置
    required_vars = ["OASYCE_VAULT_DIR", "OASYCE_OWNER", "OASYCE_SIGNING_KEY"]
    missing = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        print(f"⚠️  缺少配置：{', '.join(missing)}")
        print(f"   请编辑 .env 文件补充配置")
        return None
    
    print("✅ 配置完整")
    return True

def test_registration():
    """测试完整注册流程"""
    print("5️⃣  测试注册流程...", end=" ")
    
    try:
        from oasyce_plugin.config import Config
        from oasyce_plugin.skills.agent_skills import OasyceSkills
        import tempfile
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Oasyce quickstart test file")
            temp_file = f.name
        
        try:
            config = Config.from_env()
            skills = OasyceSkills(config)
            
            # 执行注册流程
            file_info = skills.scan_data_skill(temp_file)
            metadata = skills.generate_metadata_skill(file_info, ["Test"], "QuickStart")
            signed = skills.create_certificate_skill(metadata)
            
            print("✅ 注册流程正常")
            return True
        finally:
            # 清理临时文件
            os.unlink(temp_file)
            
    except Exception as e:
        print(f"❌ 测试失败：{e}")
        return False

def main():
    print("=" * 60)
    print("  Oasyce Claw Plugin Engine - 快速验证")
    print("=" * 60)
    print()
    
    checks = [
        check_python_version(),
        check_dependencies(),
        check_imports(),
        check_env(),  # 可能返回 None (警告)
        test_registration(),
    ]
    
    print()
    print("=" * 60)
    
    # 统计结果
    passed = sum(1 for c in checks if c is True)
    warnings = sum(1 for c in checks if c is None)
    failed = sum(1 for c in checks if c is False)
    
    if failed == 0:
        print(f"✅ 所有检查通过！Oasyce 已就绪 ({passed} 通过, {warnings} 警告)")
        print()
        print("下一步:")
        print("  - 运行：oasyce --help  查看 CLI 帮助")
        print("  - 运行：oasyce register /path/to/file.pdf  注册文件")
        print("  - 查看：examples/ 目录获取示例代码")
        return 0
    else:
        print(f"❌ {failed} 项检查失败，请先修复问题")
        print()
        print("帮助:")
        print("  - 安装依赖：pip install -e .")
        print("  - 配置环境：cp .env.example .env")
        print("  - 查看文档：README.md")
        return 1

if __name__ == "__main__":
    sys.exit(main())

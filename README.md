# 🦎 Oasyce Claw Plugin Engine

<div align="center">

**面向 AGI 时代的数据确权与隐私清算协议**

[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Proprietary-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-9%20passed-brightgreen.svg)](tests/)

📜 本地数据 Backpack | 🔐 PoPC 物理证书 | 💰 L2 动态定价 | 🧠 Agent Skills 集成

[安装](#-快速安装) • [使用](#-使用方法) • [示例](#-示例代码) • [API 文档](#-api-参考) • [FAQ](#-常见问题)

</div>

---

## 🌟 这是什么？

**Oasyce Claw Plugin Engine** 是一个本地数据网关，让你的 AI Agent 能够：

1. **📦 数据确权** - 扫描本地文件，生成 SHA-256 哈希，创建 PoPC 物理证书
2. **🛡️ 访问控制** - 拦截未授权的 AI 读取，需要密码学验证
3. **💰 动态定价** - 基于 Bonding Curve 的 L2 访问定价
4. **🤖 Agent 集成** - 作为 OpenClaw Skill，用自然语言调用

### 适用场景

| 场景 | 痛点 | Oasyce 方案 |
|------|------|-------------|
| 个人文档保护 | AI 随意读取本地 PDF/笔记 | 需 Session Key + PoPC 验证 |
| 知识付费 | 内容被免费爬取 | L2 定价，按访问付费 |
| 企业数据网关 | 敏感数据泄露风险 | 本地确权 + 加密签名 |
| 创作者经济 | 作品版权归属难证明 | 时间戳 + 哈希存证 |

---

## 🚀 快速安装

### 方式 1: 从 GitHub 安装（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine.git
cd Oasyce_Claw_Plugin_Engine

# 2. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -e .
```

### 方式 2: 从 PyPI 安装（即将发布）

```bash
pip install oasyce-claw-plugin-engine
```

### 验证安装

```bash
# CLI 命令可用
oasyce --help

# Python 导入正常
python -c "from oasyce_plugin.skills.agent_skills import OasyceSkills; print('✅ 安装成功')"
```

---

## ⚙️ 配置

### 方式 1: .env 文件（推荐）

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件
nano .env  # 或用你喜欢的编辑器
```

**必填配置**：
```env
# 数据账本目录（存放已注册资产的 JSON 凭证）
OASYCE_VAULT_DIR=~/oasyce/genesis_vault

# 资产所有者名称
OASYCE_OWNER=YourName

# HMAC-SHA256 签名私钥（⚠️ 生产环境请使用强随机密钥！）
OASYCE_SIGNING_KEY=your-secret-key-here

# 签名密钥标识符
OASYCE_SIGNING_KEY_ID=my_key_001
```

### 方式 2: 环境变量

```bash
export OASYCE_VAULT_DIR=~/oasyce/genesis_vault
export OASYCE_OWNER=YourName
export OASYCE_SIGNING_KEY=your-secret-key
export OASYCE_SIGNING_KEY_ID=my_key_001
```

### ⚠️ 安全提醒

- **开发环境**: 可使用示例密钥 `DEFAULT_INSECURE_DEV_KEY_0x123`
- **生产环境**: 必须生成强随机密钥（至少 32 字符）
- **密钥管理**: 考虑使用 1Password / macOS Keychain 存储密钥

---

## 📖 使用方法

### 方法 1: CLI 命令行（适合脚本）

```bash
# 1. 注册文件
oasyce register /path/to/file.pdf --owner "YourName" --tags "Core,Genesis"

# 2. 搜索资产
oasyce search Genesis

# 3. 查询 L2 价格
oasyce quote OAS_6596A36F

# 4. 验证证书
oasyce verify OAS_6596A36F

# 5. JSON 输出（适合脚本处理）
oasyce search Core --json
```

### 方法 2: Python SDK（适合集成）

```python
from oasyce_plugin.config import Config
from oasyce_plugin.skills.agent_skills import OasyceSkills

# 初始化（自动读取 .env 或环境变量）
config = Config.from_env()
skills = OasyceSkills(config)

# 注册文件
file_info = skills.scan_data_skill("/path/to/file.pdf")
metadata = skills.generate_metadata_skill(file_info, ["Core"], "YourName")
signed = skills.create_certificate_skill(metadata)
result = skills.register_data_asset_skill(signed)

print(f"✅ Asset ID: {signed['asset_id']}")
```

### 方法 3: OpenClaw Skill（自然语言）

如果你是 OpenClaw 用户，直接对我说：

> "帮我把桌面上的白皮书用 Oasyce 确权"

我会自动调用 Oasyce Gateway Skill 完成注册。

---

## 📁 项目结构

```
Oasyce_Claw_Plugin_Engine/
├── oasyce_plugin/          # 核心代码包
│   ├── engines/            # 引擎层
│   │   ├── core_engines.py    # L1/L2 核心引擎
│   │   ├── l3_tee/           # L3 TEE 引擎 (zk-PoE)
│   │   ├── result.py         # 统一结果类型
│   │   └── schema.py         # 数据验证
│   ├── skills/             # Agent Skills 接口
│   │   └── agent_skills.py    # OasyceSkills 类
│   ├── gui/                # 终端 UI
│   │   └── app.py             # CLI 交互界面
│   ├── cli.py              # 命令行入口
│   ├── config.py           # 配置管理
│   ├── models.py           # 数据模型 (Dataclass)
│   └── logging/            # 结构化日志
├── examples/               # 使用示例
│   ├── 01_register_asset.py
│   ├── 02_batch_register.py
│   └── 03_cli_usage.py
├── tests/                  # 单元测试
│   ├── test_core_flow.py
│   ├── test_engines.py
│   └── test_l3_tee_engine.py
├── genesis_vault/          # 数据账本（注册后生成）
├── .env.example            # 配置模板
├── pyproject.toml          # 项目配置
└── README.md               # 本文档
```

---

## 🔬 示例代码

### 示例 1: 基础注册流程

```python
# 见 examples/01_register_asset.py
from oasyce_plugin.config import Config
from oasyce_plugin.skills.agent_skills import OasyceSkills

config = Config.from_env()
skills = OasyceSkills(config)

file_info = skills.scan_data_skill("/path/to/file.pdf")
metadata = skills.generate_metadata_skill(file_info, ["Demo"], "Alice")
signed = skills.create_certificate_skill(metadata)
result = skills.register_data_asset_skill(signed)

print(f"Registered: {signed['asset_id']}")
```

### 示例 2: 批量注册 + L2 询价

```python
# 见 examples/02_batch_register.py
for file_path in ["file1.pdf", "file2.md", "file3.txt"]:
    info = skills.scan_data_skill(file_path)
    meta = skills.generate_metadata_skill(info, ["Batch"], "Alice")
    signed = skills.create_certificate_skill(meta)
    skills.register_data_asset_skill(signed)

# 查询价格
quote = skills.trade_data_skill("OAS_6596A36F")
print(f"Price: {quote['current_price_oas']} OAS")
```

### 示例 3: CLI 自动化

```bash
# 批量注册
for file in *.pdf; do
    oasyce register "$file" --tags "PDF,Archive"
done

# 导出所有资产到 JSON
oasyce search Core --json > assets.json
```

---

## 🧪 测试

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行全部测试
pytest tests/ -v

# 带覆盖率测试
pytest tests/ -v --cov=oasyce_plugin --cov-report=term-missing
```

**测试覆盖**:
- ✅ 端到端注册流程
- ✅ 核心引擎单元测试
- ✅ L3 TEE 引擎测试（zk-PoE 证明生成）

---

## 📚 API 参考

### Config 类

```python
from oasyce_plugin.config import Config

# 从环境变量加载
config = Config.from_env(
    vault_dir="~/my_vault",      # 可选，默认：./genesis_vault
    owner="Alice",               # 可选，默认："Shangrila"
    tags="Core,Genesis",         # 可选，默认："Core,Genesis"
    signing_key="secret",        # 可选，默认：OASYCE_SIGNING_KEY env
    signing_key_id="key_001"     # 可选，默认：OASYCE_SIGNING_KEY_ID env
)
```

### OasyceSkills 类

```python
from oasyce_plugin.skills.agent_skills import OasyceSkills

skills = OasyceSkills(config)

# 扫描文件
file_info = skills.scan_data_skill("/path/to/file")

# 生成元数据
metadata = skills.generate_metadata_skill(file_info, ["Tag1"], "Owner")

# 创建证书
signed = skills.create_certificate_skill(metadata)

# 注册资产
result = skills.register_data_asset_skill(signed)

# 搜索资产
assets = skills.search_data_skill("TagName")

# 查询价格
quote = skills.trade_data_skill("OAS_XXXXXXXX")
```

---

## ❓ 常见问题

### Q: 注册后的资产存在哪里？
A: 默认存储在 `genesis_vault/` 目录，每个资产一个 JSON 文件（如 `OAS_6596A36F.json`）。

### Q: 如果忘记签名密钥怎么办？
A: 无法恢复已注册资产的证书验证能力。建议：
- 将密钥存储在 1Password / Keychain
- 备份 `.env` 文件到安全位置

### Q: L2 定价的 OAS 代币是什么？
A: OAS 是 Oasyce 网络的模拟代币，目前用于演示 Bonding Curve 定价机制。

### Q: 可以和真实区块链集成吗？
A: 当前版本是 Mock 实现。未来计划：
- L1: 将 PoPC 证书哈希上链（Ethereum/Solana）
- L2: 真实 Bonding Curve 智能合约
- L3: TEE 硬件集成（Intel SGX）

### Q: 如何卸载？
```bash
# 删除虚拟环境
rm -rf venv/

# 删除安装包
pip uninstall oasyce-claw-plugin-engine

# 删除配置和账本（⚠️ 不可恢复！）
rm -rf ~/.oasyce/ ~/oasyce/
```

---

## 🛣️ 路线图

| 版本 | 计划 | 时间 |
|------|------|------|
| v0.3.0 | CLI + 日志 + 配置系统 | ✅ 完成 |
| v0.4.0 | PyPI 发布 + CI/CD | 2026 Q2 |
| v0.5.0 | 区块链集成（L1 上链） | 2026 Q3 |
| v1.0.0 | 生产就绪 + 审计 | 2026 Q4 |

---

## 📄 许可证

Proprietary - 保留所有权利

---

<div align="center">

**🌱 让数据回归用户，让价值流动起来**

[GitHub](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine) • [文档](#-api-参考) • [问题反馈](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/issues)

</div>

---

## 🎁 Bonus: 交互式安装向导

如果你不想手动配置，可以用**傻瓜式安装向导**：

```bash
python scripts/install_wizard.py
```

跟着提示回答几个问题，2 分钟自动完成所有配置！

**适合**：
- 不想看文档的人
- 第一次接触命令行的人
- 想要一键搞定的人


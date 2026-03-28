# Oasyce

[![CI](https://github.com/Shangri-la-0428/oasyce-net/actions/workflows/ci.yml/badge.svg)](https://github.com/Shangri-la-0428/oasyce-net/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/oasyce)](https://pypi.org/project/oasyce/)
[![Python](https://img.shields.io/pypi/pyversions/oasyce)](https://pypi.org/project/oasyce/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> English version: [README_EN.md](README_EN.md)

**Agent 世界的产权、合同和仲裁。**

当 AI Agent 开始互相协作，问题不再是"怎么调 API"，而是：谁拥有数据？如何定价？对方作弊怎么办？如何分润？

Stripe / x402 解决了"怎么付钱"。Oasyce 解决的是"**为什么付钱是合理的**"。

| | 支付通道 (Stripe, x402) | Oasyce |
|--|------------------------|--------|
| 核心问题 | 怎么转账 | 为什么转账是合理的 |
| 数据 | 文件传输 | 金融资产（联合曲线定价 + 股份 + 版本迁移） |
| 服务调用 | API call + 付费 | 链上合同（托管 + 结算 + 仲裁） |
| 信任 | 无 / 平台背书 | 链上信用评分（时间衰减 + 可验证反馈） |
| 争议 | 人工客服 | 链上陪审投票 |

```bash
pip install oasyce
oas bootstrap         # 自更新 + 钱包 + DataVault 就绪
oas demo              # 跑一遍核心流程
oas start             # Dashboard: localhost:8420
```

打开 `http://localhost:8420`，进入GUI面板（浏览器会自动打开）。

---

## Oasyce 能帮我做什么？

### 我有数据（照片、文档、传感器数据……）

你的数据注册成**链上金融资产**，不是文件。价格随需求自动上涨（Bancor 联合曲线），持有股份 ≥1% 解锁 L1 访问权。你越早注册，成本越低。

```bash
oas register myfile.csv --owner alice --tags medical,imaging
```

### 我是 AI 开发者

你的 Agent 把能力注册为**链上服务合同**——"医学影像分析"、"翻译"、"代码审查"。每次调用：资金锁定在托管 → 你完成服务 → 100 区块挑战窗口 → 自动结算（90% 给你）。不诚实？消费者可以在窗口内发起争议，资金原路退回。

### 我想接入协议

Oasyce 是**经济协议**，不是平台。底层帮你搞定：产权（数据证券化）、合同（能力托管结算）、信用（链上声誉）、仲裁（陪审投票）。你负责产品。

---

## 30 秒体验

```bash
pip install oasyce
oas bootstrap
oas demo
```

一键跑完整个流程：**注册 -> 定价 -> 购买 -> 结算 -> 分润**。你会看到数据权利是怎么被创建和交易的。

---

## 快速开始

### 1. 安装

```bash
pip install oasyce
```

> 需要 Python 3.9+

### 2. 初始化（推荐）

```bash
oas bootstrap
```

`oas bootstrap` 会优先升级 `oasyce + odv`，确保钱包存在，验证 DataVault 可用，并为后续 `oas` / `datavault` 调用开启托管自动更新。

如需诊断环境，再运行：

```bash
oas doctor
```

### 3. 启动 Dashboard

```bash
oas start
```

浏览器自动打开 `http://localhost:8420`，进入 Dashboard — 注册数据、浏览资产、调用能力。

如需 API 服务（程序化调用），另开终端运行 `oas serve`。

或者用 Docker：

```bash
docker compose up -d
```

### 4. 注册你的第一个资产

命令行：
```bash
oas register myfile.csv --owner alice --tags medical,imaging
```

或者直接在 Dashboard 里拖拽上传。

### 5. 浏览和交易

打开 `http://localhost:8420/explore`，你能看到网络上所有的数据资产和 AI 能力。查看报价、购买份额、调用服务。

---

<!-- BEGIN GENERATED:PUBLIC_BETA -->
## Testnet（公开测试与本地沙盒）

公开测试的**唯一产品入口文档**在 [docs/public-testnet-guide.md](/Users/wutongcheng/Desktop/Net/oasyce-net/docs/public-testnet-guide.md)。真实链上接入请看 [chain.oasyce](https://chain.oasyce.com) 的链侧说明。`oas sandbox *` 只负责本地沙盒模拟，不代表真实公网测试网接入。

```bash
oas --json sandbox status   # 查看本地沙盒状态
oas --json sandbox onboard  # 本地模拟：faucet + 示例资产 + 质押
oas sandbox reset --force   # 重置本地沙盒
oas doctor --public-beta --json   # 公测发布 gate
```
<!-- END GENERATED:PUBLIC_BETA -->

---

## CLI 速查

```
oas start              # 启动 Dashboard（推荐）
oas demo               # 跑一遍完整演示
oas bootstrap          # AI-first 自更新 + 钱包 + DataVault 就绪
oas account status     # 查看这台机器绑定的 canonical account
oas account verify     # 验证这台机器的账号绑定是否一致
oas account adopt      # 显式附着到已有账号（多设备场景）
oas doctor             # 健康检查
oas update             # 升级 Oasyce + DataVault
oas info               # 项目信息、链接、架构、经济模型
oas info --section economics    # 查看经济模型详情
oas info --section architecture # 查看技术架构
oas info --json        # JSON 格式输出完整信息
```

### 数据资产

```
oas register <file>    # 注册数据资产
  --rights-type original|co_creation|licensed|collection
  --co-creators '[{"address":"A","share":60},{"address":"B","share":40}]'
oas search <tag>       # 按标签搜索
oas quote <asset_id>   # 查看 Bonding Curve 报价
oas buy <asset_id>     # 购买份额
oas sell <asset_id> --amount <n>  # 卖回份额
  --max-slippage 0.05               # 滑点保护（默认 5%）
```

多设备如果要使用**同一个经济账号**，第二台机器先执行 `oas account adopt`，再执行 `oas bootstrap` 和 `oas account verify`。完整流程见 [docs/public-testnet-guide.md](/Users/wutongcheng/Desktop/Net/oasyce-net/docs/public-testnet-guide.md) 里的“多设备使用同一账号”章节。

### 争议

```
oas dispute <id> --reason "..."     # 对资产发起争议
oas jury-vote <id> --verdict consumer|provider  # 陪审投票
oas resolve <id> --remedy delist    # 裁决争议
  --remedy delist|transfer|rights_correction|share_adjustment
  --details '{"new_owner":"0x..."}'
```

### 能力发现

```
oas discover --intents "翻译,文本处理"  # Recall->Rank 能力发现
  --tags ai,nlp --limit 5
```

### 能力市场

```
oas capability register --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx --price 0.5 --tags nlp,translation
oas capability list [--tag nlp]
oas capability invoke CAP_ID --input '{"text":"hello"}'
oas capability earnings --provider addr
```

### 任务悬赏 (AHRP)

```
oas task post "翻译这份文档" --budget 50 --deadline 3600
oas task list                                  # 查看所有任务
oas task bid TASK_ID --price 30 --seconds 1800 # 竞标
oas task select TASK_ID --agent AGENT_ID       # 选择中标者
oas task complete TASK_ID                      # 标记完成
oas task cancel TASK_ID                        # 取消任务
```

### AI 反馈

```
oas feedback "购买流程有 bug" --type bug --agent my-agent
oas feedback "建议增加批量导入" --type suggestion --json
```

### 共识与治理（链上功能）

以下命令在 **L1 链** (`oasyced`) 上运行：

```
oasyced tx staking create-validator ...              # 注册成为验证者
oasyced tx staking delegate <validator> <amount>uoas # 委托质押
oasyced tx gov submit-proposal ...                   # 提交治理提案
oasyced tx gov vote <proposal_id> yes|no|abstain     # 投票
```

完整链命令参见 [oasyce-chain](https://github.com/Shangri-la-0428/oasyce-chain)。

### 节点管理

```
oas node start         # 只启动 P2P 节点
oas node info          # 查看节点身份
oas node peers         # 列出已知节点
oas node ping <host>   # Ping 另一个节点
```

### 分级访问

```
oas access quote <asset_id>                     # 查询各级别保证金报价 (L0-L3)
oas access buy <asset_id> --level L0|L1|L2|L3   # 购买分级访问权
oas access query <asset_id>                     # L0: 聚合统计
oas access sample <asset_id>                    # L1: 脱敏片段
oas access compute <asset_id>                   # L2: TEE 执行
oas access deliver <asset_id>                   # L3: 完整交付
```

### 其他

```
oas --json sandbox status   # 本地沙盒状态
oas --json sandbox onboard  # 本地模拟：faucet + 示例资产 + stake
oas bootstrap          # AI-first 自更新 + 钱包 + DataVault 就绪
oas start --no-browser # 启动 Dashboard（不自动开浏览器）
oas explorer           # 区块浏览器（端口 8421）
oas keys generate      # 生成 Ed25519 密钥对
oas keys show          # 显示公钥
```

所有命令支持 `--json` 输出，方便程序调用。

---

## OpenClaw 用户

如果你在用 [OpenClaw](https://github.com/openclaw/openclaw)，直接跟你的 Agent 说：

```text
帮我安装 oasyce skill
```

Agent 会自动安装 Oasyce Skill，你就能用自然语言注册数据、查询资产、调用能力了。不需要敲命令行。

---

## 核心概念

| 概念 | 一句话解释 | 生活类比 |
|------|-----------|---------|
| **OAS** | 协议代币，所有交易用它结算 | 就像游乐场的游戏币 |
| **Bonding Curve** | 自动定价——买的人越多越贵 | 演唱会门票，越晚买越贵 |
| **Escrow** | 先锁钱，验收后才放款 | 淘宝的担保交易 |
| **Reputation** | 长期信誉积分，做坏事会掉 | 芝麻信用分 |
| **Capability** | Agent 挂载的可调用服务 | 外卖骑手接单——有活就干，按单收费 |
| **Rights Type** | 声明数据权利来源（原创/共创/授权/收藏） | 音乐版权里的词曲原创 vs 翻唱 |
| **Dispute** | 对侵权/盗用资产发起争议，陪审团裁决 | 淘宝的售后投诉 + 仲裁 |

### 五条铁律

1. **访问需要抵押** — 想看数据？先押钱
2. **暴露不可逆** — 你看过的数据，网络永远记得
3. **身份有代价** — 作恶记录跟着你，甩不掉
4. **数据可溯源** — 指纹水印追踪每一份拷贝
5. **责任不过期** — 出了事，不会因为时间久就没人管

---

## Dashboard

运行 `oas start` 后，浏览器自动打开 `http://localhost:8420`：

- **首页** — 注册数据资产（拖拽上传）、网络状态、收益概览
- **我的数据** — 管理你的资产和已发布能力，编辑标签，退市/终止
- **市场** — 浏览资产、查看价格、购买份额、悬赏任务、质押
- **自动化** — Agent 定时任务：自动扫描、注册、交易
- **网络** — 节点身份、指纹水印、贡献证明、AI 反馈

---

<details>
<summary><h2>架构与技术细节（点击展开）</h2></summary>

### 系统架构

```
┌──────────────────────────────────────────┐
│           oasyce-chain (Go L1)           │
│  CometBFT + x/datarights + x/settlement │
│  x/capability + x/reputation             │
│  gRPC :9090 / REST :1317                 │
├──────────────────────────────────────────┤
│           oasyce (Python v2.3.1)         │
│  CLI + Dashboard + API + Skills Bridge   │
│  Facade -> Settlement -> Ledger          │
│  1322 tests                              │
├──────────────────────────────────────────┤
│           DataVault (AI Skill)           │
│  scan -> classify -> privacy -> report   │
│  pip install oasyce + oas bootstrap      │
└──────────────────────────────────────────┘
```

### 模块分层

```
oasyce/
├── core/
│   ├── formulas.py          # Layer 0: 纯函数（Bancor 曲线、费用、陪审评分）
│   └── evidence.py          # 证据提交接口
├── storage/ledger.py        # Layer 1: 所有状态 CRUD，线程安全
├── services/
│   ├── facade.py            # Layer 3: 薄编排层（每个方法 < 15 行）
│   ├── settlement/engine.py # Layer 2: 联合曲线（委托 core/formulas.py）
│   ├── reputation/          # Layer 2: 评分 + 衰减
│   ├── access/              # Layer 2: 股权 -> 分级访问
│   ├── capability_delivery/ # 产品层: 端点注册、托管、网关、结算
│   ├── discovery/           # 产品层: Recall -> Rank + 反馈
│   ├── fingerprint.py       # 证据提供者
│   ├── watermark.py         # 证据提供者
│   └── leakage/             # 证据提供者
├── engines/
│   ├── core_engines.py      # 扫描 -> 分类 -> 元数据 -> PoPc -> 注册
│   └── risk.py              # 证据提供者: 风险分级
├── gui/app.py               # Layer 4: Dashboard
└── cli.py                   # Layer 4: CLI
```

### 经济参数

| 参数 | 值 |
|------|-----|
| 代币 | OAS |
| 联合曲线 | Bancor, CW = 0.5 |
| 引导价格 | 1 OAS/token |
| 协议费 | 5% |
| 燃烧率 | 2% |
| 储备金上限 | 95% |
| 费用分配 | 提供者 93%, 协议 5%, 燃烧 2% |

### 四种资产类型

| 类型 | 说明 | 示例 |
|------|------|------|
| **data** | 文件/数据集 | 医学影像、CSV、PDF |
| **capability** | 可调用 AI 服务 | 翻译、代码审查、图像分析 |
| **oracle** | 数据源/预言机 | 价格 feed、天气数据 |
| **identity** | 身份凭证 | DID、声誉证明 |

由 Schema Registry 统一验证，每种类型独立 schema 版本管理。

### 测试

```bash
pytest      # 1322 tests passed, 19 skipped
```

</details>

---

## 当前进度

| 仓库 | 版本 | 测试 | 状态 |
|------|------|------|------|
| **oasyce-chain** (Go L1) | Cosmos SDK v0.50.10 | 30+ | Phase A 完成 |
| **oasyce** (本仓库) | v2.3.1 | 1322 | AI-first 托管安装 + 核心流程契约已收口 |
| **DataVault** | v0.2.1 | 48 | safe-only 自动注册就绪 |

### 已完成

- 分层架构强制执行（零违规）
- Facade API 完整（quote, buy, sell, dispute, jury_vote, evidence...）
- GUI Dashboard 全功能
- 架构不变量测试（防止 facade 绕过、SQL 注入、引擎越权实例化）
- PyPI 发布自动化

### 下一步

- 白皮书 v4 参数对齐（F=0.35、费率 60/20/15/5、销毁 15%）— 需要链上 ConsensusVersion 升级
- AHRP 任务市场接入（Python facade + API + CLI 对接已有的 x/work 悬赏系统）
- 生态扩展（跨链数据权益、隐私计算、移动钱包）

---

## 文档

- [协议概览](docs/OASYCE_PROTOCOL_OVERVIEW.md)
- [经济学设计](docs/ECONOMICS.md)
- [协议规范](docs/PROTOCOL.md)
- [测试网指南](docs/TESTNET.md)

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 社区

- [Discord](https://discord.gg/tfrCn54yZW) — 提问、反馈、闲聊
- [GitHub Issues](https://github.com/Shangri-la-0428/oasyce-net/issues) — Bug 报告、功能建议

## 许可证

MIT

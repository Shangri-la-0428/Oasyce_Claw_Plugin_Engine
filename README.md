# Oasyce

[![CI](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/oasyce)](https://pypi.org/project/oasyce/)
[![Python](https://img.shields.io/pypi/pyversions/oasyce)](https://pypi.org/project/oasyce/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> English version: [README_EN.md](README_EN.md)

**数据有了主权，能力有了价格。**

Oasyce 是一个去中心化的**权利清算网络**——让 AI Agent 之间的数据访问和能力调用，每一笔都有定价、有担保、有结算。

想象一下：你拍了一张照片，AI 想用它来训练。在传统世界里，你的数据被白嫖了。在 Oasyce 里，AI 必须付费获取访问权，你自动收到收益。就像 Stripe 让互联网有了支付，Oasyce 让 AI 世界有了**权利清算层**。

```bash
pip install oasyce
oasyce doctor            # 健康检查
oasyce serve             # Dashboard: localhost:8420
```

打开 `http://localhost:8420`，进入GUI面板。

---

## Oasyce 能帮我做什么？

### 我有数据（照片、文档、传感器数据……）

你的数据可以注册成链上资产，任何 AI 访问都需要付费。越多人用，价格越高（Bonding Curve 自动定价），你越早注册赚越多。

```bash
oasyce register myfile.csv --owner alice --tags medical,imaging
```

### 我是 AI 开发者

你的 Agent 可以把能力挂载到网络上——比如"医学影像分析"、"翻译"、"代码审查"。其他 Agent 调用一次，你赚一次。质量有担保金兜底，不怕跑路。

### 我想接入协议

Oasyce 是协议，不是平台。你可以在上面建任何东西——数据交易所、Agent 劳务市场、AI 能力商店。底层帮你搞定定价、清算、信誉、争议。

---

## 30 秒体验

```bash
pip install oasyce
oasyce demo
```

一键跑完整个流程：**注册 -> 定价 -> 购买 -> 结算 -> 分润**。你会看到数据权利是怎么被创建和交易的。

---

## 快速开始

### 1. 安装

```bash
pip install oasyce
```

> 需要 Python 3.9+

### 2. 健康检查

```bash
oasyce doctor
```

自动检查密钥、端口、依赖、网络连通性。有问题会告诉你怎么修。

### 3. 启动节点

```bash
oasyce serve
```

这会启动：
- **API 服务** — 匹配、竞价、结算
- **Dashboard**（端口 8420）— 注册数据、浏览资产、调用能力

或者用 Docker：

```bash
docker compose up -d
```

### 4. 注册你的第一个资产

命令行：
```bash
oasyce register myfile.csv --owner alice --tags medical,imaging
```

或者直接在 Dashboard 里拖拽上传。

### 5. 浏览和交易

打开 `http://localhost:8420/explore`，你能看到网络上所有的数据资产和 AI 能力。查看报价、购买份额、调用服务。

---

## Testnet（测试网）

不想用真的 OAS？一键加入测试网：

```bash
oasyce testnet onboard    # 加入测试网
oasyce testnet faucet     # 领免费测试币
```

---

## CLI 速查

```
oasyce serve              # 启动一切（推荐）
oasyce demo               # 跑一遍完整演示
oasyce doctor             # 健康检查
oasyce update             # 自动更新
oasyce info               # 项目信息、链接、架构、经济模型
oasyce info --section economics    # 查看经济模型详情
oasyce info --section architecture # 查看技术架构
oasyce info --json        # JSON 格式输出完整信息
```

### 数据资产

```
oasyce register <file>    # 注册数据资产
  --rights-type original|co_creation|licensed|collection
  --co-creators '[{"address":"A","share":60},{"address":"B","share":40}]'
oasyce search <tag>       # 按标签搜索
oasyce quote <asset_id>   # 查看 Bonding Curve 报价
oasyce buy <asset_id>     # 购买份额
oasyce sell <asset_id> --amount <n>  # 卖回份额
  --max-slippage 0.05               # 滑点保护（默认 5%）
```

### 争议

```
oasyce dispute <id> --reason "..."     # 对资产发起争议
oasyce jury-vote <id> --verdict consumer|provider  # 陪审投票
oasyce resolve <id> --remedy delist    # 裁决争议
  --remedy delist|transfer|rights_correction|share_adjustment
  --details '{"new_owner":"0x..."}'
```

### 能力发现

```
oasyce discover --intents "翻译,文本处理"  # Recall->Rank 能力发现
  --tags ai,nlp --limit 5
```

### 能力市场

```
oasyce capability register --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx --price 0.5 --tags nlp,translation
oasyce capability list [--tag nlp]
oasyce capability invoke CAP_ID --input '{"text":"hello"}'
oasyce capability earnings --provider addr
```

### 共识与治理（链上功能）

以下命令在 **L1 链** (`oasyced`) 上运行，不在 Python CLI 中：

```
oasyced tx staking create-validator ...              # 注册成为验证者
oasyced tx staking delegate <validator> <amount>uoas # 委托质押
oasyced tx gov submit-proposal ...                   # 提交治理提案
oasyced tx gov vote <proposal_id> yes|no|abstain     # 投票
```

Dashboard 提供本地共识/治理状态模拟（`/api/consensus/*`、`/api/governance/*`）。完整链命令参见 [oasyce-chain](https://github.com/Shangri-la-0428/oasyce-chain)。

### 节点管理

```
oasyce node start         # 只启动 P2P 节点
oasyce node info          # 查看节点身份
oasyce node peers         # 列出已知节点
oasyce node ping <host>   # Ping 另一个节点
```

### 分级访问

```
oasyce access quote <asset_id>                     # 查询各级别保证金报价 (L0-L3)
oasyce access buy <asset_id> --level L0|L1|L2|L3   # 购买分级访问权
oasyce access query <asset_id>                     # L0: 聚合统计
oasyce access sample <asset_id>                    # L1: 脱敏片段
oasyce access compute <asset_id>                   # L2: TEE 执行
oasyce access deliver <asset_id>                   # L3: 完整交付
```

### 其他

```
oasyce testnet onboard    # 一键加入测试网
oasyce testnet faucet     # 领测试币
oasyce gui                # 只启动 Dashboard（端口 8420）
oasyce explorer           # 区块浏览器（端口 8421）
oasyce keys generate      # 生成 Ed25519 密钥对
oasyce keys show          # 显示公钥
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

运行 `oasyce serve` 后，打开 `http://localhost:8420`：

- **Overview** — 网络状态、已注册资产、交易量
- **Register** — 注册数据资产（支持拖拽上传）
- **Explore** — 浏览所有资产和能力，查看价格，购买份额
- **Market** — 分级访问市场、卖出和滑点控制
- **Watermark** — 数据指纹嵌入和泄漏追踪
- **Stake** — 质押 OAS 成为验证者

区块浏览器：`http://localhost:8421`

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
│           oasyce (Python v2.1.0)         │
│  CLI + Dashboard + API + Skills Bridge   │
│  Facade -> Settlement -> Ledger          │
│  1063 tests                              │
├──────────────────────────────────────────┤
│           DataVault (AI Skill)           │
│  scan -> classify -> privacy -> report   │
│  pip install odv[oasyce]                 │
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
pytest      # 1063 tests, 19 skipped
```

</details>

---

## 当前进度

| 仓库 | 版本 | 测试 | 状态 |
|------|------|------|------|
| **oasyce-chain** (Go L1) | Cosmos SDK v0.50.10 | 30+ | Phase A 完成 |
| **oasyce** (本仓库) | v2.1.0 | 1063 | 功能完整，架构约束强制执行 |
| **DataVault** | v0.2.0 | 44 | AI Skill 模式就绪 |

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
- [GitHub Issues](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/issues) — Bug 报告、功能建议

## 许可证

MIT

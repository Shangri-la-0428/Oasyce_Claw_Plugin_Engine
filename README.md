# Oasyce

![CI](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/actions/workflows/ci.yml/badge.svg) ![PyPI](https://img.shields.io/pypi/v/oasyce) ![Python](https://img.shields.io/pypi/pyversions/oasyce) ![License](https://img.shields.io/github/license/Shangri-la-0428/Oasyce_Claw_Plugin_Engine)

**数据有了主权，能力有了价格。**

Oasyce 是一个去中心化的**权利清算网络**——让 AI Agent 之间的数据访问和能力调用，每一笔都有定价、有担保、有结算。

想象一下：你拍了一张照片，AI 想用它来训练。在传统世界里，你的数据被白嫖了。在 Oasyce 里，AI 必须付费获取访问权，你自动收到收益。就像 Stripe 让互联网有了支付，Oasyce 让 AI 世界有了**权利清算层**。

```bash
pip install oasyce
oasyce start
```

打开 `http://localhost:8420`，完事。

<!-- TODO: Dashboard 截图 -->

---

## 🤔 Oasyce能帮我做什么？

### 👤 我有数据（照片、文档、传感器数据……）

你的数据可以注册成链上资产，任何 AI 访问都需要付费。越多人用，价格越高（Bonding Curve 自动定价），你越早注册赚越多。

```bash
oasyce register myfile.csv --owner alice --tags medical,imaging
```

### 🤖 我是 AI 开发者

你的 Agent 可以把能力挂载到网络上——比如"医学影像分析"、"翻译"、"代码审查"。其他 Agent 调用一次，你赚一次。质量有担保金兜底，不怕跑路。

### 🔌 我想接入协议

Oasyce 是协议，不是平台。你可以在上面建任何东西——数据交易所、Agent 劳务市场、AI 能力商店。底层帮你搞定定价、清算、信誉、争议。

---

## ✨ 30 秒体验

```bash
pip install oasyce
oasyce demo
```

一键跑完整个流程：**注册 → 定价 → 购买 → 结算 → 分润**。你会看到数据权利是怎么被创建和交易的。

---

## 🚀 快速开始

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
oasyce start
```

这会启动：
- **协议节点**（端口 8000）—— 匹配、竞价、结算
- **Dashboard**（端口 8420）—— 注册数据、浏览资产、调用能力

### 4. 注册你的第一个资产

命令行：
```bash
oasyce register myfile.csv --owner alice --tags medical,imaging
```

或者直接在 Dashboard 里拖拽上传。

### 5. 浏览和交易

打开 `http://localhost:8420/explore`，你能看到网络上所有的数据资产和 AI 能力。查看报价、购买份额、调用服务。

---

## 🧪 Testnet（测试网）

不想用真的 OAS？一键加入测试网：

```bash
oasyce testnet onboard    # 加入测试网
oasyce testnet faucet     # 领免费测试币
```

---

## 📋 CLI 速查

```
oasyce start              # 启动一切（推荐）
oasyce demo               # 跑一遍完整演示
oasyce doctor             # 健康检查
oasyce info               # 项目信息、链接、架构、经济模型
oasyce info --section economics    # 查看经济模型详情
oasyce info --section architecture # 查看技术架构
oasyce info --json        # JSON 格式输出完整信息

oasyce register <file>    # 注册数据资产
  --rights-type original|co_creation|licensed|collection
  --co-creators '[{"address":"A","share":60},{"address":"B","share":40}]'
oasyce search <tag>       # 按标签搜索
oasyce quote <asset_id>   # 查看 Bonding Curve 报价
oasyce buy <asset_id>     # 购买份额

oasyce dispute <id> --reason "..."     # 对资产发起争议
oasyce resolve <id> --remedy delist    # 裁决争议
  --remedy delist|transfer|rights_correction|share_adjustment
  --details '{"new_owner":"0x..."}'

oasyce discover --intents "翻译,文本处理"  # Recall→Rank 能力发现
  --tags ai,nlp --limit 5

oasyce node start         # 只启动 P2P 节点
oasyce node info          # 查看节点身份
oasyce node peers         # 列出已知节点
oasyce node ping <host>   # Ping 另一个节点

oasyce testnet onboard    # 一键加入测试网
oasyce testnet faucet     # 领测试币

oasyce gui                # 只启动 Dashboard（端口 8420）
oasyce explorer           # 区块浏览器（端口 8421）
```

所有命令支持 `--json` 输出，方便程序调用。

---

## 🦞 OpenClaw 用户

如果你在用 [OpenClaw](https://github.com/openclaw/openclaw)，直接跟你的 Agent 说：

```text
帮我安装 oasyce skill
```

Agent 会自动安装 Oasyce Skill，你就能用自然语言注册数据、查询资产、调用能力了。不需要敲命令行。

---

## 💡 核心概念

### 用人话说

| 概念 | 一句话解释 | 生活类比 |
|------|-----------|---------|
| **OAS** | 协议代币，所有交易用它结算 | 就像游乐场的游戏币 |
| **Bonding Curve** | 自动定价——买的人越多越贵 | 演唱会门票，越晚买越贵 |
| **Diminishing Returns** | 100%→80%→60%→40% 递减分润 | 防止一个人把蛋糕全吃了 |
| **Escrow** | 先锁钱，验收后才放款 | 淘宝的担保交易 |
| **Reputation** | 长期信誉积分，做坏事会掉 | 芝麻信用分 |
| **Capability** | Agent 挂载的可调用服务 | 外卖骑手接单——有活就干，按单收费 |
| **Rights Type** | 声明数据权利来源（原创/共创/授权/收藏） | 音乐版权里的词曲原创 vs 翻唱 |
| **Dispute** | 对侵权/盗用资产发起争议，仲裁者裁决 | 淘宝的售后投诉 + 仲裁 |

### 五条铁律

1. **访问需要抵押** — 想看数据？先押钱
2. **暴露不可逆** — 你看过的数据，网络永远记得
3. **身份有代价** — 作恶记录跟着你，甩不掉
4. **数据可溯源** — 指纹水印追踪每一份拷贝
5. **责任不过期** — 出了事，不会因为时间久就没人管

---

<details>
<summary><h2>🏗 架构与技术细节（点击展开）</h2></summary>

### 系统架构

```
┌─────────────────────────────────────────────────┐
│                  oasyce (PE)                     │
│  CLI · Dashboard · P2P Node · Skills · Bridge    │
│  Schema Registry · Risk Engine · Feedback Loop   │
├─────────────────────────────────────────────────┤
│               oasyce-core (Protocol)             │
│  AHRP · Settlement · Staking · Capabilities      │
│  Crypto · Reputation · Access Control · Standards │
└─────────────────────────────────────────────────┘
```

- **oasyce-core**: 协议引擎（678 tests）。匹配、托管、Bonding Curve 定价、费用分配、能力资产、争议仲裁。
- **oasyce**: 用户层（590 tests）。CLI、Dashboard、P2P 组网、Schema Registry、Discovery Recall→Rank、Feedback Loop、Risk 自动分级。

### 协议模块一览

```
oasyce_plugin/
├── schema_registry/  # 统一 Schema 验证（data / capability / oracle / identity）
├── engines/
│   ├── core_engines.py  # 扫描 → 分类 → 元数据 → PoPc → 注册（含自动风险分级）
│   ├── schema.py        # 向后兼容入口（委托 schema_registry）
│   └── risk.py          # 静态风险自动分级（public / internal / sensitive）
├── services/
│   ├── discovery/       # Recall→Rank 能力发现 + FeedbackStore 反馈循环
│   ├── settlement/      # 结算引擎
│   └── ...
├── info.py           # 项目信息中心（GUI / CLI / API 共用）
└── ...

oasyce_core/
├── ahrp/           # Agent 握手路由协议（匹配 + 竞价 + 结算）
├── capabilities/   # 能力资产（注册 → 调用 → 托管 → 结算 → 争议 → 评分 → 份额 → Pipeline）
├── oracle/         # 预言机框架（天气/价格/内部/聚合器）
├── settlement/     # Bonding Curve + 费用分配 + 递减分润
├── staking/        # 验证者质押 + Slashing
├── network/        # P2P Gossip Mesh + 节点交换 + 评分
├── services/       # 访问控制、信誉、暴露追踪、泄漏检测、验证
├── standards/      # OAS 统一资产标准（data + capability + oracle + identity）
├── crypto/         # Ed25519 签名 + Merkle 证明
├── storage/        # 账本 + IPFS
└── server.py       # FastAPI 入口
```

### 经济参数

| 参数 | 值 |
|------|-----|
| 最大供应量 | 100,000,000 OAS |
| 区块奖励 | 4 OAS |
| 费用因子 F | 0.35 |
| 费用分配 | 数据方 60% · 验证者 20% · 协议 15% · Burn 5% |
| 递减分润 | 100% → 80% → 60% → 40% |
| 最低质押 | 10,000 OAS |
| 首年通胀 | ~5.25% |

### 安全分级

| 级别 | 最低质押 | 最大数据量 | 责任窗口 |
|------|---------|-----------|---------|
| L0 | 10,000 OAS | 10 MB | 1 天 |
| L1 | 50,000 OAS | 100 MB | 3 天 |
| L2 | 200,000 OAS | 1 GB | 7 天 |
| L3 | 1,000,000 OAS | 无限 | 30 天 |

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
cd oasyce-core && pytest                    # 678 tests
cd oasyce-claw-plugin-engine && pytest      # 590 tests
```

</details>

---

## 📚 更多文档

- [协议概览](docs/OASYCE_PROTOCOL_OVERVIEW.md)
- [经济学设计](docs/ECONOMICS.md)
- [协议规范](docs/PROTOCOL.md)

## License

MIT

## Community

- [Discord](https://discord.gg/tfrCn54yZW) — 提问、反馈、闲聊
- [GitHub Issues](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/issues) — Bug 报告、功能建议

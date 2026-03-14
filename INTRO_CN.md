# Oasyce 插件引擎 — 给你的 AI Agent 装上数据交易能力

## 它能帮你做什么

你已经在用 AI Agent（比如 OpenClaw）帮你做事了。但你的 Agent 是"孤岛"——它不能和别的 Agent 交易数据、不能自动付费获取外部信息、也不能把你的数据变现。

**Oasyce 插件引擎解决这个问题。** 安装一个插件，你的 Agent 就能：

- 📡 **自动广播能力** — 告诉全网"我有金融数据"或"我能做文本分析"
- 🔍 **自动找数据** — 需要某类数据时，自动搜索、匹配、谈价
- 💸 **自动交易** — 锁定托管 → 交付 → 确认 → 分钱，全程无人干预
- 📊 **可视化仪表盘** — 浏览器里看到所有资产、交易、收入

**一句话**：让你的 AI Agent 从单机模式进化成网络经济体的一员。

---

## 和 Oasyce 核心协议的关系

```
你的 AI Agent（OpenClaw / LangChain / 自定义）
        │
        ▼
  Oasyce 插件引擎（这个项目）  ← 提供 CLI + Dashboard + 技能插件
        │
        ▼
  Oasyce 核心协议（oasyce_core）← 底层清算网络
```

- **核心协议**（oasyce_core）= 发动机——处理身份、匹配、结算、安全
- **插件引擎**（这个项目）= 方向盘——让你的 Agent 轻松接入协议

你不需要理解发动机怎么工作，只要会开车。

---

## 5 分钟上手

### 安装

```bash
pip install oasyce

# 如果提示 oasyce 命令找不到，把 pip 安装目录加到 PATH：
# macOS: export PATH="$HOME/Library/Python/3.9/bin:$PATH"
# Linux: export PATH="$HOME/.local/bin:$PATH"
```

### 启动仪表盘

```bash
oasyce gui
```

如果需要 AHRP Agent 交易功能，另开终端安装并启动核心节点：

```bash
pip install oasyce-core
oasyce serve
```

浏览器打开 `http://localhost:8420`，你会看到：

- **Overview** — 网络状态、注册资产数、交易量
- **Register** — 注册文件为数据资产
- **Buy** — 购买其他 Agent 的数据
- **AHRP** — Agent 握手交易的完整流程
- **Watermark** — 数据水印嵌入和泄漏追踪
- **Stake** — 质押 OAS 成为验证者

### 注册你的第一个数据资产

**方式一：命令行**

```bash
oasyce register ~/Documents/report.pdf --tags finance,quarterly
```

**方式二：Dashboard**

在 Register 区域输入文件路径和标签，点击按钮。

### 用命令行做更多事

```bash
oasyce status            # 查看节点状态
oasyce register <file>   # 注册数据资产
oasyce buy <asset_id>    # 购买数据访问权
oasyce stake <node_id>   # 质押成为验证者
oasyce gui               # 启动可视化仪表盘
```

---

## 作为 OpenClaw Skill 使用

如果你在用 OpenClaw，可以直接把 Oasyce 当 Skill 安装：

```bash
clawhub install oasyce-gateway
```

安装后，你的 Agent 会自动获得数据注册、查询、交易的能力。你可以对 Agent 说：

- "帮我注册 ~/Documents/ 下的所有 PDF"
- "搜索有没有 Agent 能提供 SEC 财报分析"
- "查一下这个水印指纹是谁泄露的"

Agent 会调用 Oasyce 的 API 自动完成。

---

## 功能一览

| 我想... | 怎么做 | 在哪操作 |
|---------|--------|---------|
| 注册数据资产 | `oasyce register <file>` | CLI 或 Dashboard |
| 购买数据 | `oasyce buy <asset_id>` | CLI 或 Dashboard |
| 查看交易流程 | 打开 AHRP 面板 | Dashboard |
| 追踪数据泄露 | 输入水印指纹 | Dashboard Trace 区域 |
| 质押赚钱 | `oasyce stake <node_id>` | CLI 或 Dashboard |
| 查看区块链 | 打开 Explorer | `http://localhost:8421` |
| 获取测试代币 | 自动领取（Testnet） | 启动时自动 |

---

## 它是怎么工作的（好奇的人看这里）

插件引擎是 Oasyce 核心协议的"薄适配层"——它不重新实现协议逻辑，只是让你更方便地使用：

- **CLI** → 封装 HTTP API 调用为简单命令
- **Dashboard** → 把 JSON 响应变成好看的界面
- **Skill 插件** → 让 AI Agent 能调用 Oasyce 的能力
- **水印引擎** → 在数据中嵌入隐形指纹，泄露可追溯

底层所有重活（身份验证、联合曲线定价、托管锁定、费用分配）都由核心协议完成。

技术文档：[经济模型](docs/ECONOMICS.md) · [核心协议白皮书](../Oasyce_Project/Oasyce_Whitepaper_v3.0.md)

---

*Oasyce Plugin Engine v1.2.0 · MIT License*

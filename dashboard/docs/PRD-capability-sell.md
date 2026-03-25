# PRD: Capability 市场 + 卖出报价

## 目标

补齐 dashboard 缺失的 80% — 让用户完成完整经济闭环：注册 → 定价 → 交易 → 使用 → 赚钱 → 退出。

## 现状

| 功能 | 后端 | 前端 | 缺口 |
|------|------|------|------|
| Capability 注册 | `POST /api/capability/register` | RegisterForm 有 mode="capability" | **未验证是否完整接入** |
| Capability 调用 | `POST /api/delivery/invoke` | explore-browse 已实现 | 无 |
| 调用争议 | `POST /api/delivery/invocation/{id}/dispute` | explore-browse 已实现 | 无 |
| Provider 收益 | `GET /api/delivery/earnings` | **零 UI** | **P0** |
| 调用历史 | `GET /api/delivery/invocations` | **零 UI** | **P0** |
| 卖出执行 | `POST /api/sell` | explore-portfolio 已实现 | 无 |
| 卖出报价 | `GET /api/sell/quote` | **零 UI，直接执行** | **P1** |

## 需求

### Feature 1: Provider 收益面板 (P0)

**位置**: explore 页面新增 sub-tab「收益」，或嵌入 portfolio tab

**API**: `GET /api/delivery/earnings?provider={walletAddress}`

**响应**:
```json
{
  "provider_id": "string",
  "total_earnings": 123.45,
  "invocations": 42
}
```

**UI 结构**:
```
┌─────────────────────────────────┐
│ 总收益          42 次调用        │
│ 123.45 OAS                     │
├─────────────────────────────────┤
│ 调用记录（最近 20 条）           │
│ ┌─────────────────────────────┐ │
│ │ CAP_xx..xx  2.5 OAS  3分钟前 │ │
│ │ CAP_yy..yy  1.0 OAS  1小时前 │ │
│ └─────────────────────────────┘ │
└─────────────────────────────────┘
```

**数据**: 调用历史来自 `GET /api/delivery/invocations?provider={walletAddress}&limit=20`

**空状态**: "注册一个 AI 能力，开始赚取收益"，CTA 跳转到注册

### Feature 2: 调用历史面板 (P0)

**位置**: 与收益面板合并（provider 看收益，consumer 看消费）

**API**: `GET /api/delivery/invocations?consumer={walletAddress}&limit=20`

**每条记录字段**: capability_id, status, price, timestamp, invocation_id

**交互**:
- 点击记录可展开详情（invocation_id 可复制）
- 未过挑战窗口的记录显示「争议」按钮

### Feature 3: 卖出报价预览 (P1)

**位置**: explore-portfolio 现有卖出流程中插入

**当前流程**: 输入数量 → 直接执行
**目标流程**: 输入数量 → 查看报价 → 确认执行

**API**: `GET /api/sell/quote?asset_id={id}&seller={addr}&tokens={n}`

**响应**:
```json
{
  "payout_oas": 45.2,
  "protocol_fee": 2.4,
  "burn_amount": 0.96,
  "price_impact_pct": 3.5
}
```

**UI 结构**:
```
卖出 12.5 份额
┌───────────────────────────┐
│ 预计收入    45.20 OAS     │
│ 协议费用     2.40 OAS     │
│ 销毁         0.96 OAS     │
│ 价格影响     3.5%         │
├───────────────────────────┤
│ [返回]         [确认卖出]  │
└───────────────────────────┘
```

**价格影响 > 5% 时**: 显示警告色（--yellow）

### Feature 4: Capability 注册入口 (P0)

**现状**: RegisterForm 已有 `mode="capability"` props，支持 name/endpoint/apiKey/price/tags/rateLimit

**需要验证**:
1. capability 模式的 UI 是否在 dashboard 中可达（有没有入口渲染它）
2. 提交是否调用正确的 API endpoint

**如果未接入**: 在 explore 页面 browse tab 顶部加「注册能力」按钮，点击展开 RegisterForm mode="capability"

## i18n 新增 keys

```
// 收益
'earnings-tab': '收益' / 'Earnings'
'total-earnings': '总收益' / 'Total earnings'
'total-invocations': '调用次数' / 'Invocations'
'earnings-empty': '注册 AI 能力，开始赚取收益' / 'Register a capability to start earning'
'earnings-empty-cta': '注册能力' / 'Register capability'

// 调用历史
'invocation-history': '调用记录' / 'Invocation history'
'my-invocations': '我的调用' / 'My invocations'
'invocation-empty': '调用 AI 能力后，记录将显示在这里' / 'Invoke a capability to see your history here'

// 卖出报价
'sell-quote': '卖出报价' / 'Sell quote'
'sell-payout': '预计收入' / 'Expected payout'
'sell-fee': '协议费用' / 'Protocol fee'
'sell-burn': '销毁' / 'Burned'
'sell-impact': '价格影响' / 'Price impact'
'sell-impact-warning': '价格影响较大，请确认' / 'High price impact, please confirm'
'sell-confirm': '确认卖出' / 'Confirm sell'
'sell-quoting': '计算中...' / 'Calculating...'
```

## 设计约束

- 遵循 .impeccable.md 设计系统（Geist Mono, 语义色, kv-pair 布局）
- 复用已有组件: EmptyState, Section, badge, kv, item-list
- 零内联样式
- WCAG AA 对比度
- 所有交互状态: loading skeleton, empty, error, success
- 移动端适配 (≤768px, ≤600px, ≤375px)

## 不做

- 不改后端 API
- 不加新依赖
- 不重构现有已工作的 capability 调用/争议流程
- 不做 capability 版本管理 UI（后续迭代）

# Legacy → Preact SPA 迁移清单

> 目标：将 `app.py` 内嵌 `_INDEX_HTML`（2544 行）的所有功能迁移到 `dashboard/src/` Preact SPA，迁完删除 legacy fallback。

## 页面对照

| Legacy 页面 | Legacy ID | Preact 页面 | 状态 |
|---|---|---|---|
| Register（拖拽注册+描述） | `pg-register` | `mydata.tsx` (合并) | ✅ 已有 |
| Trade（报价+购买份额） | `pg-trade` | `explore.tsx` (部分) | ⚠️ 缺购买确认流程 |
| Your Assets（资产列表+详情+删除） | `pg-assets` | `mydata.tsx` | ✅ 已有 |
| Agent Protocol（注册Agent+发现+交易） | `pg-agents` | ❌ 无 | 🔴 需新建 |
| Network（节点状态+验证者） | `pg-network` | `network.tsx` | ✅ 已有 |

## 功能模块对照

| 功能 | Legacy 位置 | Preact | 状态 |
|---|---|---|---|
| 暗黑/明亮主题 | CSS vars + toggle | `design.css` + `ui.ts` | ✅ |
| 中英文 i18n | 嵌入 dict + toggle | `ui.ts` dict + Nav | ✅ |
| 拖拽注册文件 | pg-register dropzone | `mydata.tsx` dropzone | ✅ |
| 像素网格可视化 | 无（后加） | `network-grid.tsx` | ✅ |
| Identity 面板（密钥展示+说明） | identity-card | `network.tsx`（基础） | ⚠️ 缺说明文本+密钥遮罩 |
| Buy Shares（报价→确认→结果） | pg-trade card | `explore.tsx` | ⚠️ 缺完整购买流程 |
| Portfolio（持仓查看） | pg-trade portfolio | ❌ 无 | 🔴 需新建 |
| Stake（质押验证者） | pg-trade stake | ❌ 无 | 🔴 需新建 |
| Watermark（嵌入/提取/追踪） | pg-network card | ❌ 无 | 🔴 需新建 |
| Agent Announce（注册 Agent） | pg-agents card | ❌ 无 | 🔴 需新建 |
| Agent Discover（发现 Agent） | pg-agents card | ❌ 无 | 🔴 需新建 |
| Agent Transaction（执行交易） | pg-agents card | ❌ 无 | 🔴 需新建 |
| Scanner（扫描目录发现资产） | API only | ❌ 无 | 🔴 需新建 |
| Inbox（确认/拒绝/编辑待注册） | API only | ❌ 无 | 🔴 需新建 |
| Trust Level（设置信任等级） | API only | ❌ 无 | 🔴 需新建 |
| Validators（质押列表） | stakes-card | ❌ 无 | 🔴 需新建 |

## 迁移顺序（按用户流优先级）

### Phase A — 核心用户流补全
1. [ ] **Scanner + Inbox 页面** — 扫描→确认→注册，最核心的新用户流
2. [ ] **Buy 完整流程** — Explore 页加报价→确认→结果面板
3. [ ] **Identity 面板增强** — 密钥遮罩、说明文本、生成提示

### Phase B — 经济功能
4. [ ] **Portfolio** — 持仓查看（可合并到 MyData）
5. [ ] **Stake** — 质押验证者面板（可合并到 Network）
6. [ ] **Watermark** — 嵌入/提取/追踪（新页面或 Network 子模块）

### Phase C — Agent 协议
7. [ ] **Agent Announce** — 注册 Agent 身份
8. [ ] **Agent Discover** — 发现网络上的 Agent
9. [ ] **Agent Transaction** — Agent 间交易

### Phase D — 清理
10. [ ] 删除 `_INDEX_HTML` 和 fallback 逻辑
11. [ ] 删除 `dist.bak/`

## 约束
- 每完成一个模块，对照此清单打勾
- 不允许"先砍掉后面补"
- 合并前 diff review 确认无功能丢失
- `dist.bak/` 保留到全部迁完

---
*Created: 2026-03-17*

# Oasyce 工作进度 (2026-03-22)

## 已完成

### 三刀架构重构 (Cut 1-3) ✅
- **Cut 1 — GUI→Facade**: 所有 11 个 GET helper 改为通过 `OasyceServiceFacade` 的 `query_*` 方法
- **Cut 2 — Query/Command 分离**: `OasyceQuery` 只读视图类（frozenset 白名单），GET 用 `_get_query()`，POST 用 `_get_facade()`
- **Cut 3 — 默认模式修正**: `allow_local_fallback=True` 为默认，`OASYCE_STRICT_CHAIN=1` 切换链模式
- **L3 倍率对齐**: 白皮书 v4 的 5× multiplier

### P0/P1 产品审查修复 ✅
- **A1 P0**: `import hashlib/struct` 从 `do_POST` 移到模块级，消除作用域污染导致的 `/api/buy` 崩溃
- **A2 P1**: 7 处 `ConfirmationInbox()` 传入 `data_dir=_config.data_dir`
- **A3 P1**: Inbox 原子写（`_atomic_write`: tmp→fsync→replace）+ JSONDecodeError 恢复（.corrupt 备份）
- **B1 P1**: `access_buy()` 增加 `pre_quoted_bond` 参数，消除 quote/buy bond 漂移
- **B2 P1**: `/api/fingerprint/embed` 接受 `file_path` 作为 `content` 替代
- **C1 P0**: CLAUDE.md 分离链上/本地命令，增加 Running Modes 表
- **C2 P1**: FAQ Q12 两层版本模型说明（链上 immutable + 本地 re-register）

### 文档交付 ✅
- `docs/WALKTHROUGH_CHECKLIST.md` — 95 API + 76 CLI 功能走查表 + 5 用户旅程 + 16 FAQ 核验
- `docs/PRODUCT_AUDIT_2026-03-22.md` — 全量产品审查报告
- `docs/USER_JOURNEY_MAP.md` — 100 操作用户旅程走查文档 + GUI 缺口修复追踪

### GUI 缺口修复 (v2.1.3) ✅
- **23 项 GUI 缺口修复**: 85/100 操作完整支持（was 72）
- **7 新 API endpoints**: asset/shutdown, asset/terminate, asset/claim, evidence/submit, identity/export, identity/import, asset/versions
- **~60 i18n keys**: 中英双语覆盖所有新增功能
- **explore-portfolio.tsx**: 卖出份额 + 交易记录 + L0-L3 访问操作
- **mydata.tsx**: 元数据编辑 + 手动版本更新 + 资产生命周期 + 版本历史
- **network.tsx**: 治理提案/投票 + 钱包导出导入 + 指纹列表 + 信誉显示
- **dispute-form.tsx**: 陪审团投票 + 争议解决 + 证据提交

### P1 架构收敛 (v2.2.0) ✅
- **Dispute GET → facade**: `query_disputes(buyer, dispute_id)` 方法 + OasyceQuery 白名单 + app.py GET 走 facade
- ~~白皮书 v4 参数对齐~~: **阻塞** — 需链上 ConsensusVersion 升级，Python 端无法单独修改

### P2 功能接入 (v2.2.0) ✅
- **AHRP Task Market**: facade 8 方法 + CLI 7 命令 + API 7 端点 + GUI Bounty tab
- **do_POST 拆分**: 1660 行单函数 → 10 个领域 handler + 薄 dispatcher（~50 行）
- **Contribution/Leakage/Cache**: facade 6 方法 + API 6 端点 + GUI 3 个 Network sections

### P3 清理 (v2.2.0) ✅
- **_INDEX_HTML 删除**: 1491 行遗留 HTML 移除，SPA 缺失时返回 503
- **_html_response 删除**: 不再使用
- **MIGRATION.md 完成**: 全部 Phase D 项目标记完成

### 构建状态 ✅
- 1064 tests passed, 19 skipped
- TypeScript: 0 errors
- app.py: 5128 → 3634 行 (-29%)
- v2.2.0

---

## 当前架构

```
CLI (cli.py)  ──┐
                ├──▶ OasyceServiceFacade ──▶ Services
GUI (app.py)  ──┘     │                       ├── SettlementEngine
                      │                       ├── ReputationEngine
                      ├── OasyceQuery         ├── DataAccessProvider
                      │   (read-only view)    ├── FingerprintEngine
                      │                       ├── TaskMarket (AHRP)
                      │                       └── bridge (chain fallback)
                      └── ServiceResult
                          (success/data/error)
```

---

## 待处理

### 阻塞项（需链上升级）
- [ ] 白皮书 v4 参数对齐：F=0.35, fee 60/20/15/5, burn 15%（需 oasyce-chain ConsensusVersion 升级）

### 可选优化
- [ ] AHRP task_market.py 测试用例（market.py 有 18 个测试，task_market.py 0 个）
- [ ] do_GET 拆分（与 do_POST 同样的 handler 模式）
- [ ] GUI: 争议详情时间线增强（6.7 仍为 ⚠️）

---

## 架构备忘

### 分级访问体系
```
L0 查询   → 聚合统计，数据不离开安全区  → bond 1×  → 锁 1 天
L1 采样   → 脱敏水印样本片段          → bond 2×  → 锁 3 天
L2 计算   → 代码在 TEE 执行，仅输出离开 → bond 3×  → 锁 7 天
L3 交付   → 完整数据交付             → bond 5×  → 锁 30 天
```

### 运行模式
| Mode | Env Var | Backend |
|------|---------|---------|
| Standalone (default) | — | Local SQLite |
| Chain-linked | `OASYCE_STRICT_CHAIN=1` | oasyce-chain L1 |

### 交易保障机制
| 场景 | 保障 | 说明 |
|------|------|------|
| 数据购买 | Bancor 曲线即时结算 | 份额立即 mint，无需托管 |
| 能力调用 | Escrow 托管 | LOCKED→RELEASED/REFUNDED |
| 分级访问 | Bond 保证金 | 存入保证金，不是付款给卖家 |

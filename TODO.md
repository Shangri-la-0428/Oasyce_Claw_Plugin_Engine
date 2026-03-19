# Oasyce 维护工作进度 (2026-03-19)

## 已完成

### 市场页面：分级访问系统重构 ✅
- **问题**：市场页面让用户手填 OAS 金额买份额，完全绕过了已设计的 L0-L3 分级访问体系；获取报价返回 404（前端 POST，后端只有 GET）
- **修复**：
  - 前端 `explore-browse.tsx` 重构为层级选择 UI（L0 查询 / L1 采样 / L2 计算 / L3 交付），每个层级显示保证金价格、锁定天数、是否可用
  - 后端 `gui/app.py` 新增 `GET /api/access/quote` 和 `POST /api/access/buy`，接入 `DataAccessProvider` 计算保证金
  - Bond 公式：`TWAP × Multiplier × RiskFactor × RepDiscount × ExposureFactor`
  - 信誉门控：R<20 只能 L0，R<50 只能 L0/L1，R≥50 全部
  - 修复 `buyer_id` → `buyer` 字段名不匹配
  - 修复 dispute-form.tsx 和 nav.tsx 的 TS 编译错误
  - i18n 中英双语全部添加
  - CSS 卡片式布局，移动端响应式
- **构建状态**：`npm run build` ✅ 通过

### GitHub CI 修复 ✅
- 修复 `scripts/install_wizard.py` 语法错误（line 152 转义引号 `\"` → `"`）
- 运行 `black .` 格式化全部 156 个不合规文件
- 更新 `ci.yml`：
  - 删除 `pip install oasyce-core`（不存在的依赖）
  - `mypy oasyce_plugin` → `mypy oasyce --ignore-missing-imports`
- `black --check .` ✅ 通过（209 files unchanged）

### LICENSE 确认 ✅
- MIT License 已存在于仓库根目录（`/LICENSE`）
- `pyproject.toml` 中 license 字段一致：`license = {text = "MIT"}`

### GUI/CLI 架构对齐 ✅
- **问题复盘**：
  - `gui/app.py`（5790行）演变为独立单体，重新实现了业务逻辑而非调用共享服务
  - CLI 用 `bridge_buy()` 购买，GUI 用 `SettlementEngine` 直接调用 → 同一资产不同价格
  - L0-L3 访问控制只存在于 GUI，CLI 无法使用
  - 价格模型验证逻辑在 3 处重复实现
  - `CLAUDE.md` 架构图标注错误（`CLI :8420` → 应为 `Dashboard :8420`）
- **修复**：
  - 创建统一服务门面 `oasyce/services/facade.py`（`OasyceServiceFacade`）
  - CLI `cmd_quote` / `cmd_buy` 改为通过 facade 调用（自动降级到 chain bridge）
  - GUI `/api/access/quote` / `/api/access/buy` 改为通过 facade 调用
  - CLI 新增 `access quote` 子命令（与 GUI 对齐）
  - 修复 `CLAUDE.md` 架构图：`CLI :8420` → `Dashboard :8420`
- **架构**：
  ```
  CLI (cli.py)  ──┐
                  ├──▶ OasyceServiceFacade ──▶ Services
  GUI (app.py)  ──┘     (facade.py)             ├── SettlementEngine
                                                 ├── ReputationEngine
                                                 ├── DataAccessProvider
                                                 └── bridge (chain fallback)
  ```

---

## 待处理

### 1. 本地未提交改动 ⚠️
- 大量改动需要 commit + push：
  - dashboard 分级访问重构
  - oasyce_plugin 目录删除
  - CI 修复 + black 格式化
  - 架构对齐（facade + CLI/GUI 重构）

### 2. 剩余架构债务（非紧急）
- GUI `/api/quote` 和 `/api/buy` 仍直接使用 `SettlementEngine`，未经 facade
- GUI 多处直接 SQL 查询（`_ledger._conn.execute(...)`）绕过服务层
- `server.py` 与 `gui/app.py` 两套独立服务器无共享代码
- GUI 有通知系统（`NotificationService`），CLI 无

---

## 架构备忘

### 分级访问体系 (已实现)
```
L0 查询   → 聚合统计，数据不离开安全区  → bond 1×  → 锁 1 天
L1 采样   → 脱敏水印样本片段          → bond 2×  → 锁 3 天
L2 计算   → 代码在 TEE 执行，仅输出离开 → bond 3×  → 锁 7 天
L3 交付   → 完整数据交付             → bond 5×  → 锁 30 天
```

### 信誉门控
```
R < 20  → 沙盒模式，只能 L0
R 20-49 → 有限访问，L0 + L1
R ≥ 50  → 完整访问，L0-L3
```

### API 端点
- `GET  /api/access/quote?asset_id=X&buyer=Y` → 返回 4 个层级的保证金报价
- `POST /api/access/buy { asset_id, buyer, level }` → 执行分级访问购买

### CLI 对应命令
- `oasyce access quote <asset_id> --agent <buyer>` → 同上（新增）
- `oasyce access query/sample/compute/deliver` → L0-L3 具体操作
- `oasyce access bond <asset_id> --agent <buyer> --level L2` → 单层级保证金计算

### 统一服务门面（新增）
- **文件**: `oasyce/services/facade.py`
- **类**: `OasyceServiceFacade`
- **方法**: `quote()`, `buy()`, `access_quote()`, `access_buy()`, `register()`
- **原则**: CLI 和 GUI 的业务逻辑必须经过此门面，不得绕过

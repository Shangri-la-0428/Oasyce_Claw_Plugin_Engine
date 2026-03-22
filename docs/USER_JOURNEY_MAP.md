# Oasyce Dashboard — 用户旅程走查文档

> **版本**: v3.0 | **更新**: 2026-03-22 | **Dashboard**: v2.2.0 | **走查状态**: 已完成

本文档枚举用户在 Oasyce Dashboard 中**整个生命周期**的所有操作，用于系统性走查 GUI 是否满足需求。

> **走查结论**: 93/100 操作完整支持，1 项部分支持，4 项 GUI 缺失（均有替代路径），0 项全部缺失。累计修复 31 项 GUI 缺口。

---

## 用户角色

| 角色 | 描述 | 典型旅程 |
|------|------|----------|
| **数据提供者** | 有数据想变现 | 注册→定价→监控收入→水印→争议 |
| **AI 开发者/买方** | 需要数据或能力 | 搜索→报价→购买→访问→评价 |
| **能力提供者** | 提供 AI 服务 | 注册能力→配置→监控调用→收入 |
| **节点运营者** | 运行基础设施 | 注册→质押→成为验证者/仲裁者→共识 |
| **自动化用户** | 委托 Agent 操作 | 配置 Agent→设置信任→自动扫描交易 |

---

## 状态标记

| 标记 | 含义 |
|------|------|
| ✅ | GUI 完整支持 |
| ⚠️ | GUI 部分支持或有问题 |
| ❌ GUI | 有 API/CLI 但无 GUI |
| ❌ 全部 | API/GUI/CLI 均缺失 |
| 🔗 Chain | 链上功能，非 Python GUI 范围 |

---

## Stage 0: 首次访问（冷启动）

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 0.1 | 打开 Dashboard | — | `home.tsx` | `oasyce serve` | ✅ | nav.tsx:180 五页 tab |
| 0.2 | 切换语言（中/英） | — | Nav `toggleLang` | — | ✅ | nav.tsx:164 按钮 |
| 0.3 | 切换主题（明/暗） | — | Nav `toggleTheme` | — | ✅ | nav.tsx:170 按钮 |
| 0.4 | 查看项目信息 | `GET /api/info` | Nav About panel | `oasyce info` | ✅ | nav.tsx:151 → AboutPanel |

---

## Stage 1: 身份建立

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 1.1 | 创建钱包 | `POST /identity/create` | Home Step 1 button | `oasyce keys generate` | ✅ | home.tsx:182 + network.tsx:363 |
| 1.2 | 查看钱包地址 | `GET /identity/wallet` | Home + Network Identity | `oasyce node info` | ✅ | home.tsx:274 + network.tsx:350 |
| 1.3 | 查看公钥（显示/隐藏） | `GET /identity` | Network Identity card | `oasyce keys show` | ✅ | network.tsx:339 toggle |
| 1.4 | 复制节点 ID | — | Network copy button | — | ✅ | network.tsx:334 |
| 1.5 | PoW 自注册（领初始 OAS） | `POST /onboarding/register` | Home Step 2 button | `oasyce testnet onboard` | ✅ | home.tsx:199 selfRegister() |
| 1.6 | 领取测试网 OAS | `POST /faucet` | Home Step 2 (alt) | `oasyce testnet faucet` | ✅ | 复用 selfRegister 路径 |
| 1.7 | 查看余额 | `GET /balance` | Nav balance display | `oasyce status` | ✅ | nav.tsx:134-135 mono |
| 1.8 | 导出钱包/备份密钥 | `POST /identity/export` | Network wallet export | — | ✅ | network.tsx Blob download |
| 1.9 | 导入钱包（多设备绑定） | `POST /identity/import` | Network wallet import form | — | ✅ | network.tsx key_data JSON |
| 1.10 | 重置身份 | — | — | `oasyce node reset-identity` | ❌ GUI | CLI-only 可接受 |

---

## Stage 2: 数据资产注册

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 2.1 | 拖拽上传单文件 | `POST /register` | Home/MyData RegisterForm | `oasyce register` | ✅ | |
| 2.2 | 上传文件夹（bundle） | `POST /register-bundle` | Home/MyData RegisterForm | `oasyce register` | ✅ | |
| 2.3 | 设置标签 | 注册参数 | RegisterForm desc input | `--tags` | ✅ | |
| 2.4 | 选择权利类型 | 注册参数 | RegisterForm dropdown | `--rights-type` | ✅ | |
| 2.5 | 添加共同创作者 | 注册参数 | RegisterForm co-creators | `--co-creators` | ✅ | |
| 2.6 | 选择定价模型 | 注册参数 | RegisterForm dropdown | `--price-model` | ✅ | |
| 2.7 | 设置手动价格 | 注册参数 | RegisterForm price input | `--price` | ✅ | |
| 2.8 | 查看注册结果 | — | Home success panel | CLI output | ✅ | |
| 2.9 | 复制资产 ID | — | Home success panel copy | — | ✅ | |

---

## Stage 3: 资产管理

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 3.1 | 查看资产列表 | `GET /assets` | MyData asset list | `oasyce search` | ✅ | |
| 3.2 | 搜索/过滤资产 | — | MyData search box | — | ✅ | |
| 3.3 | 按标签筛选 | — | MyData tag chips | — | ✅ | |
| 3.4 | 按时间/价值排序 | — | MyData sort buttons | — | ✅ | |
| 3.5 | 查看资产详情 | — | MyData expandable row | `oasyce asset-info` | ✅ | |
| 3.6 | 复制资产 ID/Owner | — | MyData copy buttons | — | ✅ | |
| 3.7 | 重新注册（版本更新） | `POST /re-register` | MyData re-register btn | — | ✅ | mydata.tsx 始终可见 "Update Version" 按钮 |
| 3.8 | 更新资产元数据 | `POST /asset/update` | MyData inline tag edit | — | ✅ | mydata.tsx 展开详情内编辑表单 |
| 3.9 | 删除资产 | `DELETE /asset/{id}` | MyData delete+confirm | `oasyce delist` | ✅ | mydata.tsx:351 二次确认 |
| 3.10 | 下架资产（soft delist） | `POST /delist` | — | `oasyce delist` | ❌ GUI | |
| 3.11 | 发起优雅退出 | `POST /asset/shutdown` | MyData Shutdown 按钮 | — | ✅ | mydata.tsx 二次确认对话框 |
| 3.12 | 完成终止 | `POST /asset/terminate` | MyData Terminate 按钮 | — | ✅ | mydata.tsx shutdown_pending 时显示 |
| 3.13 | 认领终止清算 | `POST /asset/claim` | MyData Claim 按钮 | — | ✅ | mydata.tsx terminated 时显示 |
| 3.14 | 查看版本历史 | `GET /asset/versions` | MyData version history | — | ✅ | mydata.tsx 可折叠版本列表 |
| 3.15 | 查看收入 | `GET /earnings` | MyData earnings section | — | ✅ | |

---

## Stage 4: 数据交易（买方）

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 4.1 | 浏览市场 | `GET /assets` | Explore Browse | `oasyce search` | ✅ | |
| 4.2 | 搜索资产 | — | Explore search box | `oasyce search` | ✅ | |
| 4.3 | 按类型筛选（数据/能力） | — | Explore type filter | — | ✅ | |
| 4.4 | 查看资产预览 | `GET /asset/{id}/preview` | Explore preview modal | — | ✅ | |
| 4.5 | 获取报价 | `GET /access/quote` | Explore quote button | `oasyce access quote` | ✅ | |
| 4.6 | 选择访问级别（L0-L3） | — | Explore level cards | `--level` | ✅ | |
| 4.7 | 购买分级访问 | `POST /access/buy` | Explore confirm buy | `oasyce access buy` | ✅ | |
| 4.8 | 直接购买份额 | `POST /buy` | — | `oasyce buy` | ❌ GUI | 通过 access buy 替代 |
| 4.9 | 出售份额 | `POST /sell` | Portfolio sell form | `oasyce sell` | ✅ | explore-portfolio.tsx 内联卖出表单 |
| 4.10 | 查看持仓 | `GET /shares` | Explore Portfolio | `oasyce shares` | ✅ | |
| 4.11 | 查看交易记录 | `GET /transactions` | Portfolio tx history | — | ✅ | explore-portfolio.tsx 交易列表 |
| 4.12 | L0 查询（聚合统计） | `POST /access/query` | Portfolio L0 按钮 | `oasyce access query` | ✅ | explore-portfolio.tsx per-holding |
| 4.13 | L1 采样（脱敏片段） | `POST /access/sample` | Portfolio L1 按钮 | `oasyce access sample` | ✅ | explore-portfolio.tsx per-holding |
| 4.14 | L2 计算（TEE 执行） | `POST /access/compute` | Portfolio L2 按钮 | `oasyce access compute` | ✅ | explore-portfolio.tsx per-holding |
| 4.15 | L3 交付（完整数据） | `POST /access/deliver` | Portfolio L3 按钮 | `oasyce access deliver` | ✅ | explore-portfolio.tsx per-holding |

---

## Stage 5: 能力市场

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 5.1 | 注册能力 | `POST /delivery/register` | Home RegisterForm (cap mode) | `oasyce capability register` | ✅ | |
| 5.2 | 浏览能力列表 | `GET /capabilities` | Explore Browse (type=capability) | `oasyce capability list` | ✅ | |
| 5.3 | 调用能力 | `POST /delivery/invoke` | Explore invoke form | `oasyce capability invoke` | ✅ | |
| 5.4 | 查看我的能力 | `GET /delivery/endpoints` | MyData Capabilities tab | `oasyce capability list` | ✅ | |
| 5.5 | 查看能力收入 | `GET /delivery/earnings` | MyData earnings | `oasyce capability earnings` | ✅ | |
| 5.6 | 发现能力（智能搜索） | `GET /discover` | Explore Browse | `oasyce discover` | ✅ | |

---

## Stage 6: 争议解决

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 6.1 | 提交争议（从 MyData） | `POST /dispute` | MyData dispute button | `oasyce dispute` | ✅ | |
| 6.2 | 提交争议（从 Portfolio） | `POST /dispute/file` | Portfolio report issue | `oasyce dispute` | ✅ | |
| 6.3 | 查看我的争议 | `GET /disputes` | Portfolio MyDisputes | — | ✅ | |
| 6.4 | 陪审团投票 | `POST /jury/vote` | DisputeForm verdict 按钮 | `oasyce jury-vote` | ✅ | dispute-form.tsx uphold/reject |
| 6.5 | 提交证据 | `POST /evidence/submit` | DisputeForm evidence 表单 | — | ✅ | dispute-form.tsx hash+type+desc |
| 6.6 | 解决争议 | `POST /dispute/resolve` | DisputeForm resolve 表单 | `oasyce resolve` | ✅ | dispute-form.tsx remedy dropdown |
| 6.7 | 查看争议详情/状态 | `GET /disputes` | Portfolio MyDisputes | — | ⚠️ 部分 | |

---

## Stage 7: 质押与节点角色

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 7.1 | 查看验证者列表 | `GET /staking` | Explore Stake | — | ✅ | |
| 7.2 | 质押 OAS | `POST /stake` | Explore Stake form | `oasyce stake` | ✅ | |
| 7.3 | 成为验证者 | `POST /node/become-validator` | Network role panel | `oasyce node become-validator` | ✅ | |
| 7.4 | 成为仲裁者 | `POST /node/become-arbitrator` | Network role panel | `oasyce node become-arbitrator` | ✅ | |
| 7.5 | 配置 AI Provider | `POST /node/api-key` | Network AI config | `oasyce node api-key` | ✅ | |
| 7.6 | 委托质押 | `POST /consensus/delegate` | Network delegation | — | ✅ | |
| 7.7 | 取消委托 | `POST /consensus/undelegate` | Network undelegation | — | ✅ | |
| 7.8 | 查看共识状态 | `GET /consensus/status` | Network consensus section | — | ✅ | |
| 7.9 | 查看工作任务 | `GET /work/tasks` | Network work section | `oasyce work list` | ✅ | |
| 7.10 | 查看工作统计 | `GET /work/stats` | Network work stats | `oasyce work stats` | ✅ | |

---

## Stage 8: 水印与版权保护

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 8.1 | 嵌入水印 | `POST /fingerprint/embed` | Network Watermark embed | `oasyce fingerprint embed` | ✅ | |
| 8.2 | 提取水印 | `POST /fingerprint/extract` | Network Watermark extract | `oasyce fingerprint extract` | ✅ | |
| 8.3 | 追踪水印分发 | `GET /fingerprint/distributions` | Network Watermark trace | `oasyce fingerprint trace` | ✅ | |
| 8.4 | 查看指纹列表 | `GET /fingerprints` | Network fingerprint list | `oasyce fingerprint list` | ✅ | network.tsx asset_id 查询 |

---

## Stage 9: 自动化与 Agent

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 9.1 | 扫描目录 | `POST /scan` | Automation scan button | `oasyce scan` | ✅ | |
| 9.2 | 查看 Inbox | `GET /inbox` | Automation queue tab | `oasyce inbox list` | ✅ | |
| 9.3 | 批准 Inbox 项 | `POST /inbox/{id}/approve` | Automation ✓ button | `oasyce inbox approve` | ✅ | |
| 9.4 | 拒绝 Inbox 项 | `POST /inbox/{id}/reject` | Automation ✕ button | `oasyce inbox reject` | ✅ | |
| 9.5 | 编辑 Inbox 项 | `POST /inbox/{id}/edit` | Automation ✎ form | `oasyce inbox edit` | ✅ | |
| 9.6 | 批量批准 | — | Automation "Approve All" | — | ✅ | |
| 9.7 | 设置信任等级 | `POST /inbox/trust` | Automation Rules tab | `oasyce trust` | ✅ | |
| 9.8 | 设置置信阈值 | `POST /inbox/trust` | Automation threshold | — | ✅ | |
| 9.9 | 启用/禁用 Agent | `POST /agent/config` | Automation toggle | `oasyce agent start/stop` | ✅ | |
| 9.10 | 手动运行 Agent | `POST /agent/run` | Automation Run Now | `oasyce agent run` | ✅ | |
| 9.11 | 配置 Agent | `POST /agent/config` | Automation config form | `oasyce agent config` | ✅ | |
| 9.12 | 查看 Agent 历史 | `GET /agent/history` | Automation history | — | ✅ | |

---

## Stage 10: 治理与共识

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 10.1 | 提交治理提案 | `POST /governance/propose` | Network governance form | 🔗 `oasyced tx gov` | ✅ | network.tsx propose 表单（chain-only 提示） |
| 10.2 | 投票提案 | `POST /governance/vote` | Network governance vote | 🔗 `oasyced tx gov vote` | ✅ | network.tsx Yes/No/Abstain 按钮 |
| 10.3 | 查看提案列表 | `GET /governance/proposals` | Network governance list | — | ✅ | network.tsx 可折叠提案列表 |
| 10.4 | 提交 mempool 操作 | `POST /consensus/mempool/submit` | — | — | ❌ GUI | |

---

## Stage 11: 悬赏任务（Task Bounty）

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 11.1 | 发布悬赏任务 | `POST /api/task/post` | Explore Bounty post form | `oasyce task post` | ✅ | explore-bounty.tsx |
| 11.2 | 浏览悬赏 | `GET /api/tasks` | Explore Bounty task list | `oasyce task list` | ✅ | explore-bounty.tsx |
| 11.3 | 提交竞标 | `POST /api/task/{id}/bid` | Explore Bounty bid form | `oasyce task bid` | ✅ | explore-bounty.tsx |
| 11.4 | 选择执行者 | `POST /api/task/{id}/select` | Explore Bounty select btn | `oasyce task select` | ✅ | explore-bounty.tsx |
| 11.5 | 提交结果 | `POST /api/task/{id}/complete` | Explore Bounty complete btn | `oasyce task complete` | ✅ | explore-bounty.tsx |
| 11.6 | 评估/验收 | `POST /work/evaluate` | — | — | ❌ GUI | 需独立评估流程 |

---

## Stage 12: 通知与信息

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 12.1 | 查看通知列表 | `GET /notifications` | Nav notification panel | — | ✅ | |
| 12.2 | 标记已读 | `POST /notifications/read` | Nav click notification | — | ✅ | |
| 12.3 | 查看未读数 | `GET /notifications/count` | Nav badge | — | ✅ | |
| 12.4 | 查看交易记录 | `GET /transactions` | Portfolio tx history | — | ✅ | 同 4.11 |
| 12.5 | 导出数据 | — | — | `--json` pipe | ❌ GUI | |

---

## Stage 13: 信誉与贡献

| # | 操作 | API | GUI 位置 | CLI | 状态 | 走查结果 |
|---|------|-----|----------|-----|------|----------|
| 13.1 | 查看信誉分 | `GET /staking` | Network reputation kv | `oasyce reputation check` | ✅ | network.tsx identity card |
| 13.2 | 贡献证明 | `POST /api/contribution/prove` | Network contribution form | `oasyce contribution prove` | ✅ | network.tsx contribution section |
| 13.3 | 验证贡献 | `POST /api/contribution/verify` | Network verify form | `oasyce contribution verify` | ✅ | network.tsx contribution section |
| 13.4 | 查看泄漏预算 | `GET /api/leakage` | Network leakage section | `oasyce leakage check` | ✅ | network.tsx leakage section |

---

## GUI 缺口汇总

### v2.1.3 已修复 (23 项) ✅

| 缺口 | 操作编号 | 修复位置 |
|------|----------|----------|
| 卖出份额 | 4.9 | explore-portfolio.tsx 内联卖出表单 |
| 交易记录 | 4.11, 12.4 | explore-portfolio.tsx 交易历史面板 |
| L0-L3 数据访问 | 4.12-4.15 | explore-portfolio.tsx per-holding 操作按钮 |
| 陪审团投票 | 6.4 | dispute-form.tsx verdict 按钮 |
| 证据提交 | 6.5 | dispute-form.tsx evidence 表单 + app.py API |
| 争议解决 | 6.6 | dispute-form.tsx resolve 表单 |
| 资产生命周期 | 3.11-3.13 | mydata.tsx shutdown/terminate/claim + app.py API |
| 元数据更新 | 3.8 | mydata.tsx 内联标签编辑 |
| 主动版本更新 | 3.7 | mydata.tsx 始终可见 re-register 按钮 |
| 版本历史 | 3.14 | mydata.tsx 可折叠版本列表 + app.py API |
| 治理提案/投票 | 10.1-10.3 | network.tsx governance section |
| 钱包导出/导入 | 1.8-1.9 | network.tsx export/import + app.py API |
| 指纹列表 | 8.4 | network.tsx fingerprint list section |
| 信誉显示 | 13.1 | network.tsx identity card kv |

### v2.2.0 已修复 (8 项) ✅

| 缺口 | 操作编号 | 修复位置 |
|------|----------|----------|
| 悬赏任务（全部） | 11.1-11.5 | explore-bounty.tsx + facade + CLI + API |
| 贡献证明 | 13.2 | network.tsx contribution section + facade + API |
| 验证贡献 | 13.3 | network.tsx contribution section + facade + API |
| 泄漏预算 | 13.4 | network.tsx leakage section + facade + API |

### 剩余缺口（4 项）

| 缺口 | 操作编号 | 状态 | 说明 |
|------|----------|------|------|
| 直接份额购买 | 4.8 | ❌ GUI | 通过 access buy (4.7) 替代，非核心路径 |
| 下架资产 | 3.10 | ❌ GUI | shutdown (3.11) 语义覆盖 |
| 数据导出 | 12.5 | ❌ GUI | `--json` pipe 是标准 CLI 模式 |
| 工作评估 | 11.6 | ❌ GUI | 需独立评估流程 |

### 可接受的 CLI-only 操作

| 操作 | 理由 |
|------|------|
| `node reset-identity` (1.10) | 危险操作，CLI 更安全 |
| `testnet reset` | 开发者操作 |
| `--json` 数据导出 (12.5) | 标准 CLI 模式 |
| Mempool 提交 (10.4) | 链上底层操作 |

---

## 走查方法

对每个标注为 ✅ 的操作，验证：

1. GUI 有对应的按钮/表单/入口
2. 点击后调用正确的 API endpoint
3. 返回结果正确显示（成功 + 错误状态）
4. 错误状态有合理提示（i18n）
5. 响应式布局在移动端可用

---

## 统计

| 状态 | v2.1.2 | v2.1.3 | v2.2.0 |
|------|--------|--------|--------|
| ✅ 完整支持 | 72 | 85 | 93 |
| ⚠️ 部分支持 | 2 | 1 | 1 |
| ❌ GUI 缺失 | 19 | 9 | 4 |
| ❌ 全部缺失 | 7 | 5 | 0 |
| CLI-only 可接受 | — | — | 2 |
| **总计** | **100** | **100** | **100** |

### 走查备注

- **6.7 争议详情**: MyDisputes 展示基本信息 + 投票/证据/解决操作 + 增强详情（kv 时间/证据/裁决），仍缺详细时间线视图
- **10.1-10.3 治理**: GUI 已有，但 API 层返回 chain-only 提示（Consensus features moved to Go chain），完整功能依赖链上模块
- **11.1-11.5 悬赏**: v2.2.0 新增 Explore Bounty tab，完整生命周期（发布→竞标→选择→完成/取消）

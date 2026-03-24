# Oasyce 产品需求文档 (PRD) + QA 走查规格

> 本文档既是产品定义，也是 QA 走查规格。每个功能点都有唯一编号 `[QA-xxx]`，
> 对应 `scripts/qa_regression.py` 中的自动化检查。跑一次脚本 = 一次完整 QA 走查。

**版本**: v2.1.1 | **最后更新**: 2026-03-23 | **状态**: 主网准备中 | **QA 检查点**: 381

---

## 一、愿景

**Oasyce = AI 经济的 Stripe**

构建一个去中心化的 AI 数据与能力交易网络，让：
- **数据有主权** — 数据所有者通过 bonding curve 定价，持股即拥有访问权
- **能力有价格** — AI agent 注册能力并通过 AHRP 协议完成交易
- **智能可聚合** — 从"锯齿状智能"（每个 agent 擅长不同领域）走向"球形智能"（通过市场聚合成全能力覆盖）

**核心经济模型**:
- Bancor bonding curve (CW=0.50, sqrt 曲线)，买入越多价格越高
- Fee split: 85% creator / 7% validator / 5% burn / 3% treasury
- 四级访问: L0 聚合查询 → L1 水印样本 → L2 TEE 计算 → L3 全量交付
- PoW 自注册 + 减半经济 → 自然 Sybil 防御

---

## 二、产品架构

```
用户 / AI Agent
    │
    ├── CLI (oas)          ── 命令行接口，40+ 命令
    ├── Dashboard (GUI)    ── Web 界面，localhost:8420
    └── Facade API         ── 程序化接口，ServiceResult 封装
         │
         ├── Settlement Engine  ── bonding curve 交易引擎
         ├── AHRP Executor      ── agent 握手协议
         ├── Task Market        ── 任务竞价市场
         ├── Reputation Engine  ── 信誉评分系统
         ├── Access Provider    ── 分级访问控制
         └── Chain Client       ── L1 链交互
              │
              └── oasyce-chain (Go, Cosmos SDK v0.50)
                   ├── x/settlement   ── escrow + bonding curve
                   ├── x/datarights   ── 数据资产 + 股权
                   ├── x/capability   ── 能力注册 + 调用
                   ├── x/reputation   ── 链上信誉
                   ├── x/work         ── PoUW 任务
                   └── x/onboarding   ── PoW 自注册
```

---

## 三、协议参数 [QA-100 系列]

| 参数 | 值 | QA ID |
|------|-----|-------|
| Reserve Ratio (CW) | 0.50 | QA-101 |
| Creator Rate | 85% | QA-102 |
| Validator Rate | 7% | QA-103 |
| Burn Rate | 5% | QA-104 |
| Treasury Rate | 3% | QA-105 |
| Fee Rates Sum | 1.00 | QA-106 |
| Initial Price | 1.0 OAS/token | QA-107 |
| Reserve Solvency Cap | 95% | QA-108 |
| ProtocolParams frozen | 不可变 | QA-109 |
| Formulas 常量一致 | formulas.py ↔ ProtocolParams | QA-110 |

---

## 四、网络安全模式 [QA-200 系列]

| 模式 | 签名验证 | 本地回退 | QA ID |
|------|---------|---------|-------|
| MAINNET | 必须 | 禁止 | QA-201, QA-202 |
| TESTNET | 可选 | 允许 | QA-203, QA-204 |
| LOCAL | 关闭 | 允许 | QA-205, QA-206 |

---

## 五、经济配置 [QA-300 系列]

| 配置项 | MAINNET | TESTNET | QA ID |
|--------|---------|---------|-------|
| block_reward | 4 OAS | 40 OAS | QA-301 |
| min_stake | 10,000 OAS | 100 OAS | QA-302 |
| agent_stake | 100 OAS | 1 OAS | QA-303 |
| Bootstrap 节点 | ≥3 个 | ≥1 个 | QA-304 |
| 共识参数存在 | epoch/slot/unbonding | 同上 | QA-305 |

---

## 六、Bonding Curve 生命周期 [QA-400 系列]

### 6.1 资产注册
- **功能**: 注册新数据资产，初始化 bonding curve pool
- **预期**: pool 创建，supply=1.0, reserve=0, status=ACTIVE
- **QA**: QA-401

### 6.2 报价 (Quote)
- **功能**: 计算买入报价，不执行交易
- **输入**: asset_id, amount_oas
- **输出**: QuoteResult(equity_minted, spot_price_before/after, price_impact, protocol_fee, burn_amount, treasury_amount)
- **预期**:
  - equity_minted > 0 [QA-402]
  - protocol_fee > 0 (7% of payment) [QA-403]
  - burn_amount > 0 (5% of payment) [QA-404]
  - treasury_amount > 0 (3% of payment) [QA-405]
  - spot_price_after >= spot_price_before [QA-406]
  - net_payment = amount - fee - burn - treasury = 85% [QA-407]

### 6.3 买入 (Buy)
- **功能**: 通过 bonding curve 购买股份
- **预期**:
  - 返回 SettlementReceipt, status=SETTLED [QA-408]
  - 买家 equity > 0 [QA-409]
  - pool reserve 增加 [QA-410]
  - pool supply 增加 [QA-411]
- **边界条件**:
  - 金额 = 0 → 错误 [QA-412]
  - 资产不存在 → 自动创建 pool [QA-413]
  - slippage 超限 → SlippageError [QA-414]

### 6.4 卖出报价 (Sell Quote)
- **功能**: 计算卖出回报，不执行
- **输出**: SellQuoteResult(payout_oas, protocol_fee, burn, treasury)
- **预期**:
  - payout_oas > 0 [QA-415]
  - protocol_fee = gross * 7% [QA-416]
  - 反向 Bancor 公式正确 [QA-417]
- **边界条件**:
  - 卖出超过持有量 → ValueError [QA-418]
  - 卖出全部供应 → ValueError [QA-419]
  - tokens_to_sell <= 0 → ValueError [QA-420]

### 6.5 卖出 (Sell)
- **功能**: 卖回股份给 bonding curve
- **预期**:
  - equity 减少正确数量 [QA-421]
  - pool reserve 减少 [QA-422]
  - pool supply 减少 [QA-423]
  - payout 受 95% solvency cap 限制 [QA-424]

### 6.6 往返成本 (Round-trip)
- **功能**: 买入 → 立即卖出的总成本
- **预期**: 损失约 28% (买入 15% fee + 卖出 ~15% fee) [QA-425]

### 6.7 Fee 数学验证
- **功能**: calculate_fees(amount) 返回正确四元组
- **预期**:
  - fee = amount * 0.07 [QA-426]
  - burn = amount * 0.05 [QA-427]
  - treasury = amount * 0.03 [QA-428]
  - net = amount * 0.85 [QA-429]

---

## 七、Facade API [QA-500 系列]

### 7.1 方法存在性
所有公开方法必须可调用:

**交易与定价:**

| 方法 | QA ID |
|------|-------|
| facade.quote() | QA-501 |
| facade.buy() | QA-502 |
| facade.sell() | QA-503 |
| facade.sell_quote() | QA-504 |
| facade.register() | QA-505 |

**争议与治理:**

| 方法 | QA ID |
|------|-------|
| facade.dispute() | QA-506 |
| facade.resolve_dispute() | QA-507 |
| facade.jury_vote() | QA-508 |
| facade.submit_evidence() | QA-523 |
| facade.query_disputes() | QA-535 |

**访问控制:**

| 方法 | QA ID |
|------|-------|
| facade.get_equity_access_level() | QA-509 |
| facade.access_quote() | QA-510 |
| facade.access_buy() | QA-511 |

**资产管理:**

| 方法 | QA ID |
|------|-------|
| facade.get_pool_info() | QA-512 |
| facade.get_portfolio() | QA-513 |
| facade.query_assets() | QA-516 |
| facade.update_asset_metadata() | QA-517 |
| facade.delist_asset() | QA-518 |
| facade.delete_asset() | QA-548 |
| facade.get_asset() | QA-524 |
| facade.add_asset_version() | QA-525 |
| facade.get_asset_versions() | QA-526 |
| facade.list_pools() | QA-527 |

**生命周期:**

| 方法 | QA ID |
|------|-------|
| facade.initiate_shutdown() | QA-519 |
| facade.finalize_termination() | QA-520 |
| facade.claim_termination() | QA-521 |
| facade.asset_lifecycle_info() | QA-522 |

**任务市场 (通过 facade 代理):**

| 方法 | QA ID |
|------|-------|
| facade.post_task() | QA-536 |
| facade.submit_task_bid() | QA-537 |
| facade.select_task_winner() | QA-538 |
| facade.complete_task() | QA-539 |
| facade.cancel_task() | QA-540 |

**诊断查询:**

| 方法 | QA ID |
|------|-------|
| facade.protocol_stats() | QA-514 |
| facade.query_chain_status() | QA-515 |
| facade.query_blocks() | QA-541 |
| facade.query_block() | QA-542 |
| facade.query_stakes() | QA-543 |
| facade.query_transactions() | QA-544 |

**贡献证明与追踪:**

| 方法 | QA ID |
|------|-------|
| facade.query_contribution() | QA-545 |
| facade.verify_contribution() | QA-546 |
| facade.query_fingerprints() | QA-547 |
| facade.query_trace() | QA-549 |

**信誉与缓存:**

| 方法 | QA ID |
|------|-------|
| facade.decay_all_reputations() | QA-528 |
| facade.reset_leakage() | QA-550 |
| facade.purge_cache() | QA-551 |

### 7.2 ServiceResult 格式
- 所有方法返回 ServiceResult [QA-530]
- success=True 时 error=None [QA-531]
- success=False 时 error 非空 [QA-532]

### 7.3 Sell 不再被阻塞
- facade.sell() 在 standalone 模式下可执行 [QA-533]
- facade.sell() 在 chain mode 下走 RPC [QA-534]

---

## 八、任务竞价市场 [QA-600 系列]

### 8.1 发布任务
- post_task(requester_id, description, budget, deadline_seconds)
- 返回 Task 对象 [QA-601]
- task_id 非空 [QA-602]
- status = OPEN [QA-603]

### 8.2 提交竞价
- submit_bid(task_id, agent_id, price, estimated_seconds)
- 返回 TaskBid [QA-604]
- price > budget → 拒绝 [QA-605]
- reputation < min_reputation → 拒绝 [QA-606]

### 8.3 选择中标
- select_winner(task_id, agent_id)
- task status → ASSIGNED [QA-607]
- 中标 agent 匹配 [QA-608]

### 8.4 完成/取消
- complete_task → status=COMPLETED [QA-609]
- cancel_task → status=CANCELLED (仅 OPEN/BIDDING) [QA-610]

### 8.5 过期清理
- expire_stale_tasks() 清理超时任务 [QA-611]

### 8.6 选择策略
- LOWEST_PRICE: 选最低价 [QA-612]
- BEST_REPUTATION: 选最高信誉 [QA-613]
- WEIGHTED_SCORE: 价格×0.4 + 信誉×0.4 + 时间×0.2 [QA-614]

---

## 九、Chain Client [QA-700 系列]

### 9.1 类存在性
| 类/方法 | QA ID |
|---------|-------|
| ChainClient 类 | QA-701 |
| ChainClient.buy_shares | QA-702 |
| ChainClient.sell_shares | QA-703 |
| ChainClient.get_balance | QA-704 |
| ChainClient.create_escrow | QA-705 |
| ChainClient.release_escrow | QA-706 |
| ChainClient.refund_escrow | QA-707 |
| ChainClient.is_connected | QA-708 |
| OasyceClient 类 | QA-709 |
| OasyceClient.sell_shares 代理 | QA-710 |
| OasyceClient.get_bonding_curve_price | QA-711 |
| OasyceClient.get_shareholders | QA-712 |

---

## 十、限流中间件 [QA-800 系列]

### 10.1 RateLimiter
- rate=N 个请求/窗口 [QA-801]
- 窗口内允许 N 个 [QA-802]
- 第 N+1 个被拒绝 [QA-803]
- 不同 key 独立计数 [QA-804]
- remaining() 返回正确 [QA-805]

### 10.2 APIKeyMiddleware
- 无 API key 时不拦截 [QA-806]
- 有 API key 时拦截未授权写入 [QA-807]
- 读请求始终放行 [QA-808]

### 10.3 RateLimitMiddleware
- 默认: 读 100/min, 写 20/min [QA-809]
- 超限返回 429 [QA-810]

---

## 十一、AHRP 持久化 [QA-900 系列]

### 11.1 AHRPStore
- SQLite WAL 模式 [QA-901]
- save_agent → load_agents 一致 [QA-902]
- save_capabilities → load_capabilities 一致 [QA-903]
- save_escrow → load_escrows 一致 [QA-904]
- save_transaction → load_transactions 一致 [QA-905]

### 11.2 Executor 重启恢复
- Executor 1 注册 agent [QA-906]
- 新建 Executor 2 (同一 db_path) [QA-907]
- Executor 2 自动恢复 agent [QA-908]
- 恢复后 endpoints 正确 [QA-909]

---

## 十二、只读查询层 [QA-1000 系列]

### 12.1 OasyceQuery
- 包装 facade [QA-1001]
- 允许: quote, sell_quote, query_assets, get_pool_info, get_portfolio, access_quote [QA-1002]
- 阻止: buy → AttributeError [QA-1003]
- 阻止: sell → AttributeError [QA-1004]
- 阻止: register → AttributeError [QA-1005]
- 阻止: dispute → AttributeError [QA-1006]

---

## 十三、信誉系统 [QA-1100 系列]

### 13.1 信誉引擎
- 初始信誉 = **0.0** (agent 必须从零开始挣信誉) [QA-1101]
- 成功交易 → +2.0 (递减回报: gain × 1/(1+R/50)) [QA-1102]
- 泄露检测 → -50.0 [QA-1103]
- 数据损坏 → -10.0 [QA-1111]
- 时间衰减 → 每 90 天 -5.0 [QA-1104]
- 分数范围 [0, 95] (floor=0, cap=95) [QA-1105]
- bond discount = max(0.20, 1 - rep/100) [QA-1106]
- 每日增益上限 = 5.0 OAS/天 (防 Sybil 刷分) [QA-1112]

### 13.2 信誉门控 (三级)
- R < 20 → Sandbox: 仅允许 L0 访问 [QA-1113]
- 20 ≤ R < 50 → Limited: 允许 L0, L1 [QA-1114]
- R ≥ 50 → Full: 允许 L0-L3 [QA-1115]

### 13.3 访问等级 (Equity-Based)
- ≥0.1% equity → L0 [QA-1107]
- ≥1% equity → L1 [QA-1108]
- ≥5% equity → L2 [QA-1109]
- ≥10% equity → L3 [QA-1110]

> 注: 访问同时要求 equity 达标 AND 信誉门控通过。

---

## 十四、争议解决 [QA-1200 系列]

### 14.1 争议参数

| 参数 | 值 | QA ID |
|------|-----|-------|
| DISPUTE_FEE | 5.0 OAS (反垃圾) | QA-1209 |
| DEFAULT_JURY_SIZE | 5 人 | QA-1210 |
| MAJORITY_THRESHOLD | 2/3 | QA-1211 |
| MIN_JUROR_REPUTATION | 50.0 | QA-1212 |
| JUROR_REWARD_FIXED | 2.0 OAS/人 | QA-1213 |
| JUROR_STAKE_REQUIRED | 10.0 OAS | QA-1214 |
| VOTING_DEADLINE | 604800 (7 天) | QA-1215 |

### 14.2 争议窗口 (按访问等级)

| 访问等级 | 窗口 | QA ID |
|---------|------|-------|
| L0 | 86400 (1 天) | QA-1216 |
| L1 | 259200 (3 天) | QA-1217 |
| L2 | 604800 (7 天) | QA-1218 |
| L3 | 2592000 (30 天) | QA-1219 |

### 14.3 争议状态机
- DisputeState: OPEN → VOTING → RESOLVED / CANCELLED
- open_dispute() 创建争议，状态 = OPEN [QA-1201]
- 返回 DisputeRecord，dispute_id 非空 [QA-1202]
- 初始状态 = OPEN [QA-1203]
- 指定 access_level 时使用对应窗口 [QA-1220]

### 14.4 陪审团选择
- select_jury(dispute_id, eligible_nodes, jury_size=5) [QA-1207]
- 选择算法: sha256(disputeID + nodeID) × log(1 + reputation) [QA-1221]
- 候选人信誉 ≥ MIN_JUROR_REPUTATION (50.0) [QA-1212]
- 候选人 stake ≥ JUROR_STAKE_REQUIRED (10.0 OAS) [QA-1214]
- 争议双方不能担任陪审员 [QA-1222]

### 14.5 投票
- submit_vote(dispute_id, juror_id, verdict, reason) [QA-1208]
- verdict: "consumer" 或 "provider" [QA-1223]
- 仅选定陪审员可投票 [QA-1224]
- 重复投票被拒绝 [QA-1225]

### 14.6 证据提交
- submit_evidence(dispute_id, party_id, evidence_hash, description) [QA-1226]
- 仅争议双方可提交 [QA-1227]

### 14.7 裁决
- resolve(dispute_id) 统计票数 [QA-1204]
- ≥2/3 投消费者 → CONSUMER_WINS: 退款 + slash provider [QA-1228]
- ≥2/3 投供应商 → PROVIDER_WINS: 支付 + slash consumer [QA-1229]
- 无多数 → NO_MAJORITY: 各退各 [QA-1230]
- remedy=delist → 触发 shutdown [QA-1205]
- remedy=transfer → 转移所有权 [QA-1206]

### 14.8 超时处理
- resolve_timeout(dispute_id) — 投票截止后自动裁决 [QA-1231]
- 超过 VOTING_DEADLINE 无足够票数 → NO_MAJORITY [QA-1232]

### 14.9 陪审员奖惩
- 多数方陪审员: 每人 +JUROR_REWARD_FIXED (2.0 OAS) [QA-1213]
- 多数方陪审员: 信誉 +2.0 [QA-1233]
- 少数方陪审员: 信誉 -5.0 [QA-1234]

---

## 十五、指纹水印 [QA-1300 系列]

### 15.1 文本指纹
- embed_text 嵌入指纹 [QA-1301]
- extract_text 提取指纹 [QA-1302]
- 嵌入 → 提取 = 原始指纹 [QA-1303]

### 15.2 二进制指纹
- embed_binary 嵌入 trailer [QA-1304]
- extract_binary 提取 trailer [QA-1305]
- CRC 校验通过 [QA-1306]

### 15.3 指纹生成
- generate_fingerprint 确定性 (相同输入 → 相同输出) [QA-1307]
- 不同 caller → 不同指纹 [QA-1308]

---

## 十六、数据访问控制 [QA-1400 系列]

### 16.1 分级访问

| 等级 | 方法 | 说明 | QA ID |
|------|------|------|-------|
| L0 | query() | 仅聚合统计 | QA-1401 |
| L1 | sample() | 水印样本 | QA-1402 |
| L2 | compute() | TEE 隔离执行 | QA-1403 |
| L3 | deliver() | 全量交付 | QA-1404 |

### 16.2 Bond 倍数

| 等级 | Multiplier | 最低 Stake | QA ID |
|------|-----------|-----------|-------|
| L0 | 1.0 | — | QA-1409 |
| L1 | 2.0 | — | QA-1410 |
| L2 | 3.0 | 100 OAS | QA-1411 |
| L3 | 5.0 | 500 OAS | QA-1412 |

### 16.3 Bond 计算
- bond = TWAP × Multiplier × RiskFactor × (1 - R/100) × ExposureFactor [QA-1405]
- bond_discount_floor = 0.20 (即使满信誉也至少交 20% bond) [QA-1413]
- 高信誉 → 低 bond [QA-1406]

### 16.4 风险因子

| 风险等级 | Factor | QA ID |
|---------|--------|-------|
| public | 1.0 | QA-1414 |
| low | 1.2 | QA-1415 |
| medium | 1.5 | QA-1416 |
| high | 2.0 | QA-1417 |
| critical | 3.0 | QA-1418 |

### 16.5 碎片化攻击检测
- 检测多次小额访问绕过泄露预算 [QA-1419]
- 触发时 bond 翻倍 (fragmentation_penalty = 2.0) [QA-1420]

### 16.6 泄露预算
- leakage budget 正确递减 [QA-1407]
- 超预算 → 拒绝访问 [QA-1408]
- 泄露达 20% 时发出警告 [QA-1421]
- 责任窗口: L0=1天, L1=3天, L2=7天, L3=30天 [QA-1422]

---

## 十七、Agent 技能管线 [QA-1500 系列]

### 17.1 DataVault Pipeline
- scan_data_skill 返回文件信息 [QA-1501]
- classify_data_skill 返回分类 [QA-1502]
- check_privacy_skill 检测 PII [QA-1508]
- filter_batch_skill 批量过滤 [QA-1509]
- generate_metadata_skill 返回元数据 [QA-1503]
- create_certificate_skill 返回 PoPC [QA-1504]
- register_data_asset_skill 注册资产 [QA-1505]

### 17.2 Pipeline 顺序
- scan → classify → privacy → filter → metadata → certificate → register [QA-1506]
- 中断任一步骤 → 正确报错 [QA-1507]

### 17.3 搜索与交易技能
- search_data_skill(query_tag) 返回匹配资产列表 [QA-1510]
- trade_data_skill(asset_id) 执行交易 [QA-1511]
- discover_and_buy_skill(query, buyer, max_price, amount) — 搜索+报价+购买一站式 [QA-1512]
- buy_shares_skill(asset_id, buyer, amount) 购买股份 [QA-1513]
- get_shares_skill(owner) 查询持仓 [QA-1514]

### 17.4 定价与经济
- calculate_price_skill(asset_id, base_price, ...) 返回动态价格 [QA-1515]
- calculate_bond_skill(agent_id, asset_id, access_level) 计算 bond [QA-1516]
- stake_skill(validator_id, amount) 质押 [QA-1517]
- mine_block_skill() 出块 [QA-1518]

### 17.5 指纹水印技能
- fingerprint_embed_skill(asset_id, caller_id, content) [QA-1519]
- fingerprint_extract_skill(content) [QA-1520]
- fingerprint_trace_skill(fingerprint) [QA-1521]
- fingerprint_list_skill(asset_id) [QA-1522]

### 17.6 访问控制技能 (L0-L3)
- query_data_skill(agent, asset, query) → L0 [QA-1523]
- sample_data_skill(agent, asset, size) → L1 [QA-1524]
- compute_data_skill(agent, asset, code) → L2 [QA-1525]
- deliver_data_skill(agent, asset) → L3 [QA-1526]

### 17.7 信誉与合规
- check_reputation_skill(agent_id) 查询信誉 [QA-1527]
- check_leakage_budget_skill(agent, asset) 查询泄露预算 [QA-1528]
- get_asset_standard_skill(asset_id) 资产合规标准 [QA-1529]
- validate_asset_standard_skill(asset_id) 验证合规 [QA-1530]

### 17.8 贡献证明
- generate_contribution_proof_skill(file, key, source_type) [QA-1531]
- verify_contribution_proof_skill(cert, file) [QA-1532]

### 17.9 节点技能
- start_node_skill() 启动 P2P 节点 [QA-1533]
- node_info_skill() 查看节点信息 [QA-1534]
- enable_privacy_filter(enable) 隐私过滤开关 [QA-1535]

---

## 十八、AHRP 协议 [QA-1600 系列]

### 18.1 Executor
- handle_announce 注册 agent [QA-1601]
- 要求最低 stake (mainnet) [QA-1602]
- 签名验证 (network mode) [QA-1603]
- find_matches 返回匹配 [QA-1604]

### 18.2 Router
- announce 索引 agent [QA-1605]
- search 按 tag/reputation 过滤 [QA-1606]
- route 返回排名 [QA-1607]
- 过期 agent 自动清理 [QA-1608]

### 18.3 Market (拍卖)
- 拍卖创建 [QA-1609]
- 竞价提交 [QA-1610]
- 拍卖结算 [QA-1611]

---

## 十九、资产生命周期 [QA-1700 系列]

### 19.1 状态机
- ACTIVE → SHUTDOWN_PENDING → TERMINATED [QA-1701]
- initiate_shutdown 触发关停 [QA-1702]
- 关停期间: 买入阻止, 卖出限制 [QA-1703]
- finalize_termination 完成终止 [QA-1704]
- claim_termination 领取分红 [QA-1705]

### 19.2 版本管理
- add_asset_version 追加版本 [QA-1706]
- get_asset_versions 返回版本链 [QA-1707]

---

## 二十、CLI 命令 [QA-2000 系列]

> `oas` 命令行支持 57+ 顶级命令，所有命令支持 `--json` 结构化输出。

### 20.1 数据资产

| 命令 | 功能 | QA ID |
|------|------|-------|
| `oas register` | 注册数据资产 | QA-2001 |
| `oas search <tag>` | 按标签搜索 | QA-2002 |
| `oas quote <id> <amount>` | 买入报价 | QA-2003 |
| `oas buy <id> --buyer --amount` | 买入股份 | QA-2004 |
| `oas sell <id> --tokens --seller` | 卖出股份 | QA-2005 |
| `oas shares <owner>` | 查询持仓 | QA-2006 |
| `oas asset-info <id>` | 资产详情 | QA-2007 |
| `oas asset-validate <id>` | 资产合规验证 | QA-2008 |
| `oas discover <query>` | 搜索+自动报价 | QA-2009 |
| `oas delist <id>` | 下架资产 | QA-2010 |
| `oas scan <path>` | 扫描目录寻找可注册资产 | QA-2011 |

### 20.2 访问控制

| 命令 | QA ID |
|------|-------|
| `oas access quote <id> --level` | QA-2012 |
| `oas access buy <id> --agent --level --amount` | QA-2013 |
| `oas access query <id> --agent --query` | QA-2014 |
| `oas access sample <id> --agent --size` | QA-2015 |
| `oas access compute <id> --agent --code` | QA-2016 |
| `oas access deliver <id> --agent` | QA-2017 |
| `oas access bond <id> --agent --level` | QA-2018 |

### 20.3 争议与治理

| 命令 | QA ID |
|------|-------|
| `oas dispute <id> --reason --consumer` | QA-2019 |
| `oas resolve --dispute-id --remedy` | QA-2020 |
| `oas jury-vote <dispute_id> --juror --verdict` | QA-2021 |

### 20.4 信誉与指纹

| 命令 | QA ID |
|------|-------|
| `oas reputation check <address>` | QA-2022 |
| `oas reputation update <target> --score` | QA-2023 |
| `oas fingerprint embed <file> --caller` | QA-2024 |
| `oas fingerprint extract <file>` | QA-2025 |
| `oas fingerprint trace <fp>` | QA-2026 |
| `oas fingerprint list <asset_id>` | QA-2027 |

### 20.5 贡献与泄露

| 命令 | QA ID |
|------|-------|
| `oas contribution prove <file> --key` | QA-2028 |
| `oas contribution verify <cert> <file>` | QA-2029 |
| `oas contribution score` | QA-2030 |
| `oas leakage check <id> --agent` | QA-2031 |
| `oas leakage reset <id> --agent` | QA-2032 |
| `oas price <id>` | QA-2033 |
| `oas price-factors <id>` | QA-2034 |

### 20.6 任务市场

| 命令 | QA ID |
|------|-------|
| `oas task post <desc> --budget --deadline` | QA-2035 |
| `oas task list` | QA-2036 |
| `oas task info <id>` | QA-2037 |
| `oas task bid <id> --price --seconds` | QA-2038 |
| `oas task select <id> --agent` | QA-2039 |
| `oas task complete <id>` | QA-2040 |
| `oas task cancel <id>` | QA-2041 |

### 20.7 能力市场

| 命令 | QA ID |
|------|-------|
| `oas capability register --name --endpoint --price --tags` | QA-2042 |
| `oas capability list [--tag --provider]` | QA-2043 |
| `oas capability invoke <cap_id> --input` | QA-2044 |
| `oas capability earnings --provider` | QA-2045 |

### 20.8 节点与网络

| 命令 | QA ID |
|------|-------|
| `oas node info` | QA-2046 |
| `oas node peers` | QA-2047 |
| `oas node start` | QA-2048 |
| `oas node ping --target` | QA-2049 |
| `oas node become-validator --stake` | QA-2050 |
| `oas node become-arbitrator --stake` | QA-2051 |
| `oas node api-key --key` | QA-2052 |
| `oas stake <validator> <amount>` | QA-2053 |

### 20.9 测试网

| 命令 | QA ID |
|------|-------|
| `oas testnet start` | QA-2054 |
| `oas testnet faucet` | QA-2055 |
| `oas testnet status` | QA-2056 |
| `oas testnet onboard` (PoW 自注册) | QA-2057 |
| `oas testnet faucet-serve` (运行 faucet 服务) | QA-2058 |
| `oas testnet reset` | QA-2059 |

### 20.10 Agent 调度器

| 命令 | QA ID |
|------|-------|
| `oas agent start` | QA-2060 |
| `oas agent stop` | QA-2061 |
| `oas agent status` | QA-2062 |
| `oas agent run` | QA-2063 |
| `oas agent config --interval --scan-paths --auto-trade` | QA-2064 |

### 20.11 系统诊断

| 命令 | QA ID |
|------|-------|
| `oas doctor` | QA-2065 |
| `oas status` | QA-2066 |
| `oas demo` | QA-2067 |
| `oas info [--section]` | QA-2068 |
| `oas start` (Dashboard) | QA-2069 |
| `oas serve` (API server) | QA-2070 |
| `oas feedback --message --type` | QA-2071 |
| `oas keys generate` | QA-2072 |
| `oas keys show` | QA-2073 |
| `oas cache list / clear / stats / purge` | QA-2074 |
| `oas trust --address --level` | QA-2075 |
| `oas work list / stats / history` | QA-2076 |
| `oas inbox list / approve / reject / edit` | QA-2077 |
| `oas verify` (PoPC 证书验证) | QA-2078 |

---

## 二十一、Server 端点 [QA-1800 系列]

### 21.1 健康检查
- GET /health 返回 status=ok [QA-1801]
- GET /status 返回完整状态 [QA-1802]
- GET /metrics 返回 Prometheus 格式 [QA-1803]

### 21.2 Settlement 端点
- POST /v1/escrow/create [QA-1804]
- GET /v1/escrow/{id} [QA-1805]
- GET /v1/bonding_curve/{asset_id} [QA-1806]

---

## 二十二、Go 链模块 [QA-1900 系列]

> 这些需要运行中的链才能测试。参见 `oasyce-chain/scripts/e2e_test.sh`。

### 22.1 参数对齐
- Go BurnRate = 0.05 [QA-1901]
- Go TreasuryRate = 0.03 [QA-1902]
- Go ProtocolFeeRate = 0.07 [QA-1903]
- Go ReserveRatio = 0.50 [QA-1904]
- Go ReserveSolvencyCap = 0.95 [QA-1905]

### 22.2 Fee Split
- ReleaseEscrow: 85% provider, 7% validator, 5% burn, 3% treasury [QA-1906]
- SellShares: 7% fee 扣除 [QA-1907]

### 22.3 模块功能
- x/datarights: register, buy, sell, shutdown, migrate [QA-1908]
- x/settlement: create, release, refund escrow [QA-1909]
- x/capability: register, invoke [QA-1910]
- x/reputation: submit-feedback, report [QA-1911]
- x/work: submit-task, commit, reveal, settle [QA-1912]
- x/onboarding: PoW register, repay [QA-1913]

---

## 二十三、内网联机测试 [QA-2100 系列]

> 这些检查点验证链+Python客户端+Dashboard 的全栈联通。
> 需要运行中的链：`python3 scripts/qa_regression.py --include-chain`

### 23.1 链基础设施

- 链二进制存在且可执行 [QA-2101]
- 链 REST API 可达 (GET /cosmos/base/tendermint/v1beta1/node_info) [QA-2102]
- 链 gRPC 端口可达 [QA-2103]

### 23.2 Genesis 参数验证（测试网友好）

- x/capability: min_provider_stake ≤ 100 OAS [QA-2111]
- x/datarights: dispute_deposit ≤ 100 OAS [QA-2112]
- x/onboarding: pow_difficulty ≤ 16 [QA-2113]
- x/onboarding: airdrop_amount ≥ 10 OAS [QA-2114]
- x/work: min_executor_reputation ≤ 50 [QA-2115]
- x/settlement: escrow_timeout ≥ 60s [QA-2116]
- x/settlement: protocol_fee_rate == 0.07 [QA-2117]

### 23.3 参数对齐（Python ↔ Go）

- Python fee_split sum == Go fee_split sum [QA-2121]
- Python reserve_ratio == Go ReserveRatio [QA-2122]
- Python burn_rate == Go BurnRate [QA-2123]
- Python solvency_cap == Go ReserveSolvencyCap [QA-2124]

### 23.4 链上交易流程

- 创建 escrow (LOCKED) [QA-2131]
- 释放 escrow (RELEASED, fee split 正确) [QA-2132]
- 注册数据资产 [QA-2133]
- 购买股份 (Bancor curve) [QA-2134]
- 注册 AI 能力 [QA-2135]
- 调用 AI 能力 (escrow 自动创建) [QA-2136]
- 提交信誉反馈 [QA-2137]

### 23.5 Python-Chain 连通性

- ChainClient.is_connected() == True [QA-2141]
- Facade chain mode 可用 (OASYCE_STRICT_CHAIN=1) [QA-2142]
- Dashboard 能读取链上资产列表 [QA-2143]

---

## 附录 A: QA ID 索引

| 范围 | 模块 | 检查数 |
|------|------|--------|
| QA-100 | 协议参数 | 10 |
| QA-200 | 安全模式 | 6 |
| QA-300 | 经济配置 | 5 |
| QA-400 | Bonding Curve | 29 |
| QA-500 | Facade API | 51 |
| QA-600 | 任务市场 | 14 |
| QA-700 | Chain Client | 12 |
| QA-800 | 中间件 | 10 |
| QA-900 | AHRP 持久化 | 9 |
| QA-1000 | 只读查询 | 6 |
| QA-1100 | 信誉系统 | 15 |
| QA-1200 | 争议解决 | 34 |
| QA-1300 | 指纹水印 | 8 |
| QA-1400 | 数据访问 | 22 |
| QA-1500 | Agent 技能 | 35 |
| QA-1600 | AHRP 协议 | 11 |
| QA-1700 | 资产生命周期 | 7 |
| QA-1800 | Server 端点 | 6 |
| QA-1900 | Go 链 | 13 |
| QA-2000 | CLI 命令 | 78 |
| QA-2100 | 内网联测 | 20 |
| **总计** | | **~401** |

---

## 附录 B: 运行 QA

```bash
# 完整回归 (standalone, 无需链)
python3 scripts/qa_regression.py

# 仅指定模块
python3 scripts/qa_regression.py --module bonding_curve
python3 scripts/qa_regression.py --module facade
python3 scripts/qa_regression.py --module task_market

# 含链上测试 (需要 oasyced 运行中)
python3 scripts/qa_regression.py --include-chain

# 输出 JSON 报告
python3 scripts/qa_regression.py --json > qa_report.json
```

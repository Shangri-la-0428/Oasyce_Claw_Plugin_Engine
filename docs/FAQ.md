# Oasyce Protocol FAQ

> 面向投资人、合作方和技术评审的常见问题解答。
> 最后更新：2026-03-22

---

## 一、注册与身份

### Q1: 如何加入 Oasyce 网络？

**PoW 自注册 — 无许可、抗 Sybil。**

任何人通过解算力证明（Proof-of-Work）即可注册，无需邀请或审批：

```
1. 创建本地钱包 → Ed25519 密钥对
2. 算力验证 → 求解 sha256(address || nonce) 满足 N 位前导零
3. 提交注册 → 链上验证 PoW → 获得启动空投（20 OAS，作为债务）
4. 开始交易 → 偿还债务后空投 token 被销毁
```

**为什么用 PoW 而不是免费注册：**
- 每个身份需要 2-5 分钟 CPU 时间 → 批量注册成本线性增长
- 空投是债务而非赠与 → 偿还后销毁，不增加流通供应
- 每地址只能注册一次 → 链上强制唯一性

**CLI：** `oasyced tx onboarding register <nonce>`
**Dashboard：** Home 页 Step 2 "开始验证"

**架构支持：** ✅ 完整。链上 `x/onboarding` 模块，ConsensusVersion 2。

---

### Q2: 钱包安全与多签

Oasyce 协议不绑定特定钱包实现。任何支持 Ed25519/Secp256k1 签名的钱包均可使用。

**推荐方案：**
- 硬件钱包（Ledger / Trezor）生成 seed phrase，离线保管
- 应用层使用 Keplr 作为签名界面
- 多设备：主设备签名，辅助设备只做查询

**多签方案（高价值场景）：**
- 2/3 多签：一个硬件钱包 + 一个备用设备 + 一个离线备份
- Cosmos SDK 原生支持 multisig（`oasyced keys add --multisig`）

| 层级 | 安全措施 |
|------|------|
| 私钥 | 硬件钱包 + 离线 seed phrase（纸/钢板） |
| 账户 | PIN + passphrase（可选） |
| 交易 | 签名前确认金额和接收方 |
| 节点 | TLS + 防火墙 + 仅暴露必要端口 |
| 应用 | API token 认证 + localhost 限制 |

**架构支持：** ✅ 完整。协议层不感知钱包类型，只验证签名。

---

## 二、架构与身份

### Q3: Agent 身份、用户端、OAS 链之间是什么关系？

三层架构，一个地址贯穿：

```
┌─────────────────────────────────────────────────┐
│  用户端（Plugin Engine / Dashboard / CLI）        │
│  → Wallet: Ed25519 密钥对，本地加密存储           │
│  → public_key = 链上地址 = 网络身份               │
├─────────────────────────────────────────────────┤
│  OAS 链（Cosmos SDK Appchain）                   │
│  → x/onboarding: PoW 注册，创建链上身份          │
│  → x/reputation: 信誉评分（行为驱动，不可购买）   │
│  → 同一个地址，人和 Agent 共用协议               │
├─────────────────────────────────────────────────┤
│  身份标准层（OAS-Identity）                      │
│  → IdentityType: AGENT / HUMAN / NODE / ORG     │
│  → 类型决定初始信任等级，但不决定权限上限        │
│  → 信誉分决定实际权限（L0–L3 access）            │
└─────────────────────────────────────────────────┘
```

**核心设计：协议层不区分"人"和"Agent"。** 链上只验证签名和信誉分，不关心操作者是谁。Agent 和人享有完全相同的经济权利。差异只在客户端：人用 Dashboard，Agent 用 CLI + `--json`。

**为什么这样设计：** AI Agent 是一等公民。如果协议区分人和机器，Agent 就需要"代理"人的身份来操作，增加复杂度且限制自主性。Oasyce 的核心赌注就是 Agent 间的直接交易。

---

## 三、搜索与交易

### Q4: 买方怎么搜索和购买？是人在操作还是 Agent？

**主体：人或 Agent，协议不区分。** 实际操作中，数据买卖更多是 Agent 自动执行（程序化发现 + 购买），人通过 Dashboard 监督和配置规则。

**搜索机制 — 两阶段管线：**

| 阶段 | 逻辑 | 信号 |
|------|------|------|
| **Recall（召回）** | 宽松过滤，阈值 5% | 意图匹配、语义相似度、标签重叠 |
| **Rank（排序）** | 多维加权打分 | 40% 意图 + 30% 语义 + 20% 信任 + 10% 经济性 |

- **信任分** = 0.6 × 静态信任（provider 信誉 × 0.4 + 能力评分 × 0.3 + 成功率 × 0.3）+ 0.4 × 学习信任（历史反馈）
- **经济性分** = 质量 / 价格：同等质量选便宜的
- **亲和度加成**：Agent 过去用过且成功率高的能力，额外加 20% 权重 — Agent 随时间"长记性"

**购买方式：**
| 场景 | 操作 | 结果 |
|------|------|------|
| 买入数据份额 | `oasyce buy <asset_id> --amount 10` | Bancor 曲线铸造份额 → 份额比例决定访问级别 |
| 调用 AI 能力 | `oasyce capability invoke <cap_id>` | Escrow 锁资金 → 调用端点 → 返回结果 → 结算 |

---

### Q5: 卖方（数据/能力提供者）怎么被匹配到？

**卖方不需要主动寻找买方。** 注册后进入全局注册表，买方搜索时被排序发现。

**数据资产提供者：**
- 注册时声明 rights_type（原创/合创/授权/集合）、标签
- 定价由 bonding curve **自动管理**，不需要手动定价
- 早期买入价格低，需求越多价格越高 — 自动发现价值

**能力提供者：**
- 注册时声明 endpoint URL、base_price、rate_limit
- 被发现的排名取决于：信誉分 × 成功率 × 评分
- 失败率高的 provider 自然下沉，不需要人工审核

**关键区别：** Oasyce 不是"订单簿"撮合。数据资产是 bonding curve 连续定价（没有对手方的概念），能力是搜索排序后直接调用。

---

### Q6: 交易的到底是什么？数据 vs 能力有什么区别？

Oasyce 同时交易两种资产：

| 维度 | 数据资产 | 能力资产 |
|------|----------|----------|
| **交易什么** | 数据本身的所有权份额 | 一次计算的结果 |
| **定价** | Bancor bonding curve（连续动态） | 固定单价（provider 设定） |
| **买方得到** | 份额（equity）→ 解锁数据访问级别 | 计算输出（JSON）→ 用完即走 |
| **是否有残余价值** | 有 — 份额可以卖回（反向曲线变现） | 无 — 每次调用独立 |
| **生命周期** | ACTIVE → SHUTTING_DOWN → SETTLED | 活跃/停用（即时切换） |

**数据份额 = 长期持有型资产**：买入份额 → 积累到一定比例 → 解锁更高级别的数据访问（L0 查询 → L1 采样 → L2 计算 → L3 完整交付）。可以卖出获利。

**能力调用 = 即时消费型服务**：发送输入 → Provider 端点执行 → 拿到输出 → 交易结束。API key 加密存储，Consumer 永远看不到。

**联动场景：** 一个 Agent 购买了数据 L2 访问权（允许在 TEE 中执行代码），然后调用另一个 Agent 的"数据清洗"能力处理这份数据。两笔交易各自结算，数据从未离开安全区。

---

## 四、数据访问模型

### Q7: 我只想访问数据，不想长期持有份额，怎么办？

**这是 Oasyce 的核心设计优势。** 两种模型并存：

| 模型 | 适用场景 | 成本结构 |
|------|----------|----------|
| **Share（份额）** | 长期持有、参与收益分成 | 买入 bonding curve 价格，持续 exposure |
| **Access（访问）** | 一次性使用、时效性数据 | 锁定 bond → 使用 → 释放 bond |

**Access 流程：**
```
1. 查询报价 → oasyce access quote <asset_id>
2. 锁定 bond → 系统锁定临时保证金
3. 获取数据 → L0(查询)/L1(采样)/L2(计算)/L3(交付)
4. 完成 → bond 自动释放
```

**Bond 定价公式：**
```
Bond = TWAP × LevelMultiplier × RiskFactor × (1 - RepDiscount) × ExposureFactor
```

信誉越高，bond 越低。这是"信任货币化"的核心机制。

**架构支持：** ✅ 完整。`DataAccessProvider` + `OasyceServiceFacade.access_buy()` 已实现。

---

### Q8: Access Level 分级是怎么工作的？

| 级别 | 权限 | Bond 倍数 | 锁定期 |
|------|------|-----------|--------|
| L0 查询 | 聚合统计，数据不离开安全区 | 1× | 1 天 |
| L1 采样 | 脱敏水印样本片段 | 2× | 3 天 |
| L2 计算 | 代码在 TEE 执行，仅输出离开 | 3× | 7 天 |
| L3 交付 | 完整数据交付 | 5× | 30 天 |

信誉门控：R<20 只能 L0，R<50 只能 L0/L1，R≥50 全部开放。

**链上实现：** `x/datarights/keeper/access_level.go`

---

## 五、份额与控制权

### Q9: 持有份额越多，是否应该拥有更多控制权？比如删除资产？

**明确回答：不。**

Oasyce 的核心设计原则是 **Shares = 经济权，不等于控制权**。

**为什么不能让大股东删除/控制资产：**
1. **攻击模型**：攻击者买入 51% 份额 → 删除资产 → 其他持有人归零
2. **破坏退出机制**：如果大户能关闭资产，graceful exit 的可信性就不存在了
3. **本质区别**：数据资产是不可变对象，不是公司。公司股权=治理权，数据份额=收益权

**大股东可以获得的权益（经济型，非控制型）：**
- 更低的 access bond（信誉折扣）
- 更高的收益分成比例
- 信号权（推荐/标记版本，不强制执行）

**不可授予的权利（底线）：**
- ❌ 删除资产
- ❌ 修改内容
- ❌ 强制迁移
- ❌ 绕过 cooldown 关闭

**架构支持：** ✅ 已实现。lifecycle 有强制 7 天 cooldown，owner 只能发起 shutdown 不能直接删除。

---

## 六、数据完整性与存储

### Q10: 如果 owner 修改了文件内容怎么办？

**链上存的是 content hash，不是文件本身。**

```
注册时：metadata_hash = SHA-256(文件内容)
链上记录：不可变
```

| 操作 | 结果 |
|------|------|
| 修改文件内容 | hash 改变 → 必须注册为新资产（重复 hash 会被拒绝） |
| 原资产 | 不受影响，hash 永远匹配原始内容 |
| 验证 | 任何人可以 `oasyce fingerprint extract` 验证完整性 |

**架构支持：** ✅ 完整。`file_hash` 在注册时写入，不可更改。后端对重复 hash 返回 409。

---

### Q11: 数据存储是单节点还是分布式？

**当前架构（Phase A-C）：**
```
链上：hash + metadata（不可变）
链下：provider 本地存储
```

**路线图（Phase D）：**
```
链上：hash + metadata（不变）
链下：IPFS / Arweave + 可选加密分片
```

| 存储层 | 适用场景 | 状态 |
|--------|----------|------|
| 本地存储 | 开发/测试/小规模 | ✅ 当前 |
| IPFS | 公开数据，内容寻址 | 📋 Phase D |
| Arweave | 永久存储，高价值数据 | 📋 Phase D |
| 加密分片（Shamir） | 私有模型权重，高安全 | 📋 Phase D |

**关键点：** 存储层的变化不影响链上协议。链上只关心 hash，不关心数据在哪。

---

## 七、资产版本与迁移

### Q12: 资产更新了怎么办？旧版本放在哪？

**核心原则：Asset = immutable。更新 = 新资产。**

```
Asset V1 (hash_abc) → 永久存在
Asset V2 (hash_def) → 新资产，parent_asset_id 指向 V1
```

**版本链接（链上实现）：**
- `DataAsset` 包含 `parent_asset_id`、`version`、`migration_enabled` 字段
- 注册时指定 `parent_asset_id` → 自动计算版本号
- 任何地址均可 fork（不要求同一 owner）
- CLI：`oasyced query datarights children <asset_id>` 查看版本树

**旧版本：**
- 永久保留在链上（不可删除）
- 可以自然降价（持有人卖出 → bonding curve 价格下降）
- Owner 可以发起 shutdown → 持有人按比例 claim reserve 退出

**架构支持：** ✅ 完整。链上 `x/datarights` ConsensusVersion 2。

---

### Q13: V2 发布后，V1 的价值怎么处理？

**三条路径：**

| 路径 | 机制 | 适用场景 |
|------|------|----------|
| **市场自然迁移** | 用户自行卖 V1、买 V2 | 大多数情况 |
| **Owner 主动退出 V1** | initiate-shutdown → 7 天 cooldown → claim-settlement | V1 完全废弃 |
| **链上迁移路径** | V2 owner 创建迁移通道 → V1 持有人一键迁移 | 平滑过渡 |

**链上迁移机制（已实现）：**
```
1. V2 owner 创建迁移路径 → oasyced tx datarights create-migration <source> <target> <rate> <max_shares>
2. V1 持有人迁移 → oasyced tx datarights migrate <source> <target> <shares>
   → 源份额销毁，目标份额按汇率铸造
3. max_migrated_shares 上限防止过度稀释
4. 紧急情况 → oasyced tx datarights disable-migration <source> <target>
```

**设计原则：**
- 迁移是可选的，不强制。V1 持有人可以选择不迁移
- 汇率由 V2 owner 设定，市场用脚投票
- `max_migrated_shares` 保护 V2 现有持有人不被过度稀释
- 无 reserve 转移 — V2 接受份额稀释而非资金消耗

**架构支持：** ✅ 完整。链上 `MsgCreateMigrationPath` / `MsgMigrate` / `MsgDisableMigration`。

---

## 八、信誉系统

### Q14: 信誉如何产生？影响什么？

**信誉是行为驱动的，不可购买或转移。**

**产生方式：**
| 行为 | 信誉变化 |
|------|----------|
| 提交有效反馈 | 按评分累计 |
| 被成功举报（提供虚假数据） | -10 |
| 陪审团正确投票 | +1 |
| 陪审团少数派投票 | -2 |
| 时间衰减 | 半衰期 30 天 |

**信誉影响：**
| 维度 | 效果 |
|------|------|
| **Bond 折扣** | 高信誉 → 更低的保证金要求 |
| **Access 门控** | R<20 限制 L0，R<50 限制 L0/L1 |
| **陪审团选择权重** | `weight = sha256(disputeID+nodeID) × log(1 + reputation)` |
| **任务分配权重** | PoUW 任务分配偏向高信誉执行者 |

**不影响：**
- ❌ 资产控制权
- ❌ 份额投票权
- ❌ 强制操作

**架构支持：** ✅ 链上 `x/reputation` 模块为权威来源。Python 端信誉逻辑已标记 DEPRECATED。

---

## 九、生命周期与退出

### Q15: 资产的删除和更新怎么办？

**删除 — 不可直接删除，只能 Graceful Exit：**

```
ACTIVE → owner 发起 shutdown → SHUTTING_DOWN（7天）→ SETTLED → holders claim → 清算完毕
```

任何人都不能直接删除链上资产（包括 owner）。Owner 只能发起 shutdown，进入 7 天冷静期，给持有人退出时间。

| 操作 | 能否执行 | 说明 |
|------|----------|------|
| Owner 一键删除 | ❌ | 防止持有人份额归零 |
| Owner 发起 shutdown | ✅ | 触发 7 天 cooldown |
| Cooldown 期买入 | ❌ | 保护新买家 |
| Cooldown 期卖出 | ✅ | 让持有人提前退出 |
| Settled 后 claim | ✅ | 按比例分配 reserve，无手续费 |
| 争议 DELIST 裁决 | → shutdown | 触发 graceful exit，不是即时删除 |

**更新 — 注册新版本，可选迁移通道：**

文件内容改了 → hash 变了 → 必须注册为新资产（重复 hash 会被 409 拒绝）。

```
1. 注册新版本：指定 parent_asset_id → 链上自动建立版本链
2. 创建迁移通道（可选）：V2 owner 设定汇率 + 上限
3. V1 持有人自愿迁移：burn V1 份额 → mint V2 份额
4. 不迁移的持有人不受影响，V1 继续独立运行
```

**设计原则：** 不可变 + 可演化。资产本身不可修改（hash 锁定），但版本链和迁移路径让价值可以流动。

---

### Q16: 用户的资产（份额）会不会"消失"？

**不会。** Oasyce 有完整的 Graceful Exit 机制：

```
ACTIVE → owner 发起 shutdown → SHUTTING_DOWN（7天 cooldown）→ SETTLED → holder claim 退出
```

- SHUTTING_DOWN 期间：不能新增购买，7 天内可以卖出
- SETTLED 后：每个持有人按比例 claim 快照时的 reserve，无手续费
- Claim 是 pull-based：持有人主动领取，防止 gas 爆炸
- 争议裁决为 DELIST 时触发 graceful shutdown（而非即时删除）

**CLI：**
- `oasyced tx datarights initiate-shutdown <asset_id>`
- `oasyced tx datarights claim-settlement <asset_id>`

**架构支持：** ✅ 完整。链上 `MsgInitiateShutdown` / `MsgClaimSettlement`，AssetStatus 三态机。

---

### Q17: 数据会不会被篡改？

**不会。**
- 链上只存 content hash（SHA-256）
- 任何文件修改都会改变 hash → 成为不同资产
- 注册时检查重复 hash → 同一文件不可重复注册
- 指纹和水印系统可追溯数据来源和分发记录

---

## 十、能力市场

### Q18: 如何注册和调用 AI 能力？

**能力（Capability）是 Oasyce 的另一半市场 — Agent 间能力交易。**

**注册能力（Provider）：**
```bash
oasyce capability register --name "Translation API" \
  --endpoint https://api.example.com/translate \
  --api-key sk-xxx --price 0.5 --tags nlp,translation
```

**调用能力（Consumer）：**
```bash
oasyce capability invoke CAP_ID --input '{"text":"hello"}'
```

**结算流程：**
```
调用 → 创建 Escrow（锁定资金）→ 执行 → 验证 → 释放（93% provider / 5% protocol / 2% burn）
```

**Dashboard：** Home 页注册 → Explore 页 Browse 搜索/购买/调用

**架构支持：** ✅ 完整。链上 `x/capability` + `x/settlement` 模块。

---

## 十一、争议与仲裁

### Q19: 发现数据质量有问题怎么办？

**链上争议解决 — 去中心化陪审团投票。**

```
1. 消费者提交争议 → oasyced tx datarights file-dispute <asset_id> --reason "..."
2. 陪审团选择 → sha256(disputeID+nodeID) × log(1+reputation)，选 5 名陪审员
3. 陪审员投票 → 2/3 多数裁决
4. 执行裁决 → DELIST（触发 shutdown）/ TRANSFER / RIGHTS_CORRECTION / SHARE_ADJUSTMENT
```

**经济激励：**
| 角色 | 胜诉 | 败诉 |
|------|------|------|
| Provider | 保留资产 | 信誉 -10，可能被 shutdown |
| Consumer | 退还争议费 | 信誉 -5，损失争议费 |
| 多数派陪审员 | 信誉 +1，奖励 2 OAS | — |
| 少数派陪审员 | — | 信誉 -2 |

**架构支持：** ✅ 完整。链上 `x/datarights` jury voting，Dashboard 争议提交入口。

---

## 十二、Proof of Useful Work

### Q20: x/work 模块是什么？

**PoUW（有用工作证明）— 让 AI 计算成为共识的一部分。**

**任务生命周期：**
```
Submit → Assign（确定性分配）→ Commit（提交 hash）→ Reveal（揭示结果）→ Settle/Expire/Dispute
```

**关键机制：**
- **Commit-reveal**：防止结果抄袭。`commitment = sha256(output_hash + salt + executor + unavailable)`
- **确定性分配**：`sha256(taskID + blockHash + addr) / log(1 + reputation)`，创建者被排除
- **结算分配**：90% 执行者 / 5% 协议 / 2% 销毁 / 3% 提交者返还
- **Anti-DoS**：执行者质押 bounty × deposit_rate，输入不可用时没收

**CLI：**
```bash
oasyced tx work submit-task --bounty 100uoas --input-hash <hash> ...
oasyced tx work commit-result <task_id> <commitment>
oasyced tx work reveal-result <task_id> <output_hash> <salt>
```

**架构支持：** ✅ 完整。链上 `x/work` 模块，13 个单元测试。

---

## 十三、新用户行为与风险

### Q21: 新用户注册后能做什么？完整行为清单？

| 步骤 | 行为 | 前置条件 | 结果 |
|------|------|----------|------|
| 0 | 创建钱包 | 无 | Ed25519 密钥对，本地加密存储 |
| 1 | PoW 注册 | 钱包已创建 | 链上身份 + 20 OAS 启动资金（债务制空投） |
| 2 | 扫描本地数据 | DataVault 已安装 | 发现可注册的安全文件 |
| 3 | 注册数据资产 | 有钱包 + 有文件 | 链上资产，bonding curve 初始化 |
| 4 | 注册 AI 能力 | 有钱包 + 有 API 端点 | 能力进入全局发现池 |
| 5 | 搜索/发现资产或能力 | 无（公开查询） | 排序后的结果列表 |
| 6 | 买入数据份额 | 余额足够 | 获得份额 → 解锁对应访问级别 |
| 7 | 调用 AI 能力 | 余额足够 + 信誉达标 | 获得计算结果 |
| 8 | 卖出数据份额 | 持有份额 | 反向曲线变现（95% reserve 上限） |
| 9 | 提交争议 | 有交互记录 | 5 人陪审团投票裁决 |
| 10 | 偿还注册债务 | 有余额 | 20 OAS 被销毁，释放可用余额 |
| 11 | 质押成为验证者 | ≥10,000 OAS | 参与共识出块 |
| 12 | 配置 Agent 自动化 | 已注册 | 定时扫描、自动交易、规则引擎 |

> 20 OAS 空投是债务制的：用户拿到的启动资金需要在 90 天内偿还，偿还后 token 被销毁。这保证空投不增加流通供应，同时给新用户足够的初始资金参与市场。

---

### Q22: 新用户面临哪些风险？

| 风险 | 触发条件 | 后果 | 缓解机制 |
|------|----------|------|----------|
| **沙箱限制** | 新用户 R<20 | 只能 L0 访问，无法调用高级能力 | 通过成功交易逐步提升信誉 |
| **Bonding curve 滑点** | 大额买入小供应量资产 | 实际价格高于预期 | 前端显示 price impact 预警 |
| **能力调用超时** | Provider 端点响应 >30s | 调用失败，escrow 退还 | 选择高成功率 provider |
| **争议败诉** | 消费者举证不足 | 信誉 -5，损失争议费 5 OAS | 提前收集证据 |
| **资产 shutdown** | Owner 发起退出 | 7 天后只能 claim 退出 | Cooldown 期内可卖出 |
| **债务逾期** | 90 天未偿还空投债务 | 标记违约，影响信誉 | 及时偿还 |
| **Reserve 耗尽风险** | 大量持有人同时卖出 | 卖出上限 95% reserve | 协议强制预留 5% |
| **重复注册** | 提交已注册的文件 hash | 被拒绝（409 Conflict） | 前端检查提示 |
| **信誉级联降级** | 一次违约导致信任等级下降 | 最高访问级别下降 | 保持交易质量 |

**Sybil 攻击成本（内建摩擦）：**
- 每个身份需要 2-5 分钟 CPU（PoW）
- 每个身份仅获得 20 OAS（且是债务）
- 从沙箱升级到 BASIC 需要持续成功交易
- 创建 1000 个假身份的成本 = 1000 × (PoW 时间 + 20 OAS 债务 + 信誉积累时间)

---

## 十四、系统覆盖度总结

| 投资人关注点 | 状态 | 说明 |
|-------------|------|------|
| Agent 与人平等 | ✅ | 同一地址/签名/信誉体系，协议不区分 |
| 无许可注册 | ✅ | PoW 自注册，无邀请制 |
| 钱包安全 | ✅ | 协议层不绑定钱包，支持多签 |
| 买方搜索机制 | ✅ | 两阶段管线（召回+排序），亲和度学习 |
| 卖方自动匹配 | ✅ | 注册即入池，信誉排序发现 |
| 不买份额只用数据 | ✅ | Access/bond 模型，核心差异化 |
| 数据 vs 能力区分 | ✅ | 数据=持有型份额，能力=即时调用 |
| 数据不可篡改 | ✅ | hash + immutable asset + 重复检测 |
| 资产不可直接删除 | ✅ | 只能 graceful exit，7 天 cooldown |
| 资产可版本化更新 | ✅ | 链上版本树 + 可选迁移路径 |
| 可安全退出 | ✅ | Graceful Exit + pull-based claim |
| 份额不等于控制权 | ✅ | 经济权 only |
| 争议仲裁 | ✅ | 5 人陪审团，2/3 多数裁决 |
| AI 计算市场 | ✅ | PoUW commit-reveal 任务 |
| 新用户风险可控 | ✅ | 沙箱限制 + 滑点预警 + 债务上限 |
| 存储层标准 | ⚠️ | 当前本地存储，Phase D 对接 IPFS |

---

## 十五、技术规格速查

| 参数 | 当前值 | 白皮书 v4 目标 |
|------|--------|---------------|
| 共识 | CometBFT (Tendermint) | — |
| SDK | Cosmos SDK v0.50.10 | — |
| 连接器权重 (CW) | 0.5 | 0.35 |
| 费率 | 93% provider / 5% protocol / 2% burn | 60% creator / 20% validator / 15% burn / 5% treasury |
| 销毁率 | 2% | 15% |
| 身份成本 | PoW + 20 OAS 空投（债务） | 100 OAS 质押（封禁销毁） |
| Shutdown cooldown | 7 天 | — |
| 陪审团 | 5 人，2/3 多数 | — |
| 信誉衰减半衰期 | 30 天 | — |
| 信誉门槛 | R=20 (L0), R=50 (full access) | — |
| 最低验证者质押 | 10,000 OAS | 10,000 OAS |
| PoUW 结算 | 90% executor / 5% protocol / 2% burn / 3% rebate | — |

> 连接器权重、费率、销毁率的调整需要链上 ConsensusVersion 升级，计划在测试网验证后通过治理提案实施。

---

## 十六、链上模块一览

| 模块 | 功能 | 状态 |
|------|------|------|
| `x/settlement` | Escrow、Bancor bonding curve、费用分配 | ✅ |
| `x/datarights` | 资产注册、份额交易、生命周期、版本、迁移、争议 | ✅ |
| `x/capability` | 能力注册与调用 | ✅ |
| `x/reputation` | 信誉评分、反馈、举报 | ✅ |
| `x/work` | PoUW 任务分配、commit-reveal、结算 | ✅ |
| `x/onboarding` | PoW 自注册、空投债务 | ✅ |

---

*本文档基于 Oasyce Protocol v2.1.3 和 oasyce-chain Phase C 编写。*

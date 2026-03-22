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

## 二、数据访问模型

### Q3: 我只想访问数据，不想长期持有份额，怎么办？

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

### Q4: Access Level 分级是怎么工作的？

| 级别 | 权限 | Bond 倍数 | 锁定期 |
|------|------|-----------|--------|
| L0 查询 | 聚合统计，数据不离开安全区 | 1× | 1 天 |
| L1 采样 | 脱敏水印样本片段 | 2× | 3 天 |
| L2 计算 | 代码在 TEE 执行，仅输出离开 | 3× | 7 天 |
| L3 交付 | 完整数据交付 | 5× | 30 天 |

信誉门控：R<20 只能 L0，R<50 只能 L0/L1，R≥50 全部开放。

**链上实现：** `x/datarights/keeper/access_level.go`

---

## 三、份额与控制权

### Q5: 持有份额越多，是否应该拥有更多控制权？比如删除资产？

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

## 四、数据完整性与存储

### Q6: 如果 owner 修改了文件内容怎么办？

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

### Q7: 数据存储是单节点还是分布式？

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

## 五、资产版本与迁移

### Q8: 资产更新了怎么办？旧版本放在哪？

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

### Q9: V2 发布后，V1 的价值怎么处理？

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

## 六、信誉系统

### Q10: 信誉如何产生？影响什么？

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

## 七、生命周期与退出

### Q11: 用户的资产（份额）会不会"消失"？

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

### Q12: 数据会不会被篡改？

**不会。**
- 链上只存 content hash（SHA-256）
- 任何文件修改都会改变 hash → 成为不同资产
- 注册时检查重复 hash → 同一文件不可重复注册
- 指纹和水印系统可追溯数据来源和分发记录

---

## 八、能力市场

### Q13: 如何注册和调用 AI 能力？

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

## 九、争议与仲裁

### Q14: 发现数据质量有问题怎么办？

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

## 十、Proof of Useful Work

### Q15: x/work 模块是什么？

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

## 十一、系统覆盖度总结

| 投资人关注点 | 状态 | 说明 |
|-------------|------|------|
| 无许可注册 | ✅ | PoW 自注册，无邀请制 |
| 钱包安全 | ✅ | 协议层不绑定钱包，支持多签 |
| 不买份额只用数据 | ✅ | Access/bond 模型，核心差异化 |
| 数据不可篡改 | ✅ | hash + immutable asset + 重复检测 |
| 可安全退出 | ✅ | Graceful Exit + pull-based claim |
| 份额不等于控制权 | ✅ | 经济权 only |
| 版本管理与迁移 | ✅ | 链上版本树 + 迁移路径 |
| 争议仲裁 | ✅ | 5 人陪审团，2/3 多数裁决 |
| AI 计算市场 | ✅ | PoUW commit-reveal 任务 |
| 存储层标准 | ⚠️ | 当前本地存储，Phase D 对接 IPFS |

---

## 十二、技术规格速查

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

## 十三、链上模块一览

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

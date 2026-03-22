# Oasyce 全量需求与架构审查

> Date: 2026-03-22
> Scope: `README.md`、`dashboard/README.md`、`docs/FAQ.md`、CLI surface、Dashboard 五个页面、GUI API、`OasyceServiceFacade` 及其下游服务

## 审查边界

本次审查按两类需求源处理：

- 契约性需求：`README.md`、`dashboard/README.md`、`docs/FAQ.md`、当前 CLI/GUI 对外入口。这里的缺失、失真、闭环中断按真实问题记录。
- 路线图需求：`docs/PHASE3_PLUS_DESIGN.md`、`dashboard/MIGRATION.md`、`TODO.md`。这里的未实现不直接算缺陷，但若与现状冲突，记为文档漂移或架构债务。

## 审查方法

- 静态审查：核对文档承诺、CLI parser、Dashboard 路由、`oasyce/gui/app.py`、`oasyce/services/facade.py` 及关键服务实现。
- 运行审查：
  - fallback 模式：`OASYCE_ALLOW_LOCAL_FALLBACK=1 ... python3 -m oasyce.cli gui --port 18421`
  - strict 模式：`python3 -m oasyce.cli gui --port 18420`
  - CLI surface：`python3 -m oasyce.cli --help`、`access --help`、`capability --help`、`agent --help`
- 限制：
  - 本轮没有浏览器自动化，GUI 运行态主要通过实际 API 调用和对应页面代码双向核验。
  - 本轮没有运行 Go 链节点；链模式相关结论以 strict 模式运行结果和代码路径为准。

## 状态与严重级别

### 状态

- `Implemented`
- `Implemented but undiscoverable`
- `Partial`
- `Docs-only`
- `Inconsistent`
- `Roadmap-only`

### 严重级别

- `P0`: 核心流不可用，或 README / FAQ 的核心承诺在默认产品路径上不成立
- `P1`: 功能存在但闭环断裂，或用户看到的价格 / 权限 /行为与实际不一致
- `P2`: 产品入口不足、文档失真、局部能力未闭环
- `P3`: 架构清理项、迁移债务、内部边界不统一

## 执行摘要

本轮发现 15 个有意义的需求记录，其中：

- `P0`: 2
- `P1`: 6
- `P2`: 5
- `P3`: 2

最关键的结论：

1. 默认 strict 模式下，README / FAQ 描述的新用户本地 onboarding 并不能闭环。`/api/faucet` 要求先完成注册，而 `/api/register` 在没有 Go 链时直接失败。
2. GUI 的 `/api/buy` 在真实运行时会崩溃，返回 `local variable 'hashlib' referenced before assignment`，份额购买主链路不可用。
3. `access quote` 和 `access buy` 对同一用户同一资产给出了不同的 bond 结果。报价显示 L0 为 `0`，实际购买返回 `1.0`，价格契约不可信。
4. Automation 的 `ConfirmationInbox` 没有走 `_config.data_dir`，而是硬编码写到 `~/.oasyce/inbox.json`；并且保存不是原子写，文件已在审查中被写坏，随后 `/api/inbox` 直接异常。
5. 对外契约存在明显漂移：README 仍然宣传 `consensus`、`governance`、`access grant/revoke` 等命令，但当前 CLI surface 中并不存在这些入口。

总体判断：

- 用户视角：产品不是“整体不可用”，但当前更接近“局部闭环、整体契约失真”。fallback 模式下不少流程能跑；默认 strict 模式、份额购买、自动化持久化、网络/共识承诺仍然不稳。
- 架构视角：`OasyceServiceFacade` 已经成为一部分业务收敛点，但 GUI 仍保留 direct SQL、local JSON、legacy fallback、以及 handler 内额外业务逻辑，边界尚未统一。

## 需求覆盖矩阵

| ID | 来源 | 目标用户 | 承诺行为 | 状态 | 严重级别 |
|---|---|---|---|---|---|
| REQ-01 | `README.md` 快速开始；`docs/FAQ.md` Q1 | 新用户 | 本地启动后完成 PoW 注册、领取 OAS、开始交易 | `Inconsistent` | `P0` |
| REQ-02 | `README.md` 注册第一个资产 | 数据提供者 | CLI / Dashboard 注册资产 | `Partial` | `P2` |
| REQ-03 | `README.md` Explore；Dashboard 路由 | 买方 / 浏览者 | 浏览数据资产与能力资产 | `Implemented` | `-` |
| REQ-04 | `README.md` 数据资产交易 | 买方 | 报价后购买份额 | `Inconsistent` | `P0` |
| REQ-05 | `docs/FAQ.md` Q7/Q8；`access` surface | AI 开发者 / 数据买方 | 只买访问不买份额，按 L0-L3 分级访问 | `Inconsistent` | `P1` |
| REQ-06 | `README.md` 能力市场；FAQ Q6 | 能力提供者 / 调用方 | 发布能力、发现能力、调用并结算 | `Partial` | `P2` |
| REQ-07 | Dashboard Automation；`scan/inbox/trust/agent` | 自动化用户 | 扫描目录、进入 inbox、审批与 trust 自动化 | `Inconsistent` | `P1` |
| REQ-08 | README 五条铁律；Network 水印工具 | 数据提供者 / 审计者 | 水印嵌入、提取、分发追踪 | `Partial` | `P1` |
| REQ-09 | README 共识 / 节点；Dashboard Network | 节点 / 验证者 / 仲裁者 | 节点角色、质押、共识状态 | `Inconsistent` | `P1` |
| REQ-10 | README 争议；FAQ 争议与通知 | 数据提供者 / 买方 | 发起争议、裁决、通知 | `Partial` | `P2` |
| REQ-11 | FAQ Q9 / Graceful Exit | 持有人 / owner | 份额不等于控制权，资产只能走 Graceful Exit | `Implemented but undiscoverable` | `P2` |
| REQ-12 | FAQ Q10 / Q13 | 数据提供者 | Asset immutable，更新必须是新资产 | `Inconsistent` | `P1` |
| REQ-13 | FAQ Q2 | 高价值用户 / 机构 | 冷钱包、多签、硬件钱包安全路径 | `Docs-only` | `P2` |
| REQ-14 | FAQ Q11 | 协议接入者 | 当前本地存储，未来分布式存储 | `Roadmap-only` | `P3` |
| REQ-15 | `README.md` CLI 速查 | CLI 用户 | README 列出的命令和参数能直接使用 | `Inconsistent` | `P1` |
| REQ-16 | `dashboard/MIGRATION.md`；`app.py` fallback | 维护者 | SPA 已迁完后删除 legacy fallback | `Inconsistent` | `P3` |

## 需求记录

### REQ-01 新用户 onboarding / faucet / 首次交易

- 来源：`README.md:57-103`，`docs/FAQ.md:10-31`
- 目标用户：新用户
- 承诺行为：创建钱包，完成 PoW 注册，领取启动 OAS，然后继续交易
- 实际入口：Home 页；`/api/identity/create`、`/api/faucet`、`/api/register`
- 代码证据：`oasyce/gui/app.py:1920-2123`
- 运行证据：
  - strict 模式（18420）：`POST /api/faucet` 返回 `{"ok": false, "error": "Complete registration first"}`
  - strict 模式（18420）：`POST /api/register` 返回 `Chain registration failed ... http://localhost:1317/...`
  - fallback 模式（18421）：`POST /api/faucet` 与 `GET /api/balance` 能闭环
- 状态：`Inconsistent`
- 严重级别：`P0`
- 架构归属：GUI onboarding + facade + chain bridge

结论：默认 strict 路径并不满足 README / FAQ 描述的本地即开即用体验。现在只有 fallback 本地模式能完成这个闭环，而这一点没有被文档明确成“兼容模式”。

### REQ-02 数据资产注册

- 来源：`README.md:91-103`
- 目标用户：数据提供者
- 承诺行为：CLI 或 Dashboard 注册第一个资产
- 实际入口：`oasyce register`；Dashboard `My Data`；`/api/register`
- 代码证据：`oasyce/cli.py:104-174`，`oasyce/gui/app.py:2125-2198`
- 运行证据：
  - fallback 模式（18421）：`POST /api/register` 注册 `README.md` 成功，得到 `OAS_ADD6B09E`
  - strict 模式（18420）：同样调用直接失败，卡在链交易提交
- 状态：`Partial`
- 严重级别：`P2`
- 架构归属：Facade register + GUI register handler

结论：注册功能本身存在，但当前产品没有把“链模式前置条件”解释清楚，导致 README 上的“注册第一个资产”对默认本地用户并不稳定。

### REQ-03 资产与能力浏览

- 来源：`README.md:100-103`，Dashboard Explore
- 目标用户：浏览者 / 买方
- 承诺行为：看到网络上的数据资产和能力资产
- 实际入口：`dashboard/src/pages/explore.tsx`，`dashboard/src/pages/explore-browse.tsx`
- 代码证据：`dashboard/src/pages/explore.tsx:12-40`，`dashboard/src/pages/explore-browse.tsx:67-81`
- 运行证据：
  - fallback 模式（18421）：`GET /api/assets` 返回已注册数据资产
  - fallback 模式（18421）：`GET /api/capabilities` 返回能力资产，且能看到 delivery registry 合并结果
- 状态：`Implemented`
- 严重级别：`-`
- 架构归属：Explore 页面 + merged capability listing

### REQ-04 份额报价与购买

- 来源：`README.md:132-141`
- 目标用户：数据买方
- 承诺行为：先 quote，再 buy 数据份额
- 实际入口：CLI `quote` / `buy`；Dashboard Explore；`/api/quote`、`/api/buy`
- 代码证据：
  - `oasyce/gui/app.py:1077-1118`
  - `oasyce/gui/app.py:2564-2588`
  - `oasyce/gui/app.py:1921-1923` 在 `do_POST()` 内局部 `import hashlib`
- 运行证据：
  - fallback 模式（18421）：`GET /api/quote?asset_id=OAS_ADD6B09E&amount=10` 成功
  - fallback 模式（18421）：`POST /api/buy` 返回 `{"error": "local variable 'hashlib' referenced before assignment"}`
- 状态：`Inconsistent`
- 严重级别：`P0`
- 架构归属：GUI buy handler + shared facade + Python function scope bug

结论：报价主路径正常，但购买主路径直接崩溃，属于发布阻断级缺陷。根因是 `do_POST()` 内部某个分支的局部 `import hashlib` 污染了整个函数作用域。

### REQ-05 只买访问，不买份额

- 来源：`docs/FAQ.md:155-195`，CLI `access`
- 目标用户：AI 开发者 / 数据买方
- 承诺行为：按 L0-L3 购买访问权，信誉决定可达级别
- 实际入口：CLI `access quote/buy/...`；Explore 访问面板；`/api/access/quote`、`/api/access/buy`
- 代码证据：
  - `oasyce/services/facade.py:535-671`
  - `oasyce/gui/app.py:1014-1048`
  - `oasyce/gui/app.py:2496-2562`
  - `dashboard/src/pages/explore-browse.tsx:163-212`
- 运行证据：
  - fallback 模式（18421）：`GET /api/access/quote` 对 `R=0` 返回 L0 可用、L1-L3 锁定
  - fallback 模式（18421）：`POST /api/access/buy` 购买 `L1` 返回 `Access denied: Reputation 0 < 50`
  - fallback 模式（18421）：同一用户同一资产，quote 显示 `L0 bond = 0`，实际 `POST /api/access/buy` 返回 `bond = 1.0`
- 状态：`Inconsistent`
- 严重级别：`P1`
- 架构归属：Facade access pricing + GUI mapping

结论：信誉门控是生效的，但价格契约不可信。同一个 access 流里，quote 和 buy 的实际 bond 不一致，用户无法把报价当成真实成交预期。

### REQ-06 能力市场

- 来源：`README.md:160-169`，FAQ Q6
- 目标用户：能力提供者 / 调用方
- 承诺行为：注册能力、被发现、被调用、形成收益
- 实际入口：CLI `capability`；Dashboard 注册能力与 Explore invoke；`/api/delivery/*`、`/api/capabilities`
- 代码证据：
  - `dashboard/src/components/register-form.tsx:165-194`
  - `dashboard/src/pages/explore-browse.tsx:214-231`
  - `oasyce/gui/app.py:510-564`
  - `oasyce/gui/app.py:715-760`
- 运行证据：
  - fallback 模式（18421）：`GET /api/capabilities` 返回 `CAP_6919185A89125F3D`
  - fallback 模式（18421）：`POST /api/delivery/invoke` 能创建 invocation，并在 endpoint 校验失败时退款返回结构化错误
- 状态：`Partial`
- 严重级别：`P2`
- 架构归属：Delivery registry + merged capability listing

结论：发布与发现路径已经接上，且 listing 已做 registry merge；但本轮没有跑出一个成功的外部调用结算闭环，只能确认 invoke 路径会 fail-closed 并退款。

### REQ-07 Scanner / Inbox / Trust / Agent Automation

- 来源：Dashboard Automation；CLI `scan`、`inbox`、`trust`、`agent`
- 目标用户：自动化用户
- 承诺行为：扫描本地目录，进入 inbox，编辑/批准/拒绝，保存 trust config，驱动 agent 自动化
- 实际入口：`dashboard/src/pages/automation.tsx`；`/api/scan`、`/api/inbox*`
- 代码证据：
  - `dashboard/src/pages/automation.tsx:192-420`
  - `oasyce/gui/app.py:1377-1388`
  - `oasyce/gui/app.py:3224-3315`
  - `oasyce/services/inbox.py:56-61`
  - `oasyce/services/inbox.py:217-247`
- 运行证据：
  - fallback 模式（18421）：`POST /api/scan` 扫描 examples 成功，加入 3 个 pending item
  - fallback 模式（18421）：`POST /api/inbox/trust` 成功保存 `trust_level=1`、`auto_threshold=0.8`
  - fallback 模式（18421）：approve / reject / edit 之后，`~/.oasyce/inbox.json` 出现重复尾块，不再是合法 JSON
  - 随后 `GET /api/inbox` 返回空响应；服务端堆栈为 `json.decoder.JSONDecodeError: Extra data`
- 状态：`Inconsistent`
- 严重级别：`P1`
- 架构归属：ConfirmationInbox local JSON persistence

结论：Automation 页不是简单的边角功能，而是当前 dashboard 的主用户流之一。`ConfirmationInbox` 既没有原子写，也没有使用 `_config.data_dir`，会把全局 `~/.oasyce` 写坏，属于明显的架构与运行态双重问题。

### REQ-08 水印嵌入 / 提取 / 追踪

- 来源：README 五条铁律；Network watermark 工具
- 目标用户：数据提供者 / 审计者
- 承诺行为：嵌入 fingerprint、提取 fingerprint、追踪分发记录
- 实际入口：`dashboard/src/pages/network.tsx`
- 代码证据：
  - `dashboard/src/pages/network.tsx:236-262`
  - `oasyce/gui/app.py:943-949`
  - `oasyce/gui/app.py:3138-3207`
- 运行证据：
  - fallback 模式（18421）：`POST /api/fingerprint/extract` 返回结构化结果，`GET /api/fingerprint/distributions` 返回分发列表
  - fallback 模式（18421）：前端使用的 embed payload 为 `{file_path, caller_id}`，而后端 `POST /api/fingerprint/embed` 要求 `asset_id, caller_id, content`
  - 带 token 直接调用 embed，返回 `{"error": "asset_id, caller_id, content required"}`
- 状态：`Partial`
- 严重级别：`P1`
- 架构归属：Network page contract + fingerprint API

结论：后端能力并非不存在，但 Network 页发出的请求不符合后端契约，导致“页面上看似有工具，实际上 embed 不能用”。

### REQ-09 节点角色 / 共识 / 质押

- 来源：`README.md:171-197`，Dashboard Network
- 目标用户：节点 / 验证者 / 仲裁者
- 承诺行为：查看共识状态、注册验证者、委托质押、节点信息、仲裁角色
- 实际入口：Network 页；README CLI；`/api/node/*`、`/api/consensus/*`
- 代码证据：
  - `dashboard/src/pages/network.tsx:220-280`
  - `oasyce/gui/app.py:1423-1456`
  - `oasyce/gui/app.py:2990-3137`
  - `oasyce/cli.py --help` 实际 surface 不含 `consensus` / `governance`
- 运行证据：
  - fallback 模式（18421）：`GET /api/consensus/status` 返回 `Consensus features moved to Go chain. Use oasyced CLI.`
  - 当前 CLI `--help` 没有 `consensus` 命令；README 仍将其作为直接可用命令宣传
- 状态：`Inconsistent`
- 严重级别：`P1`
- 架构归属：Network UI + README contract + Go chain migration boundary

结论：这里的问题不是“完全没有实现”，而是产品仍然对外暴露了一套已经迁移到 Go 链、但当前 Python product 不再真正承载的能力。

### REQ-10 争议与通知

- 来源：README 争议命令；FAQ 争议 / 通知能力
- 目标用户：数据提供者 / 买方
- 承诺行为：发起争议、仲裁、接收通知
- 实际入口：CLI `dispute/jury-vote/resolve`；Dashboard `My Data` / `Network`
- 代码证据：
  - `oasyce/gui/app.py:1850-1894`
  - `oasyce/gui/app.py:2439-2494`
  - `oasyce/gui/app.py:3170-3188`
- 运行证据：
  - fallback 模式（18421）：通知接口可返回结构，但本轮未形成完整 dispute -> vote -> resolve 闭环
  - 代码层面 dispute list / detail 仍走本地 sqlite，而 POST dispute / resolve 已走 facade
- 状态：`Partial`
- 严重级别：`P2`
- 架构归属：GUI dispute API split between facade and direct SQL

结论：争议流已经部分 facade 化，但 authority 还不单一。读取与写入来自不同栈，后续极易形成状态不一致。

### REQ-11 份额不等于控制权 / Graceful Exit

- 来源：`docs/FAQ.md:198-223`，`docs/FAQ.md:363-407`
- 目标用户：持有人 / owner
- 承诺行为：份额只代表经济权；资产只能走 shutdown -> termination -> claim 的 Graceful Exit
- 实际入口：当前没有公开 CLI / GUI 入口
- 代码证据：
  - `oasyce/services/facade.py:1140-1266`
  - `oasyce/services/settlement/engine.py:451-547`
- 运行证据：
  - CLI surface 无 `shutdown` / `terminate` / `claim` 命令
  - Dashboard 与 GUI API 也没有公开这组 facade 能力
- 状态：`Implemented but undiscoverable`
- 严重级别：`P2`
- 架构归属：Facade lifecycle exists, public product surface missing

结论：底层机制是有的，但“已实现”对外说法太满。对普通用户来说，这更像是还没暴露的内部能力，而不是产品能力。

### REQ-12 资产不可变，更新即新资产

- 来源：`docs/FAQ.md:228-243`，`docs/FAQ.md:276-320`
- 目标用户：数据提供者 / 技术评审
- 承诺行为：Asset immutable；更新必须注册新资产
- 实际入口：GUI 仍提供 `/api/re-register`
- 代码证据：
  - `oasyce/gui/app.py:2385-2437`
- 运行证据：
  - 代码明确对同一 `asset_id` 计算新 hash，并把 `versions` 写回同一条 metadata
  - 这与 FAQ 的 `Asset = immutable。更新 = 新资产。` 直接冲突
- 状态：`Inconsistent`
- 严重级别：`P1`
- 架构归属：GUI asset versioning vs FAQ protocol contract

结论：这不是“还没写到文档里”的小偏差，而是协议叙事和产品行为在同一问题上给出了相反答案。

### REQ-13 钱包安全 / 冷钱包 / 多签

- 来源：`docs/FAQ.md:35-56`
- 目标用户：高价值用户 / 机构
- 承诺行为：支持硬件钱包、冷钱包、多签安全路径
- 实际入口：当前产品主要暴露本地钱包文件
- 代码证据：
  - FAQ 声称协议层不绑定钱包类型
  - 当前 CLI / GUI surface 未暴露硬件钱包、多签、Keplr 集成入口
- 运行证据：
  - `python3 -m oasyce.cli --help` 无对应 surface
  - Dashboard 也无对应入口
- 状态：`Docs-only`
- 严重级别：`P2`
- 架构归属：Protocol-level claim, product-level surface absent

结论：如果这是“协议兼容性”描述，FAQ 应明确标成 protocol-level；如果把它当产品能力，则当前并不成立。

### REQ-14 本地存储 vs 分布式存储

- 来源：`docs/FAQ.md:247-259`
- 目标用户：协议接入者
- 承诺行为：当前链下本地存储；Phase D 规划 IPFS / Arweave
- 实际入口：无直接产品入口，属架构说明
- 代码证据：当前服务默认本地文件路径 + 本地数据库；无稳定分布式存储主路径
- 运行证据：本轮运行中资产与能力都依赖本地文件 / 本地 sqlite
- 状态：`Roadmap-only`
- 严重级别：`P3`
- 架构归属：Roadmap alignment

结论：这条 FAQ 当前写法是清楚的，没有把路线图伪装成现货，因此不记作产品缺陷。

### REQ-15 README CLI 契约

- 来源：`README.md:117-217`
- 目标用户：CLI 用户
- 承诺行为：README 里列出的命令与参数能直接跑
- 实际入口：`python3 -m oasyce.cli --help`
- 代码证据：
  - README 写有 `consensus`、`governance`、`access grant/revoke`、`--tier`
  - 实际 CLI surface 为 `access quote/buy/query/sample/compute/deliver/bond`，参数使用 `--level`
- 运行证据：
  - `python3 -m oasyce.cli --help` 无 `consensus`、无 `governance`
  - `python3 -m oasyce.cli access --help` 无 `grant/revoke`，也没有 `--tier`
- 状态：`Inconsistent`
- 严重级别：`P1`
- 架构归属：README public contract drift

结论：这是公开契约问题，不是内部 TODO。用户按照 README 操作会直接撞到不存在的 surface。

### REQ-16 SPA 迁移 / legacy fallback 清理

- 来源：`dashboard/MIGRATION.md:1-64`，`oasyce/gui/app.py:1918-1933`
- 目标用户：维护者
- 承诺行为：SPA 迁完后移除 `_INDEX_HTML` fallback
- 实际入口：`app.py` 仍在主请求路径上保留 fallback
- 代码证据：
  - `oasyce/gui/app.py:1927-1933`
  - `dashboard/MIGRATION.md` 仍把 Portfolio / Stake / Watermark / Scanner / Inbox 标为“无 / 需新建”，但 `dashboard/src/pages/` 中这些页面已存在
- 运行证据：
  - strict 与 fallback GUI 都由同一个 `app.py` 提供
  - dist 存在时会优先 serve SPA，不存在时仍回退 `_INDEX_HTML`
- 状态：`Inconsistent`
- 严重级别：`P3`
- 架构归属：GUI migration debt

结论：迁移并非“未开始”，而是文档和代码状态已经脱节。继续在这种状态下迭代，很容易误判哪些功能真的还没迁完。

## 用户旅程审查

### 1. 数据提供者

- 可以在 fallback 模式下创建资产、在 Explore 看见资产、使用 watermark 提取和分发追踪。
- 不能把默认 strict 模式当成真实可用的新手路径，因为注册与 faucet 依赖外部链。
- FAQ 里的“资产不可变，更新即新资产”与当前 `/api/re-register` 同 ID 版本化行为冲突。
- Graceful Exit 底层存在，但产品入口没有暴露，用户看不到如何走 shutdown / claim。

### 2. AI 开发者

- 能发布能力并在能力列表中被发现。
- 调用路径具备结算 / 退款 / invocation 记录能力，但本轮没有跑出完整成功的外部能力调用。
- 访问型购买确实存在，信誉门控也确实生效；但 quote 与实际 buy 的 bond 不一致，不能视为稳定商用契约。
- 份额购买主链路当前直接崩溃，影响“买数据份额 -> 解锁更高访问级别”的完整叙事。

### 3. 节点 / 验证者 / 仲裁者

- Network 页和部分 node role API 还在。
- 但共识状态与治理入口已迁往 Go 链，Python product 仍然把这层 surface 暴露在 README / Network 页面里。
- 对普通用户来说，这更像“还有一个看得见但不能在当前环境里闭环的子系统”。

### 4. 协议接入者

- `OasyceServiceFacade` 已经承担 register / quote / buy / access / lifecycle 等关键路径，是合理的收敛方向。
- 但 GUI 仍保留 direct SQL、local JSON、legacy HTML fallback 和 handler 内业务逻辑分叉。
- 当前系统更像“半收敛架构”，不是单一业务入口架构。

## FAQ 核验结论

| FAQ 典型问题 | 审查结论 |
|---|---|
| 只买访问不买份额 | 成立，但 access quote / buy 价格不一致，属于 `P1` |
| 份额不等于控制权 | 底层成立，holder 没有公开控制入口 |
| 资产不可变、更新即新资产 | 当前不成立，`/api/re-register` 直接冲突 |
| 信誉影响 bond / 门控 | 成立，但当前 Python 端信誉逻辑仍在运行，FAQ 中“链上权威”说法过满 |
| Graceful Exit | 底层成立，产品入口未暴露 |
| 本地存储 vs 分布式存储 | FAQ 当前区分了现状与路线图，表述基本合理 |
| 冷钱包 / 多签 | 更像 protocol-level claim，不是当前 product-level capability |

## 架构合理性判断

### 1. 单一业务入口是否成立

结论：**未成立。**

理由：

- 正向收敛：`register`、`quote`、`buy`、`access`、`lifecycle` 已有 facade。
- 反向分叉：
  - `oasyce/gui/app.py` 仍有 direct SQL dispute 读取：`1850-1880`
  - `ConfirmationInbox` 直接写 `~/.oasyce/inbox.json`
  - `/api/buy` 仍在 handler 里保留业务逻辑和额外状态
  - `app.py` 仍承担 SPA + legacy fallback 双栈职责

### 2. GUI / CLI 是否同价同规则

结论：**部分成立，但当前不能宣称“完全统一”。**

理由：

- 正向证据：`quote`、`access quote`、`access buy` 等核心路径都在 facade 上。
- 反向证据：
  - `access quote` 与 `access buy` 对同一条交易给出不同 bond
  - README 的 CLI 契约和真实 parser 已经漂移
  - consensus / governance 在 README 中仍像可直接使用的 CLI surface，但实际并不在当前 CLI 中

### 3. legacy fallback 是否仍在主路径上

结论：**是。**

理由：

- `oasyce/gui/app.py:1927-1933` 仍在主请求路径中保留 `_INDEX_HTML` fallback
- `dashboard/MIGRATION.md` 也已滞后，无法继续作为可靠迁移真相源

### 4. 状态持久化 / 通知 / 信誉 / 争议是否一致

结论：**不一致。**

理由：

- inbox 与 trust config 写在 `~/.oasyce`，忽略当前 `_config.data_dir`
- dispute 读路径仍是 direct sqlite，写路径才走 facade
- reputation gate 在 access 流中确实生效，但 FAQ 已经把 Python 端写成“deprecated”，而运行态仍依赖它

## 推荐收敛顺序

### Immediate

1. 修复 `/api/buy` 的 `hashlib` 作用域崩溃。
2. 明确 strict / fallback 的产品语义：
   - 要么让默认本地启动自动闭环；
   - 要么把 README / Home onboarding 明确写成“需要外部链”。
3. 修复 `ConfirmationInbox`：
   - 使用 `_config.data_dir`
   - 原子写文件
   - 对损坏 JSON 做恢复而不是直接把 `/api/inbox` 打挂
4. 修正 access 报价与成交 bond 不一致问题。

### Short-term

1. 修正 `network.tsx` watermark embed 的 payload，使其符合后端契约。
2. 同步 README / FAQ / CLI surface：
   - 去掉不存在的命令
   - 把 `--tier` 改成 `--level`
   - 明确 Go 链迁移边界
3. 对“Asset immutable”与 `/api/re-register` 二选一：
   - 改实现，真的生成新资产；
   - 或改 FAQ / README，承认当前是 same-ID version chain。

### Medium-term

1. 把 dispute / inbox / lifecycle 的剩余 GUI 逻辑继续收敛到 facade / services。
2. 暴露 Graceful Exit 的真实用户入口，或者降低 FAQ 中“已实现”的表述强度。
3. 清理 `dashboard/MIGRATION.md`，重新把它变成可信迁移清单。

### Long-term

1. 删除 `app.py` 的 `_INDEX_HTML` legacy fallback。
2. 彻底完成 Python 本地逻辑到 Go 链权威路径的迁移，并同步文档。

## 正向发现

- SPA 五大主页面已经建立，hash 路由也已接上：`dashboard/src/hooks/use-route.ts:1-49`
- `GET /api/capabilities` 已经做了 legacy registry 与 delivery registry 合并：`oasyce/gui/app.py:510-564`
- access reputation gate 是真实生效的，不是只停留在 FAQ 文案
- GUI 的 auth token / same-origin 保护已经存在：`oasyce/gui/app.py:155-175`，`dashboard/src/api/client.ts:17-37`

---

## 修复记录 (2026-03-22)

以下问题已在 v2.1.1 中修复：

| 原问题 | 严重度 | 修复 | 状态 |
|--------|--------|------|------|
| `/api/buy` hashlib UnboundLocalError | P0 | `import hashlib/struct` 移到模块级 | FIXED |
| 默认 strict 模式新用户流不通 | P0 | 默认改为 standalone，`OASYCE_STRICT_CHAIN=1` 切链模式 | FIXED |
| access quote/buy bond 不一致 | P1 | `access_buy()` 增加 `pre_quoted_bond` 参数 | FIXED |
| Inbox 写到 `~/.oasyce` | P1 | 7 处 `ConfirmationInbox()` 传入 `data_dir` | FIXED |
| Inbox 非原子写 + 无恢复 | P1 | `_atomic_write()` + JSONDecodeError `.corrupt` 备份 | FIXED |
| 水印 embed 前后端契约不通 | P1 | handler 增加 `file_path` 支持 | FIXED |
| CLAUDE.md 宣传不存在的 CLI | P1 | 分离链上/本地命令，增加 Running Modes | FIXED |
| FAQ “Asset immutable” 与 re-register 冲突 | P1 | 两层版本模型说明 | FIXED |

架构层面同步完成三刀重构（GUI→Facade, Query/Command 分离, 默认本地模式）。

### 剩余项

| 项 | 严重度 | 状态 |
|----|--------|------|
| Dispute GET 直读 SQLite | P2 | 未修，已知技术债 |
| do_POST ~1500 行单函数 | P2 | 未拆分，单独排期 |
| Legacy HTML fallback | P3 | React SPA 稳定后删除 |
| 白皮书 v4 参数对齐 | P1 | 需链上 ConsensusVersion 升级 |

## 总结

从用户视角看，v2.1.1 修复后：

- 所有 P0 问题已解决：`/api/buy` 不再崩溃，新用户 standalone 模式可完整闭环
- 所有 P1 问题已解决：bond 一致性、Inbox 持久化、水印契约、文档真实性
- 架构层面：三刀重构完成，GUI GET/POST 边界清晰，Query/Command 分离

从架构视角看，`OasyceServiceFacade` + `OasyceQuery` 已形成稳定的核心边界。剩余收敛项（dispute direct SQL、do_POST 拆分）属于 P2/P3 技术债，不影响功能正确性。

# 2026-03 Public Beta Retrospective

> 这一轮问题不是“功能太难”，而是边界在多个系统之间泄漏了。

## 发生了什么

多设备接入、公测 onboarding、OpenClaw / Codex 验证在同一轮里连续暴露了几类问题：

- Oasyce 设备连接文件被误当成 Thronglets 原生 connection file
- `device join` 本来是接入动作，却顺带碰了包更新和 Python 安装面
- `oas start` 把“自动打开浏览器”混进了成功路径
- Dashboard 首页把“新用户 onboarding”和“接入已有账户设备”混成一条流
- 文档对用户足够简化，但系统边界没有同样明确地写死

## 根因

### 1. 边界概念被说得太像“通用”

“连接文件”对用户来说是对的，但工程上必须明确：

- `oas device export` 产出的是 **Oasyce device file**
- 它只保证 `oas device join` 可消费
- 它不是 Thronglets 原生 connection schema

如果不把这一点写死，另一个系统自然会假设它是通用 connection file。

### 2. 命令默认值做了太多事

`device join` 的职责应该只是“让设备接入已有账户”，不应该隐式决定：

- 是否更新包
- 是否碰安装面
- 是否修改 Python 运行时环境

同理，`oas start` 的职责是“把本地服务启动起来”，不是“必须成功调起浏览器”。

### 3. 产品流和账户历史没有分开

之前 Dashboard 首页主要围绕“新手任务”组织，所以：

- 已有账户的新设备也会被误判到新手奖励流
- “接入已有账户”用户被迫看到不属于他的页面

这说明 onboarding 分流不够硬。

### 4. 真相源还不够少

虽然这一轮已经收成了 `doc_contract + public guide + AI decision rules`，但在跨系统场景里：

- Oasyce 的文件格式
- Thronglets 的文件格式
- AI 的默认决策规则

仍然需要再明确一层“谁只对谁负责”。

## 这轮已经做完的修正

### 已收紧的产品规则

- 身份 V1 收敛为：`owner account + trusted device`
- `agent / session` 暂时只做审计标签
- 主设备 `oas bootstrap`
- 第二台设备优先 `oas device join --bundle ...`
- Dashboard 首先只问：“创建新账户，还是使用已有账户”

### 已收紧的命令边界

- `oas device join` 默认不再隐式更新本机 Python 包
- `oas start` 在非交互环境默认不强行开浏览器
- 如果自动开浏览器失败，只提示手动打开 URL，不再掩盖“服务已起来”

### 已收紧的文档边界

- 明确写死：Oasyce device file 只保证 Oasyce 自己的 join 流程可消费
- AI 决策规则明确：用户没说新建账号时，禁止默认创建新账号
- 公测 guide 现在把 DataVault 提升成默认数据入口

## 永久规则

### 1. 授权可以粗，审计不能粗

- V1：设备是授权边界
- V2：如有必要，再把 agent 做成独立授权边界

### 2. 用户语言可以简单，系统边界不能模糊

用户只需要知道：

- 账户
- 设备
- 连接文件
- 只读 / 可交易

但工程文档必须继续明确：

- 哪个文件归 Oasyce
- 哪个文件归 Thronglets
- 哪个流程只对哪个命令负责

### 3. 默认值必须 fail-closed

当用户表达“接入已有账户”时：

- 缺连接文件，就停下来问
- 不允许默认新建账号

当系统处于非交互环境时：

- 启动服务可以成功
- 打不开浏览器不应算失败

## 下一阶段继续保持的简化方向

1. 继续把用户可见术语压缩成 `account + device + connection file`
2. 给 Thronglets 和 Oasyce 之间定义明确的 cross-system export/import contract，而不是继续让用户猜 schema 是否互通
3. 保持 `DataVault = 默认数据入口`，不要再把它写成附属工具

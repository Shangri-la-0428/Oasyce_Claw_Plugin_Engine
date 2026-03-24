# Oasyce 内部测试网操作手册

> 发给参与测试的朋友，照着做就行。

---

## 0. 你需要准备什么（主机方 / 自己搭测试网）

| 项目 | 要求 |
|------|------|
| 系统 | macOS / Linux |
| Go | >= 1.21 |
| Python | >= 3.9 |
| 磁盘 | >= 2GB 可用 |
| 端口 | 26656-26957, 1317-1617, 9090-9391 |

> **如果你是被邀请加入测试网的朋友**，直接跳到 [第 7 节](#7-加入已有测试网朋友专用完整指南)，那里有 macOS 和 Windows 两个版本的指南。

---

## 1. 克隆代码

```bash
# Go 链
git clone https://github.com/Shangri-la-0428/oasyce-chain.git
cd oasyce-chain
make build
# 确认编译成功
./build/oasyced version

# Python 客户端 (另一个终端)
git clone https://github.com/Shangri-la-0428/oasyce-net.git
cd oasyce-net
pip install -e .
# 确认安装成功
oas doctor
```

---

## 2. 启动 4 验证者本地测试网 (Go 链)

### 2.1 初始化

```bash
cd oasyce-chain
bash scripts/init_multi_testnet.sh
```

这一步会：
- 在 `~/.oasyce-localnet/` 下创建 4 个节点目录 (node0-node3)
- 生成 4 个验证者密钥 (keyring-backend=test，无密码)
- 创建 genesis.json (每个验证者 1,000,000 OAS，质押 100,000 OAS)
- 配置 P2P 端口和 persistent_peers
- 助记词保存在 `~/.oasyce-localnet/mnemonics.txt` (仅测试用，勿用于真实网络)

**端口分配：**

| 节点 | P2P | RPC | REST API | gRPC |
|------|-----|-----|----------|------|
| node0 | 26656 | 26657 | 1317 | 9090 |
| node1 | 26756 | 26757 | 1417 | 9190 |
| node2 | 26856 | 26857 | 1517 | 9290 |
| node3 | 26956 | 26957 | 1617 | 9390 |

### 2.2 启动所有节点

```bash
bash scripts/start_testnet.sh
```

看到以下输出表示成功：
```
==> Starting 4-validator local testnet...
    Starting node0 (log: ~/.oasyce-localnet/node0.log)
    Starting node1 (log: ~/.oasyce-localnet/node1.log)
    Starting node2 (log: ~/.oasyce-localnet/node2.log)
    Starting node3 (log: ~/.oasyce-localnet/node3.log)
All nodes started.
```

### 2.3 验证链在运行

```bash
# 查看最新区块高度 (应该在持续增长)
curl -s http://localhost:26657/status | python3 -c "
import sys, json
d = json.load(sys.stdin)
h = d['result']['sync_info']['latest_block_height']
t = d['result']['sync_info']['latest_block_time']
print(f'区块高度: {h}')
print(f'最新时间: {t}')
"

# 查看验证者集合
curl -s http://localhost:26657/validators | python3 -c "
import sys, json
d = json.load(sys.stdin)
for v in d['result']['validators']:
    print(f'  投票权: {v[\"voting_power\"]}  地址: {v[\"address\"][:16]}...')
"
```

---

## 3. 链上功能端到端测试

### 3.1 跑自动化 E2E

```bash
cd oasyce-chain
./scripts/e2e_test.sh
```

这个脚本自动测试：
- 注册数据资产 (RegisterDataAsset)
- 买入股份 (BuyShares, Bancor bonding curve)
- 创建托管 (CreateEscrow)
- 释放托管 (ReleaseEscrow, 含 93/3/2/2 费率)
- 注册能力 (RegisterCapability)
- 调用能力 (InvokeCapability)

### 3.2 手动测试 (可选)

```bash
OASYCED=./build/oasyced
KB="--keyring-backend test"
COMMON="$KB --chain-id oasyce-localnet-1 --fees 500uoas --yes"

# 查看 validator 余额
$OASYCED query bank balances $($OASYCED keys show val0 -a $KB)

# 注册数据资产
$OASYCED tx datarights register \
  --asset-id "TEST_ASSET_001" \
  --name "测试数据集" \
  --description "内部测试用" \
  --from val0 $COMMON

sleep 3

# 买入股份 (100 OAS)
$OASYCED tx datarights buy-shares \
  --asset-id "TEST_ASSET_001" \
  --amount 100000000uoas \
  --from val1 $COMMON

sleep 3

# 查询资产信息
curl -s http://localhost:1317/oasyce/datarights/v1/asset/TEST_ASSET_001 | python3 -m json.tool

# 卖出股份
$OASYCED tx datarights sell-shares \
  --asset-id "TEST_ASSET_001" \
  --shares 5000000 \
  --from val1 $COMMON
```

---

## 4. Python 客户端测试 (Standalone 模式)

不需要链在运行，直接在 oasyce-net 目录执行。

### 4.1 QA 回归套件

```bash
cd oasyce-net
python3 scripts/qa_regression.py
```

预期输出：全部 PASS，0 FAIL。

也可以只跑某个模块：
```bash
python3 scripts/qa_regression.py --module bonding_curve
python3 scripts/qa_regression.py --module dispute
python3 scripts/qa_regression.py --module access_control
python3 scripts/qa_regression.py --module facade
```

所有可用模块：
```
protocol_params, security_modes, economics, bonding_curve,
facade, task_market, chain_client, middleware, ahrp_persistence,
query_layer, reputation, dispute, fingerprint, access_control,
agent_skills, ahrp_protocol, asset_lifecycle, server
```

### 4.2 用户旅程端到端

```bash
python3 scripts/user_journey_walkthrough.py
```

预期：76/76 PASS。

### 4.3 完整测试套件

```bash
pytest --tb=short -q
```

预期：1100+ tests passed。

### 4.4 CLI 手动测试

```bash
# 注册资产
oas register test_data.csv --owner alice --tags research,nlp

# 查看报价
oas quote ASSET_ID 10.0

# 买入
oas buy ASSET_ID --buyer bob --amount 10.0

# 卖出
oas sell ASSET_ID --tokens 5 --seller bob

# 查看持仓
oas shares bob

# 任务市场
oas task post "翻译文档" --budget 50 --deadline 3600
oas task list
oas task bid TASK_ID --price 30 --seconds 1800

# 诊断
oas doctor
oas info --section economics
```

---

## 5. Python 客户端 + 链联动测试

需要 Go 链在运行 (步骤 2 已启动)。

```bash
cd oasyce-net

# 设置环境变量，启用 chain-linked 模式
export OASYCE_CHAIN_RPC="http://localhost:26657"
export OASYCE_CHAIN_API="http://localhost:1317"
export OASYCE_STRICT_CHAIN=1

# 跑联动测试
python3 scripts/qa_regression.py --include-chain
```

---

## 6. 验证经济参数一致性

Python 和 Go 必须用相同的参数：

| 参数 | Python | Go | 如何验证 |
|------|--------|-----|---------|
| Reserve Ratio | 0.50 | 0.50 | `python3 -c "from oasyce.core.formulas import RESERVE_RATIO; print(RESERVE_RATIO)"` |
| Creator Rate | 93% | 93% | QA-102 |
| Validator Rate | 3% | 3% | QA-103 |
| Burn Rate | 2% | 2% | QA-104 |
| Treasury Rate | 2% | 2% | QA-105 |
| Solvency Cap | 95% | 95% | QA-108 |

Go 链端验证：
```bash
curl -s http://localhost:1317/oasyce/settlement/v1/params | python3 -m json.tool
```

---

## 7. 加入已有测试网（朋友专用完整指南）

> **给 AI 助手的说明**：这一节是完全独立的操作指南。你的用户（下文称"朋友"）需要加入一个已经在运行的 Oasyce 测试网。测试网的主机（下文称"主机方"）已经完成了第 2 节的初始化和启动。请先确认朋友的操作系统，然后走对应的路线（A = macOS/Linux，B = Windows）。严格按顺序执行每一步，确认每步输出正确后再继续。

---

### 7.0 主机方准备（在开始之前）

主机方需要准备以下文件和信息，发给朋友：

**所有朋友都需要的：**

| # | 信息 | 怎么获取 | 怎么发 |
|---|------|---------|--------|
| 1 | **genesis.json** | 见下方命令 | 微信文件 / AirDrop / U盘 |
| 2 | **主机局域网 IP** | 见下方命令 | 微信消息 |
| 3 | **主机 Node ID** | 见下方命令 | 微信消息 |

**如果朋友是 Windows**，还需要额外发一个文件：

| # | 信息 | 怎么获取 | 怎么发 |
|---|------|---------|--------|
| 4 | **oasyced.exe** | 交叉编译（见下方） | 微信文件 / U盘 |

```bash
cd oasyce-chain

# ① 导出 genesis
cp ~/.oasyce-localnet/node0/config/genesis.json ./genesis.json

# ② 获取 Node ID（注意：输出在 stderr，需要 2>&1）
NODE_ID=$(./build/oasyced comet show-node-id --home ~/.oasyce-localnet/node0 2>&1)
echo "Node ID: $NODE_ID"

# ③ 获取局域网 IP
# macOS:
ipconfig getifaddr en0
# Linux:
hostname -I | awk '{print $1}'

# ④ 给 Windows 朋友编译 exe（macOS/Linux 朋友不需要这步）
GOOS=windows GOARCH=amd64 go build -o ./build/oasyced.exe ./cmd/oasyced
echo "把 oasyced.exe 发给 Windows 朋友"
```

> **⚠️ 重要**：每次重新初始化测试网后，genesis.json 和 Node ID 都会变化。必须重新执行上面 ①②③ 获取最新值，否则朋友端会报 `wrong Block.Header.AppHash` 或 `dialed ID mismatch` 错误。

> 以上信息已经嵌入本文档 **附录 A**。如果你直接把本文档发给朋友，朋友不需要再单独要这些文件。

让朋友根据自己的系统选择路线：
- **macOS / Linux** → 路线 A（7.A 开头的步骤）
- **Windows** → 路线 B（7.B 开头的步骤）

两条路线最后汇合到 **7.C**（通用步骤）。

---

## 路线 A：macOS / Linux 朋友

### 7.A1 环境准备

| 项目 | 要求 | 检查命令 |
|------|------|---------|
| Go | >= 1.21 | `go version` |
| Python | >= 3.9 | `python3 --version` |
| Git | 任意版本 | `git --version` |
| 网络 | 能 ping 通主机 | `ping -c 3 <主机IP>` |

安装缺失的工具：
```bash
# macOS
brew install go python3 git

# Linux (Ubuntu/Debian)
sudo apt update && sudo apt install -y build-essential golang python3 python3-pip git
```

### 7.A2 克隆 & 编译

```bash
git clone https://github.com/Shangri-la-0428/oasyce-chain.git
cd oasyce-chain
make build
./build/oasyced version   # 确认编译成功
```

### 7.A3 初始化 & 配置节点

> **推荐**：如果主机方给了 `setup_node.py`，可以直接运行 `python3 setup_node.py` 一键完成以下所有配置步骤。手动配置见下方。

```bash
# 初始化节点
./build/oasyced init my-node --chain-id oasyce-localnet-1

# 替换 genesis — 从附录 A 保存 genesis.json，或让 AI 助手从附录提取并保存为文件
cp genesis.json ~/.oasyced/config/genesis.json

# 配置 peer 连接 + 允许局域网 IP（值来自附录 A）
python3 -c "
import re, pathlib
cfg = pathlib.Path.home() / '.oasyced/config/config.toml'
txt = cfg.read_text()
peer = '7c278d8be15f829e71ea1fdc6c0f4b6ae7fe7ee1@192.168.1.12:26656'
txt = re.sub(r'^persistent_peers = \".*?\"', f'persistent_peers = \"{peer}\"', txt, flags=re.MULTILINE)
txt = re.sub(r'^addr_book_strict = true', 'addr_book_strict = false', txt, flags=re.MULTILINE)
cfg.write_text(txt)
print(f'已配置 peer: {peer}')
print('已设置 addr_book_strict = false')
"

# 启用 REST API
python3 -c "
import pathlib
app = pathlib.Path.home() / '.oasyced/config/app.toml'
txt = app.read_text()
txt = txt.replace('enable = false', 'enable = true', 1)
app.write_text(txt)
print('REST API 已启用')
"
```

> **⚠️ `addr_book_strict = false` 必须设置**，否则节点会拒绝连接局域网 IP，报 `non-routable address` 错误。这是 Windows 内测中踩过的坑。

### 7.A4 启动节点

```bash
cd oasyce-chain
./build/oasyced start --minimum-gas-prices 0uoas
```

> **macOS 用户注意**：首次运行 `oasyced` 时，macOS 会弹出防火墙提示 **"是否允许 oasyced 接受传入网络连接"**，必须点 **"允许"**，否则其他节点无法连入。如果误点了"拒绝"，到 **系统设置 → 网络 → 防火墙 → 选项** 中找到 oasyced 改为允许。

**保持这个终端开着**，另开一个新终端，跳到 → [7.C1 验证同步](#7c1-验证同步)

---

## 路线 B：Windows 朋友

> Windows 不需要安装 Go、Git 或任何编译工具。主机方已经帮你编译好了 `oasyced.exe`。

### 7.B1 你需要的东西

从主机方拿到这些文件（微信接收 / U盘拷贝）：

| 文件 | 说明 |
|------|------|
| `oasyced.exe` | 链节点程序（约 80MB） |
| `genesis.json` | 创世文件 |

以及两条信息：
- 主机 IP 地址（例如 `192.168.1.100`）
- 主机 Node ID（一串 40 个字符的十六进制）

### 7.B2 安装 Python

从 https://www.python.org/downloads/ 下载 Python 安装包。

**安装时注意**：勾选底部的 **"Add Python to PATH"**（非常重要！）

安装完成后打开 **PowerShell**（按 Win 键，输入 `powershell`，回车），验证：
```powershell
python --version
# 应显示 Python 3.x.x
```

### 7.B3 准备工作目录

在 PowerShell 中执行：
```powershell
# 在桌面创建工作目录
mkdir ~\Desktop\oasyce-test
cd ~\Desktop\oasyce-test
```

把主机方发的 `oasyced.exe` 和 `genesis.json` 复制到这个文件夹里。

验证文件在位：
```powershell
dir
# 应该看到 oasyced.exe 和 genesis.json
```

### 7.B4 初始化节点

```powershell
.\oasyced.exe init my-node --chain-id oasyce-localnet-1
```

这会在 `C:\Users\你的用户名\.oasyced\` 下创建配置文件。

### 7.B5 替换 genesis

```powershell
copy genesis.json $env:USERPROFILE\.oasyced\config\genesis.json
```

验证：
```powershell
python -c "import json; g=json.load(open(r'%USERPROFILE%\.oasyced\config\genesis.json'.replace('%USERPROFILE%', __import__('os').environ['USERPROFILE']))); print(f'Chain ID: {g[\"chain_id\"]}')"
```

应该显示 `Chain ID: oasyce-localnet-1`。

### 7.B6 配置 Peer 连接 & 启用 API

```powershell
# 值来自附录 A
python -c "
import re, pathlib, os
home = pathlib.Path(os.environ['USERPROFILE'])

# 配置 peer
cfg = home / '.oasyced/config/config.toml'
txt = cfg.read_text()
peer = '7c278d8be15f829e71ea1fdc6c0f4b6ae7fe7ee1@192.168.1.12:26656'
txt = re.sub(r'^persistent_peers = \`".*?\`"', f'persistent_peers = \`\"{peer}\`\"', txt, flags=re.MULTILINE)
cfg.write_text(txt)
print(f'已配置 peer: {peer}')

# 启用 API
app = home / '.oasyced/config/app.toml'
txt = app.read_text()
txt = txt.replace('enable = false', 'enable = true', 1)
app.write_text(txt)
print('REST API 已启用')
"
```

> 如果上面的 Python 命令因为引号问题报错，可以手动编辑配置文件：
> 1. 用记事本打开 `C:\Users\你的用户名\.oasyced\config\config.toml`
> 2. 搜索 `persistent_peers = ""`
> 3. 改成 `persistent_peers = "7c278d8be15f829e71ea1fdc6c0f4b6ae7fe7ee1@192.168.1.12:26656"`
> 4. 保存
>
> 然后用记事本打开 `C:\Users\你的用户名\.oasyced\config\app.toml`
> 1. 搜索 `enable = false`（第一个出现的）
> 2. 改成 `enable = true`
> 3. 保存

### 7.B7 启动节点

```powershell
cd ~\Desktop\oasyce-test
.\oasyced.exe start --minimum-gas-prices 0uoas
```

你会看到日志不断滚动，表示节点在运行。

**保持这个窗口开着**，另开一个新的 PowerShell 窗口，继续下面的步骤。

---

## 通用步骤（macOS / Linux / Windows 汇合）

### 7.C1 验证同步

**macOS / Linux**：
```bash
curl -s http://localhost:26657/status | python3 -c "
import sys, json
d = json.load(sys.stdin)
info = d['result']['sync_info']
print(f'区块高度: {info[\"latest_block_height\"]}')
print(f'正在追赶: {info[\"catching_up\"]}')
"
```

**Windows PowerShell**：
```powershell
python -c "
import urllib.request, json
d = json.loads(urllib.request.urlopen('http://localhost:26657/status').read())
info = d['result']['sync_info']
print(f'区块高度: {info[\"latest_block_height\"]}')
print(f'正在追赶: {info[\"catching_up\"]}')
"
```

- `catching_up: True` → 还在同步，等一会再查
- `catching_up: False` → 同步完成，继续下一步

**等到 `catching_up` 变为 `False` 再继续。**

---

### 7.C2 创建钱包

**macOS / Linux**：
```bash
cd oasyce-chain
./build/oasyced keys add mykey --keyring-backend test
MY_ADDR=$(./build/oasyced keys show mykey -a --keyring-backend test)
echo "我的地址: $MY_ADDR"
```

**Windows PowerShell**：
```powershell
cd ~\Desktop\oasyce-test
.\oasyced.exe keys add mykey --keyring-backend test
$MY_ADDR = (.\oasyced.exe keys show mykey -a --keyring-backend test)
echo "我的地址: $MY_ADDR"
```

**把你的地址（oasyce1...）发给主机方**，让他转测试代币给你。

```
📱 发给主机方的消息模板：
"节点同步好了，我的地址是 oasyce1xxxxx，帮我转点测试币"
```

**主机方收到后执行**：
```bash
cd oasyce-chain
FRIEND_ADDR="oasyce1..."   # 替换为朋友的地址

./build/oasyced tx bank send \
  $(./build/oasyced keys show val0 -a --keyring-backend test) \
  $FRIEND_ADDR \
  500000000uoas \
  --keyring-backend test --chain-id oasyce-localnet-1 --fees 500uoas --yes
```

**朋友验证余额**（等 ~6 秒后）：

macOS / Linux：
```bash
curl -s "http://localhost:1317/cosmos/bank/v1beta1/balances/$MY_ADDR" | python3 -m json.tool
```

Windows：
```powershell
python -c "
import urllib.request, json
d = json.loads(urllib.request.urlopen('http://localhost:1317/cosmos/bank/v1beta1/balances/$MY_ADDR').read())
for b in d.get('balances', []):
    amt = int(b['amount'])
    print(f'{b[\"denom\"]}: {amt} ({amt/1_000_000:.2f} OAS)')
"
```

应看到 `500.00 OAS`。

---

### 7.C3 在链上执行测试交易

**macOS / Linux**：
```bash
cd oasyce-chain
OASYCED=./build/oasyced
KB="--keyring-backend test"
COMMON="$KB --chain-id oasyce-localnet-1 --fees 500uoas --yes"

# 1. 注册数据资产
$OASYCED tx datarights register "my-test-data" "sha256:mydata123" \
    --description "朋友的测试数据" --rights-type original --tags "test,friend" \
    --from mykey $COMMON
sleep 6

# 2. 查询资产
$OASYCED query datarights list --output json | python3 -c "
import sys,json; d=json.load(sys.stdin)
for a in d.get('data_assets',[]):
    print(f'  {a[\"id\"]} — {a[\"name\"]}')
"

# 3. 买入股份（用上面查到的 ASSET_ID 替换）
$OASYCED tx datarights buy-shares "ASSET_ID" 10000000uoas --from mykey $COMMON
sleep 6

# 4. 卖出股份
$OASYCED tx datarights sell-shares "ASSET_ID" 500 --from mykey $COMMON
sleep 6

echo "=== 测试完成: 注册 → 买入 → 卖出 ==="
```

**Windows PowerShell**：
```powershell
cd ~\Desktop\oasyce-test

# 1. 注册数据资产
.\oasyced.exe tx datarights register "my-test-data" "sha256:mydata123" `
    --description "朋友的测试数据" --rights-type original --tags "test,friend" `
    --from mykey --keyring-backend test --chain-id oasyce-localnet-1 --fees 500uoas --yes
Start-Sleep 6

# 2. 查询资产
.\oasyced.exe query datarights list --output json | python -c "
import sys,json; d=json.load(sys.stdin)
for a in d.get('data_assets',[]):
    print(f'  {a[\"id\"]} - {a[\"name\"]}')
"

# 3. 买入股份（用上面查到的 ASSET_ID 替换）
.\oasyced.exe tx datarights buy-shares "ASSET_ID" 10000000uoas `
    --from mykey --keyring-backend test --chain-id oasyce-localnet-1 --fees 500uoas --yes
Start-Sleep 6

# 4. 卖出股份
.\oasyced.exe tx datarights sell-shares "ASSET_ID" 500 `
    --from mykey --keyring-backend test --chain-id oasyce-localnet-1 --fees 500uoas --yes
Start-Sleep 6

echo "=== 测试完成: 注册 → 买入 → 卖出 ==="
```

---

### 7.C4 Python 客户端（可选，需要 Git）

如果朋友还想测试 Python 客户端和 Dashboard：

```bash
# macOS / Linux
git clone https://github.com/Shangri-la-0428/oasyce-net.git
cd oasyce-net
pip install -e .
```

```powershell
# Windows（需要先安装 Git: https://git-scm.com/download/win）
git clone https://github.com/Shangri-la-0428/oasyce-net.git
cd oasyce-net
pip install -e .
```

设置链连接并启动 Dashboard：

macOS / Linux：
```bash
export OASYCE_CHAIN_RPC="http://localhost:26657"
export OASYCE_CHAIN_API="http://localhost:1317"
export OASYCE_STRICT_CHAIN=1
oas doctor
oas start    # 浏览器打开 http://localhost:8420
```

Windows PowerShell：
```powershell
$env:OASYCE_CHAIN_RPC = "http://localhost:26657"
$env:OASYCE_CHAIN_API = "http://localhost:1317"
$env:OASYCE_STRICT_CHAIN = "1"
oas doctor
oas start    # 浏览器打开 http://localhost:8420
```

---

### 7.D 常见问题

#### Q: 节点连不上主机 (`connection refused`)

先测试网络连通性：

macOS / Linux：
```bash
nc -zv <主机IP> 26656
```

Windows PowerShell：
```powershell
Test-NetConnection -ComputerName <主机IP> -Port 26656
```

如果不通，检查主机方防火墙：
- **macOS 主机**：系统设置 → 网络 → 防火墙 → 关闭或添加例外。首次运行 oasyced 时弹出的防火墙提示必须点"允许"
- **Linux 主机**：`sudo ufw allow 26656/tcp`
- **朋友端 macOS**：同样需要允许 oasyced 的传入连接

#### Q: 报 `non-routable address` 错误

`config.toml` 中 `addr_book_strict = true` 会拒绝局域网 IP。修改为：

macOS / Linux：
```bash
python3 -c "
import re, pathlib
cfg = pathlib.Path.home() / '.oasyced/config/config.toml'
txt = cfg.read_text()
txt = re.sub(r'^addr_book_strict = true', 'addr_book_strict = false', txt, flags=re.MULTILINE)
cfg.write_text(txt)
print('已修改 addr_book_strict = false')
"
```

Windows PowerShell：
```powershell
(Get-Content $env:USERPROFILE\.oasyced\config\config.toml) -replace 'addr_book_strict = true', 'addr_book_strict = false' | Set-Content $env:USERPROFILE\.oasyced\config\config.toml
```

然后重启节点。

#### Q: 报 `dialed ID mismatch`

主机方的 Node ID 变了（重新初始化测试网后会变）。让主机方重新获取：
```bash
./build/oasyced comet show-node-id --home ~/.oasyce-localnet/node0 2>&1
```
用新 ID 更新 `persistent_peers` 配置。

#### Q: 节点卡在 `waiting for peers`

检查配置是否正确：

macOS / Linux：
```bash
grep persistent_peers ~/.oasyced/config/config.toml
```

Windows PowerShell：
```powershell
Select-String "persistent_peers" $env:USERPROFILE\.oasyced\config\config.toml
```

应看到 `persistent_peers = "NodeID@IP:26656"`。如果是空的，回到 7.A3 或 7.B6 重新配置。

#### Q: `wrong Block.Header.AppHash`
genesis.json 文件有问题。重新从主机方拿 genesis.json 并替换：

macOS / Linux：
```bash
rm -rf ~/.oasyced/data
cp genesis.json ~/.oasyced/config/genesis.json
```

Windows：
```powershell
Remove-Item -Recurse $env:USERPROFILE\.oasyced\data
copy genesis.json $env:USERPROFILE\.oasyced\config\genesis.json
```

然后重新启动节点。

#### Q: 余额为 0
1. 确认节点同步完成（`catching_up: false`）
2. 确认主机方转账成功（等 6 秒后重新查询）
3. 确认地址没复制错

#### Q: `account sequence mismatch`
交易发太快了，等 6 秒再试。

#### Q: 想彻底重来

macOS / Linux：
```bash
rm -rf ~/.oasyced
```

Windows：
```powershell
Remove-Item -Recurse $env:USERPROFILE\.oasyced
```

然后从 7.A3 或 7.B4 重新开始。

---

## 8. 常见问题

### Q: 节点启动后立即退出
```bash
# 查看日志
cat ~/.oasyce-localnet/node0.log | tail -20
```
常见原因：端口被占用。用 `lsof -i :26656` 检查。

### Q: 节点不出块
确认至少 3/4 验证者在线 (BFT 需要 2/3+1)。

### Q: 重新开始
```bash
# 停掉所有节点 (Ctrl+C)
# 然后重新初始化
bash scripts/init_multi_testnet.sh
bash scripts/start_testnet.sh
```

### Q: Python 测试报 ImportError
```bash
cd oasyce-net
pip install -e .
```

### Q: E2E 测试报 "insufficient funds"
链刚启动时需要等几个区块才能用：
```bash
sleep 5
./scripts/e2e_test.sh
```

---

## 9. 关键文件位置

| 文件 | 说明 |
|------|------|
| `~/.oasyce-localnet/` | 测试网数据根目录 |
| `~/.oasyce-localnet/node0.log` | 节点 0 日志 |
| `~/.oasyce-localnet/mnemonics.txt` | 验证者助记词 (仅测试) |
| `oasyce-chain/scripts/e2e_test.sh` | 链上 E2E 测试 |
| `oasyce-net/scripts/qa_regression.py` | Python QA 回归 |
| `oasyce-net/scripts/user_journey_walkthrough.py` | 用户旅程 (76 项) |
| `oasyce-net/docs/PRD.md` | 完整产品规格 (381 个 QA 点) |

---

## 10. 测试完成 Checklist

- [ ] Go 链编译成功 (`make build`)
- [ ] 4 验证者测试网启动，持续出块
- [ ] E2E 测试全部通过 (`e2e_test.sh`)
- [ ] Python QA 回归全部通过
- [ ] 用户旅程 76/76 通过
- [ ] pytest 1100+ 通过
- [ ] CLI 手动操作：register → quote → buy → sell 流程跑通
- [ ] 经济参数 Python/Go 一致 (93/3/2/2)
- [ ] 多节点间能同步区块

全部通过 → 可以进入公开测试网阶段。

---

## 附录 A: 本次测试网连接信息

> 朋友直接用这里的值，不需要再问主机方要。

### 连接参数

| 参数 | 值 |
|------|-----|
| **主机 IP** | `192.168.1.12`（局域网，如连不上请跟主机方确认是否变了） |
| **Node ID** | `7c278d8be15f829e71ea1fdc6c0f4b6ae7fe7ee1` |
| **Chain ID** | `oasyce-localnet-1` |
| **P2P 端口** | `26656` |
| **完整 Peer 地址** | `7c278d8be15f829e71ea1fdc6c0f4b6ae7fe7ee1@192.168.1.12:26656` |

### genesis.json

> **给 AI 助手的说明**：把下面的 JSON 内容保存为 `genesis.json` 文件，后续步骤需要用到。

<details>
<summary>点击展开 genesis.json（约 600 行）</summary>

```json
{
  "app_name": "oasyced",
  "app_version": "9b62515",
  "genesis_time": "2026-03-23T21:12:05.148964Z",
  "chain_id": "oasyce-localnet-1",
  "initial_height": 1,
  "app_hash": null,
  "app_state": {
    "07-tendermint": null,
    "auth": {
      "params": {
        "max_memo_characters": "256",
        "tx_sig_limit": "7",
        "tx_size_cost_per_byte": "10",
        "sig_verify_cost_ed25519": "590",
        "sig_verify_cost_secp256k1": "1000"
      },
      "accounts": [
        {
          "@type": "/cosmos.auth.v1beta1.BaseAccount",
          "address": "oasyce1h5exsp6ae0dfamms8j6vsjxcete59ttuf597ce",
          "pub_key": null,
          "account_number": "0",
          "sequence": "0"
        },
        {
          "@type": "/cosmos.auth.v1beta1.BaseAccount",
          "address": "oasyce1axdwzml5smrn8nltegjdfl9nkgp8y5hqu6ka0c",
          "pub_key": null,
          "account_number": "1",
          "sequence": "0"
        },
        {
          "@type": "/cosmos.auth.v1beta1.BaseAccount",
          "address": "oasyce10uczwyv2ynrxdqe4fq6rxjnzuvzgll9ldufsx7",
          "pub_key": null,
          "account_number": "2",
          "sequence": "0"
        },
        {
          "@type": "/cosmos.auth.v1beta1.BaseAccount",
          "address": "oasyce1ka7ren9qv7wx28jsgucmvrkzawjtmwuu6h5p62",
          "pub_key": null,
          "account_number": "3",
          "sequence": "0"
        }
      ]
    },
    "authz": {
      "authorization": []
    },
    "bank": {
      "params": {
        "send_enabled": [],
        "default_send_enabled": true
      },
      "balances": [
        {
          "address": "oasyce10uczwyv2ynrxdqe4fq6rxjnzuvzgll9ldufsx7",
          "coins": [
            {
              "denom": "uoas",
              "amount": "100000000000000"
            }
          ]
        },
        {
          "address": "oasyce1ka7ren9qv7wx28jsgucmvrkzawjtmwuu6h5p62",
          "coins": [
            {
              "denom": "uoas",
              "amount": "100000000000000"
            }
          ]
        },
        {
          "address": "oasyce1h5exsp6ae0dfamms8j6vsjxcete59ttuf597ce",
          "coins": [
            {
              "denom": "uoas",
              "amount": "100000000000000"
            }
          ]
        },
        {
          "address": "oasyce1axdwzml5smrn8nltegjdfl9nkgp8y5hqu6ka0c",
          "coins": [
            {
              "denom": "uoas",
              "amount": "100000000000000"
            }
          ]
        }
      ],
      "supply": [
        {
          "denom": "uoas",
          "amount": "400000000000000"
        }
      ],
      "denom_metadata": [],
      "send_enabled": []
    },
    "crisis": {
      "constant_fee": {
        "denom": "uoas",
        "amount": "1000"
      }
    },
    "datarights": {
      "data_assets": [],
      "shareholders": [],
      "disputes": [],
      "params": {
        "max_co_creators": 10,
        "dispute_deposit": {
          "denom": "uoas",
          "amount": "10000000"
        },
        "dispute_timeout_days": 30,
        "shutdown_cooldown_seconds": "604800"
      },
      "migration_paths": []
    },
    "distribution": {
      "params": {
        "community_tax": "0.020000000000000000",
        "base_proposer_reward": "0.000000000000000000",
        "bonus_proposer_reward": "0.000000000000000000",
        "withdraw_addr_enabled": true
      },
      "fee_pool": {
        "community_pool": []
      },
      "delegator_withdraw_infos": [],
      "previous_proposer": "",
      "outstanding_rewards": [],
      "validator_accumulated_commissions": [],
      "validator_historical_rewards": [],
      "validator_current_rewards": [],
      "delegator_starting_infos": [],
      "validator_slash_events": []
    },
    "feegrant": {
      "allowances": []
    },
    "genutil": {
      "gen_txs": [
        {
          "body": {
            "messages": [
              {
                "@type": "/cosmos.staking.v1beta1.MsgCreateValidator",
                "description": {
                  "moniker": "validator-3",
                  "identity": "",
                  "website": "",
                  "security_contact": "",
                  "details": ""
                },
                "commission": {
                  "rate": "0.100000000000000000",
                  "max_rate": "0.200000000000000000",
                  "max_change_rate": "0.010000000000000000"
                },
                "min_self_delegation": "1",
                "delegator_address": "",
                "validator_address": "oasycevaloper1ka7ren9qv7wx28jsgucmvrkzawjtmwuur5rk3c",
                "pubkey": {
                  "@type": "/cosmos.crypto.ed25519.PubKey",
                  "key": "etUxueU0lQ6Nz9qZBon3G+fHzrc5b0uQYpRDMMzDw+c="
                },
                "value": {
                  "denom": "uoas",
                  "amount": "10000000000000"
                }
              }
            ],
            "memo": "417fa253e4a2b8b47f20b15aa5f09cfc591ed5c8@192.168.1.12:26656",
            "timeout_height": "0",
            "extension_options": [],
            "non_critical_extension_options": []
          },
          "auth_info": {
            "signer_infos": [
              {
                "public_key": {
                  "@type": "/cosmos.crypto.secp256k1.PubKey",
                  "key": "A0WzfJDxjmFJIyzIQeccl7J7CmD2z+os4iXXt5hGQoO3"
                },
                "mode_info": {
                  "single": {
                    "mode": "SIGN_MODE_DIRECT"
                  }
                },
                "sequence": "0"
              }
            ],
            "fee": {
              "amount": [],
              "gas_limit": "200000",
              "payer": "",
              "granter": ""
            },
            "tip": null
          },
          "signatures": [
            "X7oRgGsNjJFxeoIl18EGrQtVqfmk696l+rTmpUU9jsIPVXZMua73qpygDX8Pwz3HWjtT3RYXmD6o653sShN9Gw=="
          ]
        },
        {
          "body": {
            "messages": [
              {
                "@type": "/cosmos.staking.v1beta1.MsgCreateValidator",
                "description": {
                  "moniker": "validator-0",
                  "identity": "",
                  "website": "",
                  "security_contact": "",
                  "details": ""
                },
                "commission": {
                  "rate": "0.100000000000000000",
                  "max_rate": "0.200000000000000000",
                  "max_change_rate": "0.010000000000000000"
                },
                "min_self_delegation": "1",
                "delegator_address": "",
                "validator_address": "oasycevaloper1h5exsp6ae0dfamms8j6vsjxcete59ttushjfnt",
                "pubkey": {
                  "@type": "/cosmos.crypto.ed25519.PubKey",
                  "key": "BKH7SQOzu7TSTzHReZnMdlI7+OJIBee/+IQlLkD1Y2w="
                },
                "value": {
                  "denom": "uoas",
                  "amount": "10000000000000"
                }
              }
            ],
            "memo": "7c278d8be15f829e71ea1fdc6c0f4b6ae7fe7ee1@192.168.1.12:26656",
            "timeout_height": "0",
            "extension_options": [],
            "non_critical_extension_options": []
          },
          "auth_info": {
            "signer_infos": [
              {
                "public_key": {
                  "@type": "/cosmos.crypto.secp256k1.PubKey",
                  "key": "A+I19ZnEwMEHmuZvf49nOh0x48XCQOG+iyhhyRQoKMrN"
                },
                "mode_info": {
                  "single": {
                    "mode": "SIGN_MODE_DIRECT"
                  }
                },
                "sequence": "0"
              }
            ],
            "fee": {
              "amount": [],
              "gas_limit": "200000",
              "payer": "",
              "granter": ""
            },
            "tip": null
          },
          "signatures": [
            "Z8Kyi9BnTMyOV0Ybj4Yaa5AiknYi7QeY31GCwBImfJMDCvHfh/3/H5PauQp25jQQiHfovCuBJAPG0/JUZ7654g=="
          ]
        },
        {
          "body": {
            "messages": [
              {
                "@type": "/cosmos.staking.v1beta1.MsgCreateValidator",
                "description": {
                  "moniker": "validator-2",
                  "identity": "",
                  "website": "",
                  "security_contact": "",
                  "details": ""
                },
                "commission": {
                  "rate": "0.100000000000000000",
                  "max_rate": "0.200000000000000000",
                  "max_change_rate": "0.010000000000000000"
                },
                "min_self_delegation": "1",
                "delegator_address": "",
                "validator_address": "oasycevaloper10uczwyv2ynrxdqe4fq6rxjnzuvzgll9l5l78dv",
                "pubkey": {
                  "@type": "/cosmos.crypto.ed25519.PubKey",
                  "key": "hIHcnUOw76j52OXm8Z6B38jw4wthCFW7Ys2dR7vF0bc="
                },
                "value": {
                  "denom": "uoas",
                  "amount": "10000000000000"
                }
              }
            ],
            "memo": "a9e10e88f51e92b9ba118a2b7aa48c97aa07b7c7@192.168.1.12:26656",
            "timeout_height": "0",
            "extension_options": [],
            "non_critical_extension_options": []
          },
          "auth_info": {
            "signer_infos": [
              {
                "public_key": {
                  "@type": "/cosmos.crypto.secp256k1.PubKey",
                  "key": "A7lJDYIhtoRktRulgLTw3UXmYa+bTMJ6kFTaI0/q47K6"
                },
                "mode_info": {
                  "single": {
                    "mode": "SIGN_MODE_DIRECT"
                  }
                },
                "sequence": "0"
              }
            ],
            "fee": {
              "amount": [],
              "gas_limit": "200000",
              "payer": "",
              "granter": ""
            },
            "tip": null
          },
          "signatures": [
            "X0Mi3Km8M84ykLMwqF/44kl86ihh9iWd9cb41EPlexwWoExWK4j2NaLg3iLhd7Dh/IrufYhvg+cr9h/OgBVskQ=="
          ]
        },
        {
          "body": {
            "messages": [
              {
                "@type": "/cosmos.staking.v1beta1.MsgCreateValidator",
                "description": {
                  "moniker": "validator-1",
                  "identity": "",
                  "website": "",
                  "security_contact": "",
                  "details": ""
                },
                "commission": {
                  "rate": "0.100000000000000000",
                  "max_rate": "0.200000000000000000",
                  "max_change_rate": "0.010000000000000000"
                },
                "min_self_delegation": "1",
                "delegator_address": "",
                "validator_address": "oasycevaloper1axdwzml5smrn8nltegjdfl9nkgp8y5hq9ep2y2",
                "pubkey": {
                  "@type": "/cosmos.crypto.ed25519.PubKey",
                  "key": "GpMJYMIOJTyvbzXvLF+nMbII+UdyjdjC77e3FvJJnKQ="
                },
                "value": {
                  "denom": "uoas",
                  "amount": "10000000000000"
                }
              }
            ],
            "memo": "bcb9ec6439984b2c35867a36f4d00a20bb5ca8ee@192.168.1.12:26656",
            "timeout_height": "0",
            "extension_options": [],
            "non_critical_extension_options": []
          },
          "auth_info": {
            "signer_infos": [
              {
                "public_key": {
                  "@type": "/cosmos.crypto.secp256k1.PubKey",
                  "key": "As7QZvW4WyuoVfWw/K9ox4e2zAH5Xde5pJtLYrhbAZg9"
                },
                "mode_info": {
                  "single": {
                    "mode": "SIGN_MODE_DIRECT"
                  }
                },
                "sequence": "0"
              }
            ],
            "fee": {
              "amount": [],
              "gas_limit": "200000",
              "payer": "",
              "granter": ""
            },
            "tip": null
          },
          "signatures": [
            "0ydxhQEOoSqy/vqBjZHmXi1e/HaZxjhJSSL94ThSd5BtCtkn+lz+3gErFU/QJ+OjWakd3UPoxj8DbV2D8vyTMg=="
          ]
        }
      ]
    },
    "gov": {
      "starting_proposal_id": "1",
      "deposits": [],
      "votes": [],
      "proposals": [],
      "deposit_params": null,
      "voting_params": null,
      "tally_params": null,
      "params": {
        "min_deposit": [
          {
            "denom": "uoas",
            "amount": "100000000000"
          }
        ],
        "max_deposit_period": "172800s",
        "voting_period": "604800s",
        "quorum": "0.400000000000000000",
        "threshold": "0.667000000000000000",
        "veto_threshold": "0.334000000000000000",
        "min_initial_deposit_ratio": "0.000000000000000000",
        "proposal_cancel_ratio": "0.500000000000000000",
        "proposal_cancel_dest": "",
        "expedited_voting_period": "86400s",
        "expedited_threshold": "0.750000000000000000",
        "expedited_min_deposit": [
          {
            "denom": "uoas",
            "amount": "500000000000"
          }
        ],
        "burn_vote_quorum": false,
        "burn_proposal_deposit_prevote": false,
        "burn_vote_veto": true,
        "min_deposit_ratio": "0.010000000000000000"
      },
      "constitution": ""
    },
    "ibc": {
      "client_genesis": {
        "clients": [],
        "clients_consensus": [],
        "clients_metadata": [],
        "params": {
          "allowed_clients": [
            "*"
          ]
        },
        "create_localhost": false,
        "next_client_sequence": "0"
      },
      "connection_genesis": {
        "connections": [],
        "client_connection_paths": [],
        "next_connection_sequence": "0",
        "params": {
          "max_expected_time_per_block": "30000000000"
        }
      },
      "channel_genesis": {
        "channels": [],
        "acknowledgements": [],
        "commitments": [],
        "receipts": [],
        "send_sequences": [],
        "recv_sequences": [],
        "ack_sequences": [],
        "next_channel_sequence": "0",
        "params": {
          "upgrade_timeout": {
            "height": {
              "revision_number": "0",
              "revision_height": "0"
            },
            "timestamp": "600000000000"
          }
        }
      }
    },
    "mint": {
      "minter": {
        "inflation": "0.050000000000000000",
        "annual_provisions": "0.000000000000000000"
      },
      "params": {
        "mint_denom": "uoas",
        "inflation_rate_change": "0.000000000000000000",
        "inflation_max": "0.050000000000000000",
        "inflation_min": "0.050000000000000000",
        "goal_bonded": "0.670000000000000000",
        "blocks_per_year": "6311520"
      }
    },
    "oasyce_capability": {
      "capabilities": [],
      "invocations": [],
      "params": {
        "min_provider_stake": {
          "denom": "uoas",
          "amount": "10000000000"
        },
        "max_rate_limit": 1000,
        "protocol_fee_rate": 500
      }
    },
    "onboarding": {
      "registrations": [],
      "params": {
        "airdrop_amount": {
          "denom": "uoas",
          "amount": "20000000"
        },
        "pow_difficulty": 16,
        "repayment_deadline_days": 90
      }
    },
    "reputation": {
      "reputation_scores": [],
      "feedbacks": [],
      "params": {
        "max_rating": 500,
        "feedback_cooldown_seconds": 60,
        "verified_weight": "1.000000000000000000",
        "unverified_weight": "0.100000000000000000"
      },
      "reports": []
    },
    "settlement": {
      "escrows": [],
      "bonding_curve_states": [],
      "params": {
        "escrow_timeout_seconds": 3600,
        "protocol_fee_rate": "0.050000000000000000"
      }
    },
    "slashing": {
      "params": {
        "signed_blocks_window": "100",
        "min_signed_per_window": "0.500000000000000000",
        "downtime_jail_duration": "600s",
        "slash_fraction_double_sign": "0.050000000000000000",
        "slash_fraction_downtime": "0.010000000000000000"
      },
      "signing_infos": [],
      "missed_blocks": []
    },
    "staking": {
      "params": {
        "unbonding_time": "1814400s",
        "max_validators": 100,
        "max_entries": 7,
        "historical_entries": 10000,
        "bond_denom": "uoas",
        "min_commission_rate": "0.000000000000000000"
      },
      "last_total_power": "0",
      "last_validator_powers": [],
      "validators": [],
      "delegations": [],
      "unbonding_delegations": [],
      "redelegations": [],
      "exported": false
    },
    "transfer": {
      "port_id": "transfer",
      "denom_traces": [],
      "params": {
        "send_enabled": true,
        "receive_enabled": true
      },
      "total_escrowed": []
    },
    "vesting": {},
    "work": {
      "params": {
        "default_redundancy": 3,
        "min_timeout_blocks": "100",
        "max_timeout_blocks": "10000",
        "reveal_blocks": "50",
        "min_bounty": "1000000",
        "executor_share": "0.900000000000000000",
        "protocol_share": "0.050000000000000000",
        "burn_share": "0.020000000000000000",
        "submitter_rebate": "0.030000000000000000",
        "deposit_rate": "0.100000000000000000",
        "dispute_bond_rate": "0.100000000000000000",
        "min_executor_reputation": 50,
        "max_tasks_per_block": 100,
        "reputation_cap_per_epoch": 100
      },
      "tasks": [],
      "executors": [],
      "task_counter": "0"
    }
  },
  "consensus": {
    "params": {
      "block": {
        "max_bytes": "22020096",
        "max_gas": "-1"
      },
      "evidence": {
        "max_age_num_blocks": "100000",
        "max_age_duration": "172800000000000",
        "max_bytes": "1048576"
      },
      "validator": {
        "pub_key_types": [
          "ed25519"
        ]
      },
      "version": {
        "app": "0"
      },
      "abci": {
        "vote_extensions_enable_height": "0"
      }
    }
  }
}
```

</details>

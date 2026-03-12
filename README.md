# Oasyce Claw Plugin Engine

**—— 面向 AGI 时代的无许可数据确权与隐私清算协议 (本地工程版)**

## 架构说明
本目录是基于《工程级 Claw 插件架构.pdf》设计的 `Oasyce Claw Plugin` 核心工程。
作为 Oasyce 网络的本地物理节点网关 (Data Backpack)。

## 目录结构
- `engines/`: 基础设施层 (Plugin)
  - 包含 `DataEngine`, `MetadataEngine`, `CertificateEngine`, `UploadEngine`, `SearchEngine`, `TradeEngine`。
- `skills/`: Agent 可调用的能力层接口 (Skills)
  - 提供标准的 `scan_data_skill`, `classify_data_skill`, `register_data_asset_skill` 等。
- `gui/`: 纯终端可视化的极客控制台
  - `app.py`: Oasyce Genesis Node (终端 UI，支持拖拽文件确权)。
- `scripts/`: 自动化集成测试
  - `auto_test_genesis.py`: 批量模拟 AI 授权抓取、防线拦截及 L2 动态定价查询。
- `genesis_vault/`: 创世数据账本
  - 存放已通过 PoPC 物理私钥确权的核心资产 JSON 凭证。

## 配置
通过环境变量或命令行参数进行配置：
- `OASYCE_VAULT_DIR`: 账本目录
- `OASYCE_OWNER`: 资产所有者
- `OASYCE_TAGS`: 逗号分隔标签
- `OASYCE_SIGNING_KEY`: 证书签名密钥 (必填)
- `OASYCE_SIGNING_KEY_ID`: 签名密钥标识

## 运行方式
启动节点与网关控制台：
```bash
python3 -m oasyce_plugin.gui.app --signing-key "your-secret"
```
单文件注册：
```bash
python3 -m oasyce_plugin.gui.app --file "/path/to/file" --signing-key "your-secret"
```
证书验证（支持 JSON 文件路径或资产 ID）：
```bash
python3 -m oasyce_plugin.gui.app --verify "OAS_XXXXXXXX" --signing-key "your-secret"
```
执行自动化的网关防御与资产确权测试：
```bash
python3 -m oasyce_plugin.scripts.auto_test_genesis --files "/path/a.pdf,/path/b.pdf" --signing-key "your-secret"
```

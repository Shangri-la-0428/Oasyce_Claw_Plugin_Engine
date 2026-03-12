# CHANGELOG

All notable changes to this project will be documented in this file.

## [0.6.0] - 2026-03-13

### ✨ Added
- **PrivacyFilter (隐私过滤器)**: 自动识别并过滤敏感文件
  - 默认敏感文件名模式：`*身份证*`, `*银行卡*`, `*passport*`, `*.key`, `*.pem`, `*password*`, `*.env`
  - 默认敏感路径前缀：`/etc/`, `/private/`, `~/.ssh/`, `~/.gnupg/`, `*/credentials/`
  - 支持自定义敏感模式和路径
  - 批量过滤 API: `PrivacyFilter.filter_batch()`
  - 集成到 `DataEngine.scan_data_with_privacy_check()`
- **IPFS 可插拔存储系统**: 支持多种存储后端无缝切换
  - `LocalStorage`: 本地文件系统存储（默认）
  - `IPFSBackend`: IPFS 分布式存储（需运行 IPFS 节点）
  - 统一接口：`upload()`, `download()`, `pin()`, `unpin()`
  - `IPFSClient.register_asset_with_storage()`: 一键注册并存储
  - 配置项：`OASYCE_STORAGE_TYPE`, `OASYCE_STORAGE_DIR`
- **新增 Agent Skills**:
  - `check_privacy_skill()`: 检查文件是否敏感
  - `filter_batch_skill()`: 批量过滤文件列表
  - `enable_privacy_filter()`: 启用/禁用隐私检查
  - `scan_data_skill()`: 新增 `skip_privacy_check` 参数
  - `register_data_asset_skill()`: 新增 `storage_backend` 参数
- **12 个新测试用例**: 覆盖 PrivacyFilter 和 IPFS 存储功能

### 🔧 Changed
- 更新 `core_engines.py`: 添加 `PrivacyFilter` 类和 `scan_data_with_privacy_check()` 方法
- 更新 `UploadEngine`: 新增 `register_asset_with_storage()` 方法支持可插拔存储
- 更新 `agent_skills.py`: 集成 PrivacyFilter 和存储后端配置
- 新增 `storage/` 模块：包含 `ipfs_client.py` 和 `__init__.py`
- 版本号更新：`ENGINE_VERSION = "0.3.0"` → `"0.6.0"`

### 📖 Documentation
- 更新 README.md: 添加 PrivacyFilter 和 IPFS 存储详细说明
- 添加使用示例和 API 文档
- 更新测试覆盖率徽章：9 → 71 个测试

### 🧪 Testing
- 新增 `tests/test_privacy_and_storage.py`: 12 个测试用例
- 总测试覆盖：71/71 通过

---

## [0.5.0] - 2026-03-13

### Added
- **PoPC Verification Service** — Complete 6-layer verification pipeline
  - L1: Device TEE certificate chain validation
  - L2: ECDSA cryptographic signature verification
  - L3: Gyroscope micro-jitter entropy analysis (anti-emulator/anti-replay)
  - L4: Temporal consistency checking
  - L5: GPS geo-plausibility validation
  - L6: Capture source trust classification
- **FastAPI REST API** — 4 endpoints: verify, lookup, health, stats
- **21 new verification tests** — Full pipeline coverage
- **GitHub Actions CI/CD** — Python 3.9–3.12 test matrix

### Changed
- Dependencies: added fastapi, uvicorn, pydantic v2, httpx
- Bumped version to 0.5.0

### Security
- Album imports hard-coded `can_be_public=False`
- Emulator detection via zero-entropy gyro analysis
- Random noise injection detection via high-entropy threshold

## [0.3.0] - 2026-03-12

### ✨ Added
- **CLI 命令行工具**: `oasyce` 命令支持 `register` / `search` / `quote` / `verify`
- **结构化日志系统**: 支持日志级别、文件输出、JSON 格式
- **配置系统**: `.env` 文件支持，自动加载配置
- **示例代码**: `examples/` 目录包含 3 个完整示例
- **L3 TEE 引擎测试**: 新增 5 个 zk-PoE 测试用例

### 🔧 Changed
- 更新 `config.py` 支持 `python-dotenv` 自动加载
- 升级 `pyproject.toml` 添加 CLI 入口点和完整 metadata
- 重构 `agent_skills.py` 使用统一 `Config` 对象

### 📖 Documentation
- 完全重写 README.md，面向外部用户
- 添加安装、配置、使用、FAQ 等完整章节
- 添加 API 参考和示例代码

### 🧪 Testing
- 新增 `test_l3_tee_engine.py` (5 个测试用例)
- 总测试覆盖：9/9 通过

---

## [0.2.0] - 2026-03-12

### ✨ Added
- 企业级重构：Dataclass 数据模型
- HMAC-SHA256 PoPC 签名
- 64KB 流式防溢出哈希
- `pyproject.toml` Python 打包配置

### 🧪 Testing
- 端到端注册流程测试
- 核心引擎单元测试

---

## [0.1.0] - 2026-03-11

### ✨ Added
- 初始版本
- DataEngine / MetadataEngine / CertificateEngine / UploadEngine
- 基础 Agent Skills 接口
- Terminal CLI GUI

# CHANGELOG

All notable changes to this project will be documented in this file.

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

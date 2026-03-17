# Contributing to Oasyce

感谢你有兴趣参与 Oasyce！这份指南帮你快速上手。

## 🚀 快速开始

```bash
# 1. Fork & Clone
git clone https://github.com/<your-username>/Oasyce_Claw_Plugin_Engine.git
cd Oasyce_Claw_Plugin_Engine

# 2. 安装依赖
pip install -e ".[dev]"

# 3. 跑测试，确保环境正常
pytest
```

## 📋 提交流程

1. **开 Issue 先讨论**（大改动必须，小 fix 可以跳过）
2. 从 `main` 创建分支：`git checkout -b feat/your-feature`
3. 写代码 + 写测试
4. 本地跑通：`pytest`
5. 提交 PR，描述清楚改了什么、为什么

## 🔧 代码规范

- Python 3.9+（用 `Optional[str]` 不是 `str | None`）
- UTF-8，LF 换行
- 缩进：4 空格（Python）
- 提交信息格式：`类型: 简短描述`
  - `feat:` 新功能
  - `fix:` 修复
  - `docs:` 文档
  - `test:` 测试
  - `refactor:` 重构

## ✅ PR 要求

- [ ] 所有现有测试通过
- [ ] 新功能有对应测试
- [ ] 没有引入敏感信息（密钥、私有路径等）

## 🏗 项目结构

```
Oasyce_Claw_Plugin_Engine/     ← 你在这里（用户层）
├── CLI、Dashboard、P2P、Skills
└── 依赖 oasyce-core

Oasyce_Project/oasyce_core/    ← 协议核心（单独仓库）
├── AHRP、Settlement、Staking、Capabilities...
└── 改协议逻辑去这个仓库
```

如果你的改动涉及协议核心逻辑，请去 [oasyce-core](https://github.com/Shangri-la-0428/Oasyce_Project) 提 PR。

## 💬 交流

- GitHub Issues（Bug 报告、功能建议）
- [Discord](https://discord.gg/dPP5eZKs)（闲聊、提问）

## 📦 发布流程

### PyPI

```bash
# 1. 更新 pyproject.toml 中的 version
# 2. 构建
python -m build
# 3. 上传
twine upload dist/*
```

包名 `oasyce`，发布到 https://pypi.org/project/oasyce/

### ClawHub（OpenClaw Skill 市场）

```bash
# Oasyce Skill 已内置，不需要单独发布
# 如果你修改了 Skill 接口，确保兼容 OpenClaw ≥ 0.5.0
```

### Git 提交与 PR

```bash
# 1. 确保测试通过
pytest

# 2. 提交（遵循 type: description 格式）
git add .
git commit -m "feat: add rights declaration system"

# 3. 推送到你的 fork
git push origin feat/your-feature

# 4. 在 GitHub 上创建 PR
# 5. CI 会自动跑测试（Python 3.9-3.12）
```

## License

贡献的代码遵循 MIT 协议。

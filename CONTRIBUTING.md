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
- [Discord](https://discord.gg/oasyce)（闲聊、提问）

## License

贡献的代码遵循 MIT 协议。

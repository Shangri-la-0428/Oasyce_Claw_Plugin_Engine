# Contributing to Oasyce

感谢你有兴趣参与 Oasyce！ / Thanks for your interest in contributing!

## Setup / 开发环境

```bash
git clone https://github.com/<your-username>/Oasyce_Claw_Plugin_Engine.git
cd Oasyce_Claw_Plugin_Engine
pip install -e ".[dev]"
```

## Running Tests / 运行测试

```bash
pytest                # run all tests
pytest --tb=short -q  # quick summary
```

确保提交前所有测试通过。 / Make sure all tests pass before submitting.

## Code Style / 代码规范

- Formatter: **black** (default settings)
- Type hints required for public APIs
- Python 3.9+ (`Optional[str]`, not `str | None`)
- UTF-8, LF line endings, 4-space indent
- 提交信息 / Commit messages: `type: description`
  - `feat:` / `fix:` / `docs:` / `test:` / `refactor:`

## Submitting PRs / 提交 PR

1. Open an issue first for large changes / 大改动先开 Issue 讨论
2. Branch from `main`: `git checkout -b feat/your-feature`
3. Write code + tests
4. Run `pytest` and `black --check .`
5. Push and open a PR with a clear description

### PR checklist

- [ ] All existing tests pass / 所有现有测试通过
- [ ] New features have tests / 新功能有对应测试
- [ ] No secrets committed / 没有提交敏感信息

## Release Process / 发布流程

1. Update `version` in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Tag: `git tag v2.x.x && git push --tags`
4. CI automatically builds and publishes to [PyPI](https://pypi.org/project/oasyce/)

## Project Structure / 项目结构

```
Oasyce_Claw_Plugin_Engine/   <-- this repo (Python client, CLI, Dashboard)
oasyce-chain/                <-- L1 Cosmos SDK appchain (Go, separate repo)
DataVault/                   <-- data scanning skill (separate repo)
```

Chain-level changes go to [oasyce-chain](https://github.com/Shangri-la-0428/oasyce-chain). Data scanning changes go to [DataVault](https://github.com/Shangri-la-0428/DataVault).

## Contact / 交流

- [GitHub Issues](https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine/issues)
- [Discord](https://discord.gg/dPP5eZKs)

## License

Contributions are licensed under MIT. / 贡献的代码遵循 MIT 协议。

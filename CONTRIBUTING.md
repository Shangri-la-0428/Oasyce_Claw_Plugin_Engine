# Contributing to Oasyce

Thanks for your interest. Oasyce is a decentralized protocol — contributions make it stronger for everyone.

## Quick Start

```bash
git clone https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine.git
cd Oasyce_Claw_Plugin_Engine
python3 -m venv venv
source venv/bin/activate
pip install -e ".[test,dev]"
pytest tests/ -v
```

## Rules

1. **All tests must pass.** Run `pytest tests/ -v` before submitting. Currently 220 tests.
2. **Python 3.9 compatible.** Use `Optional[X]` not `X | None`. Use `from __future__ import annotations`.
3. **No new dependencies without discussion.** Core protocol runs on cryptography + python-dotenv + aiohttp. That's it.
4. **Write tests.** Every new feature needs test coverage.

## Code Style

- UTF-8, LF line endings
- 2-space or 4-space indent (follow existing file conventions)
- `black` for formatting (optional but appreciated)
- Clear docstrings on public functions

## Pull Requests

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes + add tests
4. Run `pytest tests/ -v` — all green
5. Submit PR with a clear description

## What We Need Help With

- Multi-machine P2P testing (different networks, NAT traversal)
- Token contract implementation (ERC-20 / Solana SPL)
- Additional watermark strategies (image, audio, video)
- Language bindings (Rust, TypeScript, Go)
- Security audits

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

# Changelog

All notable changes to this project will be documented in this file.

## [0.9.0] - 2026-03-13

### Architecture (Phases 1-9)
- **Phase 1:** Ed25519 cryptographic key management and digital signatures
- **Phase 2:** SQLite persistent ledger with blockchain-structured storage
- **Phase 3:** Block mining with Merkle trees and hash chaining
- **Phase 4:** P2P TCP+JSON networking with peer discovery (port 9527)
- **Phase 5:** Block synchronization with 3-way validation and fork detection
- **Phase 6:** Consensus engine — longest chain rule, reorganization, rate limiting
- **Phase 7:** Multi-node demo (`oasyce demo-network --nodes N`)
- **Phase 8:** Staking economy — PoS validators, slashing, halving block rewards
- **Phase 9:** Fingerprint watermarking — steganographic embedding and leak tracing

### Settlement & Economics
- Bancor bonding curve pricing engine
- Dual-layer fee structure (settlement + network)
- Deflationary tokenomics with multi-source burns

### Tools & Interface
- Full CLI: register, search, quote, buy, stake, shares, verify, node, fingerprint, demo, gui
- Web dashboard (`oasyce gui` on port 8420) — zero-dependency SPA
- Agent Skills API for programmatic access
- Privacy filter for sensitive file detection
- IPFS-compatible pluggable storage

### Documentation
- `README.md` — project overview with full CLI reference
- `docs/ECONOMICS.md` — complete economic model with formulas and game theory
- `docs/OASYCE_PROTOCOL_OVERVIEW.md` — protocol brief for investors and researchers

### Testing
- 220 tests passing across 15 test files
- Coverage: crypto, ledger, blockchain, P2P, consensus, sync, staking, settlement, fingerprint, privacy, integration

## [0.3.0] - 2026-03-12

- Initial CLI + config system + PoPC certificates
- Privacy filter + IPFS storage
- Core engine architecture

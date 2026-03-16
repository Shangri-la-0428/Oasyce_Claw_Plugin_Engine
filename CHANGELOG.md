# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [1.4.0] - 2026-03-16

### Added
- CLAUDE.md for Claude Code integration
- OpenClaw Skill v3.0.0 (unified 4-in-1)
- Capability assets in Dashboard Explore view
- Testnet onboarding (`oasyce testnet onboard/faucet`)

### Changed
- README rewritten for accessibility (role-based guide, collapsible tech details)

## [1.3.0] - 2026-03-16

### Added
- Phase 2: Capability Assets (register → invoke → escrow → settle → dispute → rating → shares → pipeline)
- Oracle Feed framework (weather, price, time, random, DataAssetFeed, AggregatorFeed)
- OAS unified standard for data + capability + oracle + identity

### Changed
- Dashboard unified explore view (data + capability)
- PyPI package updated

## [1.2.0] - 2026-03-15

### Added
- Dashboard Vite + Preact rewrite
- Cloudflare Worker seed discovery
- P2P networking with peer scoring and PEX

## [1.1.0] - 2026-03-14

### Added
- AHRP v0.1 (Agent Handshake & Routing Protocol)
- OAS-DAS origin_type (HUMAN/SENSOR/CURATED/SYNTHETIC)
- Two-repo restructure (Core = protocol, PE = thin adapter)

## [1.0.0] - 2026-03-13

### Added
- Initial release
- Data asset registration, Bonding Curve pricing, settlement
- Ed25519 signing, Merkle proofs
- CLI + basic Dashboard
- 499 tests

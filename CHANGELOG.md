# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

## [1.11.0] - 2026-03-18

### Added
- **Agent Scheduler**: autonomous scan → classify → register → trade pipeline
- **Manual Pricing**: auto / fixed / floor pricing models for assets and capabilities
- **Capability Marketplace**: register endpoints, invoke via settlement, earnings tracking, discovery
- **Oracle Feeds**: weather, price, time, random, DataAssetFeed, AggregatorFeed
- **Dashboard deep links**: split Explore page with shared register form and deep-link routing
- **Collapsible Network page** in Dashboard
- **Fingerprint Watermarking CLI**: content fingerprinting and infringement detection commands
- **Consensus / Governance CLI**: full suite of `oasyce consensus` and `oasyce governance` commands
- **Testnet onboarding**: `oasyce testnet init/genesis/join/faucet/faucet-serve`
- **Capability delivery protocol**: provider endpoint registry, encrypted API keys, escrow gateway, 5% protocol fee

### Changed
- **Design system overhaul**: 9 quality skills applied across the entire Dashboard
- **i18n narrative refresh**: updated copy and multilingual support
- Explore page split into data / capability sections with unified register form

## [1.10.0] - 2026-03-18

### Added
- **Block production pipeline**: mempool queue + `BlockProducer` (builds and applies blocks)
- Dashboard API for mempool (`/api/consensus/mempool`) and block producer status (`/api/consensus/producer`)
- E2E integration tests for block production

## [1.9.0] - 2026-03-18

### Added
- **Chain ID replay protection**: operations include `chain_id`, validated during `apply_operation`
- **HTTP JSON transport** for P2P block sync (`SyncServer` port 9528 + `HTTPPeerTransport`)
- Dashboard API endpoints for governance, slashing, and sync status

## [1.8.0] - 2026-03-17

### Added
- **Consensus Node lifecycle**: `ConsensusNode` with join, sync, produce phases
- **Fork choice**: longest-chain rule with stake-weighted tiebreaker, reorg support via event-sourced rollback
- **Governance engine**: stake-weighted on-chain voting, proposals with parameter changes, 40% quorum, 2/3 pass threshold, auto-execution
- **Block sync protocol**: `BlockSyncProtocol` async coordinator, genesis hash validation, batch download
- **Genesis**: state creation, validation, import/export
- CLI commands for `testnet init/genesis/join/faucet`, `governance`, `sync`

## [1.7.0] - 2026-03-17

### Added
- **PoS Consensus Engine**: event-sourced architecture with integer units (1 OAS = 10^8 units)
- **Enforcement system**: fingerprint scanning, infringement detection, bounty hunting
- **Multi-asset support**: asset registry (OAS, USDC, DATA_CREDIT, CAPABILITY_TOKEN), per-address per-asset SQLite balances
- **Offline mode**: feature tiers (CRITICAL / DEGRADED / UNAVAILABLE), provider cache for offline browsing
- Snapshot caching, Ed25519 block signatures, reorg support
- CLI `keys` and `enforcement` commands
- Testnet config and deploy scripts

## [1.5.1] - 2026-03-17

### Fixed
- 10 first-user readiness fixes — graceful degradation, port handling, honest labels

## [1.5.0] - 2026-03-17

### Added
- **Schema Registry**: unified validation for `data`, `capability`, `oracle`, `identity` asset types (`oasyce_plugin/schema_registry/`)
- **Discovery Recall→Rank refactor**: `_recall()` (low-threshold OR logic) → `_rank()` (trust + feedback-adjusted scoring)
- **Feedback Loop**: `FeedbackStore` with time-decayed learned trust, per-skill execution tracking (`services/discovery/feedback.py`)
- **Risk auto-classification**: `auto_classify_risk()` — public/internal/sensitive based on PrivacyFilter + extensions + rights_type (`engines/risk.py`)
- **Info hub**: `oasyce_plugin/info.py` — single source of truth for project info (consumed by GUI, CLI, API)
- `oasyce info` CLI command with `--section quickstart|architecture|economics|update|links` and `--json`
- `/api/info` endpoint (supports `?lang=zh`)
- Dashboard about panel upgraded: tabbed UI (Overview / Quick Start / Architecture / Economics / Maintain / Links)
- Discord community link and dual GitHub repo links in about panel
- `AssetMetadata.asset_type` field in `models.py`
- `SchemaAssetType` re-export in `standards/__init__.py`
- Rights declaration system: `original`, `co_creation`, `licensed`, `collection` with pricing multipliers
- Co-creator support with share validation (must sum to 100%)
- Dispute mechanism: file disputes, auto-discover arbitrators via Recall→Rank Discovery
- Dispute resolution: `delist`, `transfer`, `rights_correction`, `share_adjustment` remedies
- `oasyce dispute` CLI command
- `oasyce resolve` CLI command
- `oasyce discover` CLI command (Recall→Rank capability search)
- Capability publishing from Dashboard home page
- `/api/dispute`, `/api/dispute/resolve`, `/api/discover` API endpoints
- SkillAffinity: agents remember successful skill pairings
- 590 tests (was 499)

### Changed
- `engines/schema.py:validate_metadata()` now delegates to `schema_registry.validate("data", ...)` (backward-compatible)
- `MetadataEngine.generate_metadata()` auto-injects `risk_level` and `max_access_level`
- `SkillDiscoveryEngine` uses `FeedbackStore` for blended trust: `0.6 * static + 0.4 * learned`
- `discover()` internal pipeline: monolithic loop → `_recall()` + `_rank()` phases
- Dashboard upload UX: unified dropzone (click = file, drag = file or folder), × clear button
- Removed scan mode from home page (available in Automation tab)
- Capability form simplified to name + description only (sensible defaults)
- Embedded SPA (app.py) updated with all new features

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

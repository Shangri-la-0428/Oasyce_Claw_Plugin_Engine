# Changelog

All notable changes to this project will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/).

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

# Legacy → Preact SPA Migration Checklist

> Target: Migrate all features from `app.py` inline `_INDEX_HTML` to `dashboard/src/` Preact SPA, then delete legacy fallback.
> Updated: 2026-03-22 | **Status: COMPLETE ✅**

## Page Mapping

| Legacy Page | Legacy ID | Preact Page | Status |
|---|---|---|---|
| Register (drag + describe) | `pg-register` | `mydata.tsx` (merged) | Done |
| Trade (quote + buy shares) | `pg-trade` | `explore.tsx` + `explore-browse.tsx` | Done |
| Your Assets (list + detail + delete) | `pg-assets` | `mydata.tsx` | Done |
| Agent Protocol (register + discover + trade) | `pg-agents` | `explore-bounty.tsx` + capability endpoints | Done |
| Network (node status + validators) | `pg-network` | `network.tsx` | Done |

## Feature Module Mapping

| Feature | Legacy Location | Preact | Status |
|---|---|---|---|
| Dark/Light theme | CSS vars + toggle | `design.css` + `ui.ts` | Done |
| i18n (CN/EN) | embedded dict + toggle | `ui.ts` dict + Nav | Done |
| Drag-drop register | pg-register dropzone | `mydata.tsx` dropzone | Done |
| Pixel grid viz | N/A | `network-grid.tsx` | Done |
| Identity panel (keys + info) | identity-card | `network.tsx` | Done |
| Buy Shares (quote → confirm → result) | pg-trade card | `explore-browse.tsx` (L0-L3 access) | Done |
| Portfolio (holdings view) | pg-trade portfolio | `explore-portfolio.tsx` | Done |
| Stake (validator staking) | pg-trade stake | `explore-stake.tsx` | Done |
| Watermark (embed/extract/trace) | pg-network card | `network.tsx` (watermark section) | Done |
| Scanner (scan directory for assets) | API only | `automation.tsx` (scan section) | Done |
| Inbox (approve/reject/edit pending) | API only | `automation.tsx` (inbox section) | Done |
| Trust Level (set automation trust) | API only | `automation.tsx` (trust config) | Done |
| Agent Scheduler (start/stop/config) | API only | `automation.tsx` (agent section) | Done |
| Task Bounty (post/bid/select/complete) | N/A | `explore-bounty.tsx` | Done |
| Agent Announce (register Agent) | pg-agents card | capability register API | Done (via CLI/API) |
| Agent Discover (find Agents) | pg-agents card | discover API | Done (via CLI/API) |
| Agent Transaction (agent trades) | pg-agents card | invoke API | Done (via CLI/API) |
| Validators list (stake table) | stakes-card | `network.tsx` (validators section) | Done |

## Current SPA Pages

| Page | File | Content |
|------|------|---------|
| Home | `home.tsx` | Status overview, quick actions |
| My Data | `mydata.tsx` | Asset list, register, detail, lifecycle, versions |
| Explore | `explore.tsx` | Browse + Portfolio + Stake + Bounty tabs |
| Explore Browse | `explore-browse.tsx` | Market listing, access quote/buy |
| Explore Portfolio | `explore-portfolio.tsx` | Holdings, sell, tx history, L0-L3 access |
| Explore Stake | `explore-stake.tsx` | Validator staking |
| Explore Bounty | `explore-bounty.tsx` | Task market: post, bid, select, complete |
| Automation | `automation.tsx` | Scanner, Inbox, Trust, Agent Scheduler |
| Network | `network.tsx` | Identity, peers, consensus, watermark, governance, contribution, leakage, cache |

## Completed Work

### Phase D — Cleanup ✅
- [x] Delete `_INDEX_HTML` and legacy fallback logic from `app.py` (1491 lines removed)
- [x] Delete `dist.bak/` if present (not present, already clean)
- [x] `_html_response()` helper removed (no longer used)
- [x] Fallback now returns 503 with build instructions

---
*Created: 2026-03-17 | Completed: 2026-03-22*

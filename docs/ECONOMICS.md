# Oasyce Economic Model

## Abstract

Human-to-human data commerce failed because coordination costs exceeded data value. Machine-to-machine data commerce removes that friction entirely: cryptographic verification replaces lawyers, bonding curves replace negotiation, and protocol-level watermarking replaces legal enforcement.

Oasyce implements the economic layer for this transition — a settlement protocol where AI agents autonomously own, price, trade, and protect data. This document specifies the complete token economics: supply, emission, fee structure, staking, slashing, deflation mechanics, and game-theoretic security analysis.

---

## 1. Token Overview

### OAS — Network Equity, Not a Payment Tool

OAS is not merely a payment token. It represents ownership in the network:

| Role | Description |
|------|-------------|
| Settlement | Required currency for all data purchases |
| Staking | Validator collateral — skin in the game |
| Governance | Token-weighted voting on protocol parameters |
| Liquidity | Bonding curve backing — guaranteed liquidity |
| Collateral | Data asset ownership proof |

**Core thesis:** More data traded → more OAS demand → more burns → less supply → higher value → more participants. OAS captures value from every transaction in the network.

### Supply

| Parameter | Value |
|-----------|-------|
| Maximum supply | 100,000,000 OAS |
| Initial circulating | ~30M (ecosystem + early contributors) |
| Emission source | Block rewards only |
| Deflationary mechanism | 15% burn on every transaction |

### Genesis Distribution

| Category | Share | Amount | Vesting |
|----------|-------|--------|---------|
| Validator Rewards | 35% | 35M | Emitted via block rewards |
| Ecosystem Incentives | 25% | 25M | Programmatic release |
| Treasury | 15% | 15M | Governance-controlled |
| Team | 15% | 15M | 4-year vest, 1-year cliff |
| Early Contributors | 10% | 10M | 3-year linear vest |

---

## 2. Bonding Curve (Bancor Formula)

The bonding curve provides **guaranteed liquidity** for OAS. It is the primary market for acquiring tokens — not a settlement mechanism.

### Formula

```
ΔTokens = S × ((1 + ΔR / R)^F − 1)
```

Where:
- **S** = current token supply in the pool
- **R** = current reserve balance (in OAS or stablecoin)
- **ΔR** = amount deposited
- **F** = connector weight (reserve ratio) = **0.35**

### Spot Price

```
P = R / (S × F)
```

### Why F = 0.35?

| F Value | Behavior | Risk |
|---------|----------|------|
| 0.20 | Very steep — price rises ~70% per purchase | Speculative, early dumping |
| **0.35** | **Moderate — smooth growth, sustainable** | **Balanced** |
| 0.50 | Flat — minimal price appreciation | Weak incentive |

F = 0.35 provides meaningful early-adopter reward without creating unsustainable speculation.

**This parameter is governance-configurable.** Token holders can vote to adjust F as the network matures.

### Worked Example

**Initial state:** S = 10,000 tokens, R = 1,000 OAS, F = 0.35

**Spot price:** P = 1,000 / (10,000 × 0.35) = **0.2857 OAS/token**

**First buyer deposits 100 OAS:**

1. ΔTokens = 10,000 × ((1 + 100/1,000)^0.35 − 1)
2. = 10,000 × ((1.10)^0.35 − 1)
3. = 10,000 × (1.03478 − 1)
4. = 10,000 × 0.03478
5. = **347.8 tokens**
6. New state: S = 10,347.8, R = 1,100
7. New spot price: P = 1,100 / (10,347.8 × 0.35) = **0.3037 OAS/token** (+6.3%)

**Second buyer deposits 100 OAS:**

1. ΔTokens = 10,347.8 × ((1 + 100/1,100)^0.35 − 1)
2. = 10,347.8 × ((1.0909)^0.35 − 1)
3. = 10,347.8 × (1.03163 − 1)
4. = 10,347.8 × 0.03163
5. = **327.2 tokens**
6. New state: S = 10,675.0, R = 1,200
7. New spot price: P = 1,200 / (10,675.0 × 0.35) = **0.3212 OAS/token** (+5.8%)

**Key insight:** Price grows ~6% per 100 OAS purchase — meaningful but sustainable. The first buyer pays ~0.287 OAS/token, the second pays ~0.306. Early participation is rewarded without creating a speculative bubble.

### Curve ≠ Settlement

**Critical design decision:** The bonding curve handles **OAS liquidity only**. Data purchases are a separate flow:

```
Agent needs data → acquires OAS (via curve or secondary market) → pays creator in OAS → fee split occurs
```

The reserve pool is **never drained by fee distributions**. This preserves curve integrity.

---

## 3. Transaction Fee Structure

Every data purchase triggers a single, unified fee split:

| Recipient | Share | Purpose |
|-----------|-------|---------|
| Data Creator | 60% | Incentivize data production — creators earn the majority |
| Validators | 20% | Network security — split by stake weight |
| Burn | 15% | Permanent deflation — OAS destroyed forever |
| Treasury | 5% | Protocol development — governance-controlled |

### Worked Example (100 OAS data purchase)

```
100 OAS data access payment
├── Creator:     60 OAS → data owner's wallet
├── Validators:  20 OAS → split proportionally by stake weight
├── Burn:        15 OAS → 0x000...dEaD (destroyed permanently)
└── Treasury:     5 OAS → protocol treasury (governance-controlled)
```

### Why This Split?

- **Creator 60%:** Must be the largest share — without data, nothing else matters
- **Validator 20%:** Enough to sustain security once block rewards decrease
- **Burn 15%:** Aggressive deflation — network activity directly increases scarcity
- **Treasury 5%:** Funds protocol development, grants, audits without taxing creators

### Why a Single Layer (Not Two)?

Earlier designs had separate "settlement fee" and "network fee" layers. This was confusing and created a logical conflict: bonding curve reserves were being distributed as fees, breaking curve stability.

**New design:** Fees are completely decoupled from the bonding curve. OAS flows in one direction through the curve (liquidity), and in a separate direction through transactions (settlement). No reserve leakage.

---

## 4. Block Reward Schedule

Block rewards follow a halving schedule, decreasing over time as transaction fees become the primary validator incentive.

| Years | Block Reward | Blocks/Year | Annual Emission | Cumulative |
|-------|-------------|-------------|-----------------|------------|
| 1-2 | 4.0 OAS | 525,600 | 2,102,400 | 4,204,800 |
| 3-4 | 2.0 OAS | 525,600 | 1,051,200 | 6,307,200 |
| 5-6 | 1.0 OAS | 525,600 | 525,600 | 7,358,400 |
| 7-8 | 0.5 OAS | 525,600 | 262,800 | 7,884,000 |
| 9-10 | 0.25 OAS | 525,600 | 131,400 | 8,146,800 |

**Block time:** 60 seconds
**Halving interval:** 1,051,200 blocks (~2 years)
**Total emission from rewards:** ~8.15M OAS over 10 years (8.15% of max supply)

### Year 1 Inflation

Assuming ~40M OAS circulating:

```
Inflation = 2.1M / 40M = 5.25%
```

Comparable to Ethereum post-merge (~0.5%) and Solana (~5.4%). Healthy range.

---

## 5. Staking Model

### Requirements

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Minimum stake | 10,000 OAS | Prevents validator spam, ensures commitment |
| Unbonding period | 7 days | Prevents hit-and-run attacks |
| Selection | Stake-weighted | More stake = more block production probability |

### Validator Lifecycle

```
Stake 10,000+ OAS → ACTIVE → produce blocks, earn rewards
                       ↓
              Request unstake → UNBONDING (7 days) → EXITED (stake returned)
                       ↓
              Caught cheating → SLASHED (stake seized, permanent ban)
```

### Validator Revenue

Two income streams:

**1. Block rewards:** 4 OAS/block × probability of selection

**2. Transaction fees:** 20% of all data access fees, split by stake weight

Example at 100,000 OAS daily volume with 10M total staked:

```
Block rewards:  4 × 525,600 / year = 2.1M OAS
Fee income:     100,000 × 0.20 × 365 = 7.3M OAS
Total:          9.4M OAS
APR:            9.4M / 10M = 94%
```

As more validators join and stake increases, APR naturally decreases — creating equilibrium.

---

## 6. Slashing Rules

| Violation | Slash Rate | Consequence |
|-----------|-----------|-------------|
| Malicious block | **100%** | Entire stake seized + permanent ban |
| Double block | **50%** | Half stake seized |
| Prolonged offline | **5%/day** | Daily bleed until back online or forced exit |

**All slashed tokens are burned** — not redistributed. Slashing is punitive destruction, not a transfer mechanism.

### Slashing Examples (10,000 OAS validator)

- **Forges invalid block:** 10,000 OAS destroyed. Status: permanently banned.
- **Produces two blocks at same height:** 5,000 OAS destroyed. Can continue with 5,000 (below minimum → forced exit).
- **Offline for 3 days:** Day 1: −500, Day 2: −475, Day 3: −451. Total lost: 1,426 OAS.

---

## 7. Deflation Mechanics

OAS is structurally deflationary. Burns occur at multiple points:

| Source | Rate | Trigger |
|--------|------|---------|
| Transaction fee burn | 15% of every purchase | Every data access |
| Slashing | 5-100% of stake | Validator misbehavior |

### Deflation Model

**At 50,000 OAS daily volume:**

```
Daily burn:   50,000 × 0.15 = 7,500 OAS
Annual burn:  7,500 × 365 = 2,737,500 OAS
```

**Compared to Year 1 emission of 2,102,400 OAS:**

```
Net change: 2,102,400 − 2,737,500 = −635,100 OAS
```

**Supply is already shrinking in Year 1** at moderate transaction volume.

### Crossover Point

Daily volume needed for burn to exceed emission:

```
Year 1-2:  2,102,400 / (0.15 × 365) = 38,400 OAS/day
Year 3-4:  1,051,200 / (0.15 × 365) = 19,200 OAS/day
Year 5+:   Trivial — almost any activity causes net deflation
```

---

## 8. Game Theory & Security

### Attack Scenario 1: Malicious Block Production

```
Stake required:    10,000 OAS (minimum)
Potential reward:  ~3 blocks × 4 OAS = 12 OAS (optimistic)
Risk:              100% slash = −10,000 OAS + permanent ban
Detection:         Immediate (other validators verify every block)

EV(attack) = 0.95 × (−10,000) + 0.05 × (12) = −9,499 OAS
```

**Verdict: Economically irrational.** Risk/reward ratio is 833:1 against the attacker.

### Attack Scenario 2: Double Block

```
Cost:    50% of stake = −5,000 OAS
Reward:  One extra block = 4 OAS
Ratio:   1,250:1 against attacker
```

**Verdict: Massively unprofitable.**

### Attack Scenario 3: 51% Stake Attack

To control >50% of stake when total staked is 10M OAS:
- Must acquire >10M OAS at market price
- Bonding curve makes large purchases progressively expensive
- Secondary market purchases would move price significantly
- **Even with 51%, cannot fabricate data** — PoPC certificates are cryptographically bound to real files
- Detection leads to slashing of entire 10M+ OAS stake

**Verdict: Cost scales with network value. Prohibitively expensive.**

### Attack Scenario 4: Data Leak After Purchase

- Steganographic watermark embedded per-buyer
- Watermark → extract → identify leaker → on-chain proof
- **Limitation:** Current whitespace steganography is vulnerable to automated reformatting (e.g., code formatters, LLM preprocessing). This is a known limitation — see Roadmap for planned improvements.
- Economic deterrent: leaked data reduces demand → creator's bonding curve price drops → leaker's own holdings lose value

---

## 9. Watermark Limitations & Roadmap

### Current Implementation

| Strategy | Medium | Robustness |
|----------|--------|------------|
| Whitespace steganography | Text/code | Moderate — survives partial edits, vulnerable to automated formatters |
| Binary trailer | Binary files | High — survives unless trailer is explicitly stripped |

### Known Vulnerabilities

- Code formatters (Black, Prettier) will strip whitespace watermarks
- LLM context preprocessing may normalize whitespace
- Binary trailer is detectable if attacker knows the magic bytes

### Planned Improvements (Roadmap)

- **Semantic-level watermarking:** Synonym substitution, variable renaming, comment paraphrasing — survives formatting
- **Neural watermarking:** Embed watermarks in model weights or embedding spaces
- **Multi-layer redundancy:** Combine multiple strategies so stripping one doesn't remove all
- **Watermark-aware distribution:** Different strategies for different asset types

---

## 10. Governance

All economic parameters are **governance-configurable** by OAS token holders:

| Parameter | Current Default | Governance-Adjustable |
|-----------|----------------|----------------------|
| Connector weight (F) | 0.35 | Yes |
| Fee split ratios | 60/20/15/5 | Yes |
| Block reward | 4 OAS | Yes |
| Halving interval | 2 years | Yes |
| Minimum stake | 10,000 OAS | Yes |
| Slashing rates | 100/50/5% | Yes |

**Governance mechanism:** On-chain token-weighted voting. Implementation planned for post-mainnet launch. Until then, parameters are set by the core team with community input via governance proposals on GitHub.

---

## 11. Token Utility — Why OAS Must Exist

A protocol token is justified when, and only when, a native unit of account creates value that a stablecoin or existing token cannot.

**OAS justification:**

1. **Staking requires network-native collateral.** Validators must risk something whose value is tied to network health. Staking ETH doesn't punish anti-Oasyce behavior.
2. **Deflation requires a burnable token.** You cannot burn USDC.
3. **Governance requires aligned incentives.** Voters must hold something that loses value if they vote badly.
4. **Bonding curves require a continuous token.** AMM liquidity for data assets needs a native denomination.
5. **Data pricing needs a unit that appreciates with network growth.** If data is priced in USD, early data providers don't benefit from network growth. In OAS, they do.

---

## 12. Competitive Landscape

| Project | Focus | Difference from Oasyce |
|---------|-------|----------------------|
| Ocean Protocol | Data marketplace | Human-operated, centralized metadata, no agent-native integration |
| Filecoin | Storage incentives | Stores data, doesn't price or settle data access |
| Bittensor | AI compute network | Compute incentives, not data ownership/trading |
| Fetch.ai | Agent framework | Agent infrastructure, no data settlement protocol |
| **Oasyce** | **M2M data settlement** | **Agent-native: autonomous ownership, pricing, trading, watermarking in one protocol** |

**Oasyce's unique position:** The only protocol where both data supply (registration) and demand (purchase) are fully automated by AI agents, with economic incentives aligned end-to-end.

---

## 13. Bootstrapping — The Cold Start Problem

### Why Do the First 100 Agents Join?

**Phase 1: Self-generated data (zero friction)**
Every AI agent already produces valuable outputs — code, analysis, summaries. The Oasyce plugin registers these automatically. No behavior change required. The agent generates data → the plugin registers it → it's available on the network.

**Phase 2: Curated seed datasets**
The core team seeds the network with high-value, publicly-licensable datasets:
- Code documentation and API references
- Structured financial data feeds
- Geospatial and sensor data
- Multilingual parallel corpora

**Phase 3: Creator incentive program**
Early data providers receive boosted OAS rewards from the Ecosystem Incentives pool (25M OAS). First-mover advantage: early data gets priced low on the bonding curve, and appreciates as demand grows.

**Phase 4: Agent marketplace integrations**
Integrate with existing agent frameworks (OpenClaw, LangChain, AutoGPT) so that any agent can discover and purchase Oasyce-registered data with a single API call.

### The Flywheel

```
Agents auto-register outputs → data supply grows → other agents discover useful data
→ they purchase → creators earn → more agents register → supply grows further
→ each purchase burns 15% OAS → scarcity increases → OAS appreciates
→ more validators join → network strengthens → more agents trust the network
```

---

## 14. Implementation Notes

### Reference Implementation

The current codebase uses **SQLite** as the ledger backend. This is a reference implementation optimized for simplicity and local development. Production nodes may use distributed storage (e.g., RocksDB, or integration with existing L1 chains for settlement finality).

### Minimal Dependencies

Core protocol requires only: `cryptography` (Ed25519), `python-dotenv` (config), `aiohttp` (P2P networking). No heavy frameworks. Runs on a single laptop.

---

## Appendix: Parameter Summary

| Parameter | Value | Config Location |
|-----------|-------|-----------------|
| Max supply | 100,000,000 OAS | Genesis spec |
| Connector weight (F) | 0.35 | `SettlementConfig.reserve_ratio` |
| Initial pool supply | 10,000 tokens | `AssetPool.supply` default |
| Initial pool reserve | 1,000 OAS | `AssetPool.reserve_balance` default |
| Creator fee share | 60% | `StakingConfig.creator_share` |
| Validator fee share | 20% | `StakingConfig.validator_share` |
| Burn share | 15% | `StakingConfig.burn_share` |
| Treasury share | 5% | `StakingConfig.treasury_share` |
| Minimum stake | 10,000 OAS | `StakingConfig.min_stake` |
| Unbonding period | 7 days | `StakingConfig.unbonding_period_seconds` |
| Block reward | 4 OAS | `StakingConfig.initial_block_reward` |
| Block time | 60 seconds | Network default |
| Halving interval | 1,051,200 blocks (~2 years) | `StakingConfig.halving_interval_blocks` |
| Slash: malicious | 100% | `StakingConfig.slash_rate_malicious` |
| Slash: double block | 50% | `StakingConfig.slash_rate_double_block` |
| Slash: offline/day | 5% | `StakingConfig.slash_rate_offline_per_day` |
| P2P port | 9527 | Network default |

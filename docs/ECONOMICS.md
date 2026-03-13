# Oasyce Economic Model

## Abstract

Human-to-human data commerce failed because coordination costs exceeded data value. Machine-to-machine data commerce removes that friction entirely: cryptographic verification replaces lawyers, bonding curves replace negotiation, and protocol-level watermarking replaces legal enforcement.

Oasyce implements the economic layer for this transition. A dual-layer model — Bancor bonding curve settlement combined with Proof-of-Stake validator economics — creates a self-sustaining data marketplace where prices emerge algorithmically, validators are incentivized to behave honestly, and persistent deflation via token burning aligns every participant's interest with the network's growth.

---

## 1. Bonding Curve (Bancor Formula)

### Formula

The Bancor continuous liquidity model determines how many tokens a buyer receives for a given payment:

```
ΔTokens = S × ((1 + ΔR / R)^F − 1)
```

Where:
- **S** = current token supply
- **R** = current reserve balance (in OAS)
- **ΔR** = net deposit (payment after protocol fee deduction)
- **F** = connector weight / reserve ratio (0.20 = 20%)

### Spot Price

The instantaneous price at any point:

```
P = R / (S × F)
```

Where F = 0.20 (configurable via `SettlementConfig.reserve_ratio`).

### Properties

- **Monotonically increasing**: Each purchase increases R and S, pushing P higher
- **Continuous liquidity**: No order book needed; price is always available
- **Deterministic**: Same inputs always produce same outputs
- **Sub-linear connector weight (F=0.20)**: Price rises steeply with demand — early buyers are rewarded

### Worked Example

**Initial state:** S=1000 tokens, R=100 OAS, F=0.20

**Spot price:** P = 100 / (1000 × 0.20) = **0.50 OAS/token**

**Buyer pays 100 OAS:**

1. Protocol fee: 100 × 0.05 = 5.0 OAS
2. Net deposit (ΔR): 100 − 5.0 = 95.0 OAS
3. Tokens minted: ΔTokens = 1000 × ((1 + 95/100)^0.20 − 1)
   - = 1000 × ((1.95)^0.20 − 1)
   - = 1000 × (1.1432 − 1)
   - = 1000 × 0.1432
   - = **143.2 tokens**
4. New state: S=1143.2, R=195.0
5. New spot price: P = 195 / (1143.2 × 0.20) = **0.853 OAS/token** (+70.6%)

**Second buyer pays 100 OAS:**

1. Protocol fee: 5.0 OAS
2. Net deposit: 95.0 OAS
3. Tokens minted: 1143.2 × ((1 + 95/195)^0.20 − 1)
   - = 1143.2 × ((1.4872)^0.20 − 1)
   - = 1143.2 × (1.0826 − 1)
   - = 1143.2 × 0.0826
   - = **94.4 tokens** (fewer tokens than first buyer — price went up)
4. New state: S=1237.6, R=290.0
5. New spot price: P = 290 / (1237.6 × 0.20) = **1.172 OAS/token** (+37.4%)

**Key insight:** The first buyer paid ~0.70 OAS/token (effective), the second paid ~1.06 OAS/token. Early participation is rewarded.

---

## 2. Fee Structure

Oasyce has two complementary fee layers operating at different protocol levels.

### Layer 1: Settlement Fee (Per-Purchase)

Applied by the Settlement Engine when a buyer purchases data access:

| Component | Rate | Destination |
|-----------|------|-------------|
| Protocol fee | 5% of payment | Split below |
| → Burn | 50% of fee (2.5% of total) | Dead address — permanent deflation |
| → Verifier | 50% of fee (2.5% of total) | PoPC certificate verifier |
| Net deposit | 95% of payment | Enters bonding curve reserve |

**Example (100 OAS payment):**

```
100 OAS payment
├── Protocol Fee: 5.0 OAS
│   ├── Burn: 2.5 OAS → 0x000...dEaD (destroyed forever)
│   └── Verifier Reward: 2.5 OAS → verifier who validated the PoPC certificate
└── Net Deposit: 95.0 OAS → bonding curve reserve (pushes price up)
```

### Layer 2: Transaction Fee Distribution (Network Level)

Applied at the network consensus layer when data access fees are collected:

| Recipient | Share | Rationale |
|-----------|-------|-----------|
| Creator | 70% | Data creator receives the majority — incentivizes content creation |
| Validators | 20% | Split proportionally by stake weight — incentivizes honest validation |
| Burn | 10% | Permanent deflation — increases scarcity over time |

**Example (100 OAS in data access fees):**

```
100 OAS data access fee
├── Creator: 70 OAS → data owner
├── Validator Pool: 20 OAS → split by stake weight among active validators
└── Burn: 10 OAS → permanently destroyed
```

### How the Two Layers Interact

1. Buyer pays 100 OAS for data access
2. **Settlement layer** takes 5 OAS protocol fee (2.5 burn + 2.5 verifier), deposits 95 OAS into bonding curve
3. The 95 OAS effectively becomes the "data access fee" that flows through the **network layer**
4. Network distributes: Creator 66.5 OAS (70%), Validators 19.0 OAS (20%), Burn 9.5 OAS (10%)
5. **Total burn per 100 OAS transaction: 2.5 + 9.5 = 12.0 OAS (12%)**

---

## 3. Staking Model

### Validator Requirements

| Parameter | Value |
|-----------|-------|
| Minimum stake | 1,000 OAS |
| Unbonding period | 7 days (604,800 seconds) |
| Validator selection | Proportional to stake weight |

### Validator Lifecycle

```
ACTIVE → UNBONDING → EXITED
   ↓
SLASHED (cannot re-stake)
```

- **ACTIVE**: Staked and participating in block validation
- **UNBONDING**: Withdrawal requested, 7-day cooldown (stake still at risk during this period)
- **SLASHED**: Caught misbehaving, stake partially or fully seized, permanently banned
- **EXITED**: Unbonding complete, stake returned

### Stake-Weighted Selection

Probability of being selected to produce a block:

```
P(validator_i) = stake_i / Σ(all_stakes)
```

A validator with 5,000 OAS staked in a pool of 100,000 total has a 5% chance of producing each block.

---

## 4. Slashing Rules

| Violation | Slash Rate | Description |
|-----------|-----------|-------------|
| Malicious block | **100%** | Forging an invalid block — entire stake seized, permanent ban |
| Double block | **50%** | Producing two blocks at the same height — half stake seized |
| Prolonged offline | **5%/day** | Offline for >1 day — continuous daily bleed until back online or forced exit |

### Slashing Examples

**Validator with 5,000 OAS stake:**

- **Produces invalid block:** 5,000 OAS seized (100%). Status → SLASHED. Cannot re-stake.
- **Produces two blocks at height 1000:** 2,500 OAS seized (50%). Remaining 2,500 OAS still staked.
- **Offline for 3 days:** Day 1: −250 OAS, Day 2: −237.5 OAS, Day 3: −225.6 OAS. Total lost: 713.1 OAS. Remaining: 4,286.9 OAS.

### Slashed Funds Destination

Slashed tokens are **burned** — they go to the dead address. This is not a transfer to other validators, but permanent destruction. This ensures slashing is punitive, not redistributive.

---

## 5. Block Reward Schedule

Block rewards follow a Bitcoin-style halving schedule:

| Year | Block Reward | Blocks/Year | Annual Emission | Cumulative Supply |
|------|-------------|-------------|----------------|-------------------|
| 1 | 50.0 OAS | 525,600 | 26,280,000 OAS | 26,280,000 |
| 2 | 25.0 OAS | 525,600 | 13,140,000 OAS | 39,420,000 |
| 3 | 12.5 OAS | 525,600 | 6,570,000 OAS | 45,990,000 |
| 4 | 6.25 OAS | 525,600 | 3,285,000 OAS | 49,275,000 |
| 5 | 3.125 OAS | 525,600 | 1,642,500 OAS | 50,917,500 |
| 6 | 1.5625 OAS | 525,600 | 821,250 OAS | 51,738,750 |
| 7 | 0.78125 OAS | 525,600 | 410,625 OAS | 52,149,375 |
| 8 | 0.390625 OAS | 525,600 | 205,312 OAS | 52,354,687 |
| 9 | 0.195313 OAS | 525,600 | 102,656 OAS | 52,457,343 |
| 10 | 0.097656 OAS | 525,600 | 51,328 OAS | 52,508,671 |

**Halving interval:** 525,600 blocks (~1 year at 1 block per minute)

**Asymptotic max supply:** ~52.56 million OAS (before accounting for burns)

**Long-term sustainability:** As block rewards decrease, transaction fee revenue (from data marketplace activity) becomes the primary validator incentive.

---

## 6. Deflation Mechanics

OAS is designed to be deflationary. Burns happen at multiple points:

### Burn Sources

| Source | Rate | Trigger |
|--------|------|---------|
| Settlement protocol fee | 2.5% of each purchase | Every data access purchase |
| Network transaction burn | 10% of access fees | Every data access fee distribution |
| Slashing | Variable (5-100%) | Validator misbehavior |

### Deflation Model

Total burn per 100 OAS data purchase: **~12 OAS** (12%)

At scale, if the network processes 10,000 OAS in daily transactions:
- Daily burn: ~1,200 OAS destroyed
- Annual burn: ~438,000 OAS destroyed

Compared to Year 2 emission of 13,140,000 OAS, this is ~3.3% offset. As adoption grows and emission decreases, the burn rate increasingly outpaces emission, creating net deflation.

**Crossover point:** When daily transaction volume exceeds ~36,000 OAS (Year 1) or ~18,000 OAS (Year 2), the daily burn exceeds the daily emission, and the total supply begins to shrink.

---

## 7. Game Theory

### Attack Scenario 1: Malicious Block Production

**Attacker goal:** Produce invalid blocks to double-spend or rewrite history.

**Attack requirements:**
- Stake minimum 1,000 OAS to become a validator
- Get selected to produce a block (probability = stake / total_stake)

**Expected value analysis:**

```
Cost:    1,000 OAS minimum stake (at risk)
Reward:  Block reward × number of malicious blocks before detection
         = 50 OAS × ~3 blocks ≈ 150 OAS (optimistic)
Risk:    100% slash = lose 1,000+ OAS
         Permanent ban = lose all future block rewards

EV(attack) = 0.95 × (−1000) + 0.05 × (150) = −942.5 OAS
EV(honest) = 50 × (stake/total) × 525600 = positive ongoing income
```

**Conclusion:** Attack is economically irrational. Risk/reward ratio is ~6.7:1 against the attacker.

### Attack Scenario 2: Double Block Production

**Attacker goal:** Produce competing blocks to create a fork.

```
Cost:    50% of stake = 500+ OAS
Reward:  One extra block reward ≈ 50 OAS
Risk/Reward: 10:1 against attacker
```

**Conclusion:** Massively unprofitable.

### Attack Scenario 3: 51% Stake Attack

**Attacker goal:** Control block production by staking >50% of total OAS.

**If total staked is 1,000,000 OAS:**
- Attacker must stake 1,000,001+ OAS
- Cost: >1M OAS acquired at market price (price impact: bonding curve makes large purchases progressively more expensive)
- Risk: Detection → mass slashing of 1M+ OAS
- Reward: Ability to censor transactions (but not steal funds — cryptographic proofs prevent fabrication)

**Conclusion:** Cost of attack scales with network value. The bonding curve makes acquiring large amounts of OAS progressively more expensive, creating a natural defense.

### Attack Scenario 4: Data Leak After Purchase

**Attacker goal:** Buy data, remove watermark, redistribute.

**Defense:**
- Steganographic watermark embedded at bit-level — not visible, not easily removable
- Fingerprint bound on-chain: `fingerprint_hash ↔ caller_id ↔ timestamp`
- Leak detection: extract watermark → identify buyer → on-chain evidence
- Economic deterrent: leaked data loses value (supply increases, price drops via curve)

**Conclusion:** Cryptographic accountability makes leaking attributable and punishable.

---

## 8. Fingerprint Economics

### Watermark Distribution Model

Each data access purchase generates a **unique watermarked copy** of the data:

1. Buyer pays via bonding curve → receives access
2. Fingerprint engine generates unique watermark from `caller_id + timestamp + asset_id`
3. Watermark embedded steganographically into the data
4. Distribution record stored on-chain: `{fingerprint_hash, caller_id, asset_id, timestamp}`

### Leak Tracing Flow

```
Leaked file found
    → Extract watermark bits
    → Compute fingerprint hash
    → Query on-chain registry
    → Identify: buyer_id, purchase_timestamp, asset_id
    → Cryptographic proof of leak origin
```

### Economic Impact of Leaks

If data is leaked and redistributed freely:
- Demand for the bonding curve drops (why pay when it's free?)
- Price decreases along the curve (fewer purchases = lower price)
- Creator revenue drops
- **But:** The leaker is identified, and penalties can be enforced (contractual, legal, or protocol-level slashing of future access rights)

---

## Appendix: Parameter Summary

| Parameter | Value | Source |
|-----------|-------|--------|
| Protocol fee rate | 5% | `SettlementConfig.protocol_fee_rate` |
| Fee burn rate | 50% of fee | `SettlementConfig.burn_rate` |
| Bancor connector weight (F) | 0.20 | `SettlementConfig.reserve_ratio` |
| Minimum payment | 0.001 OAS | `SettlementConfig.min_payment` |
| Max slippage | 50% | `SettlementConfig.max_slippage` |
| Creator fee share | 70% | `StakingConfig` (network layer) |
| Validator fee share | 20% | `StakingConfig` (network layer) |
| Network burn share | 10% | `StakingConfig` (network layer) |
| Minimum stake | 1,000 OAS | `StakingConfig.min_stake` |
| Unbonding period | 7 days | `StakingConfig.unbonding_period_seconds` |
| Slash: malicious block | 100% | `StakingConfig.slash_rate_malicious` |
| Slash: double block | 50% | `StakingConfig.slash_rate_double_block` |
| Slash: offline/day | 5% | `StakingConfig.slash_rate_offline_per_day` |
| Initial block reward | 50 OAS | `StakingConfig.initial_block_reward` |
| Halving interval | 525,600 blocks | `StakingConfig.halving_interval_blocks` |
| Initial pool supply | 1,000 tokens | `AssetPool.supply` default |
| Initial pool reserve | 100 OAS | `AssetPool.reserve_balance` default |
| Burn address | `0x000...dEaD` | `SettlementConfig.burn_address` |
| P2P port | 9527 | Network default |
| Quote validity | 60 seconds | `Quote.__post_init__` |

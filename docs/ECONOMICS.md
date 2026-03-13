# Oasyce Economic Model

## Abstract

Human-to-human data-rights settlement failed because coordination costs exceeded data value. Machine-to-machine data-rights settlement removes that friction entirely: cryptographic verification replaces lawyers, bonding curves replace negotiation, and protocol-level watermarking replaces legal enforcement.

Oasyce implements the economic layer for this transition — a settlement protocol where AI agents autonomously register, license, settle, and enforce data rights. This document specifies the complete token economics: supply, emission, fee structure, staking, slashing, deflation mechanics, and game-theoretic security analysis.

**Key insight:** In the bit economy, you don't sell data (bits copy at zero cost). You settle **rights** — access, usage, revenue, attribution. OAS is the settlement currency for these rights.

---

## 1. Token Overview

### OAS — Network Equity, Not a Payment Tool

OAS is not merely a payment token. It represents ownership in the network:

| Role | Description |
|------|-------------|
| Settlement | Required currency for all rights purchases |
| Staking | Validator collateral — skin in the game |
| Governance | Token-weighted voting on protocol parameters |
| Liquidity | Bonding curve backing — guaranteed liquidity |
| Collateral | Data asset ownership proof |

**Core thesis:** More data-rights settled → more OAS demand → more burns → less supply → higher value → more participants. OAS captures value from every transaction in the network.

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

### Validator Slashing

| Violation | Slash Rate | Consequence |
|-----------|-----------|-------------|
| Malicious block | **100%** | Entire stake seized + permanent ban |
| Double block | **50%** | Half stake seized |
| Prolonged offline | **5%/day** | Daily bleed until back online or forced exit |

### Buyer Slashing

Buyers who hold shares must maintain a collateral deposit proportional to their holdings. This creates economic alignment — leaking or misusing data destroys the buyer's own capital.

| Violation | Slash Rate | Consequence |
|-----------|-----------|-------------|
| Watermark-traced data leak | **100%** | Entire collateral destroyed + all shares frozen |
| License violation (commercial use of non-commercial asset) | **50%** | Half collateral destroyed |
| Repeated violations | **100% + ban** | All collateral across all assets destroyed, network ban |

#### Buyer Collateral Requirements

| Parameter | Value |
|-----------|-------|
| Minimum collateral | 10% of shares purchase price |
| Collateral lock period | Duration of share holding |
| Release on sell | Collateral returned when shares are sold back to curve |

#### Why This Works (Game Theory)

```
Buyer holds 1,000 OAS of shares → collateral: 100 OAS minimum
Buyer leaks data → watermark forensics identify buyer
→ 100 OAS collateral burned
→ All shares frozen (1,000 OAS illiquid)
→ Future revenue stream: 0

EV(leak) = value of leaked data − 1,100 OAS − all future dividends
```

For any rational agent, the cost of leaking permanently exceeds the one-time value of the leaked data, because shares generate **recurring** revenue. Destroying a perpetual income stream for a one-time gain is economically irrational.

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
- **Buyer slashing:** 100% collateral burned + all shares frozen (see §6 Buyer Slashing)
- **Limitation:** Current whitespace steganography is vulnerable to automated reformatting (e.g., code formatters, LLM preprocessing). This is a known limitation — see Roadmap for planned improvements.
- Economic deterrent: leaked data reduces demand → creator's bonding curve price drops → leaker's own holdings lose value

**With buyer collateral (new):**

```
Buyer holds 1,000 OAS shares + 100 OAS collateral
Buyer leaks data → watermark traced → slash triggered
Loss: 100 OAS collateral (burned) + 1,000 OAS shares (frozen) + all future dividends
EV(leak) = one-time data value − 1,100 OAS − PV(perpetual dividends)
```

For any asset generating recurring revenue, this is always negative.

### Attack Scenario 5: Malicious Registration (Squatting)

```
Attacker registers data they didn't create
Legitimate creator files Dispute with git/PoPC evidence
Validator committee verifies → dispute upheld
Loss: Attacker's registration revoked + collateral burned + network ban
Attacker's dispute defense cost: 0 (they have no valid evidence)

EV(squat) = 0 (no revenue while disputed) − collateral − ban
```

**Verdict: No rational actor squats.** The dispute mechanism makes it a pure loss.

---

## 9. Shares Model

### What You Buy

When an agent purchases a data asset, it acquires **shares** — ownership stakes in that asset's revenue stream.

```
buy(asset_id, amount) → receive shares → auto-receive dividends from all future purchases
```

Shares are not one-time access tokens. They are **perpetual equity** in a data asset.

### Shares Lifecycle

```
Register asset → Bonding Curve created (supply=0)
  ↓
Buyer deposits OAS → receives shares (price set by curve)
  ↓
Buyer holds shares → earns dividends from subsequent purchases
  ↓
Buyer sells shares → shares returned to curve → OAS returned (minus collateral release delay)
```

### Free Assets (price = 0)

Not all assets need a Bonding Curve. Creators can register assets with `price_model = "free"`:

- Attribution rights recorded on-chain (permanent, irrevocable)
- No Bonding Curve, no shares, no collateral required
- Access is open to all agents
- Useful for: open source code, public datasets, Creative Commons content
- Free assets still generate network activity → OAS burns still occur on related transactions

Free assets serve as **user acquisition** — agents discover value on the network, then encounter paid assets.

### Shares Secondary Market

Shares can be sold back to the Bonding Curve at the current spot price (continuous liquidity). Peer-to-peer share transfers are **not** supported in v1 — this prevents wash trading and simplifies enforcement.

---

## 10. Dispute Resolution

### The Problem

First-to-register gets priority, but malicious actors can register data they didn't create.

### Dispute Flow

```
Challenger stakes 1,000 OAS → submits Dispute(asset_id, evidence)
  ↓
Evidence types accepted:
  - Git commit history with GPG signatures (code assets)
  - PoPC certificate from earlier timestamp (physical capture assets)
  - Prior on-chain registration on another network
  - Timestamped publication proof (academic papers, blog posts)
  ↓
Validator committee reviews (random selection, 5 validators minimum)
  ↓
Outcome A: Dispute upheld
  → Original registration revoked
  → Challenger becomes new registrant
  → Malicious registrant's collateral burned + network ban
  → Challenger's dispute stake returned
  ↓
Outcome B: Dispute rejected
  → Challenger's 1,000 OAS stake burned (anti-spam)
  → Original registration unchanged
```

### Why This Works

- **Cost to challenge:** 1,000 OAS (prevents frivolous disputes)
- **Cost of losing a challenge (registrant):** All collateral + shares + permanent ban
- **Honest registrants:** Low risk — legitimate evidence is hard to fabricate
- **Malicious registrants:** High risk — git/PoPC evidence is cryptographically verifiable

---

## 11. Data Security & Access Control

### The Core Problem

Data, once accessed, can be copied and resold off-chain. No amount of on-chain slashing can recover leaked bits. Economic penalties are necessary but insufficient — the protocol must **minimize exposure of raw data** in the first place.

### Design Principle: Data Doesn't Leave Home

The default posture is that raw data **never leaves the creator's environment**. Buyers purchase rights to *use* data, not to *possess* it. Full data delivery (L3) is the exception, not the rule.

### Access Levels (L0–L3)

Every data asset supports four access tiers. The buyer's access level is determined by their share holdings and collateral:

| Level | Name | What the Buyer Gets | Collateral Multiplier | Data Exposure |
|-------|------|---------------------|-----------------------|---------------|
| **L0** | Query | Statistical answers, aggregations, Q&A results | 1× (base 10%) | **Zero** — raw data never transmitted |
| **L1** | Sample | Partial data, anonymized/redacted snippets | 2× (20% of holdings) | **Minimal** — fragments only |
| **L2** | Compute | Buyer submits model/code → runs on creator's data → receives results only | 3× (30% of holdings) | **Zero** — data stays in TEE/enclave |
| **L3** | Deliver | Full raw data with per-buyer watermark | 5× (50% of holdings) | **Full** — watermark is last defense |

### Access Bond Formula (Final)

The bond formula integrates five risk dimensions into a single calculation:

```
Bond = TWAP(ShareValue, 7d)
     × CollateralMultiplier(Level)
     × RiskFactor
     × (1 - Reputation / 100)
     × ExposureFactor
```

| Variable | Definition | Purpose |
|----------|-----------|---------|
| `TWAP(ShareValue, 7d)` | 7-day time-weighted average position value | Prevents flash collateral attacks |
| `CollateralMultiplier` | L0=1×, L1=2×, L2=3×, L3=5× | Access depth risk |
| `RiskFactor` | Creator-defined dataset sensitivity (0–2) | Data-specific risk scaling |
| `Reputation` | Agent reputation score (0–100) | Behavioral history discount |
| `ExposureFactor` | `max(current_access, cumulative_exposure)` | Prevents dataset reconstruction via fragmented queries |

**Why TWAP:** Using 7-day average instead of spot price prevents an attacker from temporarily inflating their position to reduce bond requirements, then withdrawing immediately after data access.

### Data Risk Levels (Creator-Defined)

Data providers classify their assets by sensitivity:

| Risk Level | RiskFactor | Example |
|------------|-----------|---------|
| Public | 0 | Open datasets, CC-licensed content |
| Low | 0.2 | Aggregated statistics, public APIs |
| Medium | 0.5 | User-generated content, photos |
| High | 1.0 | Financial data, health records |
| Critical | 2.0 | Trade secrets, PII, government data |

### Bond Calculation Examples

**Scenario A:** New agent (R=10), normal data (RF=0.5), L0 query, 1000 OAS position:

```
Bond = 1000 × 0.1 × 1 × 0.5 × (1 - 10/100) × 1.0
     = 1000 × 0.1 × 1 × 0.5 × 0.9 × 1.0
     = 45 OAS
```

**Scenario B:** Trusted agent (R=90), same data, same level:

```
Bond = 1000 × 0.1 × 1 × 0.5 × (1 - 90/100) × 1.0
     = 1000 × 0.1 × 1 × 0.5 × 0.1 × 1.0
     = 5 OAS
```

**Scenario C:** New agent (R=10), critical data (RF=2), L3 delivery:

```
Bond = 1000 × 0.1 × 5 × 2.0 × 0.9 × 1.0
     = 900 OAS
```

**Key insight:** The same data costs a trusted agent 5 OAS and an untrusted agent 900 OAS at L3. This is by design — trust is earned, not bought.

### Agent Reputation System

Each agent maintains an on-chain reputation score:

```
R ∈ [0, 100]    Initial: R = 10    Cap: R_max = 95
```

**Reputation changes:**

| Event | Impact |
|-------|--------|
| Successful transaction completed | +0.05 |
| 7-day period with no disputes | +1 |
| Data provider positive rating | +1 |
| Dispute loss | −10 |
| Confirmed data leak | −100 (instant ban if R ≤ 0) |

**Reputation decay** (prevents oligopoly entrenchment):

```
Every 90 days: R -= 5    (floor: R_min = 50 for active agents)
```

Without decay, early agents accumulate permanent advantages and new entrants can never compete — the network becomes a closed oligopoly. Decay ensures that only **active, honest** agents retain their discount, not just **old** agents.

**Why R_max = 95:** No agent ever gets zero bond. Even the most trusted participant maintains skin in the game.

### Sandbox Mode (Cold Start)

Agents with low reputation enter a zero-barrier restricted environment:

```
Condition: R < 20
```

| Restriction | Value |
|-------------|-------|
| Access level | L0 only |
| Data types | Public only (RiskFactor = 0) |
| Query rate | ≤ 10 queries/day |
| Bond required | 0 |

**Purpose:** Let new agents build reputation through genuine usage before requiring economic commitment. This solves the cold-start problem — agents can discover the network's value before investing.

### Agent Identity & Anti-Sybil

Creating a new agent identity requires a one-time stake:

```
CreateAgent() → lock 100 OAS
```

If the agent is blacklisted:

```
Agent stake → slashed (burned)
```

This makes identity reconstruction expensive. An attacker who is banned loses their agent stake, must acquire another 100 OAS, and starts at R=10 (Sandbox) — unable to access any valuable data.

### Cryptographic Blacklist Registry

The protocol maintains an on-chain blacklist:

```
BlacklistRegistry {
  agent_pubkey: Ed25519PublicKey,
  evidence_hash: SHA256,
  timestamp: BlockHeight,
  reason: DisputeVerdict | AutoSlash
}
```

All nodes **must** reject requests from blacklisted agents. This is enforced at the consensus layer — a validator that processes a blacklisted agent's transaction is itself slashable.

### Exposure Registry (Anti-Fragmentation)

The protocol tracks cumulative data access per agent per dataset:

```
ExposureRegistry {
  agent_pubkey: Ed25519PublicKey,
  dataset_id: AssetID,
  cumulative_exposure: OAS,  // total value of data accessed
  last_updated: BlockHeight
}
```

Bond calculation uses:

```
ExposureFactor = max(current_access_value, cumulative_exposure) / current_access_value
```

**Why this matters:** Without exposure tracking, an attacker can reconstruct a full dataset through 1000 small L0 queries, each with trivial bond. With exposure tracking, the 1000th query carries the same bond as a single L3 delivery — because cumulative exposure equals the full dataset value.

### Liability Window (Bond Release Delay)

Bonds are not released immediately after data access. Each access level has a mandatory holding period:

| Access Level | Liability Window |
|-------------|-----------------|
| L0 Query | 1 day |
| L1 Sample | 3 days |
| L2 Compute | 7 days |
| L3 Deliver | 30 days |

**Why:** Prevents delayed leak attacks — an attacker who accesses data and waits for bond release before leaking is still covered during the liability window. For L3 (full delivery), the 30-day window provides substantial time for watermark-based detection.

### Dynamic Collateral (Margin Call)

Collateral is pegged to **TWAP market price**, not purchase price.

```
On every block:
  For each buyer B holding shares in asset A:
    required_C = TWAP(shares(B,A) × spot_price(A), 7d)
                 × collateral_ratio(access_level)
                 × RiskFactor(A)
                 × (1 - Reputation(B) / 100)
    if collateral(B,A) < required_C:
      emit MarginCall(B, A, deficit)
      if not topped up within grace_period (72 hours):
        downgrade access level to what current collateral supports
        if collateral < L0 requirement:
          freeze shares until collateral restored
```

This eliminates the "buy cheap, abuse expensive" attack vector. As data appreciates, the buyer's skin in the game grows proportionally.

### Enforcement by Level

| Level | Enforcement Mechanism | If Violated |
|-------|----------------------|-------------|
| L0 | Query results are computed server-side; no raw data transmitted | N/A — nothing to leak |
| L1 | Samples are redacted + watermarked fragments | Watermark trace → slash |
| L2 | Code runs inside TEE (zk-PoE attestation); only outputs leave enclave | TEE attestation failure → reject |
| L3 | Full watermark + collateral at 5× | Watermark trace → 100% collateral burn + shares frozen + network ban |

### TEE Integration (L2 Compute)

L2 is the sweet spot — buyers get full computational value without any data exposure:

```
Buyer submits: { model_code, parameters, asset_id }
  ↓
Creator's node loads data into TEE enclave
  ↓
Buyer's model executes inside enclave (data decrypted only in hardware memory)
  ↓
Output + zk-PoE proof returned to buyer
  ↓
Data shredded from enclave memory
  ↓
Settlement: fee split as normal (60/20/15/5)
```

**Current implementation:** `TEEComputeEngine` (mock/simulation). Production requires Intel SGX, AMD SEV, or ARM TrustZone hardware.

### Why Most Buyers Never Need L3

| Use Case | Sufficient Level | Why |
|----------|-----------------|-----|
| AI model training | L2 (Compute) | Send training loop to TEE, receive trained weights |
| Data analysis | L0 (Query) | Ask questions, get statistics |
| Research sampling | L1 (Sample) | Redacted snippets for feasibility studies |
| Data integration/ETL | L2 (Compute) | Transform pipeline runs in enclave |
| Full dataset purchase | L3 (Deliver) | Only when buyer truly needs raw possession |

By making L0-L2 the default path, the protocol minimizes the attack surface. L3 exists for completeness but carries extreme collateral requirements as a natural deterrent.

### Creator-Controlled Access Caps

Creators can set a **maximum access level** per asset:

```python
register_asset(
    file_path="sensitive_medical_data.csv",
    max_access_level=AccessLevel.L2,  # Never allow raw delivery
    ...
)
```

Medical data, trade secrets, or any high-sensitivity asset can be permanently locked to L2 or below. No amount of collateral unlocks L3 if the creator forbids it.

### Game Theory Update: Full Security Model

The protocol enforces three invariants (Protocol Axioms):

1. **Economic Liability:** Data access requires proportional financial responsibility
2. **Persistent Identity:** Agents bear long-term consequences for malicious actions
3. **Traceable Exposure:** All data access is cryptographically attributable

**Revisiting Attack Scenario 4 (Data Leak) with full model:**

```
Buyer bought shares early at 1 OAS each (100 shares = 100 OAS)
Data appreciates → spot price now 100 OAS each
TWAP position value: 100 × 100 = 10,000 OAS
Buyer reputation: R = 80 (established agent)
Data risk: RF = 1.0 (High)
Access: L3 Deliver

Bond = 10,000 × 0.1 × 5 × 1.0 × (1 - 80/100) × 1.0
     = 10,000 × 0.1 × 5 × 1.0 × 0.2
     = 1,000 OAS locked for 30 days (Liability Window)

If buyer leaks:
  Bond slashed: 1,000 OAS burned
  Shares frozen: 10,000 OAS illiquid
  Agent stake slashed: 100 OAS burned
  Reputation: → 0 (instant ban)
  Blacklisted: permanent network exclusion
  Total loss: 11,100 OAS + all future dividends + network identity

EV(leak) = one-time resale − 11,100 OAS − PV(perpetual dividends) − identity value
```

**Attack Scenario 6: Fragmentation Attack (NEW)**

```
Attacker wants to reconstruct dataset worth 10,000 OAS via 1000 small L0 queries

Query 1: exposure = 10, bond based on 10
Query 2: exposure = 20, bond based on 20
...
Query 100: exposure = 1,000, bond based on 1,000
...
Query 1000: exposure = 10,000, bond based on 10,000

By query 1000, bond is identical to a single L3 request.
Fragmentation provides zero economic advantage.
```

**Attack Scenario 7: Collusion Attack (NEW)**

```
10 agents each access 1/10 of dataset, then merge offline

Each agent's exposure: 1,000 OAS
Each agent's bond: ~100 OAS (with reputation discount)
Total collusion bond: ~1,000 OAS

But: each agent receives uniquely watermarked data
Leaked merged file → 10 distinct watermarks detected
→ all 10 agents slashed, staked, blacklisted
Total collusion loss: 10 × (bond + stake + reputation + identity)

Plus: coordinating 10 agents is operationally complex
and any single defector can report the conspiracy for reward.
```

**Attack Scenario 8: Delayed Leak (NEW)**

```
Attacker accesses L3 data, waits for bond release, then leaks

L3 Liability Window = 30 days
Bond remains locked for 30 days after access
If leak detected within 30 days: full slash applies

After 30 days: bond is released, but:
  - Watermark still traceable (permanent)
  - Reputation still slashable (permanent)
  - Agent stake still slashable (permanent)
  - Blacklist still applies (permanent)

Only the bond escapes — everything else is lifetime liability.
```

---

## 12. Watermark Limitations & Roadmap

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

## 13. Governance

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

## 14. Token Utility — Why OAS Must Exist

A protocol token is justified when, and only when, a native unit of account creates value that a stablecoin or existing token cannot.

**OAS justification:**

1. **Staking requires network-native collateral.** Validators must risk something whose value is tied to network health. Staking ETH doesn't punish anti-Oasyce behavior.
2. **Deflation requires a burnable token.** You cannot burn USDC.
3. **Governance requires aligned incentives.** Voters must hold something that loses value if they vote badly.
4. **Bonding curves require a continuous token.** AMM liquidity for data assets needs a native denomination.
5. **Data pricing needs a unit that appreciates with network growth.** If data is priced in USD, early data providers don't benefit from network growth. In OAS, they do.

---

## 15. Competitive Landscape

| Project | Focus | Difference from Oasyce |
|---------|-------|----------------------|
| Ocean Protocol | Data marketplace | Human-operated, centralized metadata, no agent-native integration |
| Filecoin | Storage incentives | Stores data, doesn't price or settle data access |
| Bittensor | AI compute network | Compute incentives, not data ownership/trading |
| Fetch.ai | Agent framework | Agent infrastructure, no data settlement protocol |
| **Oasyce** | **M2M data settlement** | **Agent-native: autonomous ownership, pricing, trading, watermarking in one protocol** |

**Oasyce's unique position:** The only protocol where both data supply (registration) and demand (purchase) are fully automated by AI agents, with economic incentives aligned end-to-end.

---

## 16. Bootstrapping — The Cold Start Problem

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

## 17. Implementation Notes

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
| Buyer collateral ratio | 10% of purchase | `SettlementConfig.buyer_collateral_ratio` |
| Buyer slash (leak) | 100% collateral + freeze shares | `SlashConfig.buyer_leak` |
| Buyer slash (license violation) | 50% collateral | `SlashConfig.buyer_license` |
| Dispute stake | 1,000 OAS | `DisputeConfig.challenge_stake` |
| Dispute committee size | 5 validators | `DisputeConfig.committee_size` |
| L0 collateral multiplier | 1× | `AccessConfig.l0_collateral_multiplier` |
| L1 collateral multiplier | 2× | `AccessConfig.l1_collateral_multiplier` |
| L2 collateral multiplier | 3× | `AccessConfig.l2_collateral_multiplier` |
| L3 collateral multiplier | 5× | `AccessConfig.l3_collateral_multiplier` |
| Margin call grace period | 72 hours | `AccessConfig.margin_call_grace_hours` |
| Collateral rebalance interval | Every block | `AccessConfig.rebalance_frequency` |
| TWAP window | 7 days | `AccessConfig.twap_window_days` |
| Reputation initial | 10 | `ReputationConfig.initial_score` |
| Reputation max | 95 | `ReputationConfig.max_score` |
| Reputation decay | −5 per 90 days | `ReputationConfig.decay_rate` |
| Reputation floor (active) | 50 | `ReputationConfig.active_floor` |
| Sandbox threshold | R < 20 | `ReputationConfig.sandbox_threshold` |
| Sandbox query limit | 10/day | `ReputationConfig.sandbox_daily_limit` |
| Agent creation stake | 100 OAS | `SybilConfig.agent_creation_stake` |
| Liability window L0 | 1 day | `LiabilityConfig.l0_window` |
| Liability window L1 | 3 days | `LiabilityConfig.l1_window` |
| Liability window L2 | 7 days | `LiabilityConfig.l2_window` |
| Liability window L3 | 30 days | `LiabilityConfig.l3_window` |
| Data risk: Public | RF = 0 | `RiskConfig.public` |
| Data risk: Low | RF = 0.2 | `RiskConfig.low` |
| Data risk: Medium | RF = 0.5 | `RiskConfig.medium` |
| Data risk: High | RF = 1.0 | `RiskConfig.high` |
| Data risk: Critical | RF = 2.0 | `RiskConfig.critical` |

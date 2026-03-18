# Oasyce Economic Model

## Token: OAS

OAS is the native protocol token used for all transactions, staking, and settlement in the Oasyce network.

- **Decimal precision**: 1 OAS = 10^8 units (8 decimal places). All internal arithmetic uses integer units to avoid floating-point errors.
- **Multi-asset support**: The protocol also supports `USDC` (6 decimals), `DATA_CREDIT` (0 decimals), and `CAPABILITY_TOKEN` (0 decimals), registered via the asset registry.
- **Supply model**: Block rewards with halving schedule (see Staking Rewards below). No pre-defined hard cap. Block reward issuance converges asymptotically to `halving_interval * base_reward * 2` total OAS (~8,000,000 OAS for mainnet parameters of 4.0 OAS/block with 1M-block halving interval). Effective supply is further reduced by slashing burns.

---

## Bonding Curve Pricing

Asset prices are determined by a demand-scarcity-quality bonding curve. The final price is the product of a base price and five market-driven factors:

```
final_price = max(base_price * demand * scarcity * quality * freshness * rights_type, min_price)
```

### Factors

| Factor | Formula | Range | Purpose |
|--------|---------|-------|---------|
| **Demand** | `1 + alpha * log(1 + query_count)` | [1, inf) | More queries drive up price |
| **Scarcity** | `1 / (1 + similar_count)` | (0, 1] | Rare data is worth more |
| **Quality** | `1 + weight * contribution_score` | [1, 1.5] | Better data earns premium |
| **Freshness** | `0.5^(days / halflife) + 0.5` | (0.5, 1.5] | Decays toward 0.5 over time |
| **Rights type** | Lookup table (see below) | [0.3, 1.0] | Rights origin affects value |

### Default Configuration

```python
demand_alpha          = 0.1    # demand growth coefficient
scarcity_base         = 1.0    # scarcity baseline
freshness_halflife    = 180    # days until freshness halves
min_price             = 0.001  # OAS floor price
contribution_weight   = 0.5    # quality score influence
```

### Rights Type Multipliers

| Rights Type | Multiplier | Description |
|-------------|-----------|-------------|
| `original` | 1.0x | Original work by the registrant |
| `co_creation` | 0.9x | Jointly created work |
| `licensed` | 0.7x | Licensed for resale |
| `collection` | 0.3x | Personal collection / curated |

---

## Pricing Models

The protocol supports three pricing strategies, controlled by the `price_model` parameter:

### Auto (default)

The bonding curve determines the price dynamically. No manual intervention.

```python
result = curve.calculate_price(
    asset_id="asset_001",
    base_price=1.0,
    query_count=50,
    similar_count=3,
    contribution_score=0.8,
    days_since_creation=30,
    rights_type="original",
    price_model="auto",
)
# result["final_price"] computed from all factors
```

### Fixed

The seller sets an exact price. The bonding curve is bypassed entirely.

```python
result = curve.calculate_price(
    asset_id="asset_002",
    base_price=1.0,
    price_model="fixed",
    manual_price=5.0,
)
# result["final_price"] == 5.0
```

### Floor

The bonding curve runs normally, but the price never drops below the seller's floor.

```python
result = curve.calculate_price(
    asset_id="asset_003",
    base_price=1.0,
    query_count=2,
    price_model="floor",
    manual_price=2.0,
)
# result["final_price"] == max(bonding_curve_result, 2.0)
```

---

## Staking Rewards

Validators earn rewards for producing blocks and completing protocol work (data verification, arbitration).

### Block Rewards and Halving

- **Base block reward**: 4.0 OAS per block (= 400,000,000 units)
- **Halving interval**: Every 10,000 blocks (testnet). ~1,000,000 blocks on mainnet.
- **Halving formula**: `reward = base_reward >> halvings` where `halvings = block_height // halving_interval`

| Block Height | Reward per Block |
|-------------|-----------------|
| 0 - 9,999 | 4.0 OAS |
| 10,000 - 19,999 | 2.0 OAS |
| 20,000 - 29,999 | 1.0 OAS |
| 30,000 - 39,999 | 0.5 OAS |

### Reward Distribution

At each epoch boundary, rewards are split between validators and their delegators:

1. **Block rewards**: `blocks_proposed * current_block_reward`
2. **Work rewards**: Sum of `final_value` from settled work tasks in the epoch
3. **Validator income**: Commission on block rewards (in basis points) + 90% of work rewards
4. **Delegator pool**: Remainder of block rewards + 10% of work rewards, distributed proportionally by delegation amount

```
validator_block_income = block_reward_total * commission_rate / 10000
validator_work_income  = work_value * 9000 / 10000   (90%)
delegator_block_pool   = block_reward_total - validator_block_income
delegator_work_pool    = work_value * 1000 / 10000   (10%)
```

Commission rates are in basis points (1000 = 10%), max 5000 (50%).

---

## Slashing Conditions and Penalties

Three conditions trigger slashing. All slash amounts use integer basis-point arithmetic.

### 1. Offline

- **Trigger**: Missed more than 50% of assigned slots in an epoch
- **Penalty**: 1% of total stake (100 bps)
- **Jail**: Yes (standard duration)

### 2. Double Sign

- **Trigger**: Two different blocks signed at the same block height
- **Penalty**: 5% of total stake (500 bps)
- **Jail**: Yes (3x standard duration)

### 3. Low Quality Work

- **Trigger**: Average quality score below 0.3 (3000 bps) over the last 10 tasks
- **Penalty**: 0.5% of total stake (50 bps)
- **Jail**: No (but auto-jailed if stake falls below minimum 10,000 OAS)

### Slash Distribution

Slashed funds are deducted from the validator's self-stake first. Any remaining penalty is distributed proportionally across delegators.

### Unjailing

Jailed validators must wait for the jail duration to expire, then submit an `UNJAIL` operation.

---

## Protocol Fees

- **Capability settlement fee**: 5% of the settled amount (500 bps), deducted at escrow release
  - Provider receives: `amount - protocol_fee`
  - Protocol receives: `amount * 500 / 10000`
- **Transaction fee share**: 20% of all transaction fees go to validators

---

## Share Minting Formula

When buyers purchase access to an asset, they receive shares with diminishing returns to reward early participants:

| Purchase Order | Share Rate |
|---------------|-----------|
| 1st buyer | 100% of payment converted to shares |
| 2nd buyer | 80% |
| 3rd buyer | 60% |
| 4th+ buyer | 40% |

This ensures early supporters of valuable data receive proportionally more ownership, while later buyers still participate in the asset's economics.

---

## Escrow

All capability invocations use escrow-protected settlement:

1. Consumer's funds are locked in escrow before execution
2. Provider executes the capability
3. On success: escrow releases funds to provider (minus 5% protocol fee)
4. On failure: escrow refunds funds to consumer

Source files:
- `oasyce_plugin/services/pricing/__init__.py` -- Bonding curve and pricing models
- `oasyce_plugin/consensus/rewards.py` -- Reward engine and distribution
- `oasyce_plugin/consensus/slashing.py` -- Slashing conditions and penalties
- `oasyce_plugin/consensus/core/types.py` -- OAS units, slash rates, Operation type
- `oasyce_plugin/services/capability_delivery/escrow.py` -- Escrow and protocol fees
- `oasyce_plugin/models.py` -- Rights type multipliers

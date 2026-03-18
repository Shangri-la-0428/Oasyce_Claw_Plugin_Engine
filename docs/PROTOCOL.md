# Oasyce Protocol Specification

## Operation Types

All state changes in the consensus engine are expressed as `Operation` objects -- frozen (immutable) dataclasses that flow through a single entry point: `apply_operation()`.

### Operation Fields

```python
@dataclass(frozen=True)
class Operation:
    op_type: OperationType       # the operation kind (see below)
    validator_id: str            # target validator
    amount: int = 0              # integer units (1 OAS = 10^8 units)
    asset_type: str = "OAS"      # multi-asset identifier
    from_addr: str = ""          # sender address
    to_addr: str = ""            # recipient address
    reason: str = ""             # human-readable reason / metadata
    commission_rate: int = 1000  # basis points (1000 = 10%)
    signature: str = ""          # Ed25519 signature
    chain_id: str = ""           # replay protection
    sender: str = ""             # public key of the sender
    timestamp: int = 0           # unix timestamp (anti-replay)
```

Amounts are **always** in integer units. 1 OAS = 100,000,000 units. No floating-point values are used for monetary amounts.

### Operation Kinds

| `op_type` | Purpose | Key Fields |
|-----------|---------|------------|
| `REGISTER` | Register a new validator | `validator_id`, `amount` (self-stake), `commission_rate` |
| `DELEGATE` | Delegate OAS to a validator | `from_addr`, `validator_id`, `amount` |
| `UNDELEGATE` | Withdraw delegated OAS | `from_addr`, `validator_id`, `amount` |
| `EXIT` | Voluntary validator exit | `validator_id` |
| `UNJAIL` | Request unjail after penalty | `validator_id` |
| `SLASH` | Penalize a validator (system-generated) | `validator_id`, `reason` |
| `REWARD` | Distribute rewards (system-generated) | `validator_id` |
| `TRANSFER` | Transfer assets between addresses | `from_addr`, `to_addr`, `asset_type`, `amount` |
| `REGISTER_ASSET` | Register a new asset type | `asset_type`, `from_addr` (issuer), `reason` (name), `commission_rate` (decimals) |

---

## Validation Rules

Validation is performed by pure functions that read state but never modify it. Each function returns `(True, "")` on success or `(False, error_message)` on failure.

### Global Validation

1. **Signature check**: If `OASYCE_REQUIRE_SIGNATURES=1` is set, all user-initiated operations must include a valid Ed25519 signature and sender public key. System operations (`SLASH`, `REWARD`) skip this check.
2. **Chain ID**: If the operation specifies a `chain_id`, it must match the engine's chain ID (replay protection).

### Per-Operation Rules

**REGISTER**
- `amount` must be >= minimum stake (default 10,000 OAS = 1,000,000,000,000 units)
- `commission_rate` must be in range [0, 5000] basis points
- Validator must not already be registered (unless status is `exited` with no pending unbondings)

**DELEGATE**
- `amount` must be > 0
- Target validator must exist
- Target validator status must be `active` or `jailed`

**UNDELEGATE**
- `amount` must be > 0
- Target validator must exist
- Delegator must have an active delegation to the target validator

**EXIT**
- Validator must exist
- Validator must not already be in `exited` status

**UNJAIL**
- Validator must exist
- Validator must be in `jailed` status

**TRANSFER**
- `amount` must be > 0
- `from_addr` and `to_addr` must be non-empty and different
- `asset_type` must be registered in the asset registry
- Sender must have sufficient balance of the specified asset

**REGISTER_ASSET**
- `asset_type` must be non-empty
- `asset_type` must not already be registered
- `from_addr` (issuer) must be non-empty

---

## State Transition Rules

The `apply_operation()` function in `transition.py` is the **only** function that modifies consensus state. The flow is:

```
1. validate_operation(engine, op, block_height)
   -> (False, error) => return {ok: False, error}
2. Execute operation-specific logic
3. Return result dict with {ok: True, ...}
```

### Execution by Operation Type

| Operation | State Change |
|-----------|-------------|
| `REGISTER` | Creates validator entry with self-stake and commission rate |
| `DELEGATE` | Records delegation from `from_addr` to `validator_id` |
| `UNDELEGATE` | Enters unbonding queue (28-day cooldown) |
| `EXIT` | Marks validator as exited, begins unbonding |
| `UNJAIL` | Restores jailed validator to active status |
| `SLASH` | Deducts from self-stake first, then delegators proportionally; optionally jails |
| `REWARD` | Recorded via epoch boundary bulk distribution |
| `TRANSFER` | Debits `from_addr` and credits `to_addr` for the specified asset |
| `REGISTER_ASSET` | Adds a new asset type to the registry |

All state changes are recorded as append-only events via `append_event()`, making the entire state event-sourced and replayable.

---

## Block Structure and Production

### Block Hashing

Blocks are identified by a deterministic hash:

```python
block_hash = SHA256(chain_id + block_number + parent_hash + operations_root + proposer_id)
```

### Epoch and Slot Scheduling

All timing is derived from block height (no wall-clock dependency for determinism):

```python
epoch = block_height // blocks_per_epoch
slot  = block_height % blocks_per_epoch
```

Key functions:
- `current_epoch(height, blocks_per_epoch)` -- epoch number
- `current_slot(height, blocks_per_epoch)` -- slot within epoch
- `epoch_start_block(epoch, blocks_per_epoch)` -- first block of epoch
- `epoch_end_block(epoch, blocks_per_epoch)` -- last block of epoch
- `is_epoch_boundary(height, blocks_per_epoch)` -- True at the last block of an epoch

### Block Production

1. The `BlockProducer` maintains a mempool (operation queue)
2. At each slot, the stake-weighted leader election determines the proposer
3. The proposer bundles pending operations from the mempool into a block
4. Each operation is validated and applied via `apply_operation()`
5. At epoch boundaries, rewards are distributed and offline slashing is processed

### Epoch Boundary Processing

When `is_epoch_boundary(height)` is True:
1. Distribute block rewards and work rewards to validators and delegators
2. Process offline slashing for validators who missed >50% of assigned slots
3. Process unbonding queue (release matured unbondings)

---

## Fork Choice Rule

The protocol uses **longest chain** with a stake-weighted tiebreaker:

1. The chain with the most blocks is canonical
2. On equal length, the chain whose tip was proposed by the validator with more stake wins
3. **Max reorg depth**: Reorgs beyond a configurable depth limit are rejected
4. **Rollback**: Event-sourced design allows safe rollback by replaying events up to a prior block

---

## Governance Process

On-chain governance allows stake-weighted voting on protocol parameter changes.

### Proposal Lifecycle

1. **Propose**: Any participant deposits OAS and submits a proposal with title, description, and parameter changes
   ```bash
   oasyce governance propose --title "Increase block reward" \
     --description "..." --changes '[...]' --deposit 1000
   ```

2. **Voting period**: Validators and delegators vote `yes`, `no`, or `abstain`
   ```bash
   oasyce governance vote PROPOSAL_ID --option yes
   ```

3. **Tally**: Votes are weighted by stake
   - **Quorum**: 40% of total staked OAS must participate
   - **Pass threshold**: 2/3 of voting power must vote `yes`

4. **Execution**: Approved proposals auto-execute parameter changes

### Governable Parameters

Parameters are registered in the governance registry. Examples include:
- `consensus.blocks_per_epoch` -- Blocks per epoch
- `consensus.min_stake` -- Minimum validator stake
- `consensus.block_reward` -- Base block reward
- `consensus.halving_interval` -- Blocks between reward halvings

Query available parameters:
```bash
oasyce governance params [--module consensus]
```

---

## Slash Rates Reference

Defined as constants in `core/types.py`:

```python
OFFLINE_SLASH_BPS     = 100   # 1%    (100 basis points)
DOUBLE_SIGN_SLASH_BPS = 500   # 5%    (500 basis points)
LOW_QUALITY_SLASH_BPS = 50    # 0.5%  (50 basis points)
MAX_COMMISSION_BPS    = 5000  # 50%   (max validator commission)
```

Slash amounts are computed with integer arithmetic:

```python
def apply_rate_bps(amount: int, rate_bps: int) -> int:
    return (amount * rate_bps) // 10000
```

---

Source files:
- `oasyce_plugin/consensus/core/types.py` -- Operation, OperationType, unit constants, slash rates
- `oasyce_plugin/consensus/core/transition.py` -- `apply_operation()` state transitions
- `oasyce_plugin/consensus/core/validation.py` -- Pure validation functions
- `oasyce_plugin/consensus/execution/engine.py` -- Epoch/slot scheduling, block hashing
- `oasyce_plugin/consensus/execution/producer.py` -- Mempool and block producer
- `oasyce_plugin/consensus/governance/` -- Proposal lifecycle, voting, parameter registry

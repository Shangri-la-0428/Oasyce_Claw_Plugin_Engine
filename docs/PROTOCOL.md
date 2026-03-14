# Oasyce Network Protocol Specification

*Version 1.0 — Data-Rights Clearing Network*

---

## 1. Overview

Oasyce is a decentralized data-rights clearing network. AI agents autonomously register, price, trade, and enforce data rights without human intervention.

The protocol stack, bottom-up:

```
Crypto Layer        Ed25519 signatures, SHA-256, Merkle trees
Storage Layer       SQLite ledger, IPFS-compatible content addressing
Network Layer       TCP mesh, JSON-newline wire protocol (port 9527)
Consensus Layer     Proof-of-Stake, longest chain rule, 60s blocks
Settlement Layer    Bancor bonding curves, unified fee split
Access Layer        L0–L3 tiered access control, TEE gate
Agent Layer         Skills API, CLI, Web GUI
```

Every node is a full participant. No privileged infrastructure.

---

## 2. Node Roles

### Creator

Registers data assets on-chain via PoPC (Proof of Physical Capture). Earns 60% of every access payment for their assets.

- No minimum stake required
- Generates Ed25519 keypair on first run
- Submits `CapturePack` → SHA-256 hash → Ed25519 signature → on-chain certificate

### Validator

Produces blocks, validates transactions, participates in consensus. Earns block rewards + 20% of transaction fees (split by stake weight).

| Parameter | Value |
|-----------|-------|
| Minimum stake | 10,000 OAS |
| Unbonding period | 7 days |
| Block reward | 4 OAS/block (halving every 2 years) |

### Agent

AI agent that discovers, quotes, and purchases data rights. Posts access bonds proportional to data exposure.

- Bond formula: `Bond = E* × M(level) × RF × (1 − R/100)`
- Reputation score (0–100) reduces bond requirements
- Three-tier reputation system: Sandbox → Limited → Full

---

## 3. Wire Protocol

### Transport

- **TCP**, default port **9527**
- Async I/O via `asyncio` (non-blocking)
- Message framing: JSON objects delimited by newline (`\n`)
- Connection timeout: 5–10s per request-response cycle

### Message Format

Every message is a JSON object with a `type` field:

```json
{
  "type": "<message_type>",
  "node_id": "<sender_hex>",
  ...payload
}
```

### Message Types

#### Liveness

| Type | Direction | Payload | Response |
|------|-----------|---------|----------|
| `ping` | → peer | `node_id` | `pong` |
| `pong` | ← peer | `node_id`, `height` | — |

#### Peer Discovery

| Type | Direction | Payload | Response |
|------|-----------|---------|----------|
| `get_peers` | → peer | — | `peers` |
| `peers` | ← peer | `[{node_id, host, port}, ...]` | — |

#### Chain Sync

| Type | Direction | Payload | Response |
|------|-----------|---------|----------|
| `get_height` | → peer | — | `height` |
| `height` | ← peer | `height: int` | — |
| `get_block` | → peer | `block_number: int` | `block` |
| `block` | ← peer | block object | — |
| `get_chain` | → peer | `from_block: int` | `chain` |
| `chain` | ← peer | `[block, ...]` | — |

#### Block Propagation

| Type | Direction | Payload | Response |
|------|-----------|---------|----------|
| `new_block` | → all peers | block object | `ack` |
| `ack` | ← peer | `status` | — |

ACK status values: `accepted`, `rejected`, `ignored`, `fork_detected`, `rate_limited`.

#### Error

| Type | Direction | Payload |
|------|-----------|---------|
| `error` | ← peer | `message: string` |

Returned for unrecognized message types.

### Rate Limiting

| Parameter | Value |
|-----------|-------|
| Window | 10 seconds |
| Max `new_block` per peer per window | 5 |

Peers exceeding the limit receive `rate_limited` ACKs; excess messages are dropped.

---

## 4. Transaction Lifecycle

```
Creator                    Network                     Agent
   │                          │                          │
   │  register_asset          │                          │
   │  (CapturePack + sig)     │                          │
   │ ────────────────────────>│                          │
   │                          │  asset LISTED on-chain   │
   │                          │                          │
   │                          │          quote(asset_id) │
   │                          │<─────────────────────────│
   │                          │  QuoteResult (spot price)│
   │                          │─────────────────────────>│
   │                          │                          │
   │                          │   execute_trade          │
   │                          │   (asset_id, buyer, amt) │
   │                          │<─────────────────────────│
   │                          │                          │
   │                          │  ┌──────────────────┐    │
   │                          │  │ Fee Settlement    │    │
   │                          │  │ 60% → Creator     │    │
   │                          │  │ 20% → Validators  │    │
   │                          │  │ 15% → Burn        │    │
   │                          │  │  5% → Treasury    │    │
   │                          │  └──────────────────┘    │
   │                          │                          │
   │   creator_revenue        │    BuyResult + tokens    │
   │<─────────────────────────│─────────────────────────>│
   │                          │                          │
   │                          │  (if L3: watermark       │
   │                          │   embedded, recorded     │
   │                          │   on-chain)              │
```

**Steps:**

1. Creator submits a `CapturePack` with Ed25519 signature. Verifier checks provenance. Asset transitions to `LISTED`.
2. Agent requests a quote. Bonding curve returns spot price based on current supply and reserve.
3. Agent executes trade with OAS payment. Bonding curve mints tokens. Fee split is applied atomically.
4. Agent receives data access at the requested level (L0–L3). L3 deliveries include per-buyer fingerprint watermark.

---

## 5. Consensus

### Mechanism

Proof-of-Stake with longest-chain rule.

| Parameter | Value |
|-----------|-------|
| Block time | 60 seconds |
| Block reward | 4 OAS (halving every 2 years) |
| Max reorg depth | 10 blocks |
| Future timestamp tolerance | 120 seconds |
| Timestamp ordering | Strictly ascending |

### Block Validity

A block is valid if:

1. Hash matches `SHA-256(header)`
2. `prev_hash` matches the hash of the preceding block
3. Merkle root matches the block's transaction set
4. Timestamp ≥ parent timestamp
5. Timestamp ≤ `now() + 120s`
6. Producer has sufficient stake

### Fork Resolution

1. Node receives `new_block` with same height but different hash → `fork_detected`
2. Node compares chain lengths. Longer valid chain wins.
3. Reorg executes atomically: all blocks from fork point onward are replaced.
4. Reorg depth is capped at `MAX_REORG_DEPTH = 10`. Deeper forks are rejected.

### Slashing

| Violation | Penalty |
|-----------|---------|
| Malicious block (invalid tx) | 100% stake slashed |
| Double block (same height) | 50% stake slashed |
| Prolonged offline | 5% stake/day bleed |

All slashed tokens are **burned**, not redistributed.

---

## 6. Economic Parameters

| Parameter | Value |
|-----------|-------|
| Token | OAS |
| Max supply | 100,000,000 OAS |
| Initial circulating | ~30M |
| Block reward | 4 OAS → 2 → 1 → 0.5 (halving every 2 years) |
| Annual emission (year 1) | 2,102,400 OAS (~5.25%) |
| Connector weight (F) | 0.35 |
| Minimum validator stake | 10,000 OAS |
| Unbonding period | 7 days |

### Fee Split (per transaction)

| Recipient | Share |
|-----------|-------|
| Creator | 60% |
| Validators | 20% (by stake weight) |
| Burn | 15% |
| Treasury | 5% |

### Deflation

At 50,000 OAS daily volume: 7,500 OAS burned/day → 2.74M OAS/year. Year-1 emission is 2.1M. **Net supply shrinks from year one at moderate volume.**

### Genesis Distribution

| Category | Share |
|----------|-------|
| Validator Rewards | 35% |
| Ecosystem Incentives | 25% |
| Treasury | 15% |
| Team (4yr vest, 1yr cliff) | 15% |
| Early Contributors (3yr vest) | 10% |

---

## 7. Security Model

### Three Axioms

**Axiom 1 — Exposure Tracking**

```
E*(agent, dataset) = max(V_current, Σ V_i)
```

Cumulative exposure is always tracked. Bond requirements scale with total historical access.

**Axiom 2 — Access Bond**

```
Bond = E* × M(level) × RF × (1 − R/100)
```

M = access-level multiplier (L0=1×, L1=2×, L2=3×, L3=5×). RF = creator-defined risk factor. R = reputation.

**Axiom 3 — Security Condition**

```
Bond + Stake ≥ DataValue
```

Attacking is always more expensive than the extractable value. When this holds, data theft is economically irrational.

### Defense Layers

| Layer | Mechanism |
|-------|-----------|
| Cryptographic | Ed25519 signatures, SHA-256 hashing, Merkle trees |
| Economic | Staking, slashing, access bonds, burn |
| Forensic | Per-buyer fingerprint watermarking (steganographic) |
| Access control | L0–L3 tiered access, TEE enclave for L2 compute |
| Reputation | Three-tier system (Sandbox/Limited/Full), registration fragmentation detection |
| Rate limiting | Per-peer message throttling, block production caps |

### Attack Economics

| Attack | Cost | Reward | Expected Value |
|--------|------|--------|----------------|
| Malicious block | ≥10,000 OAS | ~12 OAS | **−9,499 OAS** |
| Double block | 50% of stake | ~4 OAS | **−4,996 OAS** |
| 51% stake attack | >50% of all staked OAS | Censorship only | Prohibitive |

---

## 8. Node Lifecycle

### Joining the Network

1. Generate Ed25519 keypair
2. Start TCP listener on port 9527
3. Connect to seed peer(s) via `ping` → receive `pong` with chain height
4. Request peer list via `get_peers`
5. Sync chain from peers via `get_chain` (from block 0 or last known)
6. Validate full chain (hash linkage, Merkle roots, timestamps)
7. (Optional) Stake OAS to become a validator

### Leaving the Network

**Validator exit:**

1. Initiate unbonding (7-day cooldown)
2. Continue validating during unbonding period
3. After 7 days, stake is released; node stops producing blocks
4. Graceful disconnect from peers

**Non-validator exit:**

1. Close TCP connections
2. No unbonding required

---

## 9. Network Assumptions & NAT Traversal

### Current Assumptions (v1)

- Nodes have **public IPs** or are on the **same LAN**.
- Direct TCP connections on port 9527 (no firewalls or NAT between peers).
- Bootstrap nodes are publicly reachable at well-known addresses.
- Persistent node identity (`~/.oasyce/node_id.json`) survives restarts.
- Peer lists are persisted to `~/.oasyce/peers.json` and reloaded on startup.

### Node Identity

Each node generates an Ed25519 keypair on first run and stores it in
`~/.oasyce/node_id.json`. The public key (hex) serves as the stable node ID
across restarts. Use `oasyce node reset-identity` to force-regenerate.

### Peer Discovery

1. On startup, connect to hardcoded **bootstrap nodes** (see `config.py:BOOTSTRAP_NODES`).
2. Ask each bootstrap for its peer list via `get_peers`.
3. Reconnect to previously saved peers from `peers.json`.
4. Peers discovered at runtime are automatically persisted.

### NetworkConfig

```python
@dataclass
class NetworkConfig:
    listen_host: str = "0.0.0.0"       # Bind address (127.0.0.1 for local-only)
    listen_port: int = 9527             # TCP port
    public_host: Optional[str] = None   # Public IP/domain (needed behind NAT)
    public_port: Optional[int] = None   # Public port (if port-forwarded)
    use_stun: bool = False              # Future: STUN/TURN discovery
```

### Future: v1.1 — STUN/TURN + Relay Nodes

- Use STUN to discover public IP and port mapping.
- Fall back to TURN relay nodes when UDP hole-punching fails.
- Relay nodes forward TCP traffic for NATed peers (bandwidth-limited).
- `NetworkConfig.use_stun = True` to enable.

### Future: v2.0 — libp2p + Hole Punching

- Migrate transport to libp2p (noise encryption, multiplexing, mDNS).
- DCUtR (Direct Connection Upgrade through Relay) for hole punching.
- Kademlia DHT for decentralized peer discovery.
- Circuit relay v2 with reservation system.

---

## 10. Upgrade Path

### v1 — Reference Implementation (current)

- Single-machine and LAN P2P with persistent identity and peer lists
- Bootstrap node discovery
- SQLite ledger backend
- Python reference implementation
- 440+ tests, full protocol coverage

### v2 — Production Network

- Multi-machine P2P with NAT traversal (STUN/TURN) and node discovery
- RocksDB or distributed storage backend
- On-chain governance (token-weighted parameter voting)
- Semantic watermarking (robust against formatters and LLMs)
- Agent marketplace: discovery + purchase in one API call

### v3 — L1 Integration

- OAS token contract (ERC-20 or Solana SPL)
- Cross-chain settlement finality
- Formal verification of consensus rules
- Hardware TEE attestation for L2 compute access

---

*Built by Shangrila. Designed for machines. Owned by everyone.*

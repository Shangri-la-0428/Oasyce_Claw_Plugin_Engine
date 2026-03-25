/**
 * Cosmos Chain REST API client.
 *
 * Wraps the Oasyce Cosmos chain's REST endpoints (LCD / gRPC-gateway).
 * Default base URL: http://localhost:1317 (override via VITE_COSMOS_REST_URL).
 */

const COSMOS_REST_URL =
  (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_COSMOS_REST_URL as string) ||
  'http://localhost:1317';

const REQUEST_TIMEOUT_MS = 10_000;

// ── Types ───────────────────────────────────────────────────

export interface NodeInfo {
  default_node_info: {
    protocol_version: { p2p: string; block: string; app: string };
    default_node_id: string;
    listen_addr: string;
    network: string; // chain_id
    version: string;
    moniker: string;
  };
  application_version: {
    name: string;
    app_name: string;
    version: string;
    cosmos_sdk_version: string;
  };
}

export interface Block {
  block_id: { hash: string };
  block: {
    header: {
      chain_id: string;
      height: string;
      time: string;
      proposer_address: string;
    };
  };
}

export interface Coin {
  denom: string;
  amount: string;
}

export interface Balance {
  balances: Coin[];
  pagination: { next_key: string | null; total: string };
}

export interface Validator {
  operator_address: string;
  consensus_pubkey: { '@type': string; key: string };
  jailed: boolean;
  status: string;
  tokens: string;
  delegator_shares: string;
  description: {
    moniker: string;
    identity: string;
    website: string;
    details: string;
  };
  commission: {
    commission_rates: { rate: string; max_rate: string; max_change_rate: string };
  };
}

export interface ValidatorList {
  validators: Validator[];
  pagination: { next_key: string | null; total: string };
}

export interface Proposal {
  id: string;
  status: string;
  title?: string;
  summary?: string;
  submit_time: string;
  voting_end_time: string;
}

export interface ProposalList {
  proposals: Proposal[];
  pagination: { next_key: string | null; total: string };
}

// Oasyce custom module types

export interface Escrow {
  escrow_id: string;
  creator: string;
  provider: string;
  amount: Coin;
  status: string;
}

export interface BondingCurveState {
  asset_id: string;
  current_price: Coin;
  total_supply: string;
}

export interface Capability {
  capability_id: string;
  name: string;
  description: string;
  provider: string;
  endpoint_url: string;
  price_per_call: Coin;
  tags: string[];
}

export interface Invocation {
  invocation_id: string;
  capability_id: string;
  consumer: string;
  status: 'PENDING' | 'ACTIVE' | 'COMPLETED' | 'FAILED' | 'DISPUTED' | string;
  completed_height?: number;
  escrow_id?: string;
  output_hash?: string;
  usage_report?: string;
}

export interface ReputationScore {
  address: string;
  score: number;
  total_feedback: number;
}

export interface DataAsset {
  asset_id: string;
  name: string;
  description: string;
  owner: string;
  content_hash: string;
  rights_type: number;
  tags: string[];
}

export interface Dispute {
  dispute_id: string;
  asset_id: string;
  reason: string;
  status: string;
}

// ── Internal helpers ────────────────────────────────────────

async function chainGet<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, COSMOS_REST_URL);
  if (params) {
    for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(url.toString(), { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(`Chain REST ${res.status}: ${text.slice(0, 200)}`);
    }
    return (await res.json()) as T;
  } catch (e) {
    clearTimeout(timer);
    throw e;
  }
}

// ── Standard Cosmos SDK queries ─────────────────────────────

export function getNodeInfo(): Promise<NodeInfo> {
  return chainGet<NodeInfo>('/cosmos/base/tendermint/v1beta1/node_info');
}

export function getLatestBlock(): Promise<Block> {
  return chainGet<Block>('/cosmos/base/tendermint/v1beta1/blocks/latest');
}

export function getBalance(address: string, denom?: string): Promise<Balance> {
  if (denom) {
    return chainGet<Balance>(`/cosmos/bank/v1beta1/balances/${address}/by_denom`, { denom });
  }
  return chainGet<Balance>(`/cosmos/bank/v1beta1/balances/${address}`);
}

export function getValidators(status?: string): Promise<ValidatorList> {
  const params: Record<string, string> = {};
  if (status) params['status'] = status;
  return chainGet<ValidatorList>('/cosmos/staking/v1beta1/validators', params);
}

export function getProposals(status?: string): Promise<ProposalList> {
  const params: Record<string, string> = {};
  if (status) params['proposal_status'] = status;
  return chainGet<ProposalList>('/cosmos/gov/v1/proposals', params);
}

// ── Settlement module ───────────────────────────────────────

export function getEscrow(escrowId: string): Promise<{ escrow: Escrow }> {
  return chainGet(`/oasyce/settlement/v1/escrow/${escrowId}`);
}

export function getEscrowsByCreator(creator: string): Promise<{ escrows: Escrow[] }> {
  return chainGet(`/oasyce/settlement/v1/escrows/${creator}`);
}

export function getBondingCurvePrice(assetId: string): Promise<BondingCurveState> {
  return chainGet(`/oasyce/settlement/v1/bonding_curve/${assetId}`);
}

// ── Capability module ───────────────────────────────────────

export function getCapability(capabilityId: string): Promise<{ capability: Capability }> {
  return chainGet(`/oasyce/capability/v1/capability/${capabilityId}`);
}

export function listCapabilities(opts?: { tag?: string; provider?: string }): Promise<{ capabilities: Capability[] }> {
  if (opts?.provider) {
    return chainGet(`/oasyce/capability/v1/capabilities/provider/${opts.provider}`);
  }
  const params: Record<string, string> = {};
  if (opts?.tag) params['tag'] = opts.tag;
  return chainGet('/oasyce/capability/v1/capabilities', params);
}

export function getEarnings(provider: string): Promise<{ total_earned: Coin }> {
  return chainGet(`/oasyce/capability/v1/earnings/${provider}`);
}

// ── Reputation module ───────────────────────────────────────

export function getReputation(address: string): Promise<ReputationScore> {
  return chainGet(`/oasyce/reputation/v1/reputation/${address}`);
}

export function getLeaderboard(limit = 100): Promise<{ entries: ReputationScore[] }> {
  return chainGet('/oasyce/reputation/v1/leaderboard', { limit: String(limit) });
}

// ── DataRights module ───────────────────────────────────────

export function getDataAsset(assetId: string): Promise<{ asset: DataAsset }> {
  return chainGet(`/oasyce/datarights/v1/asset/${assetId}`);
}

export function listDataAssets(opts?: { tag?: string; owner?: string }): Promise<{ assets: DataAsset[] }> {
  const params: Record<string, string> = {};
  if (opts?.tag) params['tag'] = opts.tag;
  if (opts?.owner) params['owner'] = opts.owner;
  return chainGet('/oasyce/datarights/v1/assets', params);
}

export function getShareholders(assetId: string): Promise<{ shareholders: { address: string; shares: string }[] }> {
  return chainGet(`/oasyce/datarights/v1/asset/${assetId}/shareholders`);
}

// ── Invocation lifecycle ─────────────────────────────────────
// TODO: These are state-changing operations (Msg, not Query). Cosmos SDK gRPC-gateway
// only exposes GET endpoints for Query service RPCs. These need to submit TXs via
// /cosmos/tx/v1beta1/txs (broadcast_tx) with signed MsgCompleteInvocation etc.
// Left as placeholders — not currently called by the UI.

export function completeInvocation(invocationId: string, outputHash: string): Promise<any> {
  return chainGet(`/oasyce/capability/v1/invocation/${invocationId}/complete`, { output_hash: outputHash });
}

export function failInvocation(invocationId: string): Promise<any> {
  return chainGet(`/oasyce/capability/v1/invocation/${invocationId}/fail`);
}

export function claimInvocation(invocationId: string): Promise<any> {
  return chainGet(`/oasyce/capability/v1/invocation/${invocationId}/claim`);
}

export function disputeInvocation(invocationId: string, reason: string): Promise<any> {
  return chainGet(`/oasyce/capability/v1/invocation/${invocationId}/dispute`, { reason });
}

// ── Access level query ──────────────────────────────────────

export function getAccessLevel(assetId: string, address: string): Promise<any> {
  return chainGet(`/oasyce/datarights/v1/asset/${assetId}/access/${address}`);
}

// ── Connectivity check ──────────────────────────────────────

/**
 * Returns true if the Cosmos chain REST API is reachable.
 * Uses a short timeout so the UI doesn't hang.
 */
export async function isChainAvailable(): Promise<boolean> {
  try {
    await chainGet('/cosmos/base/tendermint/v1beta1/node_info');
    return true;
  } catch {
    return false;
  }
}

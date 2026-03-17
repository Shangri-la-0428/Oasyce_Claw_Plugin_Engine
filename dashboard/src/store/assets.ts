/**
 * Assets Store
 */
import { signal } from '@preact/signals';
import { get, del } from '../api/client';

export interface Asset {
  asset_id: string;
  asset_type?: 'data' | 'capability';
  owner?: string;
  provider?: string;
  name?: string;
  description?: string;
  version?: string;
  tags?: string[];
  created_at?: number;
  spot_price?: number;
  input_schema?: any;
  output_schema?: any;
  hash_status?: 'ok' | 'changed' | 'missing';
  rights_type?: string;
  co_creators?: { address: string; share: number }[];
  disputed?: boolean;
  dispute_reason?: string;
  dispute_time?: number;
  arbitrator_candidates?: { capability_id: string; name: string; provider: string; score: number }[];
  dispute_status?: 'open' | 'resolved' | 'dismissed';
  dispute_resolution?: { remedy: string; details?: any; resolved_at?: number };
  delisted?: boolean;
}

export const assets = signal<Asset[]>([]);

export async function loadAssets() {
  const result = await get<Asset[]>('/assets');
  if (result.success && result.data) assets.value = result.data;
}

export async function deleteAsset(id: string) {
  return await del(`/asset/${id}`);
}

/**
 * Assets Store
 */
import { signal } from '@preact/signals';
import { get, del } from '../api/client';

export interface Asset {
  asset_id: string;
  owner: string;
  tags?: string[];
  created_at?: number;
  spot_price?: number;
}

export const assets = signal<Asset[]>([]);

export async function loadAssets() {
  const result = await get<Asset[]>('/assets');
  if (result.success && result.data) assets.value = result.data;
}

export async function deleteAsset(id: string) {
  return await del(`/asset/${id}`);
}

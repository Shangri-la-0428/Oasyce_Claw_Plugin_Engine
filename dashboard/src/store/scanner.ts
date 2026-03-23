/**
 * Scanner + Inbox Store
 *
 * Mutations update the local signal optimistically and fire-and-forget
 * the HTTP call.  Only loadInbox() does a full round-trip refresh.
 */
import { signal } from '@preact/signals';
import { get, post } from '../api/client';

export interface InboxItem {
  item_id: string;
  file_path: string;
  suggested_name: string;
  suggested_tags: string[];
  suggested_description: string;
  sensitivity: 'safe' | 'moderate' | 'sensitive';
  confidence: number;
  status: 'pending' | 'approved' | 'rejected';
}

export interface TrustConfig {
  trust_level: number;
  auto_threshold: number;
}

export const inboxItems = signal<InboxItem[]>([]);
export const trustConfig = signal<TrustConfig>({ trust_level: 0, auto_threshold: 0.8 });
export const scanning = signal(false);
export const lastScan = signal<{ scanned: number; added: number } | null>(null);

export async function loadInbox() {
  const res = await get<any>('/inbox');
  if (res.success && res.data) {
    inboxItems.value = Array.isArray(res.data) ? res.data : (res.data.items || []);
  }
}

export async function loadTrust() {
  const res = await get<TrustConfig>('/inbox/trust');
  if (res.success && res.data) trustConfig.value = res.data;
}

export async function scanDirectory(path: string) {
  scanning.value = true;
  const res = await post<any>('/scan', { path });
  scanning.value = false;
  if (res.success && res.data) {
    lastScan.value = {
      scanned: res.data.scanned ?? 0,
      added: res.data.added ?? res.data.added_to_inbox ?? 0,
    };
    await loadInbox();
  }
  return res;
}

/** Approve one item — optimistic update, no refetch */
export async function approveItem(id: string) {
  inboxItems.value = inboxItems.value.map(i => i.item_id === id ? { ...i, status: 'approved' as const } : i);
  return post(`/inbox/${id}/approve`);
}

/** Reject one item — optimistic update, no refetch */
export async function rejectItem(id: string) {
  inboxItems.value = inboxItems.value.map(i => i.item_id === id ? { ...i, status: 'rejected' as const } : i);
  return post(`/inbox/${id}/reject`);
}

/** Approve all pending — single signal write + parallel HTTP */
export async function approveAll() {
  const pending = inboxItems.value.filter(i => i.status === 'pending');
  inboxItems.value = inboxItems.value.map(i => i.status === 'pending' ? { ...i, status: 'approved' as const } : i);
  await Promise.all(pending.map(i => post(`/inbox/${i.item_id}/approve`)));
}

/** Reject all pending — single signal write + parallel HTTP */
export async function rejectAll() {
  const pending = inboxItems.value.filter(i => i.status === 'pending');
  inboxItems.value = inboxItems.value.map(i => i.status === 'pending' ? { ...i, status: 'rejected' as const } : i);
  await Promise.all(pending.map(i => post(`/inbox/${i.item_id}/reject`)));
}

export async function editItem(id: string, changes: Partial<Pick<InboxItem, 'suggested_name' | 'suggested_tags' | 'suggested_description'>>) {
  inboxItems.value = inboxItems.value.map(i => i.item_id === id ? { ...i, ...changes } : i);
  return post(`/inbox/${id}/edit`, changes);
}

export async function setTrust(level?: number, threshold?: number) {
  const body: any = {};
  if (level !== undefined) body.trust_level = level;
  if (threshold !== undefined) body.auto_threshold = threshold;
  const res = await post<TrustConfig>('/inbox/trust', body);
  if (res.success && res.data) trustConfig.value = res.data;
  return res;
}

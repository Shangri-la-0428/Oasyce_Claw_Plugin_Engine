/**
 * Scanner + Inbox Store
 *
 * Mutations apply optimistic updates and roll back on HTTP failure.
 * Bulk operations (approveAll/rejectAll) use allSettled and do a full
 * refresh via loadInbox() when any individual call fails.
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

/** Approve one item — optimistic update with rollback on failure */
export async function approveItem(id: string) {
  const prev = inboxItems.value;
  inboxItems.value = prev.map(i => i.item_id === id ? { ...i, status: 'approved' as const } : i);
  const res = await post(`/inbox/${id}/approve`);
  if (!res.success) inboxItems.value = prev;
  return res;
}

/** Reject one item — optimistic update with rollback on failure */
export async function rejectItem(id: string) {
  const prev = inboxItems.value;
  inboxItems.value = prev.map(i => i.item_id === id ? { ...i, status: 'rejected' as const } : i);
  const res = await post(`/inbox/${id}/reject`);
  if (!res.success) inboxItems.value = prev;
  return res;
}

/** Approve all pending — optimistic update, allSettled + full refresh on partial failure */
export async function approveAll() {
  const prev = inboxItems.value;
  const pending = prev.filter(i => i.status === 'pending');
  inboxItems.value = prev.map(i => i.status === 'pending' ? { ...i, status: 'approved' as const } : i);
  const results = await Promise.allSettled(pending.map(i => post(`/inbox/${i.item_id}/approve`)));
  const anyFailed = results.some(r => r.status === 'rejected' || (r.status === 'fulfilled' && !r.value.success));
  if (anyFailed) {
    await loadInbox();
  }
}

/** Reject all pending — optimistic update, allSettled + full refresh on partial failure */
export async function rejectAll() {
  const prev = inboxItems.value;
  const pending = prev.filter(i => i.status === 'pending');
  inboxItems.value = prev.map(i => i.status === 'pending' ? { ...i, status: 'rejected' as const } : i);
  const results = await Promise.allSettled(pending.map(i => post(`/inbox/${i.item_id}/reject`)));
  const anyFailed = results.some(r => r.status === 'rejected' || (r.status === 'fulfilled' && !r.value.success));
  if (anyFailed) {
    await loadInbox();
  }
}

export async function editItem(id: string, changes: Partial<Pick<InboxItem, 'suggested_name' | 'suggested_tags' | 'suggested_description'>>) {
  const prev = inboxItems.value;
  inboxItems.value = prev.map(i => i.item_id === id ? { ...i, ...changes } : i);
  const res = await post(`/inbox/${id}/edit`, changes);
  if (!res.success) inboxItems.value = prev;
  return res;
}

export async function setTrust(level?: number, threshold?: number) {
  const body: any = {};
  if (level !== undefined) body.trust_level = level;
  if (threshold !== undefined) body.auto_threshold = threshold;
  const res = await post<TrustConfig>('/inbox/trust', body);
  if (res.success && res.data) trustConfig.value = res.data;
  return res;
}

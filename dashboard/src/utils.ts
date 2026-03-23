/** Shared helper functions used across pages */

/** Generic mask: head…tail (used for IDs, hashes, addresses) */
export function mask(v: string | undefined | null, head = 8, tail = 0): string {
  if (!v) return '--';
  const min = tail > 0 ? head + tail + 1 : head;
  if (v.length <= min) return v;
  return tail > 0 ? `${v.slice(0, head)}…${v.slice(-tail)}` : v.slice(0, head) + '••••';
}

/** Shorthand masks for common patterns */
export const maskIdShort = (id: string | undefined | null) => mask(id, 8);
export const maskIdLong  = (id: string | undefined | null) => mask(id, 16);
export const maskOwner   = (v: string | undefined | null) => mask(v, 6);

/** 格式化价格：>= 1 显示 2 位，< 1 显示 4 位；handles NaN/Infinity */
export function fmtPrice(p: number | undefined | null): string {
  if (p == null || !Number.isFinite(p)) return '--';
  if (p === 0) return '0.00';
  return p >= 1 ? p.toFixed(2) : p.toFixed(4);
}

/** Safe number formatting: returns '--' for null/undefined/NaN */
export function safeNum(n: number | undefined | null, decimals = 2): string {
  if (n == null || !Number.isFinite(n)) return '--';
  return n.toFixed(decimals);
}

/** Safe percentage formatting from 0-1 fraction */
export function safePct(n: number | undefined | null, decimals = 1): string {
  if (n == null || !Number.isFinite(n)) return '--';
  return (n * 100).toFixed(decimals) + '%';
}

/** Format unix timestamp (seconds) → locale string */
export function fmtDate(ts: number | undefined | null, style: 'date' | 'datetime' = 'datetime'): string {
  if (ts == null || !Number.isFinite(ts)) return '—';
  const d = new Date(ts * 1000);
  return style === 'date' ? d.toLocaleDateString() : d.toLocaleString();
}

/** 递归读取 DataTransferItem 里的文件夹，返回所有 File (带深度限制) */
export async function readEntryFiles(entry: any, maxDepth = 5): Promise<File[]> {
  if (maxDepth <= 0) return [];
  if (entry.isFile) {
    return new Promise(resolve => {
      entry.file((f: File) => resolve([f]), () => resolve([]));
    });
  }
  if (entry.isDirectory) {
    const reader = entry.createReader();
    // readEntries may not return all entries at once; loop until empty
    let allEntries: any[] = [];
    let batch: any[];
    do {
      batch = await new Promise<any[]>(resolve => {
        reader.readEntries((e: any[]) => resolve(e), () => resolve([]));
      });
      allEntries = allEntries.concat(batch);
    } while (batch.length > 0);
    const nested = await Promise.all(allEntries.map(e => readEntryFiles(e, maxDepth - 1)));
    return nested.flat();
  }
  return [];
}

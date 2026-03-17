/** Shared helper functions used across pages */

/** 遮罩 asset_id：列表里前 8 位 + •••• */
export function maskIdShort(id: string) {
  if (!id || id.length <= 8) return id;
  return id.slice(0, 8) + '••••';
}

/** 遮罩 asset_id：详情里前 16 位 + •••• */
export function maskIdLong(id: string) {
  if (!id || id.length <= 16) return id;
  return id.slice(0, 16) + '••••';
}

/** 遮罩 owner：如果是长哈希，截断为前6位 */
export function maskOwner(owner: string) {
  if (!owner || owner.length <= 12) return owner;
  return owner.slice(0, 6) + '••••';
}

/** 格式化价格：>= 1 显示 2 位，< 1 显示 4 位 */
export function fmtPrice(p: number | undefined | null): string {
  if (p == null) return '--';
  return p >= 1 ? p.toFixed(2) : p.toFixed(4);
}

/** 递归读取 DataTransferItem 里的文件夹，返回所有 File */
export async function readEntryFiles(entry: any): Promise<File[]> {
  if (entry.isFile) {
    return new Promise(resolve => {
      entry.file((f: File) => resolve([f]), () => resolve([]));
    });
  }
  if (entry.isDirectory) {
    const reader = entry.createReader();
    const entries: any[] = await new Promise(resolve => {
      reader.readEntries((e: any[]) => resolve(e), () => resolve([]));
    });
    const nested = await Promise.all(entries.map(readEntryFiles));
    return nested.flat();
  }
  return [];
}

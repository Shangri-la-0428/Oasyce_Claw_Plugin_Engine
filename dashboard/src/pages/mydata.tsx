/**
 * MyData — 我的数据
 */
import { useEffect, useRef, useState } from 'preact/hooks';
import { post, postFile, postBundle } from '../api/client';
import { assets, loadAssets, deleteAsset } from '../store/assets';
// scanDirectory/lastScan/scanning available from '../store/scanner' if needed
import { showToast, i18n } from '../store/ui';
import { readEntryFiles, maskIdShort, maskIdLong, maskOwner, fmtPrice } from '../utils';
import './mydata.css';

const RIGHTS_COLORS: Record<string, string> = {
  original: 'var(--green, #4ade80)',
  co_creation: 'var(--blue, #60a5fa)',
  licensed: 'var(--yellow, #facc15)',
  collection: 'var(--fg-2, #888)',
};

type SortBy = 'time' | 'value';

export default function MyData() {
  const [q, setQ] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [sortBy, setSortBy] = useState<SortBy>('time');
  const [tagFilter, setTagFilter] = useState<string | null>(null);

  /* ── Registration state ── */
  const [regFile, setRegFile] = useState('');
  const [regFileObj, setRegFileObj] = useState<File | null>(null);
  const [regDesc, setRegDesc] = useState('');
  const [regLoading, setRegLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [reregistering, setReregistering] = useState<string | null>(null);
  const [disputeTarget, setDisputeTarget] = useState<string | null>(null);
  const [disputeReason, setDisputeReason] = useState('');
  const [disputing, setDisputing] = useState(false);
  const [droppedFolder, setDroppedFolder] = useState<string | null>(null);
  const [folderFiles, setFolderFiles] = useState<File[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const _ = i18n.value;

  useEffect(() => { loadAssets(); }, []);

  const hasSelection = !!(regFile || droppedFolder);

  const clearSelection = () => {
    setRegFile(''); setRegFileObj(null); setRegDesc('');
    setDroppedFolder(null); setFolderFiles([]);
  };

  const onFile = (name: string, fileObj?: File) => {
    setRegFile(name);
    setRegFileObj(fileObj ?? null);
    setDroppedFolder(null); setFolderFiles([]);
    if (!regDesc) {
      const dot = name.lastIndexOf('.');
      setRegDesc(dot > 0 ? name.slice(0, dot) : name);
    }
  };

  const onDrop = async (e: DragEvent) => {
    e.preventDefault(); setDragging(false);
    const items = e.dataTransfer?.items;
    if (items && items.length > 0) {
      const entry = (items[0] as any).webkitGetAsEntry?.();
      if (entry?.isDirectory) {
        const name = entry.name || 'folder';
        const files = await readEntryFiles(entry);
        setDroppedFolder(name); setFolderFiles(files);
        setRegFile(''); setRegFileObj(null);
        if (!regDesc) setRegDesc(name);
        return;
      }
    }
    setDroppedFolder(null); setFolderFiles([]);
    const f = e.dataTransfer?.files[0];
    if (f) onFile(f.name, f);
  };

  const submitBundle = async () => {
    if (folderFiles.length === 0) return;
    setRegLoading(true);
    const tags = regDesc.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean).join(',');
    const res = await postBundle(folderFiles, { name: droppedFolder || 'bundle', tags });
    if (res.success) {
      showToast(_['protected'] + ' ✓', 'success');
      loadAssets(); clearSelection();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setRegLoading(false);
  };

  const submitReg = async () => {
    if (!regFile.trim()) return;
    setRegLoading(true);
    const tags = regDesc.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean);
    const res = regFileObj
      ? await postFile('/register', regFileObj, { tags: tags.join(',') })
      : await post('/register', { file_path: regFile.trim(), tags });
    if (res.success) {
      showToast(_['protected'] + ' ✓', 'success');
      loadAssets(); clearSelection();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setRegLoading(false);
  };

  const allTags = [...new Set(assets.value.flatMap(a => a.tags ?? []))];

  const filtered = assets.value.filter(a => {
    if (tagFilter && !(a.tags ?? []).includes(tagFilter)) return false;
    if (!q) return true;
    const s = q.toLowerCase();
    return a.asset_id.toLowerCase().includes(s)
      || a.owner?.toLowerCase().includes(s)
      || a.tags?.some(tag => tag.toLowerCase().includes(s));
  });

  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === 'value') return (b.spot_price ?? 0) - (a.spot_price ?? 0);
    return (b.created_at ?? 0) - (a.created_at ?? 0);
  });

  const list = sorted.slice(0, pageSize);
  const hasMore = sorted.length > pageSize;

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text);
    showToast(_['copied'], 'success');
  };

  const onDelete = async (id: string) => {
    setDeleting(true);
    const res = await deleteAsset(id);
    if (res.success) { showToast(_['removed'], 'success'); loadAssets(); }
    else showToast(res.error || _['error-generic'], 'error');
    setConfirmDel(null); setDeleting(false);
  };

  const onReRegister = async (id: string) => {
    setReregistering(id);
    const res = await post<{ ok?: boolean; version?: number; message?: string }>('/re-register', { asset_id: id });
    if (res.success && res.data?.ok) {
      showToast(`v${res.data.version} ✓`, 'success');
      loadAssets();
    } else {
      showToast(res.data?.message || res.error || _['error-generic'], 'error');
    }
    setReregistering(null);
  };

  const onDispute = async (assetId: string) => {
    if (!disputeReason.trim()) return;
    setDisputing(true);
    const res = await post<{ ok?: boolean }>('/dispute', { asset_id: assetId, reason: disputeReason.trim() });
    if (res.success && res.data?.ok) {
      showToast(_['dispute-success'] || 'Dispute submitted', 'success');
      loadAssets();
      setDisputeTarget(null); setDisputeReason('');
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setDisputing(false);
  };

  return (
    <div class="page">
      {/* Label 标题 + 计数 */}
      <div class="row between mb-24">
        <h1 class="label" style="margin:0">{_['mydata']}</h1>
        <span class="mono" style="color:var(--fg-2)">{assets.value.length}</span>
      </div>

      {/* ── 注册区 ── */}
      <div
        class={`dropzone ${dragging ? 'dropzone-active' : ''} ${hasSelection ? 'dropzone-done' : ''} mb-24`}
        onDrop={onDrop}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onClick={() => { if (!hasSelection) fileRef.current?.click(); }}
      >
        {hasSelection ? (
          <div class="dropzone-selected">
            <span class="dropzone-selected-name">
              {droppedFolder ? `${droppedFolder}/` : regFile}
            </span>
            {droppedFolder && (
              <span class="caption">{folderFiles.length} {_['files'] || '个文件'}</span>
            )}
            <button class="dropzone-clear" onClick={e => { e.stopPropagation(); clearSelection(); }} aria-label="clear">×</button>
          </div>
        ) : (
          <>
            <div class="dropzone-icon">↑</div>
            <div class="dropzone-text">
              <strong>{_['drop-browse'] || '选择文件'}</strong>
            </div>
            <div class="caption" style="margin-top:6px">
              {_['drop-folder-hint'] || '支持拖入文件夹'}
            </div>
          </>
        )}
        <input ref={fileRef} type="file" style="display:none" onChange={e => {
          const f = (e.target as HTMLInputElement).files?.[0];
          if (f) onFile(f.name, f);
        }} />
      </div>

      {/* 文件夹 → 打包注册 */}
      {droppedFolder && (
        <div class="mydata-reg-fields mb-24">
          <div>
            <label class="label">{_['describe']}</label>
            <input class="input" value={regDesc} onInput={e => setRegDesc((e.target as HTMLInputElement).value)} placeholder={droppedFolder} />
          </div>
          <button class="btn btn-primary btn-full" onClick={submitBundle} disabled={regLoading}>
            {regLoading ? _['protecting'] : _['protect']}
          </button>
        </div>
      )}

      {/* 单文件注册 */}
      {regFile && (
        <div class="mydata-reg-fields mb-24">
          <div>
            <label class="label">{_['describe']}</label>
            <input class="input" value={regDesc} onInput={e => setRegDesc((e.target as HTMLInputElement).value)} placeholder={_['describe-hint']} />
          </div>
          <button class="btn btn-primary btn-full" onClick={submitReg} disabled={regLoading}>
            {regLoading ? _['protecting'] : _['protect']}
          </button>
        </div>
      )}

      {/* 搜索框 + 排序按钮 */}
      {assets.value.length > 0 && (
        <div class="row gap-8 mb-24">
          <div class="search-box-wrap">
            <input class="search-box" value={q} onInput={e => setQ((e.target as HTMLInputElement).value)} placeholder={_['search']} />
          </div>
          <button class={`btn btn-sm ${sortBy === 'time' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('time')}>{_['sort-time']}</button>
          <button class={`btn btn-sm ${sortBy === 'value' ? 'btn-active' : 'btn-ghost'}`} onClick={() => setSortBy('value')}>{_['sort-value']}</button>
        </div>
      )}

      {/* Tag 过滤 */}
      {allTags.length > 0 && (
        <div class="tag-chips mb-24">
          <button class={`tag-chip ${tagFilter === null ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(null)}>{_['all']}</button>
          {allTags.map(tag => (
            <button key={tag} class={`tag-chip ${tagFilter === tag ? 'tag-chip-active' : ''}`} onClick={() => setTagFilter(tagFilter === tag ? null : tag)}>{tag}</button>
          ))}
        </div>
      )}

      {/* 数据列表 */}
      {list.length === 0 ? (
        <div class="center p-0-64">
          <div style="font-size:14px;color:var(--fg-2);margin-bottom:8px">{q ? _['inbox-no-match'] : _['no-data']}</div>
          {!q && <div class="caption">{_['first-data']}</div>}
        </div>
      ) : (
        <div class="data-list">
          {list.map(a => {
            const isOpen = expanded === a.asset_id;
            const isDel = confirmDel === a.asset_id;
            return (
              <div key={a.asset_id} class="data-item">
                <button class="data-row" onClick={() => setExpanded(isOpen ? null : a.asset_id)}>
                  <div class="grow">
                    <div class="data-name">
                      {a.tags?.length ? a.tags.join(' · ') : maskIdShort(a.asset_id)}
                      {a.rights_type && (
                        <span class="badge" style={`color:${RIGHTS_COLORS[a.rights_type] || 'var(--fg-2)'};border-color:${RIGHTS_COLORS[a.rights_type] || 'var(--fg-2)'};margin-left:8px`}>
                          {_[`rights-${a.rights_type}`] || a.rights_type}
                        </span>
                      )}
                      {a.disputed && (
                        <span class="badge" style="color:var(--red, #f87171);border-color:var(--red, #f87171);margin-left:8px">{_['disputed']}</span>
                      )}
                      {a.hash_status === 'changed' && <>
                        <span class="badge" style="color:var(--yellow);border-color:var(--yellow);margin-left:8px">{_['hash-changed']}</span>
                        <button class="btn btn-sm btn-ghost" style="margin-left:6px;font-size:12px" disabled={reregistering === a.asset_id} onClick={e => { e.stopPropagation(); onReRegister(a.asset_id); }}>
                          {reregistering === a.asset_id ? '…' : _['re-register']}
                        </button>
                      </>}
                      {a.hash_status === 'missing' && <span class="badge" style="color:var(--red);border-color:var(--red);margin-left:8px">{_['file-missing']}</span>}
                    </div>
                    <div class="data-meta">
                      <span class="mono data-id-inline">{maskIdShort(a.asset_id)}</span>
                      {a.owner && <span class="data-owner-inline">{maskOwner(a.owner)}</span>}
                    </div>
                  </div>
                  <span class="mono data-price-prominent">{fmtPrice(a.spot_price)} <span style="font-weight:400;font-size:11px">OAS</span></span>
                  <span class={`data-chevron ${isOpen ? 'open' : ''}`}>›</span>
                </button>

                {/* 展开详情缩进 16px */}
                {isOpen && (
                  <div class="data-detail">
                    <div class="kv">
                      <span class="kv-key">{_['id']}</span>
                      <span class="kv-val">
                        <span class="masked">
                          <span>{maskIdLong(a.asset_id)}</span>
                          <button class="btn-copy" onClick={() => copyText(a.asset_id)}>{_['copy']}</button>
                        </span>
                      </span>
                    </div>
                    <div class="kv">
                      <span class="kv-key">{_['owner']}</span>
                      <span class="kv-val">
                        <span class="masked">
                          <span>{maskOwner(a.owner || '')}</span>
                          <button class="btn-copy" onClick={() => copyText(a.owner || '')}>{_['copy']}</button>
                        </span>
                      </span>
                    </div>
                    <div class="kv"><span class="kv-key">{_['value']}</span><span class="kv-val">{fmtPrice(a.spot_price)}</span></div>
                    {a.rights_type && (
                      <div class="kv"><span class="kv-key">{_['rights-type']}</span><span class="kv-val">{_[`rights-${a.rights_type}`] || a.rights_type}</span></div>
                    )}
                    {a.co_creators && a.co_creators.length > 0 && (
                      <div style="margin-top:8px">
                        <span class="kv-key">{_['co-creators']}</span>
                        <div style="margin-top:4px">
                          {a.co_creators.map((c: any, i: number) => (
                            <div key={i} class="caption" style="margin-left:12px">
                              {c.address || '—'} <span class="mono">{c.share}%</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Delisted badge */}
                    {a.delisted && (
                      <div class="caption" style="margin-top:8px;padding:6px 10px;border:1px solid var(--red);color:var(--red);border-radius:var(--r-m);display:inline-block">
                        {_['delisted']}
                      </div>
                    )}

                    {/* Dispute section */}
                    {a.disputed && (
                      <div style="margin-top:8px;padding:8px;border:1px solid var(--red, #f87171);border-radius:8px">
                        <div class="caption" style="color:var(--red, #f87171);margin-bottom:4px">
                          {_['dispute-status']}:{' '}
                          {a.dispute_status === 'resolved'
                            ? _['dispute-resolved']
                            : a.dispute_status === 'dismissed'
                              ? _['dispute-dismissed']
                              : _['dispute-pending']}
                        </div>
                        {a.dispute_reason && (
                          <div class="caption" style="margin-bottom:4px">{_['dispute-reason']}: {a.dispute_reason}</div>
                        )}
                        {a.dispute_resolution && (
                          <div class="caption" style="margin-bottom:4px;color:var(--green, #4ade80)">
                            {_[`remedy-${a.dispute_resolution.remedy}`] || a.dispute_resolution.remedy}
                          </div>
                        )}
                        {a.dispute_status === 'open' && a.arbitrator_candidates && a.arbitrator_candidates.length > 0 && (
                          <div style="margin-top:6px">
                            <div class="caption" style="font-weight:600;margin-bottom:4px">{_['arbitrators']}</div>
                            {a.arbitrator_candidates.map((arb: any, i: number) => (
                              <div key={i} class="caption" style="margin-left:8px;margin-bottom:2px">
                                {arb.name || arb.capability_id.slice(0, 8) + '…'}
                                <span class="mono" style="margin-left:8px;color:var(--fg-2)">{_['arbitrator-score']}: {(arb.score * 100).toFixed(0)}%</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {a.dispute_status === 'open' && (!a.arbitrator_candidates || a.arbitrator_candidates.length === 0) && (
                          <div class="caption" style="color:var(--fg-2)">{_['no-arbitrators']}</div>
                        )}
                      </div>
                    )}
                    {!a.disputed && disputeTarget !== a.asset_id && (
                      <button class="btn btn-ghost btn-sm" style="margin-top:8px" onClick={e => { e.stopPropagation(); setDisputeTarget(a.asset_id); setDisputeReason(''); }}>
                        {_['dispute']}
                      </button>
                    )}
                    {disputeTarget === a.asset_id && (
                      <div style="margin-top:8px">
                        <input class="input" style="margin-bottom:6px" value={disputeReason}
                          onInput={e => setDisputeReason((e.target as HTMLInputElement).value)}
                          placeholder={_['dispute-reason-hint']} />
                        <div class="caption" style="margin-bottom:6px;color:var(--fg-2)">{_['arbitrator-auto']}</div>
                        <div class="row gap-8">
                          <button class="btn btn-ghost btn-sm" onClick={() => { setDisputeTarget(null); setDisputeReason(''); }}>{_['cancel']}</button>
                          <button class="btn btn-danger btn-sm" onClick={() => onDispute(a.asset_id)} disabled={disputing || !disputeReason.trim()}>
                            {disputing ? (_['dispute-submitting']) : (_['dispute-confirm'])}
                          </button>
                        </div>
                      </div>
                    )}

                    {!isDel ? (
                      <button class="btn btn-danger" style="margin-top:12px" onClick={e => { e.stopPropagation(); setConfirmDel(a.asset_id); }}>{_['delete']}</button>
                    ) : (
                      <div class="data-del-confirm">
                        <span class="caption">{_['delete-confirm']}</span>
                        <div class="row gap-8">
                          <button class="btn btn-ghost btn-sm" onClick={() => setConfirmDel(null)}>{_['cancel']}</button>
                          <button class="btn btn-danger btn-sm" onClick={() => onDelete(a.asset_id)} disabled={deleting}>
                            {deleting ? '…' : _['confirm-remove']}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 加载更多 / 没有更多 */}
      {list.length > 0 && (
        <div class="center p-0-24">
          {hasMore ? (
            <button class="btn btn-ghost btn-sm" onClick={() => setPageSize(s => s + 20)}>{_['load-more']}</button>
          ) : (
            <span class="caption">{_['no-more']}</span>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * MyData — 我的数据
 */
import { useEffect, useState, useRef } from 'preact/hooks';
import { post } from '../api/client';
import { assets, loadAssets, deleteAsset } from '../store/assets';
import { showToast, i18n } from '../store/ui';
import './mydata.css';

/** 遮罩 asset_id：列表里前 8 位 + •••• */
function maskIdShort(id: string) {
  if (!id || id.length <= 8) return id;
  return id.slice(0, 8) + '••••';
}

/** 遮罩 asset_id：详情里前 16 位 + •••• */
function maskIdLong(id: string) {
  if (!id || id.length <= 16) return id;
  return id.slice(0, 16) + '••••';
}

/** 遮罩 owner：如果是长哈希，截断为前6位 */
function maskOwner(owner: string) {
  if (!owner || owner.length <= 12) return owner;
  return owner.slice(0, 6) + '••••';
}

/** 格式化价格：>= 1 显示 2 位，< 1 显示 4 位 */
function fmtPrice(p: number | undefined | null): string {
  if (p == null) return '--';
  return p >= 1 ? p.toFixed(2) : p.toFixed(4);
}

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
  const [regDesc, setRegDesc] = useState('');
  const [regLoading, setRegLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [reregistering, setReregistering] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const _ = i18n.value;

  useEffect(() => { loadAssets(); }, []);

  const onFile = (name: string) => {
    setRegFile(name);
    const ext = name.split('.').pop()?.toLowerCase() || '';
    const hint: Record<string, string> = {
      csv: 'dataset', json: 'structured data', jpg: 'image', png: 'image',
      pdf: 'document', mp4: 'video', mp3: 'audio', txt: 'text',
    };
    if (hint[ext] && !regDesc) setRegDesc(hint[ext]);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer?.files[0];
    if (f) onFile(f.name);
  };

  const submitReg = async () => {
    if (!regFile.trim()) return;
    setRegLoading(true);
    const tags = regDesc.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean);
    const res = await post('/register', { file_path: regFile.trim(), tags });
    if (res.success) {
      showToast(_['protected'] + ' ✓', 'success');
      loadAssets();
      setRegFile(''); setRegDesc('');
    } else {
      showToast(res.error || 'Failed', 'error');
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
    if (res.success) { showToast(_['protected'] ? '已移除' : 'Removed', 'success'); loadAssets(); }
    else showToast(res.error || 'Failed', 'error');
    setConfirmDel(null); setDeleting(false);
  };

  const onReRegister = async (id: string) => {
    setReregistering(id);
    const res = await post<{ ok?: boolean; version?: number; message?: string }>('/re-register', { asset_id: id });
    if (res.success && res.data?.ok) {
      showToast(`v${res.data.version} ✓`, 'success');
      loadAssets();
    } else {
      showToast(res.data?.message || res.error || 'Failed', 'error');
    }
    setReregistering(null);
  };

  return (
    <div class="page">
      {/* Label 标题 + 计数 */}
      <div class="row between mb-24">
        <h1 class="heading" style="margin:0">{_['mydata']}</h1>
        <span class="mono" style="color:var(--fg-2)">{assets.value.length}</span>
      </div>

      {/* ── 注册区：拖入文件 ── */}
      <div
        class={`dropzone ${dragging ? 'dropzone-active' : ''} ${regFile ? 'dropzone-done' : ''} mb-24`}
        onDrop={onDrop}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onClick={() => fileRef.current?.click()}
      >
        {regFile ? (
          <div class="dropzone-text"><strong>{regFile}</strong></div>
        ) : (
          <>
            <div class="dropzone-icon">↑</div>
            <div class="dropzone-text">
              {_['drop-hint']}
              {' '}
              <strong>{_['drop-browse']}</strong>
            </div>
          </>
        )}
        <input ref={fileRef} type="file" style="display:none" onChange={e => {
          const f = (e.target as HTMLInputElement).files?.[0];
          if (f) onFile(f.name);
        }} />
      </div>

      {/* 选文件后出现描述 + 提交 */}
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
        <div class="center" style="padding:64px 0">
          <div style="font-size:14px;color:var(--fg-2);margin-bottom:8px">{q ? 'No match' : _['no-data']}</div>
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
                      {a.hash_status === 'changed' && <>
                        <span class="badge" style="color:var(--yellow);border-color:var(--yellow);margin-left:8px">已变更</span>
                        <button class="btn btn-sm btn-ghost" style="margin-left:6px;font-size:12px" disabled={reregistering === a.asset_id} onClick={e => { e.stopPropagation(); onReRegister(a.asset_id); }}>
                          {reregistering === a.asset_id ? '…' : '重新注册'}
                        </button>
                      </>}
                      {a.hash_status === 'missing' && <span class="badge" style="color:var(--red);border-color:var(--red);margin-left:8px">文件丢失</span>}
                    </div>
                    <div class="data-meta">
                      <span class="mono data-id-inline">{maskIdShort(a.asset_id)}</span>
                      {a.owner && <span class="data-owner-inline">{maskOwner(a.owner)}</span>}
                    </div>
                  </div>
                  <span class="mono data-price-prominent">{fmtPrice(a.spot_price)}</span>
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
        <div class="center" style="padding:24px 0">
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

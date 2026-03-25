/**
 * MyData — 我的数据
 */
import { useEffect, useState, useMemo, useRef } from 'preact/hooks';
import { get, post } from '../api/client';
import { assets, loadAssets, deleteAsset } from '../store/assets';
import { showToast, i18n, walletAddress } from '../store/ui';
import { maskIdShort, maskIdLong, maskOwner, fmtPrice, safePct, fmtDate, copyText } from '../utils';
import { EmptyState } from '../components/empty-state';
import RegisterForm from '../components/register-form';
import './mydata.css';

type SortBy = 'time' | 'value';
type MyDataTab = 'data' | 'caps';

interface DeliveryEndpoint {
  capability_id: string;
  name: string;
  endpoint: string;
  price: number;
  total_calls: number;
  success_rate: number;
  avg_latency_ms: number;
  tags?: string[];
}

interface EarningsData {
  total_earned: number;
  total_calls: number;
  recent?: { capability_id: string; amount: number; timestamp: number }[];
}

interface OwnerEarningsData {
  total_earned: number;
  transactions: { asset_id: string; buyer: string; amount: number; timestamp: number }[];
}

export default function MyData() {
  const busyRef = useRef(false);
  const [q, setQ] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [pageSize, setPageSize] = useState(20);
  const [sortBy, setSortBy] = useState<SortBy>('time');
  const [tagFilter, setTagFilter] = useState<string | null>(null);

  const [reregistering, setReregistering] = useState<string | null>(null);
  const [disputeTarget, setDisputeTarget] = useState<string | null>(null);
  const [disputeReason, setDisputeReason] = useState('');
  const [disputing, setDisputing] = useState(false);

  // Feature 1: Inline metadata edit (tags)
  const [editTagsTarget, setEditTagsTarget] = useState<string | null>(null);
  const [editTagsValue, setEditTagsValue] = useState('');
  const [savingTags, setSavingTags] = useState(false);

  // Feature 3: Asset lifecycle management
  const [lifecycleAction, setLifecycleAction] = useState<string | null>(null);
  const [shutdownConfirm, setShutdownConfirm] = useState<string | null>(null);

  // Feature 4: Version history
  const [versionsTarget, setVersionsTarget] = useState<string | null>(null);
  const [versions, setVersions] = useState<{ version: number; timestamp: number }[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);

  // Tab state
  const [activeTab, setActiveTab] = useState<MyDataTab>('data');

  // My Capabilities state
  const [myCaps, setMyCaps] = useState<DeliveryEndpoint[]>([]);
  const [myCapsLoading, setMyCapsLoading] = useState(false);
  const [earnings, setEarnings] = useState<EarningsData | null>(null);

  // Data asset owner earnings
  const [ownerEarnings, setOwnerEarnings] = useState<OwnerEarningsData | null>(null);

  const _ = i18n.value;

  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const loadMyCaps = async () => {
    setMyCapsLoading(true);
    const res = await get<DeliveryEndpoint[]>(`/delivery/endpoints?provider=${walletAddress()}`);
    if (!mountedRef.current) return;
    if (res.success && Array.isArray(res.data)) setMyCaps(res.data);
    const eres = await get<EarningsData>(`/delivery/earnings?provider=${walletAddress()}`);
    if (!mountedRef.current) return;
    if (eres.success && eres.data && typeof eres.data === 'object') setEarnings(eres.data);
    setMyCapsLoading(false);
  };

  const loadOwnerEarnings = async () => {
    const addr = walletAddress();
    if (addr === 'anonymous') return;
    const res = await get<OwnerEarningsData>(`/earnings?owner=${encodeURIComponent(addr)}`);
    if (!mountedRef.current) return;
    if (res.success && res.data && typeof res.data === 'object') setOwnerEarnings(res.data);
  };

  useEffect(() => { loadAssets(); loadMyCaps(); loadOwnerEarnings(); }, []);

  const handleRegisterSuccess = () => {
    loadAssets();
  };

  const allTags = useMemo(() => [...new Set(assets.value.flatMap(a => a.tags ?? []))], [assets.value]);

  const filtered = useMemo(() => assets.value.filter(a => {
    if (tagFilter && !(a.tags ?? []).includes(tagFilter)) return false;
    if (!q) return true;
    const s = q.toLowerCase();
    return a.asset_id.toLowerCase().includes(s)
      || a.owner?.toLowerCase().includes(s)
      || a.tags?.some(tag => tag.toLowerCase().includes(s));
  }), [assets.value, tagFilter, q]);

  const sorted = useMemo(() => [...filtered].sort((a, b) => {
    if (sortBy === 'value') return (b.spot_price ?? 0) - (a.spot_price ?? 0);
    const ta = typeof a.created_at === 'string' ? new Date(a.created_at).getTime() : (a.created_at ?? 0);
    const tb = typeof b.created_at === 'string' ? new Date(b.created_at).getTime() : (b.created_at ?? 0);
    return tb - ta;
  }), [filtered, sortBy]);

  const list = useMemo(() => sorted.slice(0, pageSize), [sorted, pageSize]);
  const hasMore = sorted.length > pageSize;

  const onDelete = async (id: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setDeleting(true);
    const res = await deleteAsset(id);
    if (res.success) { showToast(_['removed'], 'success'); loadAssets(); }
    else showToast(res.error || _['error-generic'], 'error');
    setConfirmDel(null); setDeleting(false);
    busyRef.current = false;
  };

  const onReRegister = async (id: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setReregistering(id);
    const res = await post<{ ok?: boolean; version?: number; message?: string }>('/re-register', { asset_id: id });
    if (res.success && res.data?.ok) {
      showToast(`v${res.data.version}`, 'success');
      loadAssets();
    } else {
      showToast(res.data?.message || res.error || _['error-generic'], 'error');
    }
    setReregistering(null);
    busyRef.current = false;
  };

  const onDispute = async (assetId: string) => {
    if (busyRef.current) return;
    if (!disputeReason.trim()) return;
    busyRef.current = true;
    setDisputing(true);
    const res = await post<{ ok?: boolean }>('/dispute', { asset_id: assetId, reason: disputeReason.trim() });
    if (res.success && res.data?.ok) {
      showToast(_['dispute-success'], 'success');
      loadAssets();
      setDisputeTarget(null); setDisputeReason('');
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setDisputing(false);
    busyRef.current = false;
  };

  // Feature 1: Save tags
  const onSaveTags = async (assetId: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setSavingTags(true);
    const newTags = editTagsValue.split(',').map(t => t.trim()).filter(Boolean);
    const res = await post<{ ok?: boolean }>('/asset/update', { asset_id: assetId, tags: newTags });
    if (res.success) {
      showToast(_['metadata-updated'], 'success');
      loadAssets();
      setEditTagsTarget(null);
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setSavingTags(false);
    busyRef.current = false;
  };

  // Feature 3: Lifecycle actions
  const onShutdown = async (assetId: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLifecycleAction(assetId);
    const res = await post<{ ok?: boolean }>('/asset/shutdown', { asset_id: assetId, owner: walletAddress() });
    if (res.success) {
      showToast(_['asset-shutdown-success'], 'success');
      loadAssets();
      setShutdownConfirm(null);
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLifecycleAction(null);
    busyRef.current = false;
  };

  const onTerminate = async (assetId: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLifecycleAction(assetId);
    const res = await post<{ ok?: boolean }>('/asset/terminate', { asset_id: assetId, sender: walletAddress() });
    if (res.success) {
      showToast(_['asset-terminate-success'], 'success');
      loadAssets();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLifecycleAction(null);
    busyRef.current = false;
  };

  const onClaim = async (assetId: string) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setLifecycleAction(assetId);
    const res = await post<{ ok?: boolean }>('/asset/claim', { asset_id: assetId, holder: walletAddress() });
    if (res.success) {
      showToast(_['asset-claim-success'], 'success');
      loadAssets();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLifecycleAction(null);
    busyRef.current = false;
  };

  // Feature 4: Load version history
  const onLoadVersions = async (assetId: string) => {
    if (versionsTarget === assetId) {
      setVersionsTarget(null);
      return;
    }
    setVersionsTarget(assetId);
    setVersionsLoading(true);
    const res = await get<{ version: number; timestamp: number }[]>(`/asset/versions?asset_id=${encodeURIComponent(assetId)}`);
    if (!mountedRef.current) return;
    if (res.success && Array.isArray(res.data)) {
      setVersions(res.data);
    } else {
      setVersions([]);
    }
    setVersionsLoading(false);
  };

  return (
    <div class="page">
      {/* Label 标题 + 计数 */}
      <div class="row between mb-24">
        <h1 class="label m-0">{_['mydata']}</h1>
        <span class="mono fg-muted">{activeTab === 'data' ? assets.value.length : myCaps.length}</span>
      </div>

      {/* Tab switcher */}
      <div class="tabs mb-24" role="tablist" aria-label={_['mydata']}>
        <button role="tab" aria-selected={activeTab === 'data'} class={`tab ${activeTab === 'data' ? 'active' : ''}`} onClick={() => setActiveTab('data')}>
          {_['my-data-tab']}
        </button>
        <button role="tab" aria-selected={activeTab === 'caps'} class={`tab ${activeTab === 'caps' ? 'active' : ''}`} onClick={() => setActiveTab('caps')}>
          {_['my-caps']}
          {myCaps.length > 0 && <span class="tab-count">{myCaps.length}</span>}
        </button>
      </div>

      {activeTab === 'data' && <>
      {/* ── 注册区 ── */}
      <div class="mb-24">
        <RegisterForm mode="data" onSuccess={handleRegisterSuccess} compact />
      </div>

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
        <EmptyState icon={q ? '∅' : '[ ]'} title={q ? _['inbox-no-match'] : _['no-data']} hint={q ? undefined : _['first-data']} />
      ) : (
        <div class="item-list">
          {list.map(a => {
            const isOpen = expanded === a.asset_id;
            const isDel = confirmDel === a.asset_id;
            return (
              <div key={a.asset_id} class={`data-item${a.disputed ? ' is-disputed' : ''}${a.status === 'shutdown' || a.status === 'terminated' ? ' is-lifecycle' : ''}${a.delisted ? ' is-delisted' : ''}`}>
                <button type="button" class="item-row" aria-expanded={isOpen} onClick={() => setExpanded(isOpen ? null : a.asset_id)}>
                  <div class="grow">
                    <div class="item-name">
                      {a.tags?.length ? a.tags.join(' · ') : maskIdShort(a.asset_id)}
                      {a.disputed && (
                        <span class="badge badge-red ml-8">{_['disputed']}</span>
                      )}
                      {a.hash_status === 'changed' && <>
                        <span class="badge badge-yellow ml-8">{_['hash-changed']}</span>
                        <button class="btn btn-sm btn-ghost btn-reregister" disabled={reregistering === a.asset_id} onClick={e => { e.stopPropagation(); onReRegister(a.asset_id); }}>
                          {reregistering === a.asset_id ? '…' : _['re-register']}
                        </button>
                      </>}
                      {a.hash_status === 'missing' && <span class="badge badge-red ml-8">{_['file-missing']}</span>}
                      {a.status === 'shutdown' && <span class="badge badge-yellow ml-8">{_['asset-status-shutdown']}</span>}
                      {a.status === 'terminated' && <span class="badge badge-red ml-8">{_['asset-status-terminated']}</span>}
                      {a.delisted && <span class="badge badge-red ml-8">{_['delisted']}</span>}
                    </div>
                    <div class="item-meta">
                      <span class="mono item-id-inline">{maskIdShort(a.asset_id)}</span>
                      {a.owner && <span class="item-owner-inline">{maskOwner(a.owner)}</span>}
                      {a.version && <span class="mono fg-muted">v{a.version}</span>}
                    </div>
                  </div>
                  <span class="mono item-price">{fmtPrice(a.spot_price)} <span class="oas-unit">OAS</span></span>
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
                    {a.price_model === 'fixed' && (
                      <div class="kv"><span class="kv-key">{_['price-model']}</span><span class="kv-val">{_['price-model-fixed']}: <span class="mono">{a.price ?? '—'} OAS</span></span></div>
                    )}
                    {a.price_model === 'floor' && (
                      <div class="kv"><span class="kv-key">{_['price-model']}</span><span class="kv-val">{_['price-model-floor']}: <span class="mono">{a.price ?? '—'} OAS</span></span></div>
                    )}
                    {a.co_creators && a.co_creators.length > 0 && (
                      <div class="cocreator-list">
                        <span class="kv-key">{_['co-creators']}</span>
                        <ul class="cocreator-list-inner">
                          {a.co_creators.map((c: any) => (
                            <li key={c.address || `share-${c.share}`} class="caption cocreator-item">
                              {c.address || '—'} <span class="mono">{c.share}%</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Status */}
                    {a.status && a.status !== 'active' && (
                      <div class="kv">
                        <span class="kv-key">{_['asset-status-label']}</span>
                        <span class="kv-val">
                          <span class={`badge ${a.status === 'terminated' ? 'badge-red' : 'badge-yellow'}`}>
                            {a.status === 'terminated' ? _['asset-status-terminated'] : _['asset-status-shutdown']}
                          </span>
                        </span>
                      </div>
                    )}
                    {a.delisted && (
                      <div class="kv">
                        <span class="kv-key">{_['asset-status-label']}</span>
                        <span class="kv-val"><span class="badge badge-red">{_['delisted']}</span></span>
                      </div>
                    )}

                    {/* ── Actions ── */}
                    <div class="detail-actions">
                      {/* Edit tags */}
                      {editTagsTarget === a.asset_id ? (
                        <div class="detail-inline-form">
                          <input class="input mb-8" value={editTagsValue}
                            onInput={e => setEditTagsValue((e.target as HTMLInputElement).value)}
                            placeholder={_['edit-tags']} />
                          <div class="row gap-8">
                            <button class="btn btn-ghost btn-sm" onClick={() => setEditTagsTarget(null)}>{_['cancel']}</button>
                            <button class="btn btn-sm" onClick={() => onSaveTags(a.asset_id)} disabled={savingTags}>
                              {savingTags ? '…' : _['save']}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button class="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); setEditTagsTarget(a.asset_id); setEditTagsValue((a.tags ?? []).join(', ')); }}>
                          {_['metadata-tags']}
                        </button>
                      )}

                      <button class="btn btn-ghost btn-sm" disabled={reregistering === a.asset_id} onClick={e => { e.stopPropagation(); onReRegister(a.asset_id); }}>
                        {reregistering === a.asset_id ? '…' : _['re-register-manual']}
                      </button>

                      <button class="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); onLoadVersions(a.asset_id); }}>
                        {_['version-history']}
                      </button>

                      {!a.disputed && disputeTarget !== a.asset_id && (
                        <button class="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); setDisputeTarget(a.asset_id); setDisputeReason(''); }}>
                          {_['dispute']}
                        </button>
                      )}
                    </div>

                    {/* Version history (expandable) */}
                    {versionsTarget === a.asset_id && (
                      <div class="mt-8">
                        {versionsLoading ? (
                          <div class="skeleton skeleton-sm mb-8" role="status" aria-busy="true" aria-label={_['loading']} />
                        ) : versions.length === 0 ? (
                          <div class="caption fg-muted">{_['no-versions']}</div>
                        ) : (
                          versions.map((v) => (
                            <div key={v.version} class="kv">
                              <span class="kv-key mono">v{v.version}</span>
                              <span class="kv-val mono">{fmtDate(v.timestamp)}</span>
                            </div>
                          ))
                        )}
                      </div>
                    )}

                    {/* Dispute detail / form */}
                    {a.disputed && (
                      <div class="detail-inline-form block-dispute">
                        <div class="caption color-red mb-4">
                          {_['dispute-status']}:{' '}
                          {a.dispute_status === 'resolved'
                            ? _['dispute-resolved']
                            : a.dispute_status === 'dismissed'
                              ? _['dispute-dismissed']
                              : _['dispute-pending']}
                        </div>
                        {a.dispute_reason && (
                          <div class="caption mb-4">{_['dispute-reason']}: {a.dispute_reason}</div>
                        )}
                        {a.dispute_resolution && (
                          <div class="caption mb-4 color-green">
                            {_[`remedy-${a.dispute_resolution.remedy}`] || a.dispute_resolution.remedy}
                          </div>
                        )}
                        {a.dispute_status === 'open' && a.arbitrator_candidates && a.arbitrator_candidates.length > 0 && (
                          <div class="dispute-arb-wrap">
                            <div class="caption fw-600 mb-4">{_['arbitrators']}</div>
                            {a.arbitrator_candidates.map((arb: any) => (
                              <div key={arb.capability_id || arb.name} class="caption dispute-arb-item">
                                {arb.name || (arb.capability_id ? arb.capability_id.slice(0, 8) + '...' : '--')}
                                <span class="mono ml-8 fg-muted">{_['arbitrator-score']}: {safePct(arb.score, 0)}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {a.dispute_status === 'open' && (!a.arbitrator_candidates || a.arbitrator_candidates.length === 0) && (
                          <div class="caption fg-muted">{_['no-arbitrators']}</div>
                        )}
                      </div>
                    )}
                    {disputeTarget === a.asset_id && (
                      <div class="detail-inline-form">
                        <input class="input mb-8" value={disputeReason}
                          onInput={e => setDisputeReason((e.target as HTMLInputElement).value)}
                          placeholder={_['dispute-reason-hint']} />
                        <div class="caption mb-8 fg-muted">{_['arbitrator-auto']}</div>
                        <div class="row gap-8">
                          <button class="btn btn-ghost btn-sm" onClick={() => { setDisputeTarget(null); setDisputeReason(''); }}>{_['cancel']}</button>
                          <button class="btn btn-danger btn-sm" onClick={() => onDispute(a.asset_id)} disabled={disputing || !disputeReason.trim()}>
                            {disputing ? (_['dispute-submitting']) : (_['dispute-confirm'])}
                          </button>
                        </div>
                      </div>
                    )}

                    {/* ── Lifecycle ── */}
                    <div class="detail-lifecycle">
                      <div class="caption fg-muted mb-8">{_['asset-lifecycle']}: {_['asset-lifecycle-hint']}</div>
                      <div class="row gap-8">
                        {(a.status === 'active' || !a.status) && (
                          shutdownConfirm === a.asset_id ? (
                            <div class="data-del-confirm">
                              <span class="caption">{_['asset-shutdown-confirm']}</span>
                              <div class="row gap-8">
                                <button class="btn btn-ghost btn-sm" onClick={() => setShutdownConfirm(null)}>{_['cancel']}</button>
                                <button class="btn btn-danger btn-sm" onClick={() => onShutdown(a.asset_id)} disabled={lifecycleAction != null}>
                                  {lifecycleAction === a.asset_id ? '…' : _['asset-shutdown']}
                                </button>
                              </div>
                            </div>
                          ) : (
                            <button class="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); setShutdownConfirm(a.asset_id); }}>
                              {_['asset-shutdown']}
                            </button>
                          )
                        )}
                        {a.status === 'shutdown_pending' && (
                          <button class="btn btn-danger btn-sm" onClick={e => { e.stopPropagation(); onTerminate(a.asset_id); }} disabled={lifecycleAction != null}>
                            {lifecycleAction === a.asset_id ? '…' : _['asset-terminate']}
                          </button>
                        )}
                        {a.status === 'terminated' && (
                          <button class="btn btn-sm" onClick={e => { e.stopPropagation(); onClaim(a.asset_id); }} disabled={lifecycleAction != null}>
                            {lifecycleAction === a.asset_id ? '…' : _['asset-claim']}
                          </button>
                        )}
                        {!isDel ? (
                          <button class="btn btn-danger btn-sm" onClick={e => { e.stopPropagation(); setConfirmDel(a.asset_id); }}>{_['delete']}</button>
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
                    </div>
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

      {/* ── Earnings section for data asset owners ── */}
      {ownerEarnings && (
        <div class="mt-24">
          <h2 class="label-inline mb-12">{_['total-earned']}</h2>
          <div class="row gap-16 wrap mb-16">
            <div class="kv">
              <span class="kv-key">{_['total-earned']}</span>
              <span class="kv-val mono">{fmtPrice(ownerEarnings.total_earned)} OAS</span>
            </div>
          </div>
          <h3 class="label-inline mb-8">{_['recent-transactions']}</h3>
          {ownerEarnings.transactions.length === 0 ? (
            <EmptyState icon="⇄" title={_['no-transactions']} hint={_['no-transactions-hint']} />
          ) : (
            <div class="item-list">
              {ownerEarnings.transactions.map((tx) => (
                <div key={`${tx.asset_id}-${tx.timestamp}`} class="data-item">
                  <div class="item-row cursor-default">
                    <div class="grow">
                      <div class="item-meta">
                        <span class="mono item-id-inline">{maskIdShort(tx.asset_id)}</span>
                        <span class="caption ml-8">{maskOwner(tx.buyer)}</span>
                      </div>
                    </div>
                    <span class="mono item-price">{fmtPrice(tx.amount)} <span class="oas-unit">OAS</span></span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      </>}

      {/* ── My Capabilities Tab ── */}
      {activeTab === 'caps' && <>
        {myCapsLoading ? (
          <div role="status" aria-busy="true" aria-label={_['loading']}>
            <div class="skeleton skeleton-sm mb-8" />
            <div class="skeleton skeleton-sm mb-8" />
          </div>
        ) : myCaps.length === 0 ? (
          <EmptyState icon="λ" title={_['cap-no-caps']} hint={_['cap-no-caps-hint']}>
            <button class="btn btn-ghost" onClick={() => { location.hash = ''; }}>{_['cap-register-cta']}</button>
          </EmptyState>
        ) : (
          <div class="item-list">
            {myCaps.map(cap => (
              <div key={cap.capability_id} class="data-item">
                <div class="item-row cursor-default">
                  <div class="grow">
                    <div class="item-name">
                      <span class="type-badge cap-badge">⚡</span>
                      {cap.name || maskIdShort(cap.capability_id)}
                    </div>
                    <div class="item-meta">
                      <span class="mono item-id-inline">{maskIdShort(cap.capability_id)}</span>
                      <span class="caption ml-8">{_['cap-endpoint-url']}: {cap.endpoint ? cap.endpoint.replace(/^(https?:\/\/[^/]+).*/, '$1/•••') : '—'}</span>
                    </div>
                  </div>
                  <span class="mono item-price">{cap.price ?? 0} <span class="oas-unit">OAS</span></span>
                </div>
                <div class="cap-detail-pad">
                  <div class="row gap-16 wrap">
                    <div class="kv"><span class="kv-key">{_['cap-total-calls']}</span><span class="kv-val">{cap.total_calls ?? 0}</span></div>
                    <div class="kv"><span class="kv-key">{_['cap-success-rate']}</span><span class="kv-val">{safePct(cap.success_rate)}</span></div>
                    <div class="kv"><span class="kv-key">{_['cap-avg-latency']}</span><span class="kv-val">{cap.avg_latency_ms != null && Number.isFinite(cap.avg_latency_ms) ? cap.avg_latency_ms.toFixed(0) + ' ms' : '--'}</span></div>
                  </div>
                  {cap.tags && cap.tags.length > 0 && (
                    <div class="tag-chips mt-8">
                      {cap.tags.map(tag => <span key={tag} class="tag-chip">{tag}</span>)}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Earnings section */}
        {earnings && (
          <div class="mt-24">
            <h2 class="label-inline mb-12">{_['cap-earnings']}</h2>
            <div class="row gap-16 wrap">
              <div class="kv"><span class="kv-key">{_['cap-total-earned']}</span><span class="kv-val">{fmtPrice(earnings.total_earned)} OAS</span></div>
              <div class="kv"><span class="kv-key">{_['cap-total-calls']}</span><span class="kv-val">{earnings.total_calls ?? 0}</span></div>
            </div>
          </div>
        )}
      </>}
    </div>
  );
}
